import ast
import asyncio
import datetime as rawdt
from   enum import Enum
import logging
from   typing import Any
import voluptuous as vol
from   homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED
)
import homeassistant.helpers.config_validation as cv
from   homeassistant.helpers.entity import Entity
from   homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.const as haConst
from   homeassistant.core import HomeAssistant, Context, callback, Event, EventStateChangedData
from   homeassistant.exceptions import TemplateError, ServiceNotFound, HomeAssistantError
from   homeassistant.helpers import template as template_helper
from   homeassistant.helpers.event import TrackTemplate, TrackTemplateResult, async_track_template_result
from   homeassistant.helpers.trigger import async_initialize_triggers
from   homeassistant.components.binary_sensor import BinarySensorDeviceClass
from   homeassistant.components.sensor import SensorDeviceClass, SensorEntity
import homeassistant.util.dt as dt

from .util import (
    create_task,
    create_background_task,
    cancel_task,
    report,
    DOMAIN,
    GENERATOR_DOMAIN,
    gAssertMsg,
    EVENT_ALERT2_CREATE,
    EVENT_ALERT2_DELETE,
    EVENT_ALERT2_FIRE,
    EVENT_ALERT2_ON,
    EVENT_ALERT2_OFF,
)
from .config import ( literalIllegalChar )

_LOGGER = logging.getLogger(__name__)

class NotificationReason(Enum):
    Fire = 1
    ReminderOn = 2
    StopFiring = 3
    Summary = 4
    SnoozeEnded = 5
class ThresholdExeeded(Enum):
    Init = 1
    Max = 2
    Min = 3
NOTIFICATIONS_ENABLED  = 'enabled'
NOTIFICATIONS_DISABLED = 'disabled'

# return a string x, st, jinja2.Template(x).render() == astr
# message field in components/notify/const.py:NOTIFY_SERVICE_SCHEMA is a template and will be rendered
# That is, even though notifications comopnent complains about passing templates to notify, it still calls render()
# and so to get a straight message through you have to jinja2Escape it.
def jinja2Escape(astr):
    a2str = astr.replace('{%', '{% endraw %}{{"{%"}}{% raw %}')
    return '{% raw %}' + a2str + '{% endraw %}'

class MovingSum:
    """This class tracks how many alert firings have happened in the last inverval_mins.
    """
    def __init__(self, amax, interval_mins):
        self.maxCount = amax
        self.intervalSecs = interval_mins * 60
        self.numBuckets = 10
        # First bucket is most recent
        self.buckets = [0]*self.numBuckets
        self.singleBucketSecs = self.intervalSecs / self.numBuckets
        self.lastAdvanceTime = None
        #self.cacheKnowUnderLimit = True

    def reportFire(self, now):
        self._updateBuckets(now)
        self.buckets[0] += 1
        if self.lastAdvanceTime is None:
            self.lastAdvanceTime = now

    # Invariant after _updateBuckets() call is either
    # self.lastAdvanceTime is not None:
    #    in which case it is less than singleBucketHours older than now
    #    and sum(self.buckets) > 0
    # or self.lastAdvanceTime is None
    #    in which case sum(self.buckets) == 0
    def _updateBuckets(self, now):
        currSum = sum(self.buckets)
        if currSum == 0:
            self.lastAdvanceTime = None
            return
        if not self.lastAdvanceTime:
            report(DOMAIN, 'error', f'{gAssertMsg} MovingAvg no lastAdvanceTime but buckets not empty {currSum}')
            self.lastAdvanceTime = now
        secsSinceLastAdvance = (now - self.lastAdvanceTime).total_seconds()
        bucketAdvancesSinceLast = secsSinceLastAdvance / self.singleBucketSecs
        if bucketAdvancesSinceLast < 1:
            return
        bucketAdvancesSinceLastInt = int(bucketAdvancesSinceLast)
        numAdvances = min(self.numBuckets, bucketAdvancesSinceLastInt)
        self.buckets = [0]*numAdvances + self.buckets[:-numAdvances]
        if len(self.buckets) != self.numBuckets:
            report(DOMAIN, 'error', f'{gAssertMsg} MovingAvg bucket update logic produced wrong length {self.numBuckets} vs {self.buckets}')
            self.buckets = [0]*self.numBuckets
        newSum = sum(self.buckets)
        if newSum == 0:
            self.lastAdvanceTime = None
            return
        self.lastAdvanceTime = self.lastAdvanceTime + rawdt.timedelta(seconds=(bucketAdvancesSinceLastInt*self.singleBucketSecs))
        if (now - self.lastAdvanceTime).total_seconds() > self.singleBucketSecs:
            report(DOMAIN, 'error', f'{gAssertMsg} MovingAvg _updateBuckets left more than a single bucket interval of time left')
        return

    # Return number of seconds remaining until the number of alert fires reported in the last interval_mins has dropped below
    # the threshold.
    def remainingSecs(self, now):
        self._updateBuckets(now)
        acumm = 0
        # Calculate idx to be the first bucket that needs to rotate out to bring total down to <= max
        for idx in range(self.numBuckets):
            acumm += self.buckets[idx]
            if acumm > self.maxCount:
                break
            # There's room for more firings, so move to next bucket
        if acumm <= self.maxCount:
            return 0
        # Seconds to wait if we're at the beginning of a bucket interval right now
        secsToWait = (self.numBuckets - idx) * self.singleBucketSecs

        # Account for the fact that we are partially through a bucket advance interval
        if not self.lastAdvanceTime:
            report(DOMAIN, 'error', f'{gAssertMsg} MovingAvg not empty but somehow missing bucketAdvanceTime')
            return 0
        intervalSecsElapsed = (now - self.lastAdvanceTime).total_seconds()
        secsToWait = secsToWait - intervalSecsElapsed
        #secsToWait = secsToWait + 5
        if secsToWait < 0:
            report(DOMAIN, 'error', f'{gAssertMsg} MovingAvg secsToWait produced negative: {secsToWait}')
            return 60
        return secsToWait

def getField(fieldName, config, defaults):
    if fieldName in config:
        return config[fieldName]
    elif fieldName in defaults:
        return defaults[fieldName]
    else:
        raise vol.Invalid(f'Alert {config["domain"]},{config["name"]} config or defaults must specify {fieldName}')

def agoStr(secondsAgo):
    if secondsAgo < 1.5*60:
        astr = f'{round(secondsAgo)} s'
    elif secondsAgo < 1.5*60*60:
        astr = f'{round(secondsAgo/60)} min'
    elif secondsAgo < 1.5*24*60*60:
        astr = f'{round(secondsAgo/(60*60))} h'
    else:
        astr = f'{round(secondsAgo/(24*60*60))} d'
    return astr

# components/group/notify.py::GroupNotifyPlatform does not handle exceptions if one of the notifiers
# does not (yet) exist.  https://github.com/home-assistant/core/issues/130549
# So we gotta do a check ourselves

def entNameFromDN(domain, name):
    return f'{domain}_{name}'

def renderResultToList(arez):
    if len(arez) == 0:
        return []
    #elif isinstance(arez, list):
    #    return arez
    else:
        try:
            literalList = ast.literal_eval(arez)
        except Exception as ex:  # literal_eval can throw various kinds of exceptions
            literalList = arez
        # might not be [ str ], will check below.
        return literalList if isinstance(literalList, list) else [ literalList ]


