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
from functools import partial
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service
import homeassistant.helpers.config_validation as cv
from   homeassistant.helpers.entity_component import EntityComponent
from   homeassistant.helpers.typing import ConfigType
from   homeassistant.helpers.entity import Entity
from   homeassistant.helpers import template as template_helper
from   homeassistant.helpers import trigger as trigger_helper
import homeassistant.util.dt as dt
import homeassistant.helpers.entity_registry as entity_registry

from .config import (
    DEFAULTS_SCHEMA,
    SINGLE_TRACKED_SCHEMA,
    SINGLE_ALERT_SCHEMA_EVENT,
    SINGLE_ALERT_SCHEMA_CONDITION,
    TOP_LEVEL_SCHEMA,
)
from .entities import (
    EventAlert, ConditionAlert, AlertGenerator, NotificationReason
)
from .ui import ( UiMgr )
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
    set_shutting_down,
    global_tasks,
    gAssertMsg
)

# Need to define CONFIG_SCHEMA here to make hacs github validator happy
# We'll do proper validation below
CONFIG_SCHEMA = lambda config: config
#vol.Schema(
#    {DOMAIN: cv.schema_with_slug_keys(TOP_LEVEL_SCHEMA)}, extra=vol.ALLOW_EXTRA
#)
#CONFIG_SCHEMA = vol.Schema({
#    vol.Optional('alert2'): TOP_LEVEL_SCHEMA
#}, extra=vol.ALLOW_EXTRA)

# The notify component loads asynchronously, so we don't know when the notify legacy platforms
# will have finished loading. So wait a few seconds before throwing errors for missing notifiers
moduleLoadTime = dt.now()
kNotifierStartupGraceSecs = 30  # Default value for notifier_startup_grace_secs
kStartupWaitPollFactor = 10
# Secs after startup to wait before purging the entity registry of alerts that no longer exist
gGcDelaySecs = 10

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
    vol.Optional("ack_at_snooze_start"): cv.boolean,
}
EMPTY_SCHEMA = {}

#
# Looks like in homeassistant/setup.py:_async_setup_component
# it first calls component.async_setup,
# then if there's a config entry it calls entry.async_setup_locked -> config_entries::async_setup -> async_setup_entry
#
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    #_LOGGER.warning(f'async_setup_entry called: {"".join(traceback.format_stack())}')
    if DOMAIN in hass.data:
        _LOGGER.info('Skipping async_setup_entry for alert2, already done')
        return True
    # Alert2 is configured without any YAML, just via the UI.
    _LOGGER.info('Setting up Alert2 sans YAML')
    set_global_hass(hass)
    yaml_config = {}
    data = Alert2Data(hass, {})
    hass.data[DOMAIN] = data
    await hass.config_entries.async_forward_entry_setups(entry, ['binary_sensor'])
    await data.init2()
    return True
async def async_setup(hass, config: ConfigType):
    #_LOGGER.warning(f'async_setup called: {"".join(traceback.format_stack())}')

    # async_setup is always called before async_setup_entry
    if DOMAIN in hass.data:
        _LOGGER.error('Somehow async_setup invoked after already initialized. Should never happen')
        assert False # die hard here.
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
                        _LOGGER.info(f'Notifying (delayed) {anotifier}: {args["message"]}')
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
        #_LOGGER.debug(f'willDefer called for {anotifier} with {self.startupWaitDone} and {self.notifier_startup_grace_secs} and {self.notifier_deferred(anotifier)} and {self.defer_startup_notifications}')
        if self.startupWaitDone:
            return False
        if self._hass.services.has_service('notify', anotifier) and \
           not self.notifier_deferred(anotifier):
            return False
        if not anotifier in self.delayed_notifiers:
            _LOGGER.info(f'Adding {anotifier} to delayed_notifiers')
            self.delayed_notifiers[anotifier] = []
        self.delayed_notifiers[anotifier].append(args)
        return True

