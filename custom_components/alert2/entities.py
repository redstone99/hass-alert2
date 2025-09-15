import ast
import asyncio
import datetime as rawdt
from   enum import Enum
import logging
from   typing import Any
import re
import voluptuous as vol
import traceback
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
    EVENT_ALERT2_ACK,
    EVENT_ALERT2_UNACK,
    EVENT_ALERT2_ON,
    EVENT_ALERT2_OFF,
    PersistantNotificationHelper
)
from .config import ( literalIllegalChar )

_LOGGER = logging.getLogger(__name__)

# If change NotificationReason, be sure to update expandDataDict
class NotificationReason(Enum):
    Fire = 1
    ReminderOn = 2
    StopFiring = 3
    Summary = 4
    # SnoozeEnded does not result in notification, for internal use
    SnoozeEnded = 5
    ReminderToAck = 6
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

def getField(fieldName, config, defaultCfg):
    foundVal = False
    
    if fieldName in defaultCfg['defaults']:
        val = defaultCfg['defaults'][fieldName]
        foundVal = True

    # I think the purpose of this is to support the default values in baseTopConfig for alert2 global_exception
    if config['domain'] == DOMAIN:
        for atracked in defaultCfg['tracked']:
            if atracked['name'] == config['name'] and fieldName in atracked:
                if fieldName == 'data' and foundVal:
                    val = val.copy()
                    val.update(atracked[fieldName])
                else:
                    val = atracked[fieldName]
                foundVal = True
    
    if fieldName in config:
        if fieldName == 'data' and foundVal:
            val = val.copy()
            val.update(config[fieldName])
        else:
            val = config[fieldName]
        foundVal = True

    if not foundVal:
        if fieldName == 'data':
            return None
        raise vol.Invalid(f'Alert {config["domain"]},{config["name"]} config or defaults must specify {fieldName}')
    return val


def expandSingle(elem, fname, extraVars):
    if isinstance(elem, template_helper.Template):
        try:
            valStr = elem.async_render(variables=extraVars, parse_result=False)
        except TemplateError as err:
            raise HomeAssistantError(f'template render failed for data field "{fname}": {err}')
        if False:
            try:
                tval = ast.literal_eval(valStr)
            except Exception as err:  # literal_eval can throw various kinds of exceptions
                if re.match(r'\s*[\'"].*[\'"]\s*$', valStr):
                    raise HomeAssistantError(f'Error rendering data field "{fname}". Field rendered to string "{valStr}". Subsequent python literal eval thew error: {err}')
                else:
                    raise HomeAssistantError(f'Error rendering data field "{fname}". Note - template strings in data fields need extra quotes around them. If you mean this field to produce a string, it appears to be missing extra surrounding quotes. Field rendered to string "{valStr}". Subsequent python literal eval thew error: {err}')
        return valStr # tval
    elif isinstance(elem, dict):
        return { k : expandSingle(v, f'{fname}->{k}' if fname else k, extraVars) for k, v in elem.items() }
    elif isinstance(elem, list):
        return [ expandSingle(v, fname, extraVars) for v in elem ]
    else:
        return elem

# returns (err, newDict)
def expandDataDict(adict, reason: NotificationReason, ent):
    #keys = adict.keys()
    #newDict = {}
    variables = { 'notify_reason': reason.name, 'alert_entity_id': ent.entity_id,
                  'alert_domain': ent.alDomain, 'alert_name': ent.alName }
    if ent.extraVariables:
        variables.update(ent.extraVariables)
    return expandSingle(adict, '', variables)

    for akey in keys:
        if isinstance(adict[akey], template_helper.Template):
            try:
                valStr = adict[akey].async_render(variables=variables, parse_result=False)
            except TemplateError as err:
                return (f'template render failed for data field "{akey}": {err}', None)
            if False:
                try:
                    tval = ast.literal_eval(valStr)
                except Exception as err:  # literal_eval can throw various kinds of exceptions
                    if re.match(r'\s*[\'"].*[\'"]\s*$', valStr):
                        return (f'Error rendering data field "{akey}". Field rendered to string "{valStr}". Subsequent python literal eval thew error: {err}', None)
                    else:
                        return (f'Error rendering data field "{akey}". Note - template strings in data fields need extra quotes around them. If you mean this field to produce a string, it appears to be missing extra surrounding quotes. Field rendered to string "{valStr}". Subsequent python literal eval thew error: {err}', None)
            newDict[akey] = valStr # tval
        elif isinstance(adict[akey], dict):
            subRez = expandDataDict(adict[key], reason, ent)
            if subRez[0] is None:
                newDict[akey] = subRez[1]
            else:
                return subRez
        else:
            newDict[akey] = adict[akey]
    return (None, newDict)


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
        else:
            # We delay startWatching until hass.states has the new entity, so the above get() should never fail
            report(DOMAIN, 'error', f'{gAssertMsg}: state not set for entity {self.parentEnt.entity_id}')
        variables = {"this": this}
        if self.extraVariables:
            variables.update(self.extraVariables)
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

        self.parentEnt.async_set_context(context)
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
        NonnegativeFloat = 5
        List = 6
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
            elif ttype in [ Tracker.Type.Float,  Tracker.Type.NonnegativeFloat ]:
                try:
                    afloat = float(resultStrs[idx])
                except ValueError:
                    report(DOMAIN, 'error', f'{self.fullName} {self.cfgList[idx]["fieldName"]} template rendered to "{resultStrs[idx]}" rather than a float')
                    return
                if ttype == Tracker.Type.NonnegativeFloat and afloat < 0:
                    report(DOMAIN, 'error', f'{self.fullName} {self.cfgList[idx]["fieldName"]} template rendered to "{resultStrs[idx]}" which is negative (min is zero)')
                    return
                results[idx] = afloat
            elif ttype == Tracker.Type.List:
                results[idx] = renderResultToList(resultStrs[idx])
                #_LOGGER.warning(f'idx={idx}, resultStrs={resultStrs[idx]} -> {results[idx]}')

        self.cb(results)
        