class TriggerCond:
    # await cb() is invoked if trigger fires and condition is truthy
    def __init__(self, parentEnt, trigName, hass, alertData, cb, extraVariables, triggerConf, condTempl):
        # Base class - common to TriggerCond and Tracker
        self.hass = hass
        self.alertData = alertData
        self._self_ref_update_count = 0
        self.parentEnt = parentEnt
        if not isinstance(parentEnt, Entity):
            report(DOMAIN, 'error', f'{gAssertMsg} parentEnt type={type(parentEnt)}')
        #self.trigName = trigName
        self.fullName = f'{parentEnt.name}::{trigName}'
        self.cb = cb
        self.extraVariables = extraVariables

        # Subclass?
        self.triggerConf = triggerConf
        self.condTempl = condTempl
        self.detach_trigger = None

    def shutdown(self):
        if self.detach_trigger:
            self.detach_trigger()
            self.detach_trigger = None

    async def startWatching(self):
        def log_cb(level: int, msg: str, **kwargs: Any) -> None:
            _LOGGER.log(level, "%s %s", self.fullName, msg, **kwargs)
        # TODO - support triggering on HA start, like components/automation/__init__.py:async_enable does
        #
        # I think home_assistant_start is something about the event when HA starts. I think it's just
        # used by triggers on the homeassistant itself, like when it starts up or shuts down.  I'm a bit fuzzy on this,
        # but it seems not applicable to our use case.
        home_assistant_start = False # TODO - supp
        # A chunk of this is based on homeassistant/components/automation/__init__.py::_async_attach_triggers
        this = None
        if state := self.hass.states.get(self.parentEnt.entity_id):
            this = state.as_dict()
        variables = {"this": this}
        self.detach_trigger = await async_initialize_triggers(
            self.hass,
            self.triggerConf,
            self.async_trigger,
            self.parentEnt.alDomain,
            self.fullName,
            log_cb,
            home_assistant_start,
            variables,
        )
    # I think skip_condition is from triggers in automations, where, when you forcibly invoke the automation via the
    # front-end, you may want to bypass any condition logic that gates the automation.
    # In our context, we never want to skip the condition, so we ignore it.
    # see also homeassistant/components/automation/__init__.py
    #
    # EventAlert is used both for event alerts with a condition&trigger, as well as
    # declared alerts that only fire in response to a report()
    # async_trigger is only called by EventAlerts triggering
    async def async_trigger(
        self,
        run_variables: dict[str, Any],
        context: Context | None = None,
        skip_condition: bool = False,
    ) -> None:
        reason = ""
        alias = ""
        if "trigger" in run_variables:
            if "description" in run_variables["trigger"]:
                reason = f' by {run_variables["trigger"]["description"]}'
            if "alias" in run_variables["trigger"]:
                alias = f' trigger \'{run_variables["trigger"]["alias"]}\''
                _LOGGER.debug(f'Activity {self.fullName} triggered{reason}{alias}')

        this = self.parentEnt.state
        variables: dict[str, Any] = {"this": this, **(run_variables or {})}
        if self.extraVariables:
            variables.update(self.extraVariables)

        if self.condTempl:
            try:
                # self._condition_template ok to reference cause condition required in the config schema for events
                rez = self.condTempl.async_render(variables, parse_result=False)
            except TemplateError as err:
                report(DOMAIN, 'error', f'{self.fullName} condition template: {err}')
                return
            try:
                # result_as_boolean converts vol.Invalid to False
                #brez = template_helper.result_as_boolean(rez)
                brez = cv.boolean(rez)
            except vol.Invalid as err:
                report(DOMAIN, 'error', f'{self.fullName} condition template rendered to "{rez}", which is not truthy (e.g., "true", "on" or opposites) template="{self.condTempl.template}"')
                return
        else:
            brez = True

        if brez:
            await self.cb(variables)
        else:
            pass

# cfgList = [ { fieldName, type, template }, .. ]
class Tracker:
    class Type(Enum):
        Bool = 1
        Str  = 2
        StrEmptyOk  = 3
        Float = 4
        List = 5
    def __init__(self, parentEnt, sname, hass, alertData, cfgList, cb, extraVariables):
        self.hass = hass
        self.alertData = alertData
        self.cfgList = cfgList
        self.trackerInfo = None
        self._self_ref_update_count = 0
        self.parentEnt = parentEnt
        if not isinstance(parentEnt, Entity):
            report(DOMAIN, 'error', f'{gAssertMsg} parentEnt type={type(parentEnt)}')
        self.fullName = f'{parentEnt.name}::{sname}'
        self.cb = cb
        self.extraVariables = extraVariables

    def shutdown(self):
        if self.trackerInfo:
            self.trackerInfo.async_remove()
            self.trackerInfo = None
    def refresh(self):
        self.trackerInfo.async_refresh()

    def startWatching(self):
        trackers = []
        for x in self.cfgList:
            if isinstance(x['template'], template_helper.Template):
                pass#trackers.append(TrackTemplate(x['template'], self.extraVariables))
            else:
                # So we have a literal of some kind.
                # Well convert it to a string, then template-ify it.
                # just so the same code path is used to get the literal back.
                # a bit wasteful.
                x['template'] = template_helper.Template(str(x['template']), self.hass)
            trackers.append(TrackTemplate(x['template'], self.extraVariables))
        #trackers = [ TrackTemplate(x['template'], self.extraVariables) for x in self.cfgList ]
        # We use async_track_template_result rather than a higher-level form,
        # components/template/template_entity:TemplateEntity
        # because TemplateEntity only starts working once HA has completely started
        # and we'd like the option of starting watching while HA is starting.
        info = async_track_template_result(
            self.hass,
            trackers,
            self._result_cb,
        )
        self.trackerInfo = info
        #self.async_on_remove(info.async_remove)  # stop template listeners if ConditionAlert is removed from hass. from helpers/entity.py
        info.async_refresh() # components/template/temlate_entity.py does this, so I guess we will, though this may not be necessary per docs of async_track_template_result

    @callback
    def _result_cb(self,
                   event: Event[EventStateChangedData] | None,
                   updates: list[TrackTemplateResult]) -> None:
        if event:
            self.parentEnt.async_set_context(event.context)
        entity_id = event and event.data["entity_id"]
        _LOGGER.debug(f'{self.fullName} template result cb for entity_id={entity_id}')
        # This is how componnents/template/template_entity.py does cycle detection
        if entity_id and entity_id == self.parentEnt.entity_id:
            self._self_ref_update_count += 1
        else:
            self._self_ref_update_count = 0
        if self._self_ref_update_count > 2:
            upStr = ','.join([ x['fieldName'] for x in self.cfgList ])
            report(DOMAIN, 'error', f'{self.fullName} detected template loop. event={event}, updates for [{upStr}]. Skipping render')
            return

        tresults = [None for x in self.cfgList]
        for update in updates:
            template = update.template
            result = update.result
            try:
                cfgIdx = next(i for i,v in enumerate(self.cfgList) if v['template'] == template)
            except StopIteration:
                report(DOMAIN, 'error', f'{gAssertMsg} {self.fullName} template not found: {template} with result={result}')
                return
            cfg = self.cfgList[cfgIdx]
            if isinstance(result, TemplateError):
                report(DOMAIN, 'error', f'{self.fullName} {cfg["fieldName"]} template threw error: {result}')
                return
            if result is None:
                report(DOMAIN, 'error', f'{self.fullName} {cfg["fieldName"]} template returned None')
                return
            # async_track_template_result tracks the result with parse_result=True,
            # which calls _cached_parse_result, which does some type conversion that
            # are unecessary and probably risky.
            # TODO - make async_track_template_result take a parse_result arg
            #tresults[cfgIdx] = result

        # Now rerender templates that did not get an update.  I suppose we could cache the values
        for idx, val in enumerate(tresults):
            if tresults[idx] is None:
                try:
                    aresult = self.cfgList[idx]['template'].async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'error', f'{self.fullName} {self.cfgList[idx]["fieldName"]} template: {err}')
                    return
                tresults[idx] = aresult
            if not isinstance(tresults[idx], str):
                report(DOMAIN, 'error', f'{gAssertMsg} {self.fullName} {self.cfgList[idx]["fieldName"]} rendered to {type(tresults[idx])} rather than string')
                return
        resultStrs = [x for x in tresults]  # async_render always strips as does I think async_track_template_result
        #resultStrs = [x.strip() for x in tresults]

        # Now type convert the results
        results = [ None for x in resultStrs ]
        for idx, val in enumerate(resultStrs):
            ttype = self.cfgList[idx]['type']
            if ttype in [ Tracker.Type.Str, Tracker.Type.StrEmptyOk ]:
                rez = str(resultStrs[idx]) # I don't think this conversion can fail
                if len(rez) == 0 and ttype == Tracker.Type.Str:
                    report(DOMAIN, 'error', f'{self.fullName} {self.cfgList[idx]["fieldName"]} template rendered to empty string')
                    return
                results[idx] =  rez
            elif ttype == Tracker.Type.Bool:
                try:
                    # result_as_boolean converts vol.Invalid to False
                    #abool = template_helper.result_as_boolean(resultStrs[idx])
                    abool = cv.boolean(resultStrs[idx])
                except vol.Invalid as err:
                    report(DOMAIN, 'error', f'{self.fullName} {self.cfgList[idx]["fieldName"]} template rendered to "{resultStrs[idx]}", which is not truthy (e.g., "true", "on" or opposites) template="{self.cfgList[idx]["template"].template}"')
                    return
                results[idx] = abool
            elif ttype == Tracker.Type.Float:
                try:
                    afloat = float(resultStrs[idx])
                except ValueError:
                    report(DOMAIN, 'error', f'{self.fullName} {self.cfgList[idx]["fieldName"]} template rendered to "{resultStrs[idx]}" rather than a float')
                    return
                results[idx] = afloat
            elif ttype == Tracker.Type.List:
                results[idx] = renderResultToList(resultStrs[idx])

        self.cb(results)


def generatorElemToVars(hass, elem):
    svars = {'genRaw': elem }
    if isinstance(elem, dict):
        svars.update(elem)
    elif hass.states.get(elem):
        svars['genEntityId'] = elem
    else:
        svars['genElem'] = elem
    return svars

