# Copyright 2009 Shikhar Bhushan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys, os, warnings
import re
import ncclient.manager
import time

warnings.simplefilter("ignore", DeprecationWarning)

from ncclient.operations import util
from ncclient.operations.rpc import *
from lxml import etree
from datetime import datetime, timedelta
from dateutil.parser import parse
from ncclient.operations.errors import NotificationError, ReconnectError

NETCONF_NOTIFICATION_NS = "urn:ietf:params:xml:ns:netconf:notification:1.0"
YANGPUSH_NOTIFICATION_NS = "urn:ietf:params:xml:ns:yang:ietf-yang-push:1.0"

class NotificationType(object):
    NETCONF_CONFIG_CHANGE = 1
    NETCONF_SESSION_START = 2
    NETCONF_SESSION_END = 3
    REPLAY_COMPLETE = 4
    NOTIFICATION_COMPLETE = 5
    SUBSCRIPTION_STARTED = 6
    SUBSCRIPTION_MODIFIED = 7
    SUBSCRIPTION_TERMINATED = 8
    SUBSCRIPTION_SUSPENDED = 9
    SUBSCRIPTION_RESUMED = 10
    YANG_PUSH_UPDATE = 11
    YANG_PUSH_CHANGE_UPDATE = 12

    @staticmethod
    def str_to_type(string):
        lookup = {"netconf-config-change": NotificationType.NETCONF_CONFIG_CHANGE,
        "netconf-session-start": NotificationType.NETCONF_SESSION_START,
        "netconf-session-end": NotificationType.NETCONF_SESSION_END,
        "replayComplete": NotificationType.REPLAY_COMPLETE,
        "notificationComplete": NotificationType.NOTIFICATION_COMPLETE,
        "subscription-started": NotificationType.SUBSCRIPTION_STARTED,
        "subscription-modified": NotificationType.SUBSCRIPTION_MODIFIED,
        "subscription-terminated": NotificationType.SUBSCRIPTION_TERMINATED,
        "subscription-suspended": NotificationType.SUBSCRIPTION_SUSPENDED,
        "subscription-resumed" : NotificationType.SUBSCRIPTION_RESUMED,
        "push-update": NotificationType.YANG_PUSH_UPDATE,
        "push-change-update": NotificationType.YANG_PUSH_CHANGE_UPDATE}
        try: return lookup[string]
        except: raise Exception("Unknown notification type")

class YangPushNotification(object):

    """Represents RFC5277 notifications """

    def __init__(self, raw):
        self._raw = raw
        self._parsed = False
        self._root = None
        self._eventTime = None
        self._type = None
        self._data = None
        self._connected = True
        self._invalid = False
        self.parse()

    def __repr__(self):
        return self._raw

    def _validate(self, element, tag):
        if element is None:
            self._invalid = True

    def parse(self):
        try:
            root = self._root = to_ele(self._raw)
            eventTime = root.find(qualify("eventTime", NETCONF_NOTIFICATION_NS))
            self._validate(eventTime, "eventTime")
            data = eventTime.getnext()
            self._validate(data, "data")

            # This might be unnecessary if callback is never invoked
            # when connection drops
            reason = data.find(qualify("termination-reason", YANGPUSH_NOTIFICATION_NS))

            self._eventTime = parse(eventTime.text)
            self._type = NotificationType.str_to_type(re.sub("{.*}", "", data.tag))
            self._data = data

            # This might be unnecessary if callback is never invoked
            # when connection drops
            if reason is not None:
                self._connected = reason.text != "dropped"

            self._parsed = True
        except Exception as e:
            self._invalid = True

    @property
    def xml(self):
        return self._raw

    @property
    def eventTime(self):
        if not self._parsed:
            self.parse()
        return self._eventTime

    @property
    def type(self):
        if not self._parsed:
            self.parse()
        return self._type

    @property
    def data_ele(self):
        if not self._parsed:
            self.parse()
        return self._data

    @property
    def data_xml(self):
        if not self._parsed:
            self.parse()
        return etree.tostring(self._data)

    @property
    def connected(self):
        if not self._parsed:
            self.parse()
        return self._connected

    @property
    def invalid(self):
        return self._invalid