def generatorElemToVars(hass, elem, idx, prevDomainName):
    svars = {'genRaw': elem, 'genIdx': idx, 'genPrevDomainName': prevDomainName }
    if isinstance(elem, dict):
        svars.update(elem)
    elif isinstance(elem, str) and hass.states.get(elem):
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
        # calling async_add_entities eventuallyl calls
        #    homeassistant/helpers/entity.py::Entity::add_to_platform_finish
        # which calls async_added_to_hass BEFORE calling async_write_ha_state :(
        # this means right now, the new entity does not yet have an entry in hass.states.
        # That entry is written by async_write_ha_state.
        # So we need to yield and let the state writing happen before we declare we've really
        # added the new entity to hass
        async def waitForAdd():
            # I think just creating this task and us getting scheduled should be enough of a chance
            # for the state update to happen
            if not self.hass.states.get(self.entity_id):
                # Somehow we need more time
                count = 5
                while count > 0:
                    await asyncio.sleep(0.1)
                    if self.hass.states.get(self.entity_id):
                        break
                    count -= 1
                if count == 0:
                    report(DOMAIN, 'error', f'{gAssertMsg} Entity {self.entity_id} has not appeared in hass.states after waiting 0.5 s')
            self.hass.bus.async_fire(EVENT_ALERT2_CREATE, { 'entity_id': self.entity_id,
                                                             'domain': self.alDomain,
                                                             'name': self.alName })
            if self.earlyStart or self.alertData.haStarted:
                await self.startWatching()
            else:
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.startWatchingEv)
        create_task(self.hass, DOMAIN, waitForAdd())
    async def startWatchingEv(self, event): # async so we run in event loop
        await self.startWatching()

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        self.hass.bus.async_fire(EVENT_ALERT2_DELETE, { 'entity_id': self.entity_id,
                                                         'domain': self.alDomain,
                                                         'name': self.alName })