class AlertCommon(Entity):
    _attr_should_poll = False
    def __init__(self, hass, alertData, config):
        super().__init__()
        self.hass = hass
        self.alertData = alertData
        self.earlyStart = config['early_start'] if 'early_start' in config else False
        # self.alDomain and self.alName defined by children

    async def addedToHassDone(self):
        self.hass.bus.async_fire(EVENT_ALERT2_CREATE, { 'entity_id': self.entity_id,
                                                         'domain': self.alDomain,
                                                         'name': self.alName })
        if self.earlyStart or self.alertData.haStarted:
            await self.startWatching()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.startWatchingEv)
    async def startWatchingEv(self, event): # async so we run in event loop
        await self.startWatching()

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        self.hass.bus.async_fire(EVENT_ALERT2_DELETE, { 'entity_id': self.entity_id,
                                                         'domain': self.alDomain,
                                                         'name': self.alName })

class AlertGenerator(AlertCommon, SensorEntity):
    _attr_device_class = SensorDeviceClass.DATA_SIZE #'problem'
    #_attr_available = True  defaults to True
    def __init__(self, hass, alertData, config, rawConfig):
        AlertCommon.__init__(self, hass, alertData, config)
        SensorEntity.__init__(self)
        # super().__init__()
        self.config = config
        self.rawConfig = rawConfig
        self._attr_name = entNameFromDN(GENERATOR_DOMAIN, self.config["generator_name"])
        self._attr_unique_id = self._attr_name
        self.alDomain = GENERATOR_DOMAIN
        self.alName = self.config["generator_name"]
        self._generator_template = self.config['generator']
        self.tracker = Tracker(self, 'generator', hass, alertData,
                               [ { 'fieldName': 'generator', 'type': Tracker.Type.List,
                                   'template': self._generator_template } ], self.update_rez, extraVariables=None)

        # "name" here is overloaded. There's the 'name' from the domain+name specified in an alert config
        # then there's the 'name' that is the HA entity's name property.
        # Here we're using the entity name
        self.nameEntityMap = {} # Map from name -> ent

    @property
    def state(self) -> str:
        return len(self.nameEntityMap)
    @property
    def extra_state_attributes(self):
        return { 'generated_ids': [ ent.entity_id for ent in self.nameEntityMap.values() ] }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.addedToHassDone()
    async def startWatching(self):
        #await super().startWatching()  - parent class has no startWatching
        self.tracker.startWatching()

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        self.tracker.shutdown()
        for ent in self.nameEntityMap.values():
            await self.alertData.undeclareAlert(ent.alDomain, ent.alName) # destroys ent
        self.nameEntityMap = {}

    async def async_update(self):
        await super().async_update()
        self.tracker.async_refresh()

    def update_rez(self, results):
        create_task(self.hass, DOMAIN, self.async_update_rez(results))
    async def async_update_rez(self, results):
        alist = results[0]

        # Now see if entities are added or deleted
        needWrite = False
        currNames = set() # entity names (ie the part after alert2.)
        sawError = False
        for elem in alist:
            if not (isinstance(elem, str) or isinstance(elem, dict)):
                report(DOMAIN, 'error', f'{self.name} generator produced non-string or dict element "{elem}" of type {type(elem)}')
                sawError = True
                break
            svars = generatorElemToVars(self.hass, elem)

            try:
                nameStr = self.config['name'].async_render(variables=svars, parse_result=False).strip()
            except TemplateError as err:
                report(DOMAIN, 'error', f'{self.name} Name template returned err {err}')
                sawError = True
                break
            try:
                domainStr = self.config['domain'].async_render(variables=svars, parse_result=False).strip()
            except TemplateError as err:
                report(DOMAIN, 'error', f'{self.name} Domain template returned err {err}')
                sawError = True
                break
            entName = entNameFromDN(domainStr, nameStr)
            currNames.add(entName)
            if entName in self.nameEntityMap:
                # entity continues to exist
                pass
            else:
                # new entity added
                if len(entName) == 0:
                    report(DOMAIN, 'error', f'{self.name} Domain+Name template rendered to empty string')
                    sawError = True
                    break
                if len(domainStr) == 0 or literalIllegalChar(domainStr):
                    report(DOMAIN, 'error', f'{self.name} Domain template rendered to "{domainStr}" which is either empty or has illegal characters (like ' + '[]{}"\')')
                    sawError = True
                    break
                if len(nameStr) == 0 or literalIllegalChar(nameStr):
                    report(DOMAIN, 'error', f'{self.name} Name template rendered to "{nameStr}" which is either empty or has illegal characters (like ' + '[]{}"\')')
                    sawError = True
                    break
                # very shallow copy, don't copy object values
                # Also, use rawConfig so we don't double interpret the config dict.
                acfg = dict(self.rawConfig)
                acfg['domain'] = domainStr
                acfg['name'] = nameStr
                del acfg['generator']
                del acfg['generator_name']
                #if 'friendly_name' in self.config:
                #    try:
                #        friendlyNameStr = self.config['friendly_name'].async_render(
                #            variables=svars, parse_result=False).strip()
                #        acfg['friendly_name'] = friendlyNameStr
                #    except TemplateError as err:
                #        report(DOMAIN, 'error', f'{self.name} Friendly_name template returned err {err}')
                #        sawError = True
                #        break
                _LOGGER.info(f'Generator {self.name} creating alert: {acfg} with vars {svars}')
                ent = await self.alertData.declareAlert(acfg, genVars=svars)
                if ent is None:
                    sawError = True
                    break
                else:
                    self.nameEntityMap[entName] = ent
                    needWrite = True

        if not sawError:
            # If we saw an error while processing templates, we might be missing entities
            # so don't do any deletions
            for aname in list(self.nameEntityMap.keys()):
                if not aname in currNames:
                    # entity no longer in list
                    ent = self.nameEntityMap[aname]
                    _LOGGER.info(f'Lifecycle generator {self.name} removing alert {ent.entity_id}')
                    #await ent.async_remove() # I think this is the complement of async_add_entities
                    await self.alertData.undeclareAlert(ent.alDomain, ent.alName) # destroys ent
                    del self.nameEntityMap[aname]
                    needWrite = True
        if needWrite:
            self.async_write_ha_state()


def notifierTemplateToList(hass, extraVariables, templOrList, sourceTemplate):
    errors = []
    debugInfo = []
    if isinstance(templOrList, list):
        tnotifiers = templOrList
        # config did some validation that it's list of non-empty strings
    else:
        try:
            renderRez = templOrList.async_render(variables=extraVariables, parse_result=False).strip()
        except TemplateError as err:
            errors.append(f'{sourceTemplate} template: {err}')
            tnotifiers = []
            # Continue and notify anyways
        else:
            debugInfo.append(f'{sourceTemplate} template="{templOrList}"')
            debugInfo.append(f'rendered="{renderRez}"')
            toEval = renderRez
            tstate = hass.states.get(renderRez)
            if tstate is not None:
                toEval = tstate.state
                debugInfo.append(f'state="{toEval}"')
            try:
                literalList = ast.literal_eval(toEval)
            except Exception as ex:  # literal_eval can throw various kinds of exceptions
                # Could just be a literal notifier name, like 'foo'
                # or could be real issue, like '[ "foo"'  (missing trailing bracket)
                # we assume the best, and treat it like a literal notifier name.
                # If it's not, then we'll get an error of notifier not existing
                literalList = toEval
            # might not be [ str], will check below.
            tnotifiers = literalList if isinstance(literalList, list) else [ literalList ]

    notifiers = []
    for anotifier in tnotifiers:
        if not isinstance(anotifier, str):
            errors.append(f'a {sourceTemplate} is not a string but {type(anotifier)}: "{anotifier}"')
        elif len(anotifier) == 0:
            errors.append(f'a {sourceTemplate} cannot be the empty string')
        elif literalIllegalChar(anotifier):
            errors.append(f'a {sourceTemplate} single element has illegal characters (e.g., "[" or "\'"): "{anotifier}"')
        else:
            notifiers.append(anotifier)
    return (notifiers, errors, debugInfo)

# Functionality common to both event alerts and condition alerts
#
# Startup procedure is:
#    Final call to async_added_to_hass in child calls super().startup()
#       that checks early_start, or waits for ha started, then calls startWatching()
#    Shutdown is done by async_will_remove_from_hass