class SupersedeMgr:
    def __init__(self):
        # Map from (domain,name) -> set( (domain, name) )
        self.supersedesMap = {}
        self.supersededByMap = {}
    def addNode(self, domain, name, supersedesList):
        thisPair = (domain, name)
        if thisPair in self.supersedesMap:
            report(DOMAIN, 'error', f'{gAssertMsg} should not be adding duplicate supersedes for {thisPair}')
            return True
        if supersedesList:
            # cycle check
            supersedesSet = set([ (x['domain'], x['name']) for x in supersedesList])
            supersededBySet = self.supersededBySet(domain, name)
            if any([ dn in supersededBySet for dn in supersedesSet ]):
                    return False
            self.supersedesMap[thisPair] = supersedesSet
            for apair in supersedesSet:
                if not apair in self.supersededByMap:
                    self.supersededByMap[apair] = set()
                self.supersededByMap[apair].add(thisPair)
        else:
            self.supersedesMap[thisPair] = set()
        return True

    def removeNode(self, domain, name):
        thisPair = (domain, name)
        if thisPair not in self.supersedesMap:
            report(DOMAIN, 'error', f'{gAssertMsg} should not be removing non-existent {thisPair}')
            return
        for apair in self.supersedesMap[thisPair]:
            self.supersededByMap[apair].remove(thisPair)
            if not self.supersededByMap[apair]:
                del self.supersededByMap[apair]
        del self.supersedesMap[thisPair]

    def supersedesSet(self, domain, name):
        thisPair = (domain, name)
        rez = set()
        visitSet = set()
        if thisPair in self.supersedesMap:
            visitSet.add( thisPair )
        while visitSet:
            tpair = visitSet.pop()
            if tpair in self.supersedesMap:
                for apair in self.supersedesMap[tpair]:
                    # This may visit a node multiple but finite times if the graph is diamond shaped
                    rez.add(apair)
                    visitSet.add(apair)
        return rez
    def supersededBySet(self, domain, name):
        thisPair = (domain, name)
        rez = set()
        visitSet = set()
        if thisPair in self.supersededByMap:
            visitSet.add( thisPair )
        while visitSet:
            tpair = visitSet.pop()
            if tpair in self.supersededByMap:
                for apair in self.supersededByMap[tpair]:
                    # This may visit a node multiple but finite times if the graph is diamond shaped
                    rez.add(apair)
                    visitSet.add(apair)
        return rez

    def unused___________topoOrdering(self, aset):
        # We'll repeatedly look for nodes that are not superseded by any except visisted nodes
        result = []
        remainingNodes = aset.copy() # shallow
        #_LOGGER.info(f'will do topo ordering for {remainingNodes}')
        while remainingNodes:
            # Look for aNode that is not superseded by any except visisted node
            didSomething = False
            for aNode in remainingNodes:
                isSuperseded = False
                for tnode in remainingNodes:
                    if aNode != tnode and aNode in self.supersedesMap[tnode]:
                        isSuperseded = True
                        break
                if not isSuperseded:
                    result.append(aNode)
                    remainingNodes.remove(aNode)
                    didSomething = True
                    break
            if not didSomething:
                report(DOMAIN, 'error', f'{gAssertMsg} topo ordering failed somehow')
                result.append(aNode)
                remainingNodes.remove(aNode)
        #result.reverse()
        return result
        
# The issue this class tries to solve is the race between two alerts that want
# to notify, where one supersedes the other.  E.g., say an entity changes
# state, causing two alerts to fire.  The order in which the two alert objects
# see the state change depends on HA implementation details, as well as some
# Alert2 details (eg if one alert uses TriggerCond and one uses Tracker, and the
# order in which the alerts were declared and called
# async_track_template_result)
# Theoretically, the race could involve state outside HA. Eg two alerts are based on two
# external temperature sensors, and both sensors report hot.
#
# To mitigate this, we potentially delay the call to _notify() to give a superseding alert a
# chance to fire.
#
# A similar race occurs when two alerts stop firing.
class SupersedeNotifyMgr:
    def __init__(self, alert2Data):
        self.alert2Data = alert2Data
        # waitFireMap is map of alerts waiting to see if superseding alerts fire
        self.waitFireMap = {} # map (domain,name) -> {event, queue of partials, task, alert, isSuperseded}
        # recentOffAlerts is map of alerts that recently stopped firing. Checked
        # by other alerts to see if a superseding alert recently stopped firing.
        self.recentOffAlerts = {} # map of (domain,name) -> expire task

    def isWaiting(self, alert):
        thisPair = (alert.alDomain, alert.alName)
        return thisPair in self.waitFireMap
        
    def addAndFlushNotifications(self, thisPair, pcall, *, isSuperseded):
        if thisPair in self.waitFireMap:
            self.waitFireMap[thisPair]['queue'].append(pcall)
            self.flushNotifications(thisPair, isSuperseded)
        else:
            pcall(dt.now(), isSuperseded=isSuperseded)
    def addNotification(self, thisPair, pcall):
        if thisPair in self.waitFireMap:
            self.waitFireMap[thisPair]['queue'].append(pcall)
        else:
            pcall(dt.now(), isSuperseded=False)
    def flushNotifications(self, thisPair, isSuperseded, fromWait=False):
        now = dt.now()
        if thisPair in self.waitFireMap:
            nqueue = self.waitFireMap[thisPair]['queue']
            if not fromWait:
                task = self.waitFireMap[thisPair]['task']
                cancel_task(DOMAIN, task)
            alert = self.waitFireMap[thisPair]['alert']
            # delete waitFireMap entry so that isWaiting returns false
            # before we call _notify_post_debounce, which calls can_notify_now which checks isWaiting
            del self.waitFireMap[thisPair]
            for pcall in nqueue:
                pcall(now, isSuperseded=isSuperseded)
            # isWaiting is now false, so recalculate any reminder times
            alert.reminder_check(now)
                
    def processNotify(self, alert, now, msg, reason: NotificationReason, last_fired_time, skip_notify, debounce_secs,
                      extra_data):
        supersedesSet = self.alert2Data.supersedeMgr.supersedesSet(alert.alDomain, alert.alName)
        thisPair = (alert.alDomain, alert.alName)
        pcall = partial(alert._notify_post_debounce, msg, reason, last_fired_time, extra_data, skip_notify=skip_notify)
        
        # Update recentOffAlerts
        if reason == NotificationReason.Fire:
            if thisPair in self.recentOffAlerts:
                cancel_task(DOMAIN, self.recentOffAlerts[thisPair])
                del self.recentOffAlerts[thisPair]
        elif reason == NotificationReason.StopFiring:
            if debounce_secs > 0:
                async def removeSoon():
                    await asyncio.sleep(debounce_secs)
                    del self.recentOffAlerts[thisPair]
                self.recentOffAlerts[thisPair] = create_background_task(self.alert2Data._hass, DOMAIN, removeSoon())

        # Notify waitFireMap
        if reason == NotificationReason.Fire:
            if supersedesSet:
                for apair in supersedesSet:
                    if apair in self.waitFireMap:
                        self.waitFireMap[apair]['isSuperseded'] = apair
                        self.waitFireMap[apair]['event'].set()

        # If not superseded by any alerts, go ahead and notify
        supersededBySet = self.alert2Data.supersedeMgr.supersededBySet(alert.alDomain, alert.alName)
        if not supersededBySet:
            # There should not be anything queued, but still call addAndFlushNotifications for consistency
            #pcall(dt.now(), is_superseded=False)
            self.addAndFlushNotifications(thisPair, pcall, isSuperseded=False)
            return

        # Alert has superseding alerts - need to debounce
        
        # If superseded by firing alert, no need to debounce
        for apair in supersededBySet:
            alEnt = self.alert2Data.alerts[apair[0]][apair[1]]
            assert isinstance(alEnt, ConditionAlert)
            if alEnt.state == 'on':
                # We're superseded by an firing alert.
                # TODO - _notify will recalculate if we're superseded. Skip that.
                _LOGGER.debug(f'{alert.name} in processNotify: sup pass true')
                self.addAndFlushNotifications(thisPair, pcall, isSuperseded=apair)
                return

        # We are superseded by other alerts, and none of them are firing at present
        if debounce_secs == 0:
            self.addAndFlushNotifications(thisPair, pcall, isSuperseded=False)
            return
        
        # if lower alert starts right after superseding one ends, count as superseded
        if reason == NotificationReason.Fire:
            if thisPair not in self.waitFireMap:
                ev = asyncio.Event()
                waitObj = { 'event': ev, 'queue': [], 'task': None, 'alert': alert, 'isSuperseded': False }
                async def wait():
                    hass = self.alert2Data._hass
                    try:
                        await asyncio.wait_for(ev.wait(), timeout=debounce_secs)
                    except TimeoutError:
                        pass
                    self.flushNotifications(thisPair, isSuperseded=waitObj['isSuperseded'], fromWait=True)
                waitObj['task'] = create_background_task(self.alert2Data._hass, DOMAIN, wait())
                self.waitFireMap[thisPair] = waitObj
        else:
            for apair in supersededBySet:
                if apair in self.recentOffAlerts:
                    self.addAndFlushNotifications(thisPair, pcall, isSuperseded=apair)
                    return
        self.addNotification(thisPair, pcall)