# cfgElem is YAML element of 'supersedes'
# returns pair of ( errStr_or_none, result ).  result can be either list of dict, or a single dict (if template).
# if a single dict, it gets converted to list of dict when the generator-produced config is validated.
# errStr does not include generator name
# 
def processSupersedes(cfgElem, svars):
    #if template_helper.is_template_string(frn.template):
    if isinstance(cfgElem, template_helper.Template):
        try:
            sStr = cfgElem.async_render(variables=svars, parse_result=False)
        except TemplateError as err:
            return (f'Supersedes template returned err {err}', None)
        try:
            sArr = ast.literal_eval(sStr)
        except Exception as err:  # literal_eval can throw various kinds of exceptions
            return (f'Supersedes template trying to parse "{sStr}" returned err {err}', None)
        return (None, sArr)
        #if isinstance(sArr, list):
        #    return (None, sArr)
        #else:
        #    return (None, [sArr])
    elif isinstance(cfgElem, list):
        newSupersedes = []
        for adn in cfgElem:
            newdn = { 'domain': None, 'name': None }
            try:
                newdn['domain'] = adn['domain'].async_render(variables=svars, parse_result=False)
            except TemplateError as err:
                return (f'Supersedes domain template returned err {err}', None)
            try:
                newdn['name'] = adn['name'].async_render(variables=svars, parse_result=False)
            except TemplateError as err:
                return (f'Supersedes name template returned err {err}', None)
            newSupersedes.append(newdn)
        return (None, newSupersedes)
    elif cfgElem is None:
        return (None, None)
    else:
        return (f'Supersedes variable has bad value: "{cfgElem}"', None)
        
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
        self.alDomain = GENERATOR_DOMAIN
        self.alName = self.config["generator_name"]
        self._attr_unique_id = f'generator-n={self.alName}'
        self._generator_template = self.config['generator']
        self.tracker = Tracker(self, 'generator', hass, alertData,
                               [ { 'fieldName': 'generator', 'type': Tracker.Type.List,
                                   'template': self._generator_template } ], self.update_rez, extraVariables=None)
                               
        # "name" here is overloaded. There's the 'name' from the domain+name specified in an alert config
        # then there's the 'name' that is the HA entity's name property.
        # Here we're using the entity name
        self.nameEntityMap = {} # Map from name -> ent
        self._purgeRegistry = False
        
    def setRegistryPurge(self):
        self._purgeRegistry = True
        
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
        await self.shutdown()
        for ent in self.nameEntityMap.values():
            await self.alertData.undeclareAlert(ent.alDomain, ent.alName, removeFromRegistry=self._purgeRegistry) # destroys ent
        self.nameEntityMap = {}
    async def shutdown(self):
        self.tracker.shutdown()
        self.tracker = None

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
        prevDomainName = None
        for idx, elem in enumerate(alist):
            #if not (isinstance(elem, str) or isinstance(elem, dict)):
            #    report(DOMAIN, 'error', f'{self.name} generator produced non-string or dict element "{elem}" of type {type(elem)}')
            #    sawError = True
            #    break
            svars = generatorElemToVars(self.hass, elem, idx, prevDomainName)
            
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
            if entName in currNames:
                report(DOMAIN, 'error', f'{self.name} is requesting creation of duplicate entity id {entName}. Aborting')
                sawError = True
                break
            currNames.add(entName)
            prevDomainName = { 'domain': domainStr, 'name': nameStr }
            hassState = self.hass.states.get(f'alert2.{entName}')
            if entName in self.nameEntityMap:
                # entity continues to exist
                ent = self.nameEntityMap[entName]
                if hassState is None:
                    # If the entity is disabled, it will be removed from hass states, even though
                    # we may still have record of it.
                    pass
                elif ent.enabled:
                    pass # normal case. we generated ent and it isn't disabled
                else:
                    pass # we generated ent, but user disabled it. nothing to do.
            else:
                if hassState is None:
                    pass # Normal case, we want to create a new entity
                elif hassState.state == 'unavailable':
                    pass # Ent exists cuz it has unique_id, but hopefully we haven't created it yet.
                else:
                    pass # Ent exists cuz it has unique_id, but hopefully we haven't created it yet.

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
                # Also, use rawConfig so we don't double interpret the config dict (declareAlert interprets it)
                acfg = dict(self.rawConfig) 
                acfg['domain'] = domainStr
                acfg['name'] = nameStr
                del acfg['generator']
                del acfg['generator_name']

                if 'supersedes' in self.config:
                    (err, rez) = processSupersedes(self.config['supersedes'], svars)
                    if err:
                        report(DOMAIN, 'error', f'{self.name} {err}')
                        sawError = True
                        break
                    acfg['supersedes'] = rez
                if 'priority' in self.config:
                    try:
                        acfg['priority'] = self.config['priority'].async_render(variables=svars, parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} priority template returned err {err}')
                        sawError = True
                        break
                if 'delay_on_secs' in self.config:
                    try:
                        acfg['delay_on_secs'] = self.config['delay_on_secs'].async_render(variables=svars, parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} delay_on_secs template returned err {err}')
                        sawError = True
                        break
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
                    hassState = self.hass.states.get(ent.entity_id)
                    if hassState is None:
                        # If entity has been disabled it won't be in hass states even though we have record of it.
                        pass
                    elif ent.enabled:
                        pass # normal case. we generated ent and it isn't disabled, now we want to delete it.
                    else:
                        # we generated ent, but user disabled it. we still want to undeclareAlert
                        # to update our internal accounting of alerts.
                        pass 
                    _LOGGER.info(f'Lifecycle generator {self.name} removing alert {ent.entity_id}')
                    #await ent.async_remove() # I think this is the complement of async_add_entities
                    await self.alertData.undeclareAlert(ent.alDomain, ent.alName, removeFromRegistry=True) # destroys ent
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
            defaultCfg: dict[str, Any],
            genVars = None
    ):
        AlertCommon.__init__(self, hass, alertData, config)
        RestoreEntity.__init__(self)
        # super().__init__()
        self.config = config
        self.alDomain = config['domain']
        self.alName = config['name']
        self._attr_name = entNameFromDN(self.alDomain, self.alName)

        self._attr_unique_id = f'd={self.alDomain}-n={self.alName}'
        
        # config stuff
        self._notifier_list_template = getField('notifier', config, defaultCfg)
        self._summary_notifier = getField('summary_notifier', config, defaultCfg)
        self._done_notifier = getField('done_notifier', config, defaultCfg)
        self._priority = getField('priority', config, defaultCfg)
        self._persistent_notifier_grouping = getField('persistent_notifier_grouping', config, defaultCfg)
        self._used_persistent_notifier = False
        self._condition_template = config['condition'] if 'condition' in config else None
        self._message_template = config['message'] if 'message' in config else None
        self._title_template = config['title'] if 'title' in config else None
        self._target_template = config['target'] if 'target' in config else None
        self._data = getField('data', config, defaultCfg)
        # Added on Aug 24, 2025 for v1.16. Remove with next version
        if self._data:
            if any([ isinstance(self._data[x], template_helper.Template) for x in self._data.keys() ]):
                if alertData.uiMgr.setOneTime('v1.16_data_syntax_change'):
                    report(DOMAIN, 'warning', f'One-time msg: Alert2 v1.16 changed the syntax of how templates are used in "data" fields. If you wrote those templates pre-v1.16 you may need to update them. See docs at https://github.com/redstone99/hass-alert2?tab=readme-ov-file#common-alert-features-1')
        
        self._display_msg_template = config['display_msg'] if 'display_msg' in config else None
        self._icon = getField('icon', config, defaultCfg)
        self._ack_required = config['ack_required'] if 'ack_required' in config else False
        self._ack_reminder_message_template = config['ack_reminder_message'] if 'ack_reminder_message' in config else None
        # Reminders can either be ack reminders (if ack_required is set), or for condition alerts can be alert-on reminders
        self.reminder_frequency_mins = getField('reminder_frequency_mins', config, defaultCfg)
        self.reminders_since_fire = 0
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
        if self._ack_reminder_message_template is not None:
            self._ack_reminder_message_template.hass = hass
        if self._title_template is not None:
            self._title_template.hass = hass
        if self._target_template is not None:
            self._target_template.hass = hass
        if self._notifier_list_template is not None and not isinstance(self._notifier_list_template, list):
            self._notifier_list_template.hass = hass
        if isinstance(self._summary_notifier, template_helper.Template):
            self._summary_notifier.hass = hass
        if isinstance(self._done_notifier, template_helper.Template):
            self._done_notifier.hass = hass
        self.annotate_messages = getField('annotate_messages', config, defaultCfg)
        throttle_fires_per_mins = getField('throttle_fires_per_mins', config, defaultCfg)
        self.movingSum = None
        if throttle_fires_per_mins is not None:
            self.movingSum = MovingSum(throttle_fires_per_mins[0], throttle_fires_per_mins[1])
        self.notified_max_on = False
        self._supersede_debounce_secs = 0 # condition alerts will override this

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
    # This overrides helpers/entity.py:Entity version of this
    def _friendly_name_internal(self) -> str | None:
        return self._friendly_name or self.name

    async def startWatching(self):
        #await super().startWatching()  not in parent class
        if self.friendlyNameTracker:
            self.friendlyNameTracker.startWatching()
            
    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        # AlertBase is never instantiated directly, it is only subclassed.
        # The subclass will call shutdown(), which will call the super().shutdown (i.e., us)
        # await self.shutdown()
        
    async def shutdown(self):
        if self.friendlyNameTracker:
            self.friendlyNameTracker.shutdown()
            self.friendlyNameTracker = None
        #self._attr_available = False
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
                    if 'reminders_since_fire' in last_state.attributes:
                        self.reminders_since_fire = max(self.reminders_since_fire, last_state.attributes['reminders_since_fire'])
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
            'icon': self._icon, #'mdi:alert',
            'custom_ui_more_info' : 'more-info-alert2',
            "custom_ui_state_card": 'state-card-alert2',
            'last_notified_time': self.last_notified_time,
            'last_fired_time': self.last_fired_time,
            'last_fired_message': self.last_fired_message,
            'last_ack_time': self.last_ack_time,
            'is_acked': self.is_acked(),
            'ack_required': self._ack_required,
            #'friendly_name2': self._friendly_name, # Entity class defines "friendly_name" so we have to use something different.
            'fires_since_last_notify': self.fires_since_last_notify,
            'notified_max_on': self.notified_max_on,
            'notification_control': self.notification_control,
            'domain': self.alDomain,
            'name': self.alName,
            'has_display_msg': (self._display_msg_template is not None),
            'priority': self._priority,
            'reminders_since_fire': self.reminders_since_fire,
        }
        baseDict.update(self.more_state_attributes())
        return baseDict
    
    def notify_timer_cb(self, now):
        assert False, "not implemented"
    def sub_need_reminder(self):
        assert False, "not implemented"
    def sub_ack_int(self):
        assert False, "not implemented"
    def is_acked(self):
        assert False, "not implemented"

    async def async_notification_control(
            self, enable: bool, snooze_until: rawdt.datetime | None = None, ack_at_snooze_start: bool = True
    ) -> None:
        _LOGGER.info(f'Activity {self.entity_id} got async_notification_control with enable={enable} and snooze_until={snooze_until}')
        do_ack = True
        if enable:
            if snooze_until:
                if snooze_until.tzinfo is None or snooze_until.tzinfo.utcoffset(snooze_until) is None:
                    report(DOMAIN, 'error', f'{gAssertMsg} Notification control call has snooze time specified without timezone info: {snooze_until} for {self.name}')
                # javascript in the browser converts the local time generated to UTC when sending on the wire.
                # convert back to local time.
                new_snooze = dt.as_local(snooze_until)
                do_ack = ack_at_snooze_start
            else:
                new_snooze = NOTIFICATIONS_ENABLED
        else:
            new_snooze = NOTIFICATIONS_DISABLED
        self.notification_control = new_snooze
        now = dt.now()
        if do_ack:
            self.ack_int(now)
        self.async_write_ha_state()
        self.reminder_check(now)
    
    async def async_ack(self):
        now = dt.now()
        self.ack_int(now)
        self.hass.bus.async_fire(EVENT_ALERT2_ACK, { 'entity_id': self.entity_id,
                                                     'domain': self.alDomain,
                                                     'name': self.alName })

    async def async_unack(self):
        _LOGGER.info(f'Activity {self.entity_id} got unack')
        now = dt.now()
        if self.last_ack_time is not None:
            self.last_ack_time = None
            self.async_write_ha_state()
            self.reminder_check(now)
        # Fire event even if alert wasn't acked in the first place
        self.hass.bus.async_fire(EVENT_ALERT2_UNACK, { 'entity_id': self.entity_id,
                                                       'domain': self.alDomain,
                                                       'name': self.alName })

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
        elif self.last_fired_time is not None and self._ack_required and not self.is_acked():
            need_reminder = True
            reason = NotificationReason.ReminderToAck
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
                elif reason == NotificationReason.ReminderToAck:
                    self.ack_reminder_notify_timer_cb(now)
                else:
                    self.notify_timer_cb(now)
            else:
                if not (isinstance(remaining_secs, int) or isinstance(remaining_secs, float)) or remaining_secs <= 0:
                    report(DOMAIN, 'error', f'{gAssertMsg} reminder_check, remaining_secs={remaining_secs} of type={type(remaining_secs)} for {self.name}')
                    return
                self.schedule_reminder(remaining_secs)
        else:
            pass#_LOGGER.info(f'{self.entity_id} does not need_reminder')
    

    def ack_reminder_notify_timer_cb(self, now):
        #fired_secs = (now - self.last_fired_time).total_seconds()
        msg = ''
        if self._ack_reminder_message_template is None:
            msg += f'not acked yet'
        else:
            evars = self.extraVariables.copy() if self.extraVariables else {}
            #evars['on_secs'] = on_secs
            #evars['on_time_str'] = agoStr(on_secs)
            try:
                msg += self._ack_reminder_message_template.async_render(variables=evars, parse_result=False)
            except TemplateError as err:
                msg += f'not acked yet [ack_reminder_message template error]'
                msg += self.reportIfSafe(DOMAIN, 'error', f'{self.name} ack_reminder_message template: {err}')
        reason = NotificationReason.ReminderToAck
        self._notify_pre_debounce(now, reason, msg)
        self.reminder_check(now)  # to set up next reminder to ack
        self.async_write_ha_state()
        
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
        elif reason == NotificationReason.StopFiring:
            if self._done_notifier is True:
                pass
            elif self._done_notifier is False:
                report(DOMAIN, 'error', f'{gAssertMsg} getNotifiers called wtih done_notifier=False')
            else:
                sourceTemplate = 'done_notifier'
                notifier_template = self._done_notifier


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
        
        debounce_remaining_secs = 0
        if self.alertData.supersedeNotifyMgr.isWaiting(self):
            # The number here is just to delay reminding until after the supersedeNotifyMgr wait finishes.
            # when it finishes, supersedeNotifyMgr will call reminder_check() to process reminding for real.
            debounce_remaining_secs = self._supersede_debounce_secs + 1
        
        normal_remaining_secs = 0
        if reason in [ NotificationReason.ReminderOn, NotificationReason.ReminderToAck ]:
            reminder_frequency_mins = self.calc_next_reminder_frequency_mins(now)
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
        if debounce_remaining_secs > remaining_secs:
            remaining_secs = debounce_remaining_secs
            freas = 'supersede_debounce'
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
        #_LOGGER.info(f'{self.name}: can_notify_now remaining_secs={remaining_secs} reason={freas}')
        return (remaining_secs, freas)
            
    def calc_next_reminder_frequency_mins(self, now):
        # For condition alert, the alert may off and this may be called as part of can_notify_now() after throttling ended.
        # or alert may be off and this is called due to delayed_init
        #
        # For event or condition alert this may be called as part of ack_required
        idx = min(len(self.reminder_frequency_mins)-1, self.reminders_since_fire)
        #_LOGGER.info(f'{self.name}: reminder time index={self.reminders_since_fire} secs={60.0*self.reminder_frequency_mins[idx]}')
        return self.reminder_frequency_mins[idx]
        #mins_on = (now - self.last_on_time).total_seconds() / 60
        #total_reminder_mins = 0
        # # TODO - could optimize this computation since it's mostly the same each alert firing
        #for reminderIdx in range(len(self.reminder_frequency_mins)):
        #    total_reminder_mins += self.reminder_frequency_mins[reminderIdx]
        #    if total_reminder_mins > mins_on:
        #        return self.reminder_frequency_mins[reminderIdx]
        #return self.reminder_frequency_mins[-1]
            
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
                pass #_LOGGER.debug(f'Skipping cancel exception for task {asyncio.current_task()}')
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
    def _notify_pre_debounce(self, now, reason: NotificationReason, message, skip_notify=False, extra_data=None):
        msg = ''
        if reason == NotificationReason.Summary:
            msg += 'Summary: '
        addedName = False
        if self.annotate_messages or \
           reason == NotificationReason.Summary or \
           (reason == NotificationReason.ReminderToAck and self._ack_reminder_message_template is None) or \
           (reason == NotificationReason.ReminderOn and self._reminder_message_template is None):
            addedName = True
            if self._friendly_name is None:
                msg += f'Alert2 {self.name}'
            else:
                msg += self._friendly_name

        if len(message) > 0:
            if addedName:
                msg += ': '
            msg += f'{message}'

        _LOGGER.warning(msg)
        #_LOGGER.warning(f'_notify_pre_debounce: {"".join(traceback.format_stack())}')