class AlertBase(AlertCommon, RestoreEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM #'problem'
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults: dict[str, Any],
            genVars = None
    ):
        AlertCommon.__init__(self, hass, alertData, config)
        RestoreEntity.__init__(self)
        # super().__init__()
        self.alDomain = config['domain']
        self.alName = config['name']
        self._attr_name = entNameFromDN(self.alDomain, self.alName)
        self._attr_unique_id = self._attr_name

        # config stuff
        self._notifier_list_template = getField('notifier', config, defaults)
        self._summary_notifier = getField('summary_notifier', config, defaults)
        self._priority = getField('priority', config, defaults)
        self._condition_template = config['condition'] if 'condition' in config else None
        self._message_template = config['message'] if 'message' in config else None
        self._done_message_template = config['done_message'] if 'done_message' in config else None
        self._title_template = config['title'] if 'title' in config else None
        self._target_template = config['target'] if 'target' in config else None
        self._data = config['data'] if 'data' in config else None
        self._display_msg_template = config['display_msg'] if 'display_msg' in config else None
        if genVars is not None:
            self.extraVariables = genVars
        else:
            self.extraVariables = None
        self._friendly_name = None
        self.friendlyNameTracker = None
        if 'friendly_name' in config:
            frn = config['friendly_name']
            # Since friendly_name may be displyed quite early, so if we aren't using templates, then
            # directly process it
            if template_helper.is_template_string(frn.template):
                self.friendlyNameTracker = Tracker(self, 'friendly_name', hass, alertData,
                                                   [ { 'fieldName': 'friendly_name', 'type': Tracker.Type.Str,
                                                       'template': frn } ], self.friendly_name_update, self.extraVariables)
            else:
                self._friendly_name = frn.template.strip()
        # else _friendly_name is None
        if self._message_template is not None:
            self._message_template.hass = hass
        if self._done_message_template is not None:
            self._done_message_template.hass = hass
        if self._title_template is not None:
            self._title_template.hass = hass
        if self._target_template is not None:
            self._target_template.hass = hass
        if self._notifier_list_template is not None and not isinstance(self._notifier_list_template, list):
            self._notifier_list_template.hass = hass
        if isinstance(self._summary_notifier, template_helper.Template):
            self._summary_notifier.hass = hass
        self.annotate_messages = getField('annotate_messages', config, defaults)
        throttle_fires_per_mins = getField('throttle_fires_per_mins', config, defaults)
        self.movingSum = None
        if throttle_fires_per_mins is not None:
            self.movingSum = MovingSum(throttle_fires_per_mins[0], throttle_fires_per_mins[1])
        self.notified_max_on = False

        # State restored on restart
        #
        self.last_notified_time = None
        self.last_tried_notify_time = None
        self.last_fired_time = None
        self.last_fired_message = None
        self.last_ack_time = None
        self.fires_since_last_notify = 0  # or since last ack
        # enabled, disabled, or snooze unti time
        self.notification_control = NOTIFICATIONS_ENABLED

        self.future_notification_info = None

    async def startWatching(self):
        #await super().startWatching()  not in parent class
        if self.friendlyNameTracker:
            self.friendlyNameTracker.startWatching()

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self.friendlyNameTracker:
            self.friendlyNameTracker.shutdown()
        self._attr_available = False
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
            self.future_notification_info = None

    async def async_added_to_hass(self) -> None:
        """Restore extra state attributes on start-up."""
        await super().async_added_to_hass()

        # NOTE - RestoreEntity only saves state every 15 minutes (STATE_DUMP_INTERVAL)
        # So HA looses last 15min of alert firing information when it restarts.
        last_state = await self.async_get_last_state()
        if last_state:
            if 'last_notified_time' in last_state.attributes and last_state.attributes['last_notified_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_notified_time'])
                if not self.last_notified_time or tdate > self.last_notified_time:
                    self.last_notified_time = tdate
            if 'last_tried_notify_time' in last_state.attributes and last_state.attributes['last_tried_notify_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_tried_notify_time'])
                if not self.last_tried_notify_time or tdate > self.last_tried_notify_time:
                    self.last_tried_notify_time = tdate
            if 'last_fired_time' in last_state.attributes and last_state.attributes['last_fired_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_fired_time'])
                if not self.last_fired_time or tdate > self.last_fired_time:
                    self.last_fired_time = tdate
                    if 'last_fired_message' in last_state.attributes:
                        self.last_fired_message = last_state.attributes['last_fired_message']
                    if 'fires_since_last_notify' in last_state.attributes:
                        self.fires_since_last_notify = int(last_state.attributes['fires_since_last_notify'])
                    # Grouped within last_fired_time since notified_max_on turns on only in response to a firing
                    if 'notified_max_on' in last_state.attributes:
                        self.notified_max_on = int(last_state.attributes['notified_max_on'])
            if 'last_ack_time' in last_state.attributes and last_state.attributes['last_ack_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_ack_time'])
                if not self.last_ack_time or tdate > self.last_ack_time:
                    self.last_ack_time = tdate
            # If notification_control is set after startup but before async_added_to_hass
            # is called, then we'll overwrite it here.  TODO - improve this logic
            if 'notification_control' in last_state.attributes:
                val = last_state.attributes['notification_control']
                if val:
                    if val in [ NOTIFICATIONS_DISABLED, NOTIFICATIONS_ENABLED ]:
                        self.notification_control = val
                    else:
                        self.notification_control = dt.parse_datetime(val)
        # child class calls addedToHassDone

    async def async_update(self) -> None:
        await super().async_update()
        if self.friendlyNameTracker:
            self.friendlyNameTracker.refresh()
    def friendly_name_update(self, results):
        newname = results[0]
        if newname != self._friendly_name:
            self._friendly_name = newname
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        baseDict = {
            'icon': 'mdi:alert',
            'custom_ui_more_info' : 'more-info-alert2',
            "custom_ui_state_card": 'state-card-alert2',
            'last_notified_time': self.last_notified_time,
            'last_fired_time': self.last_fired_time,
            'last_fired_message': self.last_fired_message,
            'last_ack_time': self.last_ack_time,
            'friendly_name2': self._friendly_name, # Entity class defines "friendly_name" so we have to use something different.
            'fires_since_last_notify': self.fires_since_last_notify,
            'notified_max_on': self.notified_max_on,
            'notification_control': self.notification_control,
            'domain': self.alDomain,
            'name': self.alName,
            'has_display_msg': (self._display_msg_template is not None),
        }
        baseDict.update(self.more_state_attributes())
        return baseDict

    def notify_timer_cb(self, now):
        assert False, "not implemented"
    def sub_need_reminder(self):
        assert False, "not implemented"
    def sub_ack_int(self):
        assert False, "not implemented"

    async def async_notification_control(
        self, enable: bool, snooze_until: rawdt.datetime | None = None
    ) -> None:
        _LOGGER.info(f'Activity {self.entity_id} got async_notification_control with enable={enable} and snooze_until={snooze_until}')
        if enable:
            if snooze_until:
                if snooze_until.tzinfo is None or snooze_until.tzinfo.utcoffset(snooze_until) is None:
                    report(DOMAIN, 'error', f'{gAssertMsg} Notification control call has snooze time specified without timezone info: {snooze_until} for {self.name}')
                # javascript in the browser converts the local time generated to UTC when sending on the wire.
                # convert back to local time.
                new_snooze = dt.as_local(snooze_until)
            else:
                new_snooze = NOTIFICATIONS_ENABLED
        else:
            new_snooze = NOTIFICATIONS_DISABLED
        self.notification_control = new_snooze
        now = dt.now()
        self.ack_int(now)
        self.async_write_ha_state()
        self.reminder_check(now)

    async def async_ack(self):
        now = dt.now()
        self.ack_int(now)

    async def async_unack(self):
        _LOGGER.info(f'Activity {self.entity_id} got unack')
        now = dt.now()
        if self.last_ack_time is not None:
            self.last_ack_time = None
            self.async_write_ha_state()
            self.reminder_check(now)

    # Called directly from ackAll()
    def ack_int(self, now):
        _LOGGER.info(f'Activity {self.entity_id} ack')
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None  # TODO - could avoid recreates if we keep it around.
        needWrite = False
        if self.fires_since_last_notify != 0:
            self.fires_since_last_notify = 0
            needWrite = True
        # purpose of sub_ack_int is so, when someone clicks "Ack All", we don't actually update and log
        # every single alert in existence.
        if self.sub_ack_int():
            needWrite = True
        if needWrite:
            self.last_ack_time = now
            self.async_write_ha_state()

    # idempotent, can call many times
    def reminder_check(self, now = None):
        if not now:
            now = dt.now()
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None

        need_reminder = False
        # clauses here listed highest priority first
        if self.sub_need_reminder(): # True means condition alert is still unacked and on
            need_reminder = True
            reason = NotificationReason.ReminderOn
        elif (self.fires_since_last_notify > 0) or self.notified_max_on:
            need_reminder = True
            reason = NotificationReason.Summary
        elif isinstance(self.notification_control, rawdt.datetime):
            need_reminder = True
            reason = NotificationReason.SnoozeEnded
        #_LOGGER.debug(f'{self.entity_id} reminder_check: need_reminder={need_reminder} {self.fires_since_last_notify} {self.notified_max_on} {self.sub_need_reminder()}')
        if need_reminder:
            remaining_secs, rem_reason = self.can_notify_now(now, reason)
            #_LOGGER.info(f'{self.entity_id} need_reminder remaining_secs={remaining_secs} rem_reason={rem_reason}')
            if rem_reason == NOTIFICATIONS_DISABLED:
                return
            if remaining_secs == 0:
                if reason == NotificationReason.SnoozeEnded:
                    # Snooze should have turned off.  can_notify_now logged that. we're done.
                    if isinstance(self.notification_control, rawdt.datetime):
                        report(DOMAIN, 'error', f'{gAssertMsg} reminder_check, {self.name} snooze should have turned off, but is {self.notification_control}')
                else:
                    self.notify_timer_cb(now)
            else:
                if not (isinstance(remaining_secs, int) or isinstance(remaining_secs, float)) or remaining_secs <= 0:
                    report(DOMAIN, 'error', f'{gAssertMsg} reminder_check, remaining_secs={remaining_secs} of type={type(remaining_secs)} for {self.name}')
                    return
                self.schedule_reminder(remaining_secs)
        else:
            pass#_LOGGER.info(f'{self.entity_id} does not need_reminder')


    def sub_calc_next_reminder_frequency_mins(self, now):
        assert False, "Not Implemented"

    # returns list of notifiers
    # Returns [] if should not notify.
    def getNotifiers(self, args, reason: NotificationReason):
        # Get list of notifiers to notify

        sourceTemplate = 'notifier'
        notifier_template = self._notifier_list_template
        if reason in [ NotificationReason.Summary ]:
            if self._summary_notifier is True:
                pass
            elif self._summary_notifier is False:
                report(DOMAIN, 'error', f'{gAssertMsg} getNotifiers called wtih summary_notifier=False')
            else:
                sourceTemplate = 'summary_notifier'
                notifier_template = self._summary_notifier

        (notifiers, errors, debugInfo) = notifierTemplateToList(self.hass, self.extraVariables, notifier_template,
                                                                sourceTemplate)

        notifier_list = []
        defer_notifier_list = []
        alertData = self.hass.data[DOMAIN]
        for anotifier in notifiers:
            if alertData.delayedNotifierMgr.willDefer(anotifier, args):
                defer_notifier_list.append(anotifier)
            elif self.hass.services.has_service('notify', anotifier):
                notifier_list.append(anotifier)
            else:
                errMsg = f'{sourceTemplate} "{anotifier}" is not known to HA.'
                if '[' in anotifier:
                    errMsg += ' Possible malformed list. Try quoting the individual notifier names. See Alert2 docs for examples.'
                errors.append(errMsg)
        if len(notifier_list) == 0:
            if len(defer_notifier_list) > 0:
                pass # skip notifying
            else:
                if self.alDomain == DOMAIN and self.alName == 'error':
                    # Since alert2 depends on notify, we should be assured that persistent_notification exists.
                    notifier_list = [ 'persistent_notification' ]
                else:
                    # errors should have reason for missing notifiers, and it'll be reported
                    if len(errors) == 0:
                        pass #report(DOMAIN, 'error', f'For {self.name}: somehow no {sourceTemplate} specified')
        if len(errors) > 0:
            errStr = f'{errors} with debugInfo {debugInfo}'
            if self.alDomain == DOMAIN and self.alName == 'error':
                args['message'] += f' # Additional errors: {errStr}'
            else:
                report(DOMAIN, 'error', f'For {self.name}: {errStr} while notifying with message={args["message"]} ')
        return (notifier_list, defer_notifier_list)

    # Return False if disabled
    #        float seconds remaining till can notify otherwise. 0 if can do immediately
    # returns tuple:
    #    False/float:  False if disabled, otherwise 0 or seconds till can notify
    #    string: reason for delay
    def can_notify_now(self, now, reason: NotificationReason):
        if self.notification_control == NOTIFICATIONS_DISABLED:
            return (30*24*3600, NOTIFICATIONS_DISABLED)
        # First calculate snooze, max_limit, normal, startup remaining time till can notify independently,
        # then combine the logic.
        snooze_remaining_secs = 0
        if self.notification_control != NOTIFICATIONS_ENABLED:
            # We must be snoozed.
            snooze_remaining_secs = (self.notification_control - now).total_seconds()
            if snooze_remaining_secs <= 0:
                _LOGGER.info(f'Activity {self.entity_id} snooze has expired. Reenabling notifications')
                self.notification_control = NOTIFICATIONS_ENABLED
                self.async_write_ha_state()
                snooze_remaining_secs = 0

        max_limit_remaining_secs = self.movingSum.remainingSecs(now) if self.movingSum is not None else 0

        normal_remaining_secs = 0
        if reason == NotificationReason.ReminderOn:
            reminder_frequency_mins = self.sub_calc_next_reminder_frequency_mins(now)
            # We use last_tried_notify_time rather than last_notified_time here becuase we may not have
            # actually been notifying due to being superseded by another alert.
            if self.last_tried_notify_time and reminder_frequency_mins > 0:
                secs_since_last = (now - self.last_tried_notify_time).total_seconds()
                next_secs = reminder_frequency_mins * 60.0
                normal_remaining_secs = max(0, next_secs - secs_since_last)

        if self.notified_max_on and max_limit_remaining_secs == 0:
            # If throttling turned off, it overrides the notification frequency setting
            normal_remaining_secs = 0

        # Now combine the logic
        remaining_secs = 0
        freas = 'good-to-go-should-never-see'
        if max_limit_remaining_secs > remaining_secs:
            remaining_secs = max_limit_remaining_secs
            freas = 'max_limited'
        if snooze_remaining_secs > remaining_secs:
            remaining_secs = snooze_remaining_secs
            freas = 'snoozed'
        #if startup_remaining_secs > remaining_secs:
        #    remaining_secs = startup_remaining_secs
        #    freas = 'delayed_init'
        if normal_remaining_secs > remaining_secs:
            remaining_secs = normal_remaining_secs
            freas = 'reminder'
            #_LOGGER.debug(f'    reminder_frequency_mins = {reminder_frequency_mins}')
        #_LOGGER.debug(f'can_notify_now {self.name}, snooze_remaining_secs={snooze_remaining_secs} max_limit_remaining_secs={max_limit_remaining_secs} normal_remaining_secs={normal_remaining_secs} remaining_secs={remaining_secs} freas={freas}')
        return (remaining_secs, freas)


    def schedule_reminder(self, remaining_secs):
        async def foo():
            try:
                # + 1 so that the call to reminder_check is highly likely to see
                # can_notify_now is True
                await asyncio.sleep(remaining_secs + 1)
                if asyncio.current_task() != self.future_notification_info['task']:
                    report(DOMAIN, 'error', f'{gAssertMsg} schedule_reminder remindar somehow is not correct task: {asyncio.current_task()} vs {self.future_notification_info["task"]} for {self.name}')
                    return
                self.future_notification_info = None
                self.reminder_check()
            except asyncio.CancelledError:
                _LOGGER.debug(f'Skipping cancel exception for task {asyncio.current_task()}')
            except Exception as ex:
                msg = f'{self.name} In schedule_reminder/foo got exception: {ex.__class__}, {ex}'
                report(DOMAIN, 'error', f'{gAssertMsg} msg', isException=True)
        if self.future_notification_info is not None:
            report(DOMAIN, 'error', f'{gAssertMsg} schedule_reminder, ignoring since an outstanding reminder already exists: {self.future_notification_info} for {self.name}')
            return
        atask = create_background_task(self.hass, DOMAIN, foo())
        self.future_notification_info = { 'task': atask }

    # Assuming we want to notify
    # Does not write out state updates
    # Returns True if notified.  False if didn't notify
    #   (may return True if intended to notify but notifier wasn't available)
    # Does not call async_write_ha_state(), caller must
    #
    # There are message possibilities:
    #    Alert fired/turned on
    #    Alert fired/turned triggering over max
    #    Alert still on reminder
    #    Alert turned off
    #    max disengaged with alert off (max stopped. filtered 3 firings, mostly recently x min ago, which turned off x min ago
    #    max disengaged with alert on  (max stopped. filtered 3 firings, mostly recently x min ago, (still on)
    #
    def _notify(self, now, reason: NotificationReason, message, skip_notify=False):
        # Call can_notify_now before reportFire so that if reportFire crosses max threshold, we
        # still notify that max threshold has been crossed
        remaining_secs, remaining_reason = self.can_notify_now(now, reason)
        #_LOGGER.debug(f'in _notify, remaining_secs={remaining_secs} {remaining_reason}, ms={self.movingSum}')

        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None  # TODO - could avoid recreates if we keep it around.

        doNotify = remaining_secs == 0
        skipSummary = (reason in [ NotificationReason.Summary ]) and self._summary_notifier is False
        if skip_notify or skipSummary:
            doNotify = False
        isSuperseded = self.alertData.isSupersededByOn(self.alDomain, self.alName)
        if isSuperseded:
            doNotify = False

        msg = ''

        triggeredMaxLimit = False
        if reason == NotificationReason.Fire:
            if doNotify and self.movingSum is not None:
                # We're calling movingSum.reportFire and before above can_notify_now, which calls movingSum.remaining_secs
                # both of which call movingSum._updateBuckets().  Since we use the same 'now., we should
                # be guaranteed the 2nd call doesn't change anything.
                self.movingSum.reportFire(now)

        #what to do if stopped throttling right before call to _notify, and then fire() started throttling again?
        #then doNotify is true, and max_limit_remaining_secs > 0 and self.notified_max_on is true, so
        #will get xxx firex 6x message but no throttling update

        max_limit_remaining_secs = self.movingSum.remainingSecs(now) if self.movingSum is not None else 0
        if max_limit_remaining_secs > 0 and not self.notified_max_on:
            # throttling started hopefully due to a Fire that just happened.
            self.notified_max_on = True
            msg += '[Throttling started] '
            if not doNotify:
                report(DOMAIN, 'error', f'{gAssertMsg} {self.name}: saw throttling start, but not notifying. Seems impossible. {max_limit_remaining_secs} ')
        elif doNotify and max_limit_remaining_secs > 0 and self.notified_max_on:
            # doNotify means throttling turned off before call to _notify().
            # But it's now back on, which must be result of Fire.  In otherwords, throttling briefly turned off.
            # we would have expected a reminder call to _notify to notice the throttling had turned off, but
            # schedule_reminder() adds a second delay, so it's possible the reminder is a second away.
            # In other otherwords, a fire happened in the gap between throttling expiring and the reminder call to _notify to observe it.
            #_LOGGER.error('seems like throttling turned off earlier but without notification :(')
            msg += '[Throttling restarted] '
        elif max_limit_remaining_secs == 0 and self.notified_max_on:
            self.notified_max_on = False
            msg += '[Throttling ending] '
            if not doNotify and remaining_reason not in [ NOTIFICATIONS_DISABLED, 'snoozed' ] and not skipSummary:
                report(DOMAIN, 'error', f'{gAssertMsg} {self.name}: saw throttling stop, but not notifying, seems impossible. {remaining_secs}, {remaining_reason}')

        if reason == NotificationReason.Summary:
            msg += 'Summary: '

        addedName = False
        if self.annotate_messages or reason in [ NotificationReason.ReminderOn, NotificationReason.Summary ]:
            addedName = True
            if self._friendly_name is None:
                msg += f'Alert2 {self.name}'
            else:
                msg += self._friendly_name

        if (doNotify or skipSummary)  and self.fires_since_last_notify > 0:
            secs_since_last = (now - self.last_fired_time).total_seconds()
            msg += f' fired {self.fires_since_last_notify}x (most recently {agoStr(secs_since_last)} ago)'
            self.fires_since_last_notify = 0

        if len(message) > 0:
            if addedName:
                msg += ': '
            msg += f'{message}'

        #_LOGGER.warning(f'_notify msg={msg}')

        self.last_tried_notify_time = now
        if doNotify:
            self.last_notified_time = now

            tmsg = msg
            if len(tmsg) > 600:
                tmsg = tmsg[:600] + '...'
            if haConst.MAJOR_VERSION > 2024 or (haConst.MAJOR_VERSION == 2024 and haConst.MINOR_VERSION >= 10):
                args = {'message': tmsg }
            else:
                # message field in components/notify/const.py:NOTIFY_SERVICE_SCHEMA is a template and will be rendered
                args = {'message': jinja2Escape(tmsg) }
            if self._data is not None:
                args['data'] = self._data
            if self._target_template is not None:
                try:
                    args['target'] = self._target_template.async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'error', f'{self.name} Target template: {err}')
                    # Continue and notify anyways
            if self._title_template is not None:
                try:
                    args['title'] = self._title_template.async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'error', f'{self.name} Title template: {err}')
                    # Continue and notify anyways
            (notifier_list, defer_notifier_list) = self.getNotifiers(args, reason)
            if len(notifier_list) > 0:
                _LOGGER.warning(f'{self.entity_id} notifying {notifier_list}: {args["message"]}')
                async def foo():
                    for notifier in notifier_list:
                        try:
                            await self.hass.services.async_call('notify', notifier, # eg 'raw_jtelegram'
                                                                args)
                        except ServiceNotFound:
                            # We check has_service and depend on notify in manifest,
                            # so this should never happen.  But don't report in case it's for alert2.error
                            # so we don't loop.
                            _LOGGER.error(f'{gAssertMsg} {self.name} Somehow notify of {notifier} failed with ServiceNotFound. args={args}')
                    #futures = [ self.hass.services.async_call(
                    #    'notify', notifier, # eg 'raw_jtelegram'
                    #    args) for notifier in notifier_list ]
                    #await asyncio.gather(*futures)
                    #_LOGGER.debug(f'Notifying done: {notifier_list}')
                atask = create_task(self.hass, DOMAIN, foo())
            if len(defer_notifier_list) > 0:
                _LOGGER.warning(f'{self.entity_id} defering notifying {defer_notifier_list}: {args["message"]}')
            if len(notifier_list) == 0 and len(defer_notifier_list) == 0:
                # Notifier is set to null, no notifiation.  at least log
                _LOGGER.warning(f'{self.entity_id} (null notifier): {args["message"]}')

        else:
            if reason == NotificationReason.Fire:
                self.fires_since_last_notify += 1

            if remaining_reason == NOTIFICATIONS_DISABLED:
                tillmsg = 'disabled'
            elif remaining_secs > 0:
                tillmsg = f', {remaining_reason} next notify is {remaining_secs} secs away'
            elif skip_notify:
                tillmsg = f' (already acked)'
            elif skipSummary:
                tillmsg = f' (skipping summaries)'
            elif isSuperseded:
                tillmsg = f' (superseded by alert d={isSuperseded[0]} n={isSuperseded[1]})'
            else:
                report(DOMAIN, 'error', f'{self.name} not notifying with 0 remaining_secs and no skip_notify set')
                tillmsg = f' bad-logic-err'
            smsg = f'  {self.entity_id} skipping notify {tillmsg}: {msg}'
            _LOGGER.warning(smsg)
            #if remaining_reason != NOTIFICATIONS_DISABLED:
            #    if remaining_secs > 0:
            #        self.schedule_reminder(remaining_secs)
            #    # else:  must be that skip_notify is true because alert has already been acked

        if reason == NotificationReason.Fire:
            self.last_fired_message = message
            self.last_fired_time = now

        return doNotify


