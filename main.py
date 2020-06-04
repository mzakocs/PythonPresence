import datetime
import os
import random
import select
import sys
import termios
import urllib
import json
import dbmanager

from collections import deque
from optparse import OptionParser
from threading import Thread
from time import time

from application import log
from application.notification import IObserver, NotificationCenter, NotificationData
from application.python.queue import EventQueue
from eventlib.twistedutil import join_reactor
from twisted.internet import reactor
from twisted.internet.error import ReactorNotRunning
from zope.interface import implements

from sipsimple.account import Account, AccountManager, BonjourAccount
from sipsimple.application import SIPApplication
from sipsimple.lookup import DNSLookup
from sipsimple.configuration import ConfigurationError, ConfigurationManager
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.core import ContactHeader, Engine, FromHeader, RouteHeader, SIPCoreError, SIPURI, Subscription, ToHeader, Route, Message
from sipsimple.payloads import ParserError
from sipsimple.payloads import rpid # needed to register RPID extensions
from sipsimple.payloads.pidf import Device, Person, Service, PIDF, PIDFDocument
from sipsimple.storage import FileStorage
from sipsimple.threading import run_in_twisted_thread

from sipclient.configuration import config_directory
from sipclient.configuration.account import AccountExtension
from sipclient.configuration.settings import SIPSimpleSettingsExtension
from sipclient.log import Logger


class InputThread(Thread):
    # Handles input in console with Termios
    def __init__(self, application):
        Thread.__init__(self)
        self.application = application
        self.daemon = True
        self._old_terminal_settings = None

    def run(self):
        notification_center = NotificationCenter()
        while True:
            for char in self._getchars():
                if char == "\x04":
                    # CTRL + D ends the application
                    self.application.stop()
                    sys.exit()
                elif char == "\x0A":
                    # ENTER updates the extensions list from the database
                    self.application.db.loadExtensions()
                else:
                    notification_center.post_notification('Input Received', sender=self, data=NotificationData(input=char))

    def stop(self):
        self._termios_restore()

    def _termios_restore(self):
        if self._old_terminal_settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_terminal_settings)

    def _getchars(self):
        fd = sys.stdin.fileno()
        if os.isatty(fd):
            self._old_terminal_settings = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] = new[3] & ~termios.ICANON & ~termios.ECHO
            new[6][termios.VMIN] = '\000'
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, new)
                if select.select([fd], [], [], None)[0]:
                    return sys.stdin.read(4192)
            finally:
                self._termios_restore()
        else:
            return os.read(fd, 4192)