def updateConfigDict(currConfig, newConfig):
    currHasData = 'data' in currConfig
    if 'data' in currConfig and 'data' in newConfig:
        newData = currConfig['data'].copy()
        newData.update(newConfig['data'])
        currConfig.update(newConfig)
        currConfig['data'] = newData
    else:
        currConfig.update(newConfig)
        
class Alert2Data:
    def __init__(self, hass, config):
        # Call set_shutting_down mostly for unittests which create sequentially multiple Alert2Data
        #set_shutting_down(False)
        self._hass = hass
        self._rawYamlConfig = config[DOMAIN] if DOMAIN in config else {}
        self.tracked = {}
        self.alerts = {}
        self.generators = {}
        self.component = EntityComponent[EventAlert](_LOGGER, DOMAIN, hass)
        self.sensorComponent = EntityComponent[AlertGenerator](_LOGGER, 'sensor', hass)
        self.binarySensorDict = None
        self.haStarted = False
        self.delayedNotifierMgr = None
        self.declEvMultiArr = [] # cumulative alert configs from all calls to alert.declareEventMulti
        self.uiMgr = None
        self.rawYamlBaseTopConfig = None # stores global settings not including the UI config
        self.rawTopConfig = None
        self.topConfig = None # processed Schema() for defaults and top-level options
        self.supersedeMgr = SupersedeMgr()
        self.gcTask = None
        self.supersedeNotifyMgr = SupersedeNotifyMgr(self)

    def noteUiUpdate(self):
        tmpUiConfig = copy.deepcopy(self.rawYamlBaseTopConfig)
        cfg = self.uiMgr.getPreppedConfig()
        if cfg is None:
            return None
        if 'defaults' in cfg:
            #tmpUiConfig['defaults'].update(cfg['defaults'])
            updateConfigDict(tmpUiConfig['defaults'], cfg['defaults'])
        if 'skip_internal_errors' in cfg:
            tmpUiConfig['skip_internal_errors'] = cfg['skip_internal_errors']
        if 'notifier_startup_grace_secs' in cfg:
            tmpUiConfig['notifier_startup_grace_secs'] = cfg['notifier_startup_grace_secs']
        if 'defer_startup_notifications' in cfg:
            tmpUiConfig['defer_startup_notifications'] = cfg['defer_startup_notifications']
        try:
            self.topConfig = TOP_LEVEL_SCHEMA(tmpUiConfig)
            self.rawTopConfig = tmpUiConfig
        except vol.Invalid as v:
            return f'UI config: {v}'
        return None
    
    async def init2(self):
        # report() isn't available yet, so defer error reporting until later in init
        self.earlyErrors = []

        # Defaults
        #
        baseTopConfig = {
            'defaults': {
                'reminder_frequency_mins': [60], 'notifier': 'persistent_notification',
                'summary_notifier': False, 'done_notifier': True, 'annotate_messages': True,
                'throttle_fires_per_mins': None,
                'priority': 'low',
                'supersede_debounce_secs': 0.5,
                'icon': 'mdi:alert'
            },
            # Optional defaults for internal alerts
            'tracked': [
                { 'domain': DOMAIN, 'name': 'global_exception', 'throttle_fires_per_mins': [20, 60] }
            ],
            'skip_internal_errors': False,
            'notifier_startup_grace_secs': kNotifierStartupGraceSecs,
            'defer_startup_notifications': False,
        }
        try:
            self.topConfig = TOP_LEVEL_SCHEMA(baseTopConfig)
            self.rawTopConfig = baseTopConfig
            self.rawYamlBaseTopConfig = baseTopConfig
        except vol.Invalid as v:
            msg = f'built-in baseTopConfig validation failure: {v} for {baseTopConfig}'
            _LOGGER.error(f'alert2 {gAssertMsg} {msg}')
            self.earlyErrors.append(msg)

        # Try updating defaults with yaml
        #
        tmpYamlConfig = copy.deepcopy(baseTopConfig)
        if 'defaults' in self._rawYamlConfig:
            #tmpYamlConfig['defaults'].update(self._rawYamlConfig['defaults'])
            updateConfigDict(tmpYamlConfig['defaults'], self._rawYamlConfig['defaults'])
        if 'skip_internal_errors' in self._rawYamlConfig:
            tmpYamlConfig['skip_internal_errors'] = self._rawYamlConfig['skip_internal_errors']
        if 'notifier_startup_grace_secs' in self._rawYamlConfig:
            tmpYamlConfig['notifier_startup_grace_secs'] = self._rawYamlConfig['notifier_startup_grace_secs']
        if 'defer_startup_notifications' in self._rawYamlConfig:
            tmpYamlConfig['defer_startup_notifications'] = self._rawYamlConfig['defer_startup_notifications']
        try:
            self.rawYamlBaseTopConfig = tmpYamlConfig
            self.rawTopConfig = tmpYamlConfig
            self.topConfig = TOP_LEVEL_SCHEMA(tmpYamlConfig)
        except vol.Invalid as v:
            self.earlyErrors.append(f'YAML config: {v}')

        # Try updating defaults with ui
        #
        isFirstInit = (self.delayedNotifierMgr is None)
        if isFirstInit:
            self.uiMgr = UiMgr(self._hass, self)
        try:
            await self.uiMgr.startup() # could throw some json errors
        except Exception as v:
            _LOGGER.error(f'UI startup exception: {"".join(traceback.format_exception(v))}')
            self.earlyErrors.append(f'UI config: {v}')
        else:
            err = self.noteUiUpdate()
            if err:
                self.earlyErrors.append(err)
                
        #self.deepcleanEntityRegistry()
            
        if not self.topConfig['skip_internal_errors']:
            for internalType in ['error', 'warning', 'global_exception']:
                errCfg = None
                try:
                    cfgObj = None
                    if 'tracked' in self._rawYamlConfig:
                        for obj in self._rawYamlConfig['tracked']:
                            if obj['domain'] == DOMAIN and obj['name'] == internalType:
                                cfgObj = obj
                                break
                    if cfgObj is None:
                        cfgObj = self.uiMgr.getEarlyInternalRawConfig(internalType)
                    if cfgObj:
                        errCfg = SINGLE_TRACKED_SCHEMA(cfgObj)
                except (vol.Invalid, HomeAssistantError, TypeError, KeyError):
                    pass # Handled below in loadAlertBlock
                if errCfg:
                    errorEnt = self.declareEventInt(errCfg)
                else:
                    errorEnt = self.declareEvent(DOMAIN, internalType)
                if isinstance(errorEnt, Entity):
                    await self.component.async_add_entities([ errorEnt ])
                    _LOGGER.debug(f'Lifecycle create alert {errorEnt.entity_id}')
                else:
                    report(DOMAIN, 'error', errorEnt) # errMsg


        if isFirstInit:
            self.delayedNotifierMgr = DelayedNotifierMgr(self._hass,
                                                         self.topConfig['notifier_startup_grace_secs'],
                                                         self.topConfig['defer_startup_notifications'])
            
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
                excMsg = f'An HA task (possibly unrelated to Alert2) died to due to an unhandled exception: '
                isException = False
                if 'exception' in context:
                    ex = context['exception']
                    excMsg += f'{ex.__class__}: {ex}. '
                    isException = True #context['exception'] (could pass as exc_info to logging, but not necessary)
                excMsg += f'full context: {context}'
                report(DOMAIN, 'global_exception', excMsg, isException=isException)
                if oldHandler:
                    oldHandler(loop, context)
                self.inHandler = False
            loop.set_exception_handler(newHandler)
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.shutdown)
            #self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.startShutdown)
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.haStartedEv)
        
            self._hass.bus.async_listen(EVENT_TYPE, self.handle_event_report)
            self._hass.services.async_register(DOMAIN, 'report', self.handle_service_report)
            self._hass.services.async_register(DOMAIN, 'ack_all', self.ackAll)
            # gc_entity_registry:
            #    name: Clean entity registry
            #    description: Remove any entity regsitry entries corresponding to Alert2 entities that no longer exist
            #self._hass.services.async_register(DOMAIN, 'gc_entity_registry', self.gcEntityRegistry)
            self.component.async_register_entity_service(
                'notification_control',
                cv.make_entity_service_schema(NOTIFICATION_CONTROL_SCHEMA),
                "async_notification_control",
            )
            self.component.async_register_entity_service(
                'ack',
                cv.make_entity_service_schema(EMPTY_SCHEMA),
                "async_ack",
            )
            self.component.async_register_entity_service(
                'unack',
                cv.make_entity_service_schema(EMPTY_SCHEMA),
                "async_unack",
            )
            self.component.async_register_entity_service(
                'manual_on',
                cv.make_entity_service_schema(EMPTY_SCHEMA),
                "async_manual_on",
            )
            self.component.async_register_entity_service(
                'manual_off',
                cv.make_entity_service_schema(EMPTY_SCHEMA),
                "async_manual_off",
            )
            async_register_admin_service(
                self._hass,
                DOMAIN,
                SERVICE_RELOAD,
                self.reload_service_handler,
            )
            
        await self.processConfig()

    async def shutdown_alerts(self):
        for aName in list(self.generators.keys()):
            await self.generators[aName].shutdown()
        # then event alerts
        for domain in list(self.tracked.keys()):
            names = list(self.tracked[domain].keys())
            for name in names:
                await self.tracked[domain][name].shutdown()
        # then condition alerts
        for domain in list(self.alerts.keys()):
            names = list(self.alerts[domain].keys())
            for name in names:
                await self.alerts[domain][name].shutdown()
    
    async def unload_alerts(self):
        for aName in list(self.generators.keys()):
            await self.undeclareAlert(self.generators[aName].alDomain, self.generators[aName].alName)
        # then event alerts
        for domain in list(self.tracked.keys()):
            names = list(self.tracked[domain].keys())
            for name in names:
                await self.undeclareAlert(domain, name)
        # then condition alerts
        for domain in list(self.alerts.keys()):
            names = list(self.alerts[domain].keys())
            for name in names:
                await self.undeclareAlert(domain, name)
        # then condition alerts
        # need to unload them so an alert is not unloaded until any alert it transitively supersedes has
        # been unloaded. This is to prevent notificaitons getting sent out between the two unloadings.
        #unloadList = self.supersedeMgr.topoOrdering()
        #for adn in unloadList:
        #    await self.undeclareAlert(adn[0], adn[1])
        #if self.alerts:
        #    report(DOMAIN, 'error', f'{gAssertMsg} Unloading alerts left some behind')
        
    async def reload_service_handler(self, service_call) -> None:
        """Reload yaml entities."""

        # TODO - the order of unloading and reloading could matter if there are alerts firing and
        # some supersede others.
        
        # First unload all entities. Start with generators since they'll remove condition alerts
        #
        # TODO - I think unload will generate an unavailable entity state.
        # would be nice to reload without doing that.
        await self.unload_alerts()
        _LOGGER.info('Lifecycle reload first removed all Alert2 alerts before reloading')
        
        conf = await self.component.async_prepare_reload(skip_reset=True)
        if conf is None:
            conf = {DOMAIN: {}}
        self._rawYamlConfig = conf[DOMAIN]
        await self.init2()
        # Redo prior calls to declareEventMulti() from other components
        if self.declEvMultiArr:
            await self.declareEventMulti(self.declEvMultiArr)
        self.binarySensorDict['hastarted']._attr_extra_state_attributes['last_reload_time'] = dt.now()
        self.binarySensorDict['hastarted'].async_write_ha_state()

    async def processConfig(self):
        # Validate the config in pieces. We want alert2 to successfully initialize no matter how messed up the config is.
        # And if the config has an error, to process the rest of itas much as it can.

        # We already tried processing the defaults section once. Report errors encountered.
        if self.earlyErrors:
            report(DOMAIN, 'error', f'{self.earlyErrors}')

        # Now check the rest of the config
        # TODO - this is redoing a bunch of work parsing templates.
        try:
            dCfg = TOP_LEVEL_SCHEMA(self._rawYamlConfig)
        except vol.Invalid as v:
            msg = f'top-level alert2 config: {v}'
            # If we reported errors already, then possible (probable), that they were in TOP_LEVEL_SCHEMA
            # validation, so avoid repeating the notificaiton here.  Just log it in case it was different.
            if self.earlyErrors:
                _LOGGER.error(msg)
            else:
                report(DOMAIN, 'error', msg)

        ents = await self.loadAlertBlock(self._rawYamlConfig)
        _LOGGER.info(f'Lifecycle created {len(ents)} alerts from YAML config')
        await self.uiMgr.declareAlerts()

        # If user has removed an alert from their YAML and reloaded/restarted,
        # we want to remove the entity registry entry so the alert entity doesn't show up in hass states as 'unavailable'
        # However, generators may take some time during startup or reload to regenerate entities
        # (eg if they depend on a sensor that takes time to initialize for some reason)
        # So delay the GC on startup or reload a bit
        self.delayGcRegistry()

    # stage 1 is for supersedes.  Stage 2 is to declare the alerts
    async def loadAlertBlock(self, aRawCfg):
        entities = []
        if 'tracked' in aRawCfg and isinstance(aRawCfg['tracked'], list):
            for obj in aRawCfg['tracked']:
                newEnt = None
                skipReport = False
                try:
                    aCfg = SINGLE_TRACKED_SCHEMA(obj)
                    if aCfg['domain'] == DOMAIN and aCfg['name'] in ['error', 'warning','global_exception']:
                        skipReport = True # already handled above
                    else:
                        newEnt = self.declareEventInt(aCfg)
                except vol.Invalid as v:
                    report(DOMAIN, 'error', f'tracked section of config: {v}. Relevant section: {obj}')
                    continue
                if isinstance(newEnt, Entity):
                    entities.append(newEnt)
                elif not skipReport:
                    report(DOMAIN, 'error', newEnt) # errMsg
        await self.component.async_add_entities(entities)
        for newEnt in entities:
            _LOGGER.debug(f'Lifecycle created alert {newEnt.entity_id}')

        if 'alerts' in aRawCfg and isinstance(aRawCfg['alerts'], list):
            for obj in aRawCfg['alerts']:
                newEnt = await self.declareAlert(obj)
                entities.append(newEnt)
        return entities
        
    # if doReport then return ent or None
    # if not doReport then return ent or errMsg string
    #
    # isBulk True means that either this is called during HA startup, or it's part of a reload and
    # someone will update last_reload_time
    async def declareAlert(self, obj, genVars=None, doReport=True, checkForUpdate=False):
        newEnt = None
        try:
            if 'trigger' in obj:
                aCfg = SINGLE_ALERT_SCHEMA_EVENT(obj)
                atrig = await trigger_helper.async_validate_trigger_config(self._hass, aCfg['trigger'])
                aCfg['trigger'] = atrig
                if checkForUpdate:
                    return None
                newEnt = self.declareEventInt(aCfg)
            else:
                aCfg = SINGLE_ALERT_SCHEMA_CONDITION(obj)
                if 'trigger_on' in aCfg:
                    aCfg['trigger_on'] = await trigger_helper.async_validate_trigger_config(self._hass, aCfg['trigger_on'])
                if 'trigger_off' in aCfg:
                    aCfg['trigger_off'] = await trigger_helper.async_validate_trigger_config(self._hass, aCfg['trigger_off'])
                if checkForUpdate:
                    return None
                if 'generator' in aCfg:
                    newEnt = self.declareGenerator(aCfg, rawConfig=obj)
                else:
                    newEnt = self.declareCondition(aCfg, genVars)
        except (vol.Invalid, HomeAssistantError) as v:
            errMsg = f'alerts section of config: {v}. Relevant section: {obj}'
            if doReport:
                report(DOMAIN, 'error', errMsg)
                return None
            else:
                return errMsg
        #_LOGGER.info(f'declareAlert: {isBulk} {newEnt}')
        if isinstance(newEnt, Entity):
            if isinstance(newEnt, AlertGenerator):
                await self.sensorComponent.async_add_entities([newEnt])
            else:
                await self.component.async_add_entities([newEnt])
            if genVars is None:
                _LOGGER.debug(f'Lifecycle created alert {newEnt.entity_id}')
            else:
                _LOGGER.info(f'Lifecycle created alert {newEnt.entity_id}')
            # notify uiMgr so can update display_msg watcher if appropriate
            #_LOGGER.warning(f'will call alertCreated: {"".join(traceback.format_stack())}')
            self.uiMgr.alertCreated(newEnt.alDomain, newEnt.alName)
        elif doReport:
            # Must be error message
            report(DOMAIN, 'error', newEnt)
            return None
        return newEnt

    # Returns err if alert does not exist
    async def undeclareAlert(self, domain, name, doReport=True, removeFromRegistry=False):
        #_LOGGER.info(f'undeclareAlert for {domain} {name}')
        ent = None
        if domain in self.alerts and name in self.alerts[domain]:
            self.supersedeMgr.removeNode(domain, name)
            ent = self.alerts[domain][name]
            del self.alerts[domain][name]
            if not self.alerts[domain]:
                del self.alerts[domain]
            _LOGGER.debug(f'Lifecycle undeclareAlert {ent.entity_id}')
            await self.component.async_remove_entity(ent.entity_id)
        elif domain in self.tracked and name in self.tracked[domain]:
            ent = self.tracked[domain][name]
            del self.tracked[domain][name]
            if not self.tracked[domain]:
                del self.tracked[domain]
            _LOGGER.debug(f'Lifecycle undeclareAlert {ent.entity_id}')
            await self.component.async_remove_entity(ent.entity_id)
        elif domain == GENERATOR_DOMAIN and name in self.generators:
            ent = self.generators[name]
            if removeFromRegistry:
                ent.setRegistryPurge()
            del self.generators[name]
            _LOGGER.debug(f'Lifecycle undeclareAlert {ent.entity_id}')
            await self.sensorComponent.async_remove_entity(ent.entity_id)
        else:
            errMsg = f'Trying to remove unknown alert domain={domain} name={name}'
            if doReport:
                report(DOMAIN, 'error', f'{gAssertMsg} {errMsg}')
            return errMsg

        if removeFromRegistry:
            entRegistry = entity_registry.async_get(self._hass)
            entId = ent.entity_id
            if entRegistry.async_is_registered(entId):
                _LOGGER.info(f'Removing undeclared registry entry for {entId}')
                entRegistry.async_remove(entId)
        
        return None

    def delayGcRegistry(self):
        if self.haStarted:
            self.delayGcRegistryInt()
        else:
            pass # Wait for haStartedEv to start gc
        
    def delayGcRegistryInt(self):
        if self.gcTask != None:
            self.gcTask.cancel()
        async def adelay():
            await asyncio.sleep(gGcDelaySecs)
            self.gcTask = None
            self.gcEntityRegistry()
        self.gcTask = create_background_task(self._hass, DOMAIN, adelay())

    # Only useful if you change how unique_id is generated
    def deepcleanEntityRegistry(self):
        entRegistry = entity_registry.async_get(self._hass)
        hassIds = self._hass.states.async_entity_ids(DOMAIN)
        for anId in hassIds:
            if entRegistry.async_is_registered(anId):
                _LOGGER.info(f'gcEntityRegistry: Removing registry entry for {anId}')
                entRegistry.async_remove(anId)
        hassIds = self._hass.states.async_entity_ids('sensor')
        for anId in hassIds:
            if anId.startswith('sensor.alert2generator_') and entRegistry.async_is_registered(anId):
                _LOGGER.info(f'gcEntityRegistry: Removing registry entry for {anId}')
                entRegistry.async_remove(anId)
        
    def gcEntityRegistry(self):
        #_LOGGER.info('gcEntityRegistry: Purging unused Alert2 registry entries')
        entRegistry = entity_registry.async_get(self._hass)

        # First purge old alert2.* entities
        knownIds = set()
        for domain in self.alerts:
            for name in self.alerts[domain]:
                knownIds.add(self.alerts[domain][name].entity_id)
        for domain in self.tracked:
            for name in self.tracked[domain]:
                knownIds.add(self.tracked[domain][name].entity_id)
        hassIds = self._hass.states.async_entity_ids(DOMAIN)
        for anId in hassIds:
            if not anId in knownIds and entRegistry.async_is_registered(anId):
                _LOGGER.info(f'gcEntityRegistry: Removing unused registry entry for {anId}')
                entRegistry.async_remove(anId)

        # Then purge old generators
        knownIds = set()
        for name in self.generators:
            knownIds.add(self.generators[name].entity_id)
        hassIds = self._hass.states.async_entity_ids('sensor')
        for anId in hassIds:
            if anId.startswith('sensor.alert2generator_') and not anId in knownIds and \
               entRegistry.async_is_registered(anId):
                _LOGGER.info(f'gcEntityRegistry: Removing unused registry entry for {anId}')
                entRegistry.async_remove(anId)
        
    def domainNameToId(self, domain, name):
        if domain in self.alerts and name in self.alerts[domain]:
            return self.alerts[domain][name].entity_id
        if domain in self.tracked and name in self.tracked[domain]:
            return self.tracked[domain][name].entity_id
        if domain == GENERATOR_DOMAIN and name in self.generators:
            return self.generators[name].entity_id
        return None
        
    def isSupersededByOn(self, domain, name):
        aset = self.supersedeMgr.supersededBySet(domain, name)
        for (tdomain, tname) in aset:
            if tdomain in self.alerts and tname in self.alerts[tdomain]:
                tent = self.alerts[tdomain][tname]
                if tent.state == 'on':
                    return (tdomain, tname)
        return False
    
    async def haStartedEv(self, event): # async so we're run in event loop
        # By the time EVENT_HOMEASSISTANT_STARTED has fired, the binary sensor should have initialized
        _LOGGER.debug(f'HA started')
        self.haStarted = True
        if self.binarySensorDict is not None:
            self.binarySensorDict['hastarted']._attr_is_on = True
            self.binarySensorDict['hastarted'].async_write_ha_state()
        self.delayGcRegistry()
        
    #def startShutdown(self, event):
    #    self._hass.loop.call_soon_threadsafe(self.shutdown)
    async def shutdown(self, event):
        set_shutting_down(True)
        await self.shutdown_alerts()
        if self.uiMgr:
            self.uiMgr.shutdown()
        for atask in global_tasks:
            atask.cancel()
            
    def setBinarySensorDict(self, adict):
        self.binarySensorDict = adict
        if self.haStarted:
            self.binarySensorDict['hastarted']._attr_is_on = True
            self.binarySensorDict['hastarted'].async_write_ha_state()

    # return errMsg or None if ok
    def checkNewName(self, domain, name):
        if domain in self.alerts:
            if name in self.alerts[domain]:
                return f'Duplicate declaration of alert for domain={domain} name={name}'
        if domain in self.tracked:
            if name in self.tracked[domain]:
                return f'Duplicate declaration of alert for domain={domain} name={name} (tracked)'
        if domain == GENERATOR_DOMAIN and name in self.generators:
            return f'Duplicate generator name={name}'
        if len(domain) == 0:
            return f'zero length domain with name="{name}"'
        if len(name) == 0:
            return f'zero length name with domain="{domain}"'
        return None
            
    # Declare a single event alert
    # Return errMsg or ent
    def declareEvent(self, domain, name):
        tmp_config = { 'domain' : domain, 'name': name }
        #if notifier is not None:
        #    tmp_config['notifier'] = notifier
        return self.declareEventInt(tmp_config)
    # Internal helper
    # NOTE - the validation code in UiMgr::updateAlert() assumes that
    # declareEventInt can't fail if the alert doesn't already exist.
    # so don't add any other error return paths here.
    def declareEventInt(self, config):
        domain = config['domain']
        name = config['name']
        errMsg = self.checkNewName(domain, name)
        if errMsg:
            return errMsg
        if not domain in self.tracked:
            self.tracked[domain] = {}
        entity = EventAlert(self._hass, self, config, self.topConfig)
        self.tracked[domain][name] = entity
        #self.notifiers.add(entity.notifier)
        return entity
    # declare single condition alert
    # NOTE - the validation code in UiMgr::updateAlert() assumes that
    # declareEventInt can't fail if the alert doesn't already exist.
    # so don't add any other error return paths here.
    def declareCondition(self, config, genVars=None):
        domain = config['domain']
        name = config['name']
        errMsg = self.checkNewName(domain, name)
        if errMsg:
            return errMsg

        supersedeList = config['supersedes'] if 'supersedes' in config else []
        if not self.supersedeMgr.addNode(domain, name, supersedeList):
            errMsg = f'Not creating alert with domain={domain} and name={name} because supersedes config would introduce cycle'
            return errMsg
        if not domain in self.alerts:
            self.alerts[domain] = {}
        entity = ConditionAlert(self._hass, self, config, self.topConfig, genVars=genVars)
        self.alerts[domain][name] = entity
        #self.notifiers.add(entity.notifier)
        return entity
        
    # NOTE - the validation code in UiMgr::updateAlert() assumes that
    # declareEventInt can't fail if the alert doesn't already exist.
    # so don't add any other error return paths here.
    def declareGenerator(self, config, rawConfig):
        domain = GENERATOR_DOMAIN
        name = config['generator_name']
        errMsg = self.checkNewName(domain, name)
        if errMsg:
            return errMsg
        entity = AlertGenerator(self._hass, self, config, rawConfig)
        self.generators[name] = entity
        return entity
        
    # declare multiple event alerts, and also unhandled_exception
    async def declareEventMulti(self, arr):
        entities = []
        for x in arr:
            ent = self.declareEvent(x['domain'], x['name'])
            if isinstance(ent, Entity):
                entities.append(ent)
            else:
                report(DOMAIN, 'error', ent) # ent is errMsg
            domain = x['domain']
            if domain not in self.tracked or 'unhandled_exception' not in self.tracked[domain]:
                ent2 = self.declareEvent(x['domain'], 'unhandled_exception')
                if isinstance(ent, Entity):
                    entities.append(ent2)
                else:
                    report(DOMAIN, 'error', ent2) # ent is errMsg
        self.declEvMultiArr = self.declEvMultiArr + arr
        await self.component.async_add_entities(entities)
        for ent in entities:
            _LOGGER.debug(f'Lifecycle created alert {ent.entity_id}')
        
    async def ackAll(self, call):
        _LOGGER.info(f'Activity ackAll called')
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
    async def handle_report_int(self, evdata, tmsg):
        self._hass.verify_event_loop_thread(f'checking in handle_report_int for {tmsg}')

        # Grrr, have to manually validate evdata because voluptuous mutates a dict while validating and
        # the evdata passed with a service call is immutable.
        if not 'domain' in evdata or not isinstance(evdata['domain'], str):
            report(DOMAIN, 'error', f'malformed call {tmsg} missing/non-string "domain" {evdata}')
            return
        if not 'name' in evdata or not isinstance(evdata['name'], str):
            report(DOMAIN, 'error', f'malformed call {tmsg} missing/non-string "name" {evdata}')
            return
        domain = evdata['domain']
        name = evdata['name']
        if self.topConfig['skip_internal_errors']:
            if domain == DOMAIN and name in ['error', 'warning', 'global_exception']:
                # The internal error was logged back up in report(), so no need to log again
                return
        
        if not domain in self.tracked or not name in self.tracked[domain]:
            errmsg = f'domain={domain} name={name} (from {tmsg})'
            report(DOMAIN, 'error', f'undeclared event {errmsg}. Creating event alert')
            alertObj = self.declareEvent(domain, name)
            if isinstance(alertObj, Entity):
                await self.component.async_add_entities([alertObj])
            else:
                report(DOMAIN, 'error', alertObj) # errMsg
        else:
            alertObj = self.tracked[domain][name]

        message = ''
        if 'message' in evdata:
            if not isinstance(evdata['message'], str):
                report(DOMAIN, 'error', f'Malformed call {tmsg} non-string "message" {evdata}')
                return
            message = evdata['message']
        data = None
        if 'data' in evdata:
            if not isinstance(evdata['data'], dict):
                report(DOMAIN, 'error', f'Malformed call {tmsg} non-dict "data" {evdata}')
                return
            data = evdata['data']
        await alertObj.record_event(message, extra_data=data)
        # TODO - I'm not sure this line does anythign, and probably is wrong.
        self.inHandler = False

