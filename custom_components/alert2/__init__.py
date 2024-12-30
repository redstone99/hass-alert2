#
# Alert2
#
# Basic documentation on this integration is at https://github.com/redstone99/hass-alert2/tree/master
#
# TODO - document more completely
#
import traceback
import asyncio
import copy
import ast
import datetime as rawdt
import logging
_LOGGER = logging.getLogger(__name__)
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from   homeassistant.const import (
    SERVICE_RELOAD,
    EVENT_HOMEASSISTANT_STOP,
    EVENT_HOMEASSISTANT_STARTED
)
from   homeassistant.core import HomeAssistant, Event
from   homeassistant.helpers import discovery
from homeassistant.helpers.service import async_register_admin_service
import homeassistant.helpers.config_validation as cv
from   homeassistant.helpers.entity_component import EntityComponent
from   homeassistant.helpers.typing import ConfigType
from   homeassistant.helpers import template as template_helper
from   homeassistant.helpers import trigger as trigger_helper
import homeassistant.util.dt as dt

from .config import (
    DEFAULTS_SCHEMA,
    SINGLE_TRACKED_SCHEMA,
    SINGLE_ALERT_SCHEMA_EVENT,
    SINGLE_ALERT_SCHEMA_CONDITION,
    TOP_LEVEL_SCHEMA,
)
from .entities import (
    EventAlert, ConditionAlert, ConditionAlertManual, AlertGenerator
)
from .util import (
    report,
    create_task,
    create_background_task,
    cancel_task,
    DOMAIN,
    GENERATOR_DOMAIN,
    EVENT_TYPE,
    set_global_hass,
    get_global_hass,
    global_tasks,
    gAssertMsg
)

# The notify component loads asynchronously, so we don't know when the notify legacy platforms
# will have finished loading. So wait a few seconds before throwing errors for missing notifiers
moduleLoadTime = dt.now()
kNotifierStartupGraceSecs = 30  # Default value for notifier_startup_grace_secs
kStartupWaitPollFactor = 10


##########################################################
#
# BEGIN - Utility functions for developers to call
#
#
        
#
# declareEventMulti - takes array of config entries. E.g.:
#
#    declareEventMulti(hass, [  { 'domain': 'mydomain', 'name': 'some err 1' },
#                               { 'domain': 'mydomain', 'name': 'some err 2' } ])
#
async def declareEventMulti(arr):
    await get_global_hass().data[DOMAIN].declareEventMulti(arr)

    
##########################################################
#
# END of utility functions. Below this is Alert2 internal code.
#

NOTIFICATION_CONTROL_SCHEMA = {
    vol.Required("enable"): cv.boolean, #vol.Any(STATE_ON, STATE_OFF, NOTIFICATION_SNOOZE),  ( from homeassistant.const )
    vol.Optional("snooze_until"): cv.datetime,
}
ACK_SCHEMA = {
}
UNACK_SCHEMA = {
}
# Looks like in homeassistant/setup.py:_async_setup_component
# it first calls component.async_setup,
# then if there's a config entry it calls entry.async_setup_locked -> config_entries::async_setup -> async_setup_entry
#
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    #_LOGGER.warning(f'async_setup_entry called: {"".join(traceback.format_stack())}')
    await hass.config_entries.async_forward_entry_setups(entry, ['binary_sensor'])
    return True
async def async_setup(hass, config: ConfigType):
    #_LOGGER.warning(f'async_setup called: {"".join(traceback.format_stack())}')
    _LOGGER.info('Setting up Alert2')

    set_global_hass(hass)
    data = Alert2Data(hass, config)
    hass.data[DOMAIN] = data

    # Load binary_sensor.py wtihout requiring users put an extra line in their configuuration.yaml
    platform_domain = 'binary_sensor'
    hass.async_create_task(
        discovery.async_load_platform(
            hass,
            platform_domain,
            DOMAIN,
            { 'happy': 7 },  # can be None? I think this is the config that gets passed to the binary_sensor module.
            config,
        )
        , eager_start=True)
    
    # Note, sensor/binary_sensor init may happen later, so init2() may create templates before sensor entities exist for early_start ones.
    await data.init2()
    #create_background_task(hass, DOMAIN, data.slowStartup())
    return True