# Entity for an event alert.
class EventAlert(AlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults: dict[str, any],
    ):
        super().__init__(hass, alertData, config, defaults)
        self.config = config
        self.detach_trigger = None
        self.triggerCond = None
        if 'trigger' in config:
            self.triggerCond = TriggerCond(self, 'trigger', hass, alertData, self.triggered, self.extraVariables,
                                           config['trigger'], self._condition_template)
        else:
            pass # This is just a tracked alert, like alert2.error

    @property
    def state(self) -> str:
        if not self.last_fired_time:
            return ""
        return self.last_fired_time.isoformat()
    def more_state_attributes(self):
        return {
        }

    async def async_added_to_hass(self) -> None:
        """Restore extra state attributes on start-up."""
        await super().async_added_to_hass()
        await self.addedToHassDone()

    async def startWatching(self):
        await super().startWatching()
        if self.triggerCond:
            await self.triggerCond.startWatching()
        self.reminder_check()

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self.triggerCond:
            self.triggerCond.shutdown()

    async def triggered(self, variables):
        msg = ''
        if self._message_template is not None:
            try:
                msg = self._message_template.async_render(variables, parse_result=False)
            except TemplateError as err:
                report(DOMAIN, 'error', f'{self.name} Message template: {err}')
                return
        await self.record_event(msg)

    async def record_event(self, message: str):
        now = dt.now()
        msg = message
        didNotify = self._notify(now, NotificationReason.Fire, message)
        self.reminder_check(now) # To schedule reminder - the only reminder I think that could be needed is if throttled, a notificaiton that throttling has turned off
        self.async_write_ha_state()
        self.hass.bus.async_fire(EVENT_ALERT2_FIRE, { 'entity_id': self.entity_id,
                                                      'domain': self.alDomain,
                                                      'name': self.alName })

    def notify_timer_cb(self, now):
        if self.fires_since_last_notify > 0:
            msg = ''
            if len(self.last_fired_message) > 0:
                msg += f'Last msg: {self.last_fired_message}'
        else:
            # could be that we were throttled, and throttling is expiring. that's why we're getting the notify reminder cb
            msg = 'Did not fire during throttled interval'
            #report(DOMAIN, 'error', f'{gAssertMsg} notify_timer_cb, fires_since_last_notify is not positive, is {self.fires_since_last_notify} for {self.name}')
        didNotify = self._notify(now, NotificationReason.Summary, msg)
        self.reminder_check(now)
        self.async_write_ha_state()

    def sub_ack_int(self):
        return self.last_fired_time and (not self.last_ack_time or self.last_ack_time <= self.last_fired_time)
    #def sub_unack_int(self):
    #    return self.last_fired_time and (not self.last_ack_time or self.last_ack_time <= self.last_fired_time)
    def sub_need_reminder(self):
        return False
    def sub_calc_next_reminder_frequency_mins(self, now):
        return 0