\
        last_fired_time = self.last_fired_time
        if reason == NotificationReason.Fire:
            self.last_fired_message = message
            self.last_fired_time = now
            self.reminders_since_fire = 0
            
        alertData = self.hass.data[DOMAIN]
        alertData.supersedeNotifyMgr.processNotify(self, now, msg, reason, last_fired_time, skip_notify, debounce_secs=self._supersede_debounce_secs, extra_data=extra_data)

    # Purpose is to avoid infinite loop of alert2_error reporting an alert2_error when it has an internal issue
    # I think all calls to report errors that can happen from alert2_error either are assertion failures or use reportIfSafe.
    def reportIfSafe(self, domain, name, msg):
        if self.alDomain == DOMAIN and self.alName == 'error':
            _LOGGER.error(f'alert2.alert2_error itself had issue: {msg}')
            return f'[ alert2_error itself had issue: {msg} ]'
        else:
            report(domain, name, msg)
            return ''
        
    def _notify_post_debounce(self, msg, reason: NotificationReason, last_fired_time, extra_data, now, *, skip_notify, isSuperseded):
        assert isinstance(msg, str)
        assert isinstance(reason, NotificationReason)
        # Call can_notify_now before reportFire so that if reportFire crosses max threshold, we
        # still notify that max threshold has been crossed
        remaining_secs, remaining_reason = self.can_notify_now(now, reason)
        #_LOGGER.debug(f'in _notify, remaining_secs={remaining_secs} {remaining_reason}, ms={self.movingSum}')
        
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None  # TODO - could avoid recreates if we keep it around.

        doNotify = remaining_secs == 0
        skipSummary = (reason in [ NotificationReason.Summary ]) and self._summary_notifier is False
        skipDone    = (reason in [ NotificationReason.StopFiring ]) and self._done_notifier is False
        if skip_notify or skipSummary or skipDone:
            doNotify = False
        #isSuperseded = self.alertData.isSupersededByOn(self.alDomain, self.alName)
        if isSuperseded:
            doNotify = False
        
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
            msg += ' [Throttling started]'
            if not doNotify:
                msg += self.reportIfSafe(DOMAIN, 'error', f'{gAssertMsg} {self.name}: saw throttling start, but not notifying. Seems impossible. {max_limit_remaining_secs} ')
        elif doNotify and max_limit_remaining_secs > 0 and self.notified_max_on:
            # doNotify means throttling turned off before call to _notify().
            # But it's now back on, which must be result of Fire.  In otherwords, throttling briefly turned off.
            # we would have expected a reminder call to _notify to notice the throttling had turned off, but
            # schedule_reminder() adds a second delay, so it's possible the reminder is a second away.
            # In other otherwords, a fire happened in the gap between throttling expiring and the reminder call to _notify to observe it.
            #_LOGGER.error('seems like throttling turned off earlier but without notification :(')
            msg += ' [Throttling restarted]'
        elif max_limit_remaining_secs == 0 and self.notified_max_on:
            self.notified_max_on = False
            msg += ' [Throttling ending]'
            if not doNotify and remaining_reason not in [ NOTIFICATIONS_DISABLED, 'snoozed' ] and not skipSummary and not skipDone:
                msg += self.reportIfSafe(DOMAIN, 'error', f'{gAssertMsg} {self.name}: saw throttling stop, but not notifying, seems impossible. {remaining_secs}, {remaining_reason}')

        if (doNotify or skipSummary or skipDone) and self.fires_since_last_notify > 0:
            secs_since_last = (now - last_fired_time).total_seconds()
            msg += f' (fired {self.fires_since_last_notify}x - most recently {agoStr(secs_since_last)} ago)'
            self.fires_since_last_notify = 0
            
        #_LOGGER.warning(f'_notify msg={msg}')
            
        self.last_tried_notify_time = now
        if doNotify:
            self.last_notified_time = now

            args = {}
            if self._data is not None:
                try:
                    nDict = expandDataDict(self._data, reason, self)
                except HomeAssistantError as err:
                    msg += self.reportIfSafe(DOMAIN, 'error', f'{self.name} data {err}')
                else:
                    args['data'] = nDict
            if extra_data is not None:
                args['data'] = (args['data'] if 'data' in args else {}) | extra_data
            if self._target_template is not None:
                try:
                    args['target'] = self._target_template.async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    msg += self.reportIfSafe(DOMAIN, 'error', f'{self.name} Target template: {err}')
                    # Continue and notify anyways
            if self._title_template is not None:
                try:
                    args['title'] = self._title_template.async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    msg += self.reportIfSafe(DOMAIN, 'error', f'{self.name} Title template: {err}')
                    # Continue and notify anyways
            tmsg = msg
            if len(tmsg) > 600:
                tmsg = tmsg[:600] + '...'
            if haConst.MAJOR_VERSION > 2024 or (haConst.MAJOR_VERSION == 2024 and haConst.MINOR_VERSION >= 10):
                args['message'] = tmsg
            else:
                # message field in components/notify/const.py:NOTIFY_SERVICE_SCHEMA is a template and will be rendered
                args['message'] = jinja2Escape(tmsg)

                    
            (notifier_list, defer_notifier_list) = self.getNotifiers(args, reason)
            if len(notifier_list) > 0:
                _LOGGER.warning(f'{self.entity_id} notifying {notifier_list}: {args["message"]}')
                async def foo():
                    for notifier in notifier_list:
                        if notifier == 'persistent_notification':
                            self._used_persistent_notifier = True
                            if self._persistent_notifier_grouping != PersistantNotificationHelper.Separate:
                                if 'data' not in args:
                                    args['data'] = {}
                                args['data']['notification_id'] = PersistantNotificationHelper.genNotificationId(self)
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
            # doNotify is False
            
            if reason == NotificationReason.Fire and not isSuperseded:
                self.fires_since_last_notify += 1

            if remaining_reason == NOTIFICATIONS_DISABLED:
                tillmsg = 'disabled'
            elif remaining_secs > 0:
                tillmsg = f', {remaining_reason} next notify is {remaining_secs} secs away'
            elif skip_notify:
                tillmsg = f' (already acked)'
            elif skipSummary:
                tillmsg = f' (skipping summaries)'
            elif skipDone:
                tillmsg = f' (skipping firing done notifications)'
            elif isSuperseded:
                tillmsg = f' (superseded by alert d={isSuperseded[0]} n={isSuperseded[1]})'
            else:
                self.reportIfSafe(DOMAIN, 'error', f'{self.name} not notifying with 0 remaining_secs and no skip_notify set')
                tillmsg = f' bad-logic-err'
            smsg = f'  {self.entity_id} skipping notify {tillmsg}: {msg}'
            _LOGGER.warning(smsg)
            #if remaining_reason != NOTIFICATIONS_DISABLED:
            #    if remaining_secs > 0:
            #        self.schedule_reminder(remaining_secs)
            #    # else:  must be that skip_notify is true because alert has already been acked
        if reason in [ NotificationReason.ReminderOn, NotificationReason.ReminderToAck ]:
            # Whether or not we actually did notify, for the purposes of counting reminder delays we say we will.
            # TODO - I think we could remove reminders_since_fire and instead calculate it based on time since
            # fire.
            self.reminders_since_fire += 1
            