# NOTE - this must be a single-level Schema.  If nest anything, then fix up copy.copy() shallow copy logic down in
# handle_report_int()
#REPORT_SCHEMA = {
#    vol.Required("domain"): str,
#    vol.Required("name"): str,
#    vol.Optional("message"): str,
#}

class DelayedNotifierMgr:
    def __init__(self, hass, notifier_startup_grace_secs, defer_startup_notifications):
        self._hass = hass
        self.startupWaitDone = False
        self.delayed_notifiers = {}
        self.notifier_startup_grace_secs = notifier_startup_grace_secs
        self.defer_startup_notifications = defer_startup_notifications
        if self.notifier_startup_grace_secs == 0:
            self.startupWaitDone = True
        else:
            create_background_task(self._hass, DOMAIN, self.loop())

    def notifier_deferred(self, notifier):
        if self.startupWaitDone:
            return False
        if isinstance(self.defer_startup_notifications, list):
            return notifier in self.defer_startup_notifications
        return self.defer_startup_notifications # it's a bool
    async def loop(self):
        startupWaitPollSecs = max(0.25, self.notifier_startup_grace_secs / kStartupWaitPollFactor)
        while True:
            await asyncio.sleep(startupWaitPollSecs)
            uptimeSecs = (dt.now() - moduleLoadTime).total_seconds()
            graceRemainSecs = self.notifier_startup_grace_secs - uptimeSecs
            # When we finish startup waiting, give delayed_notifiers one last shot before
            # bailing out of while loop
            #self.startupWaitDone = self.alert2Data.haStarted and graceRemainSecs <= 0
            self.startupWaitDone = graceRemainSecs <= 0
            
            for anotifier in list(self.delayed_notifiers.keys()):
                if self.notifier_deferred(anotifier):
                    pass
                elif self._hass.services.has_service('notify', anotifier):
                    nlist = self.delayed_notifiers[anotifier]
                    del self.delayed_notifiers[anotifier]
                    for args in nlist:
                        _LOGGER.warning(f'Notifying (delayed) {anotifier}: {args["message"]}')
                        await self._hass.services.async_call('notify', anotifier, args)
            
            if self.startupWaitDone:
                break

        # grace period is up.
        leftovers = self.delayed_notifiers
        self.delayed_notifiers = None
        if leftovers: # empty dict evals to False
            alist = list(leftovers)
            errMsg = f'Following notifiers are not known to HA after startup grace period: {list(leftovers)}. Any missed alerts will be visible in the Alert2 UI card or in log files'
            for aname in alist:
                if '[' in aname:
                    errMsg += f'. Notifier "{aname}" looks to be a malformed list. Try quoting the individual notifier names. See Alert2 docs for examples.'
                    break
            report(DOMAIN, 'error', errMsg)
    def willDefer(self, anotifier, args):
        if self.startupWaitDone:
            return False
        if self._hass.services.has_service('notify', anotifier) and \
           not self.notifier_deferred(anotifier):
            return False
        if not anotifier in self.delayed_notifiers:
            _LOGGER.debug(f'adding {anotifier} to delayed_notifiers')
            self.delayed_notifiers[anotifier] = []
        self.delayed_notifiers[anotifier].append(args)
        return True
        