class EstablishSubscription(RPC):

    """The *establish-subscription* RPC.
    According to draft-ietf-netconf-yang-push-03."""



    def datetime_to_rfc(self, time_string, time):

        """Validates user-inputted time and 
        converts it to RFC 3339 time format to 
        create a startTime or stoptime element"""

        if type(time) is not datetime:
            raise TypeError("%s is not a valid %s" % (str(time), time_string))
        timeTag = etree.Element(stop_string)
        timeTag.text = time.isoformat() + "Z"
        return timeTag

    def request(self, callback, errback, manager=None, retries=20, delay=1,
        encoding=None, stream=None, update_filter=None, start_time=None, stop_time=None, 
        dscp=None, priority=None, dependency=None, update_trigger=None, period=None, 
        no_sync_on_start=None, excluded_change=None):

        """Establish a subscription to NETCONF server

        *callback* User-defined callback function to be invoked when a notification arrives

        *errback* User-defined function to e invoked when an error occurs

        *manager* Manager object returned when user connects to NETCONF server,
        used to store connection info so ncclient can reconnect using that information
        (by default ncclient will not handle reconnecting the NETCONF server if user 
        does not pass in a manager)

        *retries* Specifies the number of times ncclient will attempt to reconnect to
        the NETCONF server if the connection is dropped

        *delay* Specifies the time ncclient will wait between consecutive attempts to
        reconnect to the NETCONF server following a dropped connection

        *encoding* Distinguish between the proper encoding that was specified
        for the subscription (by default XML)

        *stream* Specifies the stram user want to receive notifications from
        (by default NETCONF stream notifications)

        *update_filter* Specifies the notifications user wants to receive based on
        xml subtree structure and content (by default all notifications arrive)

        *start_time* Specifies the time user wants to start receiving notifications
        (by default start from present time)

        *stop_time* Specifies the time user wants to stop receiving notifications

        *dscp* The push update’s IP packet transport priority.
        This is made visible across network hops to receiver.
        The transport priority is shared for all receivers of
        a given subscription.

        *priority* Relative priority for a subscription. Allows an underlying
        transport layer perform informed load balance allocations
        between various subscriptions.

        *dependency* Provides the Subscription ID of a parent subscription
        without which this subscription should not exist. In
        other words, there is no reason to stream these objects
        if another subscription is missing.

        *update_trigger* Specifies wether the user subscribes for periodic (true) or 
        on change (false) notifications. (by default periodic)

        *period* Depending on the chosen update trigger the period is either the 
        amount of time between each periodic Notification or in case of on change 
        Notification the dampening period. The dampening period is minimum amount 
        of time that needs to have passed since the last time an update was

        *no_sync_on_start* (on change only) Specifies wether a complete synchronisation 
        at the beginning of a new on change subscription is wanted or not. Just on change
        notifications will be sent if no_sync_on_start is set. (by default false)

        *excluded_change* (on change only) Use to restrict which changes trigger an update.
        For example, if modify is excluded, only creation and deletion of objects 
        is reported.

        :seealso: :ref:`filter_params`"""

        print ("EstablishSubscription: building XML...")

        # catch possible errors

        if callback is None:
            raise ValueError("Missing a callback function")

        if errback is None:
            raise ValueError("Missing a errback function")

        if period is None:
            if update_trigger == "on-change":
                raise ValueError("Missing update period")
            else:
                raise ValueError("Missing dampening period")

        # check if on change parameters are set for periodic subscription

        if (no_sync_on_start or excluded_change is not None) and update_trigger is not false:
            raise ValueError("Can not set on change update parameters for periodic updates")


        # build XML tree for the RPC request

        subscription_node = etree.Element(qualify("establish-subscription", YANGPUSH_NOTIFICATION_NS))

        if encoding is not None:
            encodingTag = etree.Element("encoding")
            encodingTag.text = encoding
            subscription_node.append(encodingTag)

        if stream is not None:
            streamTag = etree.Element("stream")
            streamTag.text = stream
            subscription_node.append(streamTag)

        if update_filter is not None:
            subscription_node.append(util.build_filter(update_filter))

        if start_time is not None:
            subscription_node.append(self.datetime_to_rfc("startTime", start_time))

        if stop_time is not None:
            subscription_node.append(self.datetime_to_rfc("stopTime", stop_time))

        #TODO------------------------------

        if dscp is not None:
            print ("EstablishSubscription: dscp input not supported yet")

        if priority is not None:
            print ("EstablishSubscription: priority input not supported yet")

        if dependency is not None:
            print ("EstablishSubscription: dependency input not supported yet")

        #TODO------------------------------    

        if update_trigger == "on-change":
            periodTag = etree.Element("dampening-period")

            #TODO------------------------------  

            if no_sync_on_start is not None:
    
                no_sync_on_startTag = etree.Element("no-sync-on-start")
                subscription_node.append(no_sync_on_startTag)

            if excluded_change is not None:
                excluded_changeTag = etree.Element("excluded-change")
                excluded_changeTag.text = excluded_change
                subscription_node.append(excluded_changeTag)
                

            #TODO------------------------------  

        else:        
            periodTag = etree.Element("period")
        periodTag.text = period
        subscription_node.append(periodTag)

        print("EstablishSubscription: XML string built!")
        print("EstablishSubscription: add NotificationListener...")

        # add NotificationListener to retrieve the notifications

        self.session.add_listener(YangPushNotificationListener(callback, errback, 
            manager=manager, retries=retries, delay=delay, 
            encoding=encoding, stream=stream, update_filter=update_filter, 
            start_time=start_time, stop_time=stop_time, dscp=dscp, priority=priority,
            dependency=dependency, update_trigger=update_trigger, period=period,
            no_sync_on_start=no_sync_on_start, excluded_change=excluded_change))

        print("EstablishSubscription: NotificationListener added!")
        print("EstablishSubscription: send RPC...")

        # send the RPC

        return self._request(subscription_node)