# Entity for an event alert.
class EventAlert(AlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaultCfg: dict[str, any],
    ):
        super().__init__(hass, alertData, config, defaultCfg)
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
            return "has never fired"
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
        await self.shutdown()
        
    async def shutdown(self):
        await super().shutdown()
        if self.triggerCond:
            self.triggerCond.shutdown()
            self.triggerCond = None
            
    async def triggered(self, variables):
        msg = ''
        if self._message_template is not None:
            try:
                msg = self._message_template.async_render(variables, parse_result=False)
            except TemplateError as err:
                report(DOMAIN, 'error', f'{self.name} Message template: {err}')
                return
        await self.record_event(msg)
        
    async def record_event(self, message: str, extra_data: dict = None):
        now = dt.now()
        _LOGGER.warning(f'Activity {self.entity_id} fired')
        msg = message
        self._notify_pre_debounce(now, NotificationReason.Fire, message, extra_data=extra_data)
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
        self._notify_pre_debounce(now, NotificationReason.Summary, msg)
        self.reminder_check(now)
        self.async_write_ha_state()
    
    def sub_ack_int(self):
        return self.last_fired_time and (not self.last_ack_time or self.last_ack_time <= self.last_fired_time)
    def is_acked(self):
        return bool(self.last_fired_time and self.last_ack_time and self.last_ack_time > self.last_fired_time)

    #def sub_unack_int(self):
    #    return self.last_fired_time and (not self.last_ack_time or self.last_ack_time <= self.last_fired_time)
    def sub_need_reminder(self):
        return False