class Alert2Data:
    def __init__(self, hass, config):
        self._hass = hass
        self._rawConfig = config[DOMAIN]
        self.tracked = {}
        self.alerts = {}
        self.generators = {}
        self.component = EntityComponent[EventAlert](_LOGGER, DOMAIN, hass)
        self.sensorComponent = EntityComponent[AlertGenerator](_LOGGER, 'sensor', hass)
        self.binarySensorDict = None
        self.haStarted = False
        self.delayedNotifierMgr = None
        self.declEvMultiArr = [] # cumulative alert configs from all calls to alert.declareEventMulti

    async def init2(self):
        # First, initialize enough so that report() will work for internal errors
        #

        # Defaults
        #
        self.defaultsError = None
        self.defaults = DEFAULTS_SCHEMA({ 'reminder_frequency_mins': [60], 'notifier': 'persistent_notification', 'summary_notifier': False, 'annotate_messages': True })
        self.skip_internal_errors = False
        self.notifier_startup_grace_secs = kNotifierStartupGraceSecs
        self.defer_startup_notifications = False

        # Try processing just the defaults part of the config, so they'll apply to the internal events we declare, below.
        # report() isn't available yet, so defer error reporting until later in init
        if 'defaults' in self._rawConfig:
            try:
                defCfg = DEFAULTS_SCHEMA(self._rawConfig['defaults'])
                self.defaults.update(defCfg)
                #self.notifiers.add(self.defaults['notifier'])
            except vol.Invalid as v:
                # Error will be reported later in init.
                self.defaultsError = v
        if 'skip_internal_errors' in self._rawConfig:
            try:
                self.skip_internal_errors = TOP_LEVEL_SCHEMA.schema['skip_internal_errors'](self._rawConfig['skip_internal_errors'])
            except vol.Invalid as v:
                # Will be handled when we validate the TOP_LEVEL_SCHEMA
                pass            
        if 'notifier_startup_grace_secs' in self._rawConfig:
            try:
                self.notifier_startup_grace_secs = TOP_LEVEL_SCHEMA.schema['notifier_startup_grace_secs'](self._rawConfig['notifier_startup_grace_secs'])
            except vol.Invalid:
                # Will be handled when we validate the TOP_LEVEL_SCHEMA
                pass            
        if 'defer_startup_notifications' in self._rawConfig:
            try:
                self.defer_startup_notifications = TOP_LEVEL_SCHEMA.schema['defer_startup_notifications'](self._rawConfig['defer_startup_notifications'])
            except vol.Invalid:
                # Will be handled when we validate the TOP_LEVEL_SCHEMA
                pass            
            
        if not self.skip_internal_errors:
            errCfg = None
            try:
                if 'tracked' in self._rawConfig:
                    for obj in self._rawConfig['tracked']:
                        if obj['domain'] == DOMAIN and obj['name'] == 'error':
                            errCfg = SINGLE_TRACKED_SCHEMA(obj)
                            break
            except (vol.Invalid, TypeError, KeyError):
                pass
            
            if errCfg:
                errorEnt = self.declareEventInt(errCfg)
            else:
                errorEnt = self.declareEvent(DOMAIN, 'error')

            await self.component.async_add_entities([ errorEnt ])


        isFirstInit = (self.delayedNotifierMgr is None)
        if isFirstInit:
            self.delayedNotifierMgr = DelayedNotifierMgr(self._hass,
                                                         self.notifier_startup_grace_secs, self.defer_startup_notifications)
            
        # Now that report() is available, continue init that might use it
        
        if isFirstInit:
            loop = asyncio.get_running_loop()
            # Gives traceback info on asyncio 'Unclosed client session' errors
            #loop.set_debug(True)
            oldHandler = loop.get_exception_handler()
            self.inHandler = False
            def newHandler(loop, context):
                if self.inHandler:
                    _LOGGER.error(f'Exception {context}')
                    return
                self.inHandler = True
                excMsg = f'Global exception handler: a task died to due to an unhandled exception: '
                if 'exception' in context:
                    ex = context['exception']
                    excMsg += f'{ex.__class__}: {ex}. '
                excMsg += f'full context: {context}'
                report(DOMAIN, 'error', excMsg)
                if oldHandler:
                    oldHandler(loop, context)
                self.inHandler = False
            loop.set_exception_handler(newHandler)
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.startShutdown)
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.haStartedEv)
        
            self._hass.bus.async_listen(EVENT_TYPE, self.handle_event_report)
            self._hass.services.async_register(DOMAIN, 'report', self.handle_service_report)
            self._hass.services.async_register(DOMAIN, 'ack_all', self.ackAll)
            #self._hass.services.async_register(DOMAIN, 'log', self.dolog)
            self.component.async_register_entity_service(
                'notification_control',
                cv.make_entity_service_schema(NOTIFICATION_CONTROL_SCHEMA),
                "async_notification_control",
            )
            self.component.async_register_entity_service(
                'ack',
                cv.make_entity_service_schema(ACK_SCHEMA),
                "async_ack",
            )
            self.component.async_register_entity_service(
                'unack',
                cv.make_entity_service_schema(UNACK_SCHEMA),
                "async_unack",
            )
            async_register_admin_service(
                self._hass,
                DOMAIN,
                SERVICE_RELOAD,
                self.reload_service_handler,
            )
        
        await self.processConfig()
        
    async def reload_service_handler(self, service_call) -> None:
        """Reload yaml entities."""
        # First unload all entities. Start with generators since they'll remove condition alerts
        for aName in self.generators:
            agen = self.generators[aName]
            await self.sensorComponent.async_remove_entity(agen.entity_id)
        self.generators = {}
        # then event alerts
        for domain in self.tracked:
            for name in self.tracked[domain]:
                ent = self.tracked[domain][name]
                await self.component.async_remove_entity(ent.entity_id)
                ent.shutdown()
        self.tracked = {}
        # then condition alerts
        for domain in self.alerts:
            for name in self.alerts[domain]:
                ent = self.alerts[domain][name]
                await self.component.async_remove_entity(ent.entity_id)
                ent.shutdown()
        self.alerts = {}
        
        conf = await self.component.async_prepare_reload(skip_reset=True)
        #_LOGGER.warning(conf)
        if conf is None:
            conf = {DOMAIN: {}}
        self._rawConfig = conf[DOMAIN]
        _LOGGER.info('alert2 re-initing after config reload')
        await self.init2()
        # Redo prior calls to declareEventMulti() from other components
        if self.declEvMultiArr:
            await self.declareEventMulti(self.declEvMultiArr)

    async def processConfig(self):
        # Validate the config in pieces. We want alert2 to successfully initialize no matter how messed up the config is.
        # And if the config has an error, to process the rest of itas much as it can.

        # We already tried processing the defaults section once. Report errors encountered.
        if self.defaultsError is not None:
            report(DOMAIN, 'error', f'defaults section of config: {self.defaultsError}')

        def adjustTemplateField(obj, name):
            # the alert may not have a condition if either it is a condition alert, or
            # it is a tracked alert specified without a trigger
            if not isinstance(obj, dict) or name not in obj:
                return
            cond = obj[name]
            # we haven't done a voluptuous validation yet, so don't know what type cond is
            if not isinstance(cond, str) or template_helper.is_template_string(cond):
                return
            try:
                x = cv.boolean(cond) if name == 'condition' else float(cond)
            except (vol.Invalid, ValueError):
                # it's not a template and not a truthy, so assume it's an entity
                if '\'' in cond or '"' in cond:
                    report(DOMAIN, 'error', f'config has {name} template that is neither a template nor an entity: {obj}')
                    return
                # TODO - Not sure if strip() is necessary. Can yaml return extra whitespace?
                obj[name] = '{{ states("' + cond.strip() + '") }}'
            
        entities = []
        sensorEntities = []
        if 'tracked' in self._rawConfig and isinstance(self._rawConfig['tracked'], list):
            for obj in self._rawConfig['tracked']:
                newEnt = None
                try:
                    aCfg = SINGLE_TRACKED_SCHEMA(obj)
                    if aCfg['domain'] == DOMAIN and aCfg['name'] == 'error':
                        pass # already handled above
                    else:
                        newEnt = self.declareEventInt(aCfg)
                except vol.Invalid as v:
                    report(DOMAIN, 'error', f'tracked section of config: {v}. Relevant section: {obj}')
                if newEnt is not None:
                    entities.append(newEnt)

        if 'alerts' in self._rawConfig and isinstance(self._rawConfig['alerts'], list):
            for obj in self._rawConfig['alerts']:
                adjustTemplateField(obj, 'condition')
                if isinstance(obj, dict) and 'threshold' in obj:
                    adjustTemplateField(obj['threshold'], 'value')
                newEnt = None
                try:
                    if 'trigger' in obj:
                        aCfg = SINGLE_ALERT_SCHEMA_EVENT(obj)
                        atrig = await trigger_helper.async_validate_trigger_config(self._hass, aCfg['trigger'])
                        aCfg['trigger'] = atrig
                        newEnt = self.declareEventInt(aCfg)
                    else:
                        aCfg = SINGLE_ALERT_SCHEMA_CONDITION(obj)
                        if 'generator' in aCfg:
                            newEnt = self.declareGenerator(aCfg)
                        else:
                            newEnt = self.declareCondition(aCfg, False)
                except vol.Invalid as v:
                    report(DOMAIN, 'error', f'alerts section of config: {v}. Relevant section: {obj}')
                if newEnt is not None:
                    if isinstance(newEnt, AlertGenerator):
                        sensorEntities.append(newEnt)
                    else:
                        entities.append(newEnt)
                    
        await self.component.async_add_entities(entities)
        await self.sensorComponent.async_add_entities(sensorEntities)

        # Now check the rest of the config
        # TODO - this is redoing a bunch of work parsing templates.
        try:
            dCfg = TOP_LEVEL_SCHEMA(self._rawConfig)
        except vol.Invalid as v:
            report(DOMAIN, 'error', f'top-level alert2 config: {v}')

    def haStartedEv(self, event):
        self._hass.loop.call_soon_threadsafe(self.haStartedEv2)
    def haStartedEv2(self):
        # By the time EVENT_HOMEASSISTANT_STARTED has fired, the binary sensor should have initialized
        _LOGGER.debug(f'HA started')
        self.haStarted = True
        self.binarySensorDict['hastarted']._attr_is_on = True
        self.binarySensorDict['hastarted'].async_write_ha_state()
        
    def startShutdown(self, event):
        self._hass.loop.call_soon_threadsafe(self.shutdown)
    def shutdown(self):
        for adomain in self.alerts:
            for alName in self.alerts[adomain]:
                entity = self.alerts[adomain][alName]
                entity.shutdown()
        for adomain in self.tracked:
            for alName in self.tracked[adomain]:
                entity = self.tracked[adomain][alName]
                entity.shutdown()
        #for aName in self.generators:
        #    self.generators[aName].shutdown()
        for atask in global_tasks:
            atask.cancel()
    #async def slowStartup(self):
    #    uptimeSecs = (dt.now() - moduleLoadTime).total_seconds()
    #    graceRemainSecs = kNotifierInitGraceSecs - uptimeSecs
    #    if graceRemainSecs > 0:
    #        await asyncio.sleep(graceRemainSecs)
    #    for ann in self.notifiers:
    #        if not self._hass.services.has_service('notify', ann):
    #            report(DOMAIN, 'error', f'notifier notify.{ann} referenced by an alert but is still not avaiable after startup grace period')
            
    def setBinarySensorDict(self, adict):
        _LOGGER.debug(f'called setBinarySensorDict')
        self.binarySensorDict = adict

    def checkNewName(self, domain, name):
        if domain in self.alerts:
            if name in self.alerts[domain]:
                report(DOMAIN, 'error', f'Duplicate declaration of alert for domain={domain} name={name}')
                return False
        if domain in self.tracked:
            if name in self.tracked[domain]:
                report(DOMAIN, 'error', f'Duplicate declaration of alert for domain={domain} name={name} (tracked)')
                return False
        if domain == GENERATOR_DOMAIN and name in self.generators:
            report(DOMAIN, 'error', f'Duplicate generator name={name}')
            return False
        if len(domain) == 0:
            report(DOMAIN, 'error', f'zero length domain with name="{name}"')
            return False
        if len(name) == 0:
            report(DOMAIN, 'error', f'zero length name with domain="{domain}"')
            return False
        return True
            
    # Declare a single event alert
    def declareEvent(self, domain, name):
        tmp_config = { 'domain' : domain, 'name': name }
        #if notifier is not None:
        #    tmp_config['notifier'] = notifier
        return self.declareEventInt(tmp_config)
    # Internal helper
    def declareEventInt(self, config):
        domain = config['domain']
        name = config['name']
        if not domain in self.tracked:
            self.tracked[domain] = {}
        if not self.checkNewName(domain, name):
            return None
        entity = EventAlert(self._hass, self, config, self.defaults)
        self.tracked[domain][name] = entity
        #self.notifiers.add(entity.notifier)
        return entity
    # declare single condition alert
    def declareCondition(self, config, isManual=False, genVars=None):
        domain = config['domain']
        name = config['name']
        if not domain in self.alerts:
            self.alerts[domain] = {}
        if not self.checkNewName(domain, name):
            return None
        if isManual:
            entity = ConditionAlertManual(self._hass, self, config, self.defaults)
        else:
            entity = ConditionAlert(self._hass, self, config, self.defaults, genVars=genVars)
        self.alerts[domain][name] = entity
        #self.notifiers.add(entity.notifier)
        return entity
    def undeclareCondition(self, domain, name):
        if not domain in self.alerts or not name in self.alerts[domain]:
            report(DOMAIN, 'error', f'{gAssertMsg} Trying to remove unknown alert domain={domain} name={name}')
            return
        ent = self.alerts[domain][name]
        del self.alerts[domain][name]
        ent.shutdown()
        
    def declareGenerator(self, config):
        domain = GENERATOR_DOMAIN
        name = config['generator_name']
        if not self.checkNewName(domain, name):
            return None
        entity = AlertGenerator(self._hass, self, config)
        self.generators[name] = entity
        return entity
        
    # declare multiple event alerts, and also unhandled_exception
    async def declareEventMulti(self, arr):
        entities = []
        for x in arr:
            entities.append(self.declareEvent(x['domain'], x['name']))
            domain = x['domain']
            if domain not in self.tracked or 'unhandled_exception' not in self.tracked[domain]:
                entities.append(self.declareEvent(x['domain'], 'unhandled_exception'))
        self.declEvMultiArr = self.declEvMultiArr + arr
        await self.component.async_add_entities(entities)
        
    #async def dolog(self, call):
    #    logLevel = 'info'
    #    if 'level' in call.data and call.data['level'] in [ 'debug', 'info', 'warning', 'error', 'critical' ]:
    #        logLevel = call.data['level']
    #    txt = call.data['message'] if 'message' in call.data else None
    #    getattr(_LOGGER, logLevel)(f'Log: {txt}')
    async def ackAll(self, call):
        _LOGGER.info(f'ackAll called')
        now = dt.now()
        for adomain in self.tracked:
            for alName in self.tracked[adomain]:
                entity = self.tracked[adomain][alName]
                entity.ack_int(now)
        for adomain in self.alerts:
            for alName in self.alerts[adomain]:
                entity = self.alerts[adomain][alName]
                entity.ack_int(now)
        

    async def handle_service_report(self, call):
        return await self.handle_report_int(call.data, 'service-call')
    async def handle_event_report(self, ev: Event):
        return await self.handle_report_int(ev.data, 'hass-event')
    async def handle_report_int(self, data, tmsg):
        self._hass.verify_event_loop_thread(f'checking in handle_report_int for {tmsg}')

        # Grrr, have to manually validate data because voluptuous mutates a dict while validating and
        # the data passed with a service call is immutable.
        if not 'domain' in data or not isinstance(data['domain'], str):
            report(DOMAIN, 'error', f'malformed call {tmsg} missing/non-string "domain" {data}')
            return
        if not 'name' in data or not isinstance(data['name'], str):
            report(DOMAIN, 'error', f'malformed call {tmsg} missing/non-string "name" {data}')
            return
        domain = data['domain']
        name = data['name']
        if self.skip_internal_errors:
            if domain == DOMAIN and name == 'error':
                # The internal error was logged back up in report(), so no need to log again
                #msg = data['message'] if 'message' in data else ''
                # _LOGGER.error(msg)
                return
        
        if not domain in self.tracked or not name in self.tracked[domain]:
            errmsg = f'{tmsg} for domain={domain} name={name}'
            report(DOMAIN, 'error', f'undeclared event {errmsg}. Creating event alert')
            alertObj = self.declareEvent(domain, name)
            await self.component.async_add_entities([alertObj])
        else:
            alertObj = self.tracked[domain][name]

        message = ''
        if 'message' in data:
            if not isinstance(data['message'], str):
                report(DOMAIN, 'error', f'Malformed call {tmsg} non-string "message" {data}')
                return
            message = data['message']

        await alertObj.record_event(message)
        # TODO - I'm not sure this line does anythign, and probably is wrong.
        self.inHandler = False