class SubscriptionApplication(object):
    implements(IObserver)

    def __init__(self):
        self.account_name = None
        self.target = None
        self.input = InputThread(self)
        self.output = EventQueue(self._write)
        self.logger = Logger(sip_to_stdout=False, pjsip_to_stdout=False, notifications_to_stdout=False)
        self.account = None
        self.subscriptions = []
        self.subscriptionqueue = []
        self.statusdict = {}
        self.stopping = False
        self.lastmessage = None

        self._subscription_routes = None
        self._subscription_timeout = 0.0
        self._subscription_wait = 0.5

        account_manager = AccountManager()
        engine = Engine()
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=account_manager)
        notification_center.add_observer(self, sender=engine)
        notification_center.add_observer(self, sender=self.input)
        notification_center.add_observer(self, name='SIPEngineGotMessage')

        log.level.current = log.level.WARNING

    def _write(self, message):
        if isinstance(message, unicode):
            message = message.encode(sys.getfilesystemencoding())
        sys.stdout.write(message+'\n')

    def run(self):
        account_manager = AccountManager()
        configuration = ConfigurationManager()
        engine = Engine()

        # start output thread
        self.output.start()

        # startup configuration
        Account.register_extension(AccountExtension)
        SIPSimpleSettings.register_extension(SIPSimpleSettingsExtension)
        SIPApplication.storage = FileStorage(config_directory)
        try:
            configuration.start()
        except ConfigurationError, e:
            raise RuntimeError("failed to load sipclient's configuration: %s\nIf an old configuration file is in place, delete it or move it and recreate the configuration using the sip_settings script." % str(e))
        account_manager.load()
        if self.account_name is None:
            # Uses a garbage default account if a account name is not specified
            self.account = account_manager.default_account
        else:
            # Otherwise iterates through the account manager and finds the account
            # You have to add a account to sip-settings through the terminal for this to work
            # ex: sip-settings -a add user@domain password
            possible_accounts = [account for account in account_manager.iter_accounts() if self.account_name in account.id and account.enabled]
            if len(possible_accounts) > 1:
                raise RuntimeError("More than one account exists which matches %s: %s" % (self.account_name, ", ".join(sorted(account.id for account in possible_accounts))))
            if len(possible_accounts) == 0:
                raise RuntimeError("No enabled account that matches %s was found. Available and enabled accounts: %s" % (self.account_name, ", ".join(sorted(account.id for account in account_manager.get_accounts() if account.enabled))))
            self.account = possible_accounts[0]
            self.account.presence.enabled = True
            self.account.save()
        if self.account is None:
            raise RuntimeError("Unknown account %s. Available accounts: %s" % (self.account_name, ', '.join(account.id for account in account_manager.iter_accounts())))
        for account in account_manager.iter_accounts():
            if account == self.account:
                account.sip.register = False
            else:
                account.enabled = False
        self.output.put('Using account %s' % self.account.id)
        settings = SIPSimpleSettings()

        # start logging
        self.logger.start()

        # start the SIPSIMPLE engine
        engine.start(
            auto_sound=False,
            events={'presence': [PIDFDocument.content_type]},
            udp_port=settings.sip.udp_port if "udp" in settings.sip.transport_list else None,
            tcp_port=settings.sip.tcp_port if "tcp" in settings.sip.transport_list else None,
            tls_port=settings.sip.tls_port if "tls" in settings.sip.transport_list else None,
            tls_verify_server=self.account.tls.verify_server,
            tls_ca_file=os.path.expanduser(settings.tls.ca_list) if settings.tls.ca_list else None,
            tls_cert_file=os.path.expanduser(self.account.tls.certificate) if self.account.tls.certificate else None,
            tls_privkey_file=os.path.expanduser(self.account.tls.certificate) if self.account.tls.certificate else None,
            user_agent=settings.user_agent,
            sample_rate=settings.audio.sample_rate,
            rtp_port_range=(settings.rtp.port_range.start, settings.rtp.port_range.end),
            trace_sip=settings.logs.trace_sip or self.logger.sip_to_stdout,
            log_level=settings.logs.pjsip_level if (settings.logs.trace_pjsip or self.logger.pjsip_to_stdout) else 0
        )

        # start the input thread
        self.input.start()

        # Sets up the database manager for adding subscriptions
        self.db = dbmanager.DatabaseManager(self)
        self.db.loadExtensions()

        # start twisted
        try:
            reactor.run()
        finally:
            self.input.stop()

        # stop the output
        self.output.stop()
        self.output.join()
        
        # closes the database connection
        self.db.destroyDBConnection()

        self.logger.stop()

        return 0

    def stop(self):
        self.stopping = True
        for subscription in self.subscriptions:
            if subscription is not None and subscription.state.lower() in ('accepted', 'pending', 'active'):
                subscription.end(timeout=1)
            else:
                engine = Engine()
                engine.stop()

    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, None)
        if handler is not None:
            handler(notification)

    def _NH_SIPSubscriptionDidStart(self, notification):
        route = Route(notification.sender.route_header.uri.host, notification.sender.route_header.uri.port, notification.sender.route_header.uri.parameters.get('transport', 'udp'))
        self._subscription_routes = None
        self._subscription_wait = 0.5
        self.output.put('Subscription succeeded at %s:%d;transport=%s' % (route.address, route.port, route.transport))

    def _NH_SIPSubscriptionChangedState(self, notification):
        route = Route(notification.sender.route_header.uri.host, notification.sender.route_header.uri.port, notification.sender.route_header.uri.parameters.get('transport', 'udp'))
        if notification.data.state.lower() == "pending":
            self.output.put('Subscription pending at %s:%d;transport=%s' % (route.address, route.port, route.transport))
        elif notification.data.state.lower() == "active":
            self.output.put('Subscription active at %s:%d;transport=%s' % (route.address, route.port, route.transport))

    def _NH_SIPSubscriptionDidEnd(self, notification):
        notification_center = NotificationCenter()
        notification_center.remove_observer(self, sender=notification.sender)
        route = Route(notification.sender.route_header.uri.host, notification.sender.route_header.uri.port, notification.sender.route_header.uri.parameters.get('transport', 'udp'))
        if (route.uri.user):
            self.statusdict.pop(str(route.uri.user)) # removes them from the status list
        self.output.put('Unsubscribed from %s:%d;transport=%s' % (route.address, route.port, route.transport))
        self.stop()

    def _NH_SIPSubscriptionGotNotify(self, notification):
        if notification.data.content_type == PIDFDocument.content_type:
            self.output.put('\nReceived NOTIFY:')
            try:
                pidf = PIDF.parse(notification.data.body)
            except ParserError, e:
                self.output.put('Got illegal PIDF document: %s\n%s' % (str(e), notification.data.body))
            else:
                from_header = FromHeader.new(notification.data.from_header)
                self.statusdict[str(from_header.uri.user)] = self._display_pidf(pidf).lower()
                if (notification.sender.route_header):
                    route = Route(notification.sender.route_header.uri.host, notification.sender.route_header.uri.port, notification.sender.route_header.uri.parameters.get('transport', 'udp'))
                    datajson = json.dumps({"data": json.dumps(self.statusdict), "to": "all", "type": "statusupdate"})
                    if (datajson != self.lastmessage):
                        self._send_message(self.account.uri, datajson, route) # sends a statusupdate sip command
                        self.lastmessage = datajson

    def _NH_DNSLookupDidFail(self, notification):
        self.output.put('DNS lookup failed: %s' % notification.data.error)
        timeout = random.uniform(1.0, 2.0)

    @run_in_twisted_thread
    def _NH_SIPEngineDidEnd(self, notification):
        self._stop_reactor()

    @run_in_twisted_thread
    def _NH_SIPEngineDidFail(self, notification):
        self.output.put('Engine failed.')
        self._stop_reactor()

    def _NH_SIPEngineGotException(self, notification):
        self.output.put('An exception occured within the SIP core:\n'+notification.data.traceback)

    def _NH_DNSLookupDidSucceed(self, notification):
        # create subscriptions for everyone in the queue and register to get notifications from it
        self._subscription_routes = deque(notification.data.result)
        route = self._subscription_routes[0]
        route_header = RouteHeader(route.uri)
        for waitingsubscription in self.subscriptionqueue:
            # Creates a subscription for the waiting subscription
            newsubscription = Subscription(waitingsubscription.uri,
                                            FromHeader(self.account.uri, self.account.display_name),
                                            waitingsubscription,
                                            ContactHeader(self.account.contact[route]),
                                            "presence",
                                            route_header,
                                            credentials=self.account.credentials,
                                            refresh=self.account.sip.subscribe_interval)
            # Sets up an event listener for this new subscription
            notification_center = NotificationCenter()
            notification_center.add_observer(self, sender=newsubscription)
            # Starts the subscribe
            newsubscription.subscribe(timeout=5)
            # Adds this subscription to the active subscriptions list
            self.subscriptions.append(newsubscription)
            # Debug stuff
            self.output.put("Started new subscription with " + waitingsubscription.uri.user)
        # Clears all of the waiting subscriptions
        self.subscriptionqueue = []

    def _stop_reactor(self):
        try:
            reactor.stop()
        except ReactorNotRunning:
            pass

    def _setup_new_subscriptions(self, urilist):
        # TODO: Add check to see active subscriptions so it doesn't subscribe twice
        # sets up a new subscription with the given list of URI's
        for uri in urilist:
            tempuri = uri
            if tempuri is None:
                tempuri = ToHeader(SIPURI(user=self.account.id.username, host=self.account.id.domain))
            else:
                if '@' not in tempuri:
                    tempuri = '%s@%s' % (tempuri, self.account.id.domain)
                if not uri.startswith('sip:') and not tempuri.startswith('sips:'):
                    tempuri = 'sip:' + tempuri
                try:
                    tempuri = ToHeader(SIPURI.parse(tempuri))
                except SIPCoreError:
                    self.output.put('Illegal SIP URI: %s' % tempuri)
                    return 1
            self.subscriptionqueue.append(tempuri)
        #reactor.callLater(0, self._subscribe)
        settings = SIPSimpleSettings()

        self._subscription_timeout = time() + 30

        lookup = DNSLookup()
        notification_center = NotificationCenter()
        notification_center.add_observer(self, sender=lookup)
        proxyuri = None
        if self.account.sip.outbound_proxy is not None:
            proxyuri = SIPURI(host=self.account.sip.outbound_proxy.host, port=self.account.sip.outbound_proxy.port, parameters={'transport': self.account.sip.outbound_proxy.transport})
        elif self.account.sip.always_use_my_proxy:
            proxyuri = SIPURI(host=self.account.id.domain)
        else:
            proxyuri = self.subscriptionqueue[0].uri
        lookup.lookup_sip_proxy(proxyuri, settings.sip.transport_list)
        
        
    def _display_pidf(self, pidf):
        persons = {}
        printed_sep = True
        for child in pidf:
            if isinstance(child, Person):
                persons[child.id] = child
        # handle subscription info
        if len(persons) == 0:
            if list(pidf.notes):
                returnstring = "%s" % pidf.notes[0]
                self.output.put(returnstring + "\n")
                return returnstring
        else:
            for person in persons.values():
                newlist = self._format_person(person, pidf)
                returnstring = ":".join(newlist)
                self.output.put(returnstring + "\n")
                return returnstring

    def _format_person(self, person, pidf):
        ## Found a function to process SIP info
        buf = []
        # display notes
        if person.notes:
            for note in person.notes:
                buf.append("%s" % note)
        elif pidf.notes:
            for note in pidf.notes:
                buf.append("%s" % note)
        # display activities
        return buf

    # Messaging Functionality
    def _NH_SIPEngineGotMessage(self, notification):
        # THIS DOESN'T WORK! Don't need it though for now
        # Receives and processes messages from SIP
        content_type = notification.data.content_type
        if content_type not in ('text/plain', 'text/html'):
            return
        from_header = FromHeader.new(notification.data.from_header)
        from_header.parameters = {}
        from_header.uri.parameters = {}
        identity = str(from_header.uri)
        if from_header.display_name:
            identity = '"%s" <%s>' % (from_header.display_name, identity)
        body = notification.data.body
        self.output.put("Got MESSAGE from '%s', Content-Type: %s\n%s\n" % (identity, content_type, body))

    def _send_message(self, targeturi, messagebody, route):
        ## sends a message to the target URI
        notification_center = NotificationCenter()
        if route:
            uri = targeturi
            if uri is None:
                uri = ToHeader(SIPURI(user=self.account.id.username, host=self.account.id.domain))
            identity = str(self.account.uri)
            if self.account.display_name:
                identity = '"%s" <%s>' % (self.account.display_name, identity)
            self.output.put("Sending MESSAGE from '%s' to '%s' using proxy %s" % (identity, targeturi, route))
            message_request = Message(FromHeader(self.account.uri, self.account.display_name), ToHeader(uri), RouteHeader(route.uri), 'text/plain', messagebody, self.account.credentials, [])
            notification_center.add_observer(self, sender=message_request)
            message_request.send()
        else:
            self.output.put('No route to try. Aborting.\n')
            return

if __name__ == "__main__":
    # Main Execution Section
    try:
        application = SubscriptionApplication()
        return_code = application.run()
    except RuntimeError, e:
        print "Error: %s" % str(e)
        sys.exit(1)
    except SIPCoreError, e:
        print "Error: %s" % str(e)
        sys.exit(1)
    else:
        sys.exit(return_code)