# Base class for two types of condition alerts. One type is the complement of EventAlert.
# The other type is an alert that can be fired manually via python.
class ConditionAlert(AlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaultCfg,
            genVars = None
    ) -> None:
        AlertBase.__init__(self, hass, alertData, config=config, defaultCfg=defaultCfg, genVars=genVars)

        # Restored on HA restart
        self.last_on_time = None
        self.last_off_time = None

        # Did we notify or reminder notify that the current alert is on.
        # used so we can then notify it turned off.
        #self.notified_on = False
        self.added_to_hass_called = False
        self._done_message_template = config['done_message'] if 'done_message' in config else None
        if self._done_message_template is not None:
            self._done_message_template.hass = hass
        self._reminder_message_template = config['reminder_message'] if 'reminder_message' in config else None
        if self._reminder_message_template is not None:
            self._reminder_message_template.hass = hass
        self._supersede_debounce_secs = getField('supersede_debounce_secs', config, defaultCfg)
            
        # For hysteresis turning on
        self.delay_on_secs = config['delay_on_secs'] if 'delay_on_secs' in config else 0
        # If delay_on_secs is set, we distinguish between when a condition turned true
        # and when the alert turns on.
        # We don't restore this parameter cuz we don't know that cond was true while HA was down.
        self.cond_true_time = None
        self.cond_true_task = None

        templs = []
        if self._condition_template is not None:
            templs.append({'fieldName': 'condition', 'type': Tracker.Type.Bool, 'template': self._condition_template })
        self._threshold_value_template = config['threshold']['value'] if 'threshold' in config else None
        if self._threshold_value_template is not None:
            self._threshold_value_template.hass = hass
            templs.append({'fieldName': 'value', 'type': Tracker.Type.Float, 'template': self._threshold_value_template })
            self._threshold_hysteresis_float_or_template =  config['threshold']['hysteresis']
            if isinstance(self._threshold_hysteresis_float_or_template, template_helper.Template):
                self._threshold_hysteresis_float_or_template.hass = hass
                templs.append({'fieldName': 'hysteresis', 'type': Tracker.Type.NonnegativeFloat, 'template': self._threshold_hysteresis_float_or_template })
            self._threshold_max_float_or_template = config['threshold']['maximum'] if 'maximum' in config['threshold'] else None
            if isinstance(self._threshold_max_float_or_template, template_helper.Template):
                self._threshold_max_float_or_template.hass = hass
                templs.append({'fieldName': 'maximum', 'type': Tracker.Type.Float, 'template': self._threshold_max_float_or_template })
            self._threshold_min_float_or_template = config['threshold']['minimum'] if 'minimum' in config['threshold'] else None
            if isinstance(self._threshold_min_float_or_template, template_helper.Template):
                self._threshold_min_float_or_template.hass = hass
                templs.append({'fieldName': 'minimum', 'type': Tracker.Type.Float, 'template': self._threshold_min_float_or_template })
            
            #self.threshold_min = config['threshold']['minimum'] if 'minimum' in config['threshold'] else None
            #self.threshold_hysteresis = config['threshold']['hysteresis'] if 'hysteresis' in config['threshold'] else None
            #self.threshold_exceeded = ThresholdExeeded.Init # to record if we crossed min or max
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
        self.ackRemindersOnly = config['ack_reminders_only'] if 'ack_reminders_only' in config else False
            
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
        rez = {
            'last_on_time': self.last_on_time,
            'last_off_time': self.last_off_time,
            'cond_true_time': self.cond_true_time,
            #'notified_on': self.notified_on,
        }
        # Don't add attribute if it is None
        if 'supersedes' in self.config and self.config['supersedes']:
            rez['supersedes'] = self.config['supersedes']
        return rez
    
    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        await self.shutdown()
        
    async def shutdown(self):
        await super().shutdown()
        if self.cond_true_task:
            cancel_task(DOMAIN, self.cond_true_task)
            self.cond_true_task = None
            self.cond_true_time = None
        self.condValTracker.shutdown()
        self.condValTracker = None
        if self.onTracker:
            self.onTracker.shutdown()
            self.onTracker = None
        if self.offTracker:
            self.offTracker.shutdown()
            self.offTracker = None
        
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
                self._notify_pre_debounce(now, NotificationReason.Fire, msg)
                self.reminder_check(now)
            else:
                _LOGGER.warning(f'Activity {self.entity_id} turned off')
                #is_acked = self.last_ack_time and self.last_on_time and self.last_ack_time > self.last_on_time
                secs_on = (self.last_off_time - self.last_on_time).total_seconds()
                if self._done_message_template is None:
                    msg = f'turned off after {agoStr(secs_on)}.'
                else:
                    try:
                        msg = self._done_message_template.async_render(variables=self.extraVariables, parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} done_message template: {err}')
                        msg = f'turned off after {agoStr(secs_on)}. [done_message template error]'
                skip_notify = self.is_acked() and not self.ackRemindersOnly
                self._notify_pre_debounce(now, NotificationReason.StopFiring, msg, skip_notify=skip_notify)
                self.reminder_check(now)

                if self._used_persistent_notifier and self._persistent_notifier_grouping == PersistantNotificationHelper.CollapseAndDismiss:
                    async def foo():
                        await self.hass.services.async_call('persistent_notification', 'dismiss', { 'notification_id': PersistantNotificationHelper.genNotificationId(self)})
                    create_background_task(self.hass, DOMAIN, foo())


                
            
            if self.annotate_messages and (msg.startswith('command_') or \
                                           any([msg.startswith(x) for x in ['clear_badge', 'clear_notification', 'update_widgets', 'remove_channel'] ])):
                if self.alertData.uiMgr.setOneTime('set_annotate_messages_for_commands'):
                    report(DOMAIN, 'warning', f'Set annotate_messages to "false" if sending commands to the HA companion app (This one time suggestion is due to {self.entity_id} with msg={msg})')
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
                on_secs = (now - self.last_on_time).total_seconds()
                if self._reminder_message_template is None:
                    msg += f'on for {agoStr(on_secs)}'
                else:
                    evars = self.extraVariables.copy() if self.extraVariables else {}
                    evars['on_secs'] = on_secs
                    evars['on_time_str'] = agoStr(on_secs)
                    try:
                        msg += self._reminder_message_template.async_render(variables=evars, parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} reminder_message template: {err}')
                        msg += f'on for {agoStr(on_secs)} [reminder_message template error]'
            reason = NotificationReason.ReminderOn
        else:
            secs_off = (now - self.last_off_time).total_seconds()
            on_secs = (self.last_off_time - self.last_on_time).total_seconds()
            msg += f'turned off {agoStr(secs_off)} ago after being on for {agoStr(on_secs)}'
            reason = NotificationReason.Summary
        self._notify_pre_debounce(now, reason, msg)
        self.reminder_check(now)  # to set up next reminder (eg if alert is still on)
        self.async_write_ha_state()
    
    def sub_ack_int(self):
        # So we update last_ack_time if state is on
        if self.state == 'on':
            return True
        return self.last_off_time and (not self.last_ack_time or self.last_ack_time <= self.last_off_time)
    def is_acked(self):
        return bool(self.last_on_time and self.last_ack_time and self.last_ack_time > self.last_on_time)
    
    def sub_need_reminder(self):
        return self.state == 'on' and (not self.last_ack_time or self.last_ack_time < self.last_on_time)
    
    def cond_val_update(self, results):
        # The order of entries in results should match the order appended to templ in initialization
        #
        condition_bool = thresh_val = hysteresis_val = min_val = max_val = None
        if self._condition_template is not None:
            condition_bool = results.pop(0)
        if self._threshold_value_template is not None:
            thresh_val = results.pop(0)
            thresh_hyst = results.pop(0) if isinstance(self._threshold_hysteresis_float_or_template, template_helper.Template) \
                else self._threshold_hysteresis_float_or_template
            max_val = results.pop(0) if isinstance(self._threshold_max_float_or_template, template_helper.Template) \
                else self._threshold_max_float_or_template
            min_val = results.pop(0) if isinstance(self._threshold_min_float_or_template, template_helper.Template) \
                else self._threshold_min_float_or_template
        if len(results) > 0:
            report(DOMAIN, 'error', f'{gAssertMsg} {self.name}.  wrong number of tracked condition/threshold parameters')
            return

        if max_val is not None and min_val is not None and min_val > max_val:
            report(DOMAIN, 'error', f'{self.name}: threshold bounds error min > max ({min_val} > {max_val})')
            return
        
        # Now we have a condition_bool|None and a thresh_val|None
        # Figure out new state
        #
        #self._attr_available = True
        if self._threshold_value_template is None:
            if self._condition_template is None:
                # Config valudation should prevent this
                report(DOMAIN, 'error', f'{gAssertMsg} template for {self.name} appears to have neither condition nor threshold test specified')
                newState = False
            else:
                newState = condition_bool
        else:
            # Update threshold_exceeded
            aboveMax = max_val is not None and thresh_val > max_val
            belowMin = min_val is not None and thresh_val < min_val
            if aboveMax:
                self.threshold_exceeded = ThresholdExeeded.Max
            elif belowMin:
                self.threshold_exceeded = ThresholdExeeded.Min
            elif self.state == 'on':
                # >=, <= so that if hysteresis is 0, it behaves as if hysteresis wasn't specified
                aboveMaxHyst = max_val is not None and \
                    self.threshold_exceeded == ThresholdExeeded.Max and \
                    thresh_val > (max_val - thresh_hyst)
                belowMinHyst = min_val is not None and \
                    self.threshold_exceeded == ThresholdExeeded.Min and \
                    thresh_val < (min_val + thresh_hyst)
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