# Base class for two types of condition alerts. One type is the complement of EventAlert.
# The other type is an alert that can be fired manually via python.
class ConditionAlert(AlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults,
            genVars = None
    ) -> None:
        AlertBase.__init__(self, hass, alertData, config=config, defaults=defaults, genVars=genVars)

        # Restored on HA restart
        self.last_on_time = None
        self.last_off_time = None
        self.reminders_since_fire = 0

        # Did we notify or reminder notify that the current alert is on.
        # used so we can then notify it turned off.
        #self.notified_on = False
        self.added_to_hass_called = False
        self.reminder_frequency_mins = getField('reminder_frequency_mins', config, defaults)
        # For hysteresis turning on
        self.delay_on_secs = config['delay_on_secs'] if 'delay_on_secs' in config else 0
        # If delay_on_secs is set, we distinguish between when a condition turned true
        # and when the alert turns on.
        # We don't restore this parameter cuz we don't know that cond was true while HA was down.
        self.cond_true_time = None
        self.cond_true_task = None

        self._threshold_value_template = config['threshold']['value'] if 'threshold' in config else None
        if self._threshold_value_template is not None:
            self._threshold_value_template.hass = hass
            self.threshold_max = config['threshold']['maximum'] if 'maximum' in config['threshold'] else None
            self.threshold_min = config['threshold']['minimum'] if 'minimum' in config['threshold'] else None
            self.threshold_hysteresis = config['threshold']['hysteresis'] if 'hysteresis' in config['threshold'] else None
            self.threshold_exceeded = ThresholdExeeded.Init # to record if we crossed min or max
        templs = []
        if self._condition_template is not None:
            templs.append({'fieldName': 'condition', 'type': Tracker.Type.Bool, 'template': self._condition_template })
        if self._threshold_value_template is not None:
            templs.append({'fieldName': 'value', 'type': Tracker.Type.Float, 'template': self._threshold_value_template })
        self.condValTracker = Tracker(self, 'condition-value', hass, alertData, templs, self.cond_val_update, self.extraVariables)

        self.onTracker = None
        if 'trigger_on' in config:
            self.onTracker = TriggerCond(self, 'trigger_on', hass, alertData, self.trigger_on, self.extraVariables,
                               config['trigger_on'], config['condition_on'] if 'condition_on' in config else None)
        elif 'condition_on' in config:
            templs = [{'fieldName': 'condition_on', 'type': Tracker.Type.Bool, 'template': config['condition_on'] }]
            self.onTracker = Tracker(self, 'condition_on', hass, alertData, templs, self.cond_on_update, self.extraVariables)

        self.offTracker = None
        if 'trigger_off' in config:
            self.offTracker = TriggerCond(self, 'trigger_off', hass, alertData, self.trigger_off, self.extraVariables,
                               config['trigger_off'], config['condition_off'] if 'condition_off' in config else None)
        elif 'condition_off' in config:
            templs = [{'fieldName': 'condition_off', 'type': Tracker.Type.Bool, 'template': config['condition_off'] }]
            self.offTracker = Tracker(self, 'condition_off', hass, alertData, templs, self.cond_off_update, self.extraVariables)


        self.manualOnEnabled = config['manual_on'] if 'manual_on' in config else False
        self.manualOffEnabled = config['manual_off'] if 'manual_off' in config else False

    async def trigger_on(self, variables):
        self.update_state_internal(True)
    def cond_on_update(self, results):
        if len(results) != 1:
            report(DOMAIN, 'error', f'{gAssertMsg} cond_on_update get len={len(results)} and results={results}')
            return
        if not isinstance(results[0], bool):
            report(DOMAIN, 'error', f'{gAssertMsg} cond_on_update get non-bool result {type(results[0])} and results={results}')
            return
        if results[0]:
            self.update_state_internal(True)
    async def trigger_off(self, variables):
        self.update_state_internal(False)
    def cond_off_update(self, results):
        if len(results) != 1:
            report(DOMAIN, 'error', f'{gAssertMsg} cond_off_update get len={len(results)} and results={results}')
            return
        if not isinstance(results[0], bool):
            report(DOMAIN, 'error', f'{gAssertMsg} cond_off_update get non-bool result {type(results[0])} and results={results}')
            return
        if results[0]:
            self.update_state_internal(False)

    async def async_manual_on(self):
        if not self.manualOnEnabled:
            raise HomeAssistantError(f'manual_on called but alert {self.entity_id} does not have manual_on enabled')
        self.update_state_internal(True)
    async def async_manual_off(self):
        if not self.manualOffEnabled:
            raise HomeAssistantError(f'manual_off called but alert {self.entity_id} does not have manual_off enabled')
        self.update_state_internal(False)

    @property
    def state(self) -> str:
        oldIsOn = self.last_on_time and ( (not self.last_off_time) or self.last_on_time > self.last_off_time)
        if oldIsOn:
            return "on"
        else:
            return "off"

    def more_state_attributes(self):
        return {
            'last_on_time': self.last_on_time,
            'last_off_time': self.last_off_time,
            'reminders_since_fire': self.reminders_since_fire,
            'cond_true_time': self.cond_true_time,
            #'notified_on': self.notified_on,
        }

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self.cond_true_task:
            cancel_task(DOMAIN, self.cond_true_task)
            self.cond_true_task = None
            self.cond_true_time = None
        self.condValTracker.shutdown()
        if self.onTracker:
            self.onTracker.shutdown()
        if self.offTracker:
            self.offTracker.shutdown()

    async def async_added_to_hass(self) -> None:
        """Restore state and register callbacks."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state:
            # First part of 'if' is just for migration I think
            if ('last_on_time' in last_state.attributes) and last_state.attributes['last_on_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_on_time'])
                if self.last_on_time is None or tdate >= self.last_on_time:
                    self.last_on_time = tdate
                    if 'reminders_since_fire' in last_state.attributes:
                        self.reminders_since_fire = max(self.reminders_since_fire, last_state.attributes['reminders_since_fire'])
                    #if 'notified_on' in last_state.attributes:
                    #    val = last_state.attributes['notified_on']
                    #    if not isinstance(val, bool):
                    #        low = val.lower()
                    #        if low not in ['true', 'false']:
                    #            _LOGGER.error(f'Got bad val for notified_on: {low} {type(low)}')
                    #        val = low == 'true'
                    #    self.notified_on = val
            if ('last_off_time' in last_state.attributes) and last_state.attributes['last_off_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_off_time'])
                if self.last_off_time is None or tdate > self.last_off_time:
                    self.last_off_time = tdate
            # We don't restore cond_true_time/task becaues we don't know the cond was true while HA was restarting.

        self.added_to_hass_called = True
        await self.addedToHassDone()

    async def startWatching(self):
        await super().startWatching()
        self.condValTracker.startWatching()
        if self.onTracker:
            if isinstance(self.onTracker, Tracker):
                self.onTracker.startWatching()
            else:
                await self.onTracker.startWatching()
        if self.offTracker:
            if isinstance(self.offTracker, Tracker):
                self.offTracker.startWatching()
            else:
                await self.offTracker.startWatching()
        self.reminder_check() #???
    async def async_update(self) -> None:
        await super().async_update()
        self.condValTracker.refresh()

    # Call when alert would otherwise be on
    # return True if will wait for delayed on
    def delayed_on_check(self, toState):
        async def dodelay():
            await asyncio.sleep(self.delay_on_secs)
            self.update_state_internal2(True)
            self.cond_true_time = None
            self.cond_true_task = None

        if toState:
            if self.state == "off":
                if self.cond_true_time == None:
                    _LOGGER.debug(f'Activity {self.entity_id} starting delay of {self.delay_on_secs} until turning on')
                    self.cond_true_time = dt.now()
                    self.cond_true_task = create_background_task(self.hass, DOMAIN, dodelay())
                # If cond_true_time is already set, it could just be that
                # update_state_internal has been called twice for the same "on" state.
                # E.g., if we exceeded a threshold, then exceed it a bit more.
                # report(DOMAIN, 'error', f'{gAssertMsg} {self.name} turning on but already have delayed wait set')
                # Return here so we don't notify till cond_true_task is ready
                return True
            # else: already on, so fall through
        else:
            if self.cond_true_time != None:
                _LOGGER.debug(f'Activity {self.entity_id} stopping turn-on delay')
                self.cond_true_time = None
                cancel_task(DOMAIN, self.cond_true_task)
                self.cond_true_task = None
        return False

    def update_state_internal(self, state:bool):
        if not isinstance(state, bool):
            report(DOMAIN, 'error', f'{gAssertMsg} update_state_internal ignoring call with non-bool {state} type={type(state)} for {self.name}')
            return

        if self.delay_on_secs > 0:
            if self.delayed_on_check(state):
                return
        return self.update_state_internal2(state)
    def update_state_internal2(self, state:bool):
        now = dt.now()
        if (self.state == "on") == state:
            # no change
            # TODO - for keeping track of extremum of offending values, may want to run some update checking code.
            return

        if state:
            self.last_on_time = now
        else:
            self.last_off_time = now

        # If we haven't called async_added_to_hass, then we don't know if this state
        # is actually a state change or not, so we don't know whether to fire or not.
        # So let the reminder_check() call in async_added_to_hass() decide.
        if self.added_to_hass_called:
            if state:
                _LOGGER.warning(f'Activity {self.entity_id} turned on')
                msg = '' #'fired.'
                if self._message_template is None:
                    msg = f'turned on'
                else:
                    try:
                        msg = self._message_template.async_render(variables=self.extraVariables, parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} Condition template: {err}')
                        return
                self.reminders_since_fire = 0
                didNotify = self._notify(now, NotificationReason.Fire, msg)
                self.reminder_check(now)
            else:
                _LOGGER.warning(f'Activity {self.entity_id} turned off')
                is_acked = self.last_ack_time and self.last_on_time and self.last_ack_time > self.last_on_time
                secs_on = (self.last_off_time - self.last_on_time).total_seconds()
                if self._done_message_template is None:
                    msg = f'turned off after {agoStr(secs_on)}.'
                else:
                    try:
                        msg = self._done_message_template.async_render(variables=self.extraVariables, parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} done_message template: {err}')
                        msg = f'turned off after {agoStr(secs_on)}. [done_message template error]'
                didNotify = self._notify(now, NotificationReason.StopFiring, msg,
                                         skip_notify=is_acked)
                self.reminder_check(now)
            self.async_write_ha_state()
            if state:
                self.hass.bus.async_fire(EVENT_ALERT2_ON, { 'entity_id': self.entity_id,
                                                            'domain': self.alDomain,
                                                            'name': self.alName })
            else:
                self.hass.bus.async_fire(EVENT_ALERT2_OFF, { 'entity_id': self.entity_id,
                                                             'domain': self.alDomain,
                                                             'name': self.alName })

    # want invariant to be that it is ok to invoke notify_timer_cb a tiny bit early.
    def notify_timer_cb(self, now):
        msg = ''
        is_on = self.state == 'on'
        if is_on:
            if not self.last_on_time:
                report(DOMAIN, 'error', f'{gAssertMsg} notify_timer_cb, is_on=True but no self.last_on_time={self.last_on_time} for {self.name}')
            else:
                secs_on = (now - self.last_on_time).total_seconds()
                msg += f'on for {agoStr(secs_on)}'
            reason = NotificationReason.ReminderOn
        else:
            secs_off = (now - self.last_off_time).total_seconds()
            secs_on = (self.last_off_time - self.last_on_time).total_seconds()
            msg += f'turned off {agoStr(secs_off)} ago after being on for {agoStr(secs_on)}'
            reason = NotificationReason.Summary
        didNotify = self._notify(now, reason, msg)
        # Whether or not we actually notified, for the purposes of counting reminder delays we say we did.
        # TODO - I think we could remove reminders_since_fire and instead calculate it based on time since
        # fire.
        self.reminders_since_fire += 1
        self.reminder_check(now)  # to set up next reminder (eg if alert is still on)
        self.async_write_ha_state()

    def sub_ack_int(self):
        # So we update last_ack_time if state is on
        if self.state == 'on':
            return True
        return self.last_off_time and (not self.last_ack_time or self.last_ack_time <= self.last_off_time)

    def sub_need_reminder(self):
        return self.state == 'on' and (not self.last_ack_time or self.last_ack_time < self.last_on_time)

    def sub_calc_next_reminder_frequency_mins(self, now):
        # alert may be off and this may be called as part of can_notify_now() after throttling ended.
        # or alert may be off and this is called due to delayed_init
        if self.state != 'on':
            #if not self.notified_max_on:
            #    report(DOMAIN, 'error', f'{gAssertMsg} sub_calc_next_reminder_frequency_mins, weird to ask when alert is not on. {self.name}')
            pass
        if not self.last_on_time:
            report(DOMAIN, 'error', f'{gAssertMsg} sub_calc_next_reminder_frequency_mins, can not calc reminder time since alert is not on. {self.name}')
            return 0
        idx = min(len(self.reminder_frequency_mins)-1, self.reminders_since_fire)
        return self.reminder_frequency_mins[idx]
        #mins_on = (now - self.last_on_time).total_seconds() / 60
        #total_reminder_mins = 0
        # # TODO - could optimize this computation since it's mostly the same each alert firing
        #for reminderIdx in range(len(self.reminder_frequency_mins)):
        #    total_reminder_mins += self.reminder_frequency_mins[reminderIdx]
        #    if total_reminder_mins > mins_on:
        #        return self.reminder_frequency_mins[reminderIdx]
        #return self.reminder_frequency_mins[-1]

    def cond_val_update(self, results):
        condition_bool = thresh_val = None
        if len(results) == 2:
            condition_bool = results[0]
            thresh_val = results[1]
        elif self._condition_template is not None:
            condition_bool = results[0]
        else:
            if self._threshold_value_template is None:
                report(DOMAIN, 'error', f'{gAssertMsg} {self.name}.  both condition and thresh val template is none')
                return
            thresh_val = results[0]

        # Now we have a condition_bool|None and a thresh_val|None
        # Figure out new state
        #
        self._attr_available = True
        if self._threshold_value_template is None:
            if self._condition_template is None:
                # Config valudation should prevent this
                report(DOMAIN, 'error', f'{gAssertMsg} template for {self.name} appears to have neither condition nor threshold test specified')
                newState = False
            else:
                newState = condition_bool
        else:
            # Update threshold_exceeded
            aboveMax = self.threshold_max is not None and thresh_val > self.threshold_max
            belowMin = self.threshold_min is not None and thresh_val < self.threshold_min
            if aboveMax:
                self.threshold_exceeded = ThresholdExeeded.Max
            elif belowMin:
                self.threshold_exceeded = ThresholdExeeded.Min
            elif self.state == 'on':
                # >=, <= so that if hysteresis is 0, it behaves as if hysteresis wasn't specified
                aboveMaxHyst = self.threshold_max is not None and \
                    self.threshold_exceeded == ThresholdExeeded.Max and \
                    thresh_val > (self.threshold_max - self.threshold_hysteresis)
                belowMinHyst = self.threshold_min is not None and \
                    self.threshold_exceeded == ThresholdExeeded.Min and \
                    thresh_val < (self.threshold_min + self.threshold_hysteresis)
                if aboveMaxHyst or belowMinHyst:
                    pass # threshold_exceeded is unchanged
                else:
                    self.threshold_exceeded = ThresholdExeeded.Init
            else:  # state is 'off'
                # If state is off, the generally we expect threshold_exceeded to be Init.
                # since the earlier turning off would have reset it.
                # but with delay_on_secs, it could be we exceeded threshold then dropped below it again
                # before turning on.  In that case, there's no hysteresis.
                # So hysteresis only applies once the alert has turned on.
                #
                # Actually, state could be off because the condition is false.  In this case also,
                # we don't track hysteresis
                self.threshold_exceeded = ThresholdExeeded.Init

            # Now update newState
            if condition_bool is False:
                newState = False
            elif condition_bool is None or condition_bool is True:
                newState = self.threshold_exceeded in [ ThresholdExeeded.Max, ThresholdExeeded.Min ]
            else:
                report(DOMAIN, 'error', f'{gAssertMsg} template for {self.name}: condition_bool is neither None or bool. Is {condition_bool} {type(condition_bool)}')
                newState = False
        return self.update_state_internal(newState)