class YangPushNotificationListener(SessionListener):

    """Class extending :class:`Session` listeners,
    which are notified when a new RFC 5277 notification
    is received or an error occurs."""

    def __init__(self, user_callback, user_errback, manager, retries, delay,
        encoding, stream, update_filter, start_time, stop_time,
        dscp, priority, dependency, update_trigger, period,
        no_sync_on_start, excluded_change):
        """Called by CreateSubscription when a new NotificationListener is added to a session.
        used to keep track of connection and subscription info in case connection gets dropped."""
        self.user_callback = user_callback
        self.user_errback = user_errback
        self.manager, self.retries, self.delay = manager, retries, delay
        self.encoding, self.stream, self.update_filter = encoding, stream, update_filter
        self.dscp, self.priority, self.dependency = dscp, priority, dependency
        self.update_trigger, self.period = update_trigger, period
        self.no_sync_on_start, self.excluded_change = no_sync_on_start, excluded_change
        self.reconnect_time, self.stop_time = start_time, stop_time

    def callback(self, root, raw):
        """Called when a new RFC 5277 notification is received.
        The *root* argument allows the callback to determine whether the message is a notification.
        Here, *root* is a tuple of *(tag, attributes)* where *tag*
        is the qualified name of the root element and *attributes* is a dictionary of its attributes (also qualified names).
        *raw* will contain the xml notification as a string."""
        tag, attrs = root
        if tag != qualify("notification", NETCONF_NOTIFICATION_NS):
            self.user_errback(NotificationError("Received a message not of type notification"))
            return
        notification = YangPushNotification(raw)
        self.reconnect_time = notification.eventTime.replace(tzinfo=None) + timedelta.resolution

        # This might be unnecessary if callback is never invoked
        # when connection drops
        if notification.connected:
            self.user_callback(notification)
        else:
            self.user_errback(notification)

    def errback(self, ex):
        """Called when an error occurs.
        For now just handles a dropped connection.

        :type ex: :exc:`Exception`
        """
        self.user_errback(ex)
        if self.manager is not None:
            disconnected = True
            retries = self.retries
            while disconnected and retries > 0:
                try:
                    self.user_errback(ReconnectError("Attempting to reconnect"))
                    session = ncclient.manager.connect(**self.manager.kwargs)
                    session.establish_subscription(self.user_callback, self.user_errback,
                        manager=self.manager, retries=self.retries, delay=self.delay,
                        encoding=self.encoding, stream=self.stream, update_filter=self.update_filter, 
                        start_time=self.reconnect_time, stop_time=self.stop_time, dscp=self.dscp, 
                        priority=self.priority, dependency=self.dependency, update_trigger=self.update_trigger,
                        period=self.period, no_sync_on_start=self.no_sync_on_start, excluded_change= self.excluded_change)
                    disconnected = False
                except Exception as e:
                    self.user_errback(ReconnectError("Failed to reconnect, trying again"))
                    time.sleep(self.delay)
                retries = retries - 1
            if retries == 0:
                self.user_errback(ReconnectError("Connection refused after %d attempts, giving up" % self.retries))