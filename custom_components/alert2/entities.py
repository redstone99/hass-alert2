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
from   homeassistant.helpers.entity import Entity
from   homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.const as haConst
from   homeassistant.core import HomeAssistant, Context, callback, Event, EventStateChangedData
from   homeassistant.exceptions import TemplateError, ServiceNotFound
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
    gAssertMsg
)

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
        _LOGGER.debug(f'reportFire: {self.buckets}')

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
        _LOGGER.debug(f'  _updateBuckets: secsSinceLastAdvance={secsSinceLastAdvance} secsLeft={self.singleBucketSecs-secsSinceLastAdvance},  {self.buckets}')
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
            _LOGGER.debug(f'remainingSecs: acumm={acumm} ret0 {self.buckets}')
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
        _LOGGER.debug(f'remainingSecs: ret={secsToWait},  {self.buckets}')
        return secsToWait

def getField(fieldName, config, defaults, requireDefault=True):
    if fieldName in config:
        return config[fieldName]
    elif fieldName in defaults:
        return defaults[fieldName]
    else:
        if requireDefault:
            raise vol.Invalid(f'Alert {config["domain"]},{config["name"]} config or defaults must specify {fieldName}')
        else:
            return None

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


# An entity, though we won't add to hass
class AlertGenerator(SensorEntity):
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.DATA_SIZE #'problem'
    #_attr_available = True  defaults to True
    def __init__(self, hass, alertData, config):
        super().__init__()
        self.hass = hass
        self.alertData = alertData
        self.config = config
        self._attr_name = entNameFromDN(GENERATOR_DOMAIN, self.config["generator_name"])
        self._generator_template = self.config['generator']
        self.templateTrackerInfo = None
        # "name" here is overloaded. There's the 'name' from the domain+name specified in an alert config
        # then there's the 'name' that is the HA entity's name property.
        # Here we're using the entity name
        self.nameEntityMap = {} # Map from name -> ent
        
    def shutdown(self):
        if self.templateTrackerInfo:
            self.templateTrackerInfo.async_remove()
            self.templateTrackerInfo = None

    @property
    def state(self) -> str:
        return len(self.nameEntityMap)
    
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        earlyStart = False  # generators have earlyStart forced to False
        if earlyStart or self.alertData.haStarted:
            self.startWatching()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.startWatchingEv)

    def startWatchingEv(self, event):
        self.hass.loop.call_soon_threadsafe(self.startWatching)
    def startWatching(self):
        if isinstance(self._generator_template, list):
            atask = create_task(self.hass, DOMAIN, self.update(self._generator_template))
            return
        trackers = [ TrackTemplate(self._generator_template, None) ]
        # We use async_track_template_result rather than a higher-level form, components/template/template_entity:TemplateEntity
        # because TemplateEntity only starts working once HA has completely started and we'd like the generator to start generating while HA is starting.
        info = async_track_template_result(
            self.hass,
            trackers,
            self._tracker_result_cb,
        )
        self.templateTrackerInfo = info
        #self.async_on_remove(info.async_remove)  # stop template listeners if ConditionAlert is removed from hass. from helpers/entity.py
        info.async_refresh() # components/template/temlate_entity.py does this, so I guess we will, though this may not be necessary per docs of async_track_template_result
            
    @callback
    def _tracker_result_cb(self, 
                           event: Event[EventStateChangedData] | None,
                           updates: list[TrackTemplateResult]):
        if event:
            self.async_set_context(event.context)
        entity_id = event and event.data["entity_id"]
        _LOGGER.debug(f'Generator result cb for name={self.name}, self.entity_id={self.entity_id} entity_id={entity_id}')
        # This is how componnents/template/template_entity.py does cycle detection
        if entity_id and entity_id == self.entity_id:
            self._self_ref_update_count += 1
        else:
            self._self_ref_update_count = 0
        if self._self_ref_update_count > 2:
            report(DOMAIN, 'error', f'{self.name} Detected template loop. event={event}. Skipping render')
            return

        for update in updates:
            template = update.template
            result = update.result
            if isinstance(result, TemplateError):
                report(DOMAIN, 'error', f'{self.name} generator template threw error: {result}')
                return
            if template is None:
                report(DOMAIN, 'error', f'{gAssertMsg} {self.name} generator template var is None with result={result}')
                return
            elif template == self._generator_template:
                atask = create_task(self.hass, DOMAIN, self.update(result))
            else:
                report(DOMAIN, 'error', f'{gAssertMsg} template cb for {self.name} returned unexpected template rez={result} template={template}')
                
    async def update(self, result):
        if isinstance(result, list):
            _LOGGER.debug(f'{self.name} generator update called with list result={result}')
            alist = result
        else:
            _LOGGER.debug(f'{self.name} generator update called with result="{result}"')
            result = result.strip()
            try:
                literalList = ast.literal_eval(result)
            except Exception as ex:  # literal_eval can throw various kinds of exceptions
                literalList = result
            if len(result) == 0:
                alist = []
            else:
                # might not be [ str], will check below.
                alist = literalList if isinstance(literalList, list) else [ literalList ]
                
        # Now see if entities are added or deleted
        needWrite = False
        newEntities = []
        currNames = set() # entity names (ie the part after alert2.)
        sawError = False
        for elem in alist:
            svars = { 'genRaw': elem }
            if isinstance(elem, dict):
                svars.update(elem)
            elif self.hass.states.get(elem):
                svars['genEntityId'] = elem
            else:
                svars['genElem'] = elem
            
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
            #_LOGGER.warning(f'got result: {nameStr} {domainStr}')
            entName = entNameFromDN(domainStr, nameStr)
            currNames.add(entName)
            if entName in self.nameEntityMap:
                # entity continues to exist
                pass
            else:
                # new entity added
                if len(entName) == 0:
                    report(DOMAIN, 'error', f'Domain+Name template for {self.name} rendered to empty string')
                    continue
                acfg = dict(self.config) # very shallow copy, don't copy object values
                acfg['domain'] = domainStr
                acfg['name'] = nameStr
                if 'friendly_name' in self.config:
                    try:
                        friendlyNameStr = self.config['friendly_name'].async_render(
                            variables=svars, parse_result=False).strip()
                        acfg['friendly_name'] = friendlyNameStr
                    except TemplateError as err:
                        report(DOMAIN, 'error', f'{self.name} Friendly_name template returned err {err}')
                        sawError = True
                        break
                _LOGGER.debug(f'{self.name} generator creating alert: {acfg} with vars {svars}')
                ent = self.alertData.declareCondition(acfg, False, genVars=svars)
                if ent is not None:
                    _LOGGER.info(f'{self.name} generator created new alert entity {DOMAIN}.{ent.name}')
                    self.nameEntityMap[entName] = ent
                    newEntities.append(ent)
                    needWrite = True
        await self.alertData.component.async_add_entities(newEntities)

        if not sawError:
            # If we saw an error while processing templates, we might be missing entities
            # so don't do any deletions
            for aname in list(self.nameEntityMap.keys()):
                if not aname in currNames:
                    # entity no longer in list
                    ent = self.nameEntityMap[aname]
                    _LOGGER.info(f'Generator {self.name} removing alert entity {DOMAIN}.{ent.name}')
                    await ent.async_remove() # I think this is the complement of async_add_entities
                    self.alertData.undeclareCondition(ent.alDomain, ent.alName) # destroys ent
                    del self.nameEntityMap[aname]
                    needWrite = True
        if needWrite:
            self.async_write_ha_state()



# Functionality common to both event alerts and condition alerts
class AlertBase(RestoreEntity):
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM #'problem'
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults: dict[str, Any],
            genVars = None
    ):
        super().__init__()
        self.hass = hass
        self.alDomain = config['domain']
        self.alName = config['name']
        self._attr_name = entNameFromDN(self.alDomain, self.alName)

        # config stuff
        self._notifier_list_template = getField('notifier', config, defaults)
        self._summary_notifier = getField('summary_notifier', config, defaults)
        #_LOGGER.warning(f'{self.name}: {self._summary_notifier}')
        self.alertData = alertData
        self._condition_template = config['condition'] if 'condition' in config else None
        self._message_template = config['message'] if 'message' in config else None
        self._done_message_template = config['done_message'] if 'done_message' in config else None
        self._title_template = config['title'] if 'title' in config else None
        self._target_template = config['target'] if 'target' in config else None
        self._data = config['data'] if 'data' in config else None
        self._friendly_name = config['friendly_name'] if 'friendly_name' in config else None
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
        throttle_fires_per_mins = getField('throttle_fires_per_mins', config, defaults, requireDefault=False)
        self.movingSum = None
        if throttle_fires_per_mins is not None:
            self.movingSum = MovingSum(throttle_fires_per_mins[0], throttle_fires_per_mins[1])
        self.notified_max_on = False
        if genVars is not None:
            self.extraVariables = genVars
        else:
            self.extraVariables = None
        
        # State restored on restart
        self.last_notified_time = None
        self.last_fired_time = None
        self.last_fired_message = None
        self.last_ack_time = None
        self.fires_since_last_notify = 0  # or since last ack
        # enabled, disabled, or snooze unti time
        self.notification_control = NOTIFICATIONS_ENABLED

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
        }
        baseDict.update(self.more_state_attributes())
        return baseDict

    def destroy(self):
        self._attr_available = False
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
            self.future_notification_info = None
    
    def notify_timer_cb(self, now):
        assert False, "not implemented"
    def sub_need_reminder(self):
        assert False, "not implemented"
    def sub_ack_int(self):
        assert False, "not implemented"

    async def async_notification_control(
        self, enable: bool, snooze_until: rawdt.datetime | None = None
    ) -> None:
        _LOGGER.info(f'{self.name} got async_notification_control with enable={enable} and snooze_until={snooze_until}')
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
        _LOGGER.info(f'{self.name} got ack')
        now = dt.now()
        self.ack_int(now)
        
    async def async_unack(self):
        _LOGGER.info(f'{self.name} got unack')
        now = dt.now()
        if self.last_ack_time is not None:
            _LOGGER.debug(f'{self.name} unack_int')
            self.last_ack_time = None
            self.async_write_ha_state()
            self.reminder_check(now)

    def ack_int(self, now):
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
            _LOGGER.debug(f'{self.name} ack_int')
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
        _LOGGER.debug(f'reminder_check for {self.name}: need_reminder={need_reminder} {self.fires_since_last_notify} {self.notified_max_on} {self.sub_need_reminder()}')
        if need_reminder:
            remaining_secs, rem_reason = self.can_notify_now(now, reason)
            _LOGGER.debug(f'    remaining_secs={remaining_secs} rem_reason={rem_reason}')
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

    def sub_calc_next_reminder_frequency_mins(self, now):
        assert False, "Not Implemented"

    # returns list of notifiers
    # Returns [] if should not notify.
    def getNotifiers(self, args, reason: NotificationReason):
        # Get list of notifiers to notify
        notifiers = [ ]
        errors = [ ]
        debugInfo = []

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
        
        if isinstance(notifier_template, list):
            notifiers = notifier_template
            # config did some validation that it's list of non-empty strings
        else:
            try:
                renderRez = notifier_template.async_render(variables=self.extraVariables, parse_result=False).strip()
            except TemplateError as err:
                errors.append(f'{sourceTemplate} template: {err}')
                # Continue and notify anyways
            else:
                debugInfo.append(f'{sourceTemplate} template="{notifier_template}"')
                debugInfo.append(f'rendered="{renderRez}"')
                toEval = renderRez
                tstate = self.hass.states.get(renderRez)
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
                notifiers = literalList if isinstance(literalList, list) else [ literalList ]
                    
            #_LOGGER.warning(f'notifiers={notifiers} errors={errors} renderRez={renderRez} literalList={literalList}')
        notifier_list = []
        defer_notifier_list = []
        alertData = self.hass.data[DOMAIN]
        for anotifier in notifiers:
            if not isinstance(anotifier, str):
                errors.append(f'a {sourceTemplate} is not a string but {type(anotifier)}: "{anotifier}"')
            elif len(anotifier) == 0:
                errors.append(f'a {sourceTemplate} cannot be the empty string')
            elif alertData.delayedNotifierMgr.willDefer(anotifier, args):
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
                        report(DOMAIN, 'error', f'For {self.name}: somehow no {sourceTemplate} specified')
        if len(errors) > 0:
            errStr = f'{errors} with debugInfo {debugInfo}'
            if self.alDomain == DOMAIN and self.alName == 'error':
                args['message'] += f' # Additional errors: {errStr}'
                #_LOGGER.warning(f'updating message to {args["message"]}')
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
                _LOGGER.info(f'{self.name} snooze has expired. Reenabling notifications')
                self.notification_control = NOTIFICATIONS_ENABLED
                self.async_write_ha_state()
                snooze_remaining_secs = 0

        max_limit_remaining_secs = self.movingSum.remainingSecs(now) if self.movingSum is not None else 0

        normal_remaining_secs = 0
        if reason == NotificationReason.ReminderOn:
            reminder_frequency_mins = self.sub_calc_next_reminder_frequency_mins(now)
            if self.last_notified_time and reminder_frequency_mins > 0:
                secs_since_last = (now - self.last_notified_time).total_seconds()
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
            _LOGGER.debug(f'    reminder_frequency_mins = {reminder_frequency_mins}')
        _LOGGER.debug(f'can_notify_now {self.name}, snooze_remaining_secs={snooze_remaining_secs} max_limit_remaining_secs={max_limit_remaining_secs} normal_remaining_secs={normal_remaining_secs} remaining_secs={remaining_secs} freas={freas}')
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
        _LOGGER.debug(f'in _notify, remaining_secs={remaining_secs} {remaining_reason}, ms={self.movingSum}')
        
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None  # TODO - could avoid recreates if we keep it around.

        doNotify = remaining_secs == 0
        skipSummary = (reason in [ NotificationReason.Summary ]) and self._summary_notifier is False
        if skip_notify or skipSummary:
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

        _LOGGER.warning(f'_notify msg={msg}')
            
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
                _LOGGER.warning(f'Notifying {notifier_list}: {args["message"]}')
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
                    _LOGGER.debug(f'Notifying done: {notifier_list}')
                atask = create_task(self.hass, DOMAIN, foo())
            if len(defer_notifier_list) > 0:
                _LOGGER.warning(f'Defering notifying {defer_notifier_list}: {args["message"]}')
                
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
            else:
                report(DOMAIN, 'error', f'{self.name} not notifying with 0 remaining_secs and no skip_notify set')
                tillmsg = f' bad-logic-err'
            smsg = f'  Skipping notify for {self.alDomain}.{self.alName} {tillmsg}'
            _LOGGER.warning(smsg)
            if remaining_reason != NOTIFICATIONS_DISABLED:
                if remaining_secs > 0:
                    self.schedule_reminder(remaining_secs)
                # else:  must be that skip_notify is true because alert has already been acked
                
        if reason == NotificationReason.Fire:
            self.last_fired_message = message
            self.last_fired_time = now
        #_LOGGER.warning('')
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
        self.hass = hass
        self.detach_trigger = None
        self.earlyStart = config['early_start'] if 'early_start' in config else False
        
    @property
    def state(self) -> str:
        if not self.last_fired_time:
            return ""
        return self.last_fired_time.isoformat()
    def more_state_attributes(self):
        return {
        }
    def shutdown(self):
        if self.detach_trigger:
            self.detach_trigger()
            self.detach_trigger = None

    async def async_added_to_hass(self) -> None:
        """Restore extra state attributes on start-up."""
        await super().async_added_to_hass()

        if self.earlyStart or self.alertData.haStarted:
            await self.startWatching()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.startWatchingEv)

    def startWatchingEv(self, event):
        self.hass.loop.call_soon_threadsafe(self.startWatchingAlmost)
    def startWatchingAlmost(self):
        create_task(self.hass, DOMAIN, self.startWatching())
            
    async def startWatching(self):
        self.reminder_check()
        if 'trigger' in self.config:
            def log_cb(level: int, msg: str, **kwargs: Any) -> None:
                _LOGGER.log(level, "%s %s", msg, self.name, **kwargs)
            # TODO - support triggering on HA start, like components/automation/__init__.py:async_enable does
            #
            # I think home_assistant_start is something about the event when HA starts. I think it's just
            # used by triggers on the homeassistant itself, like when it starts up or shuts down.  I'm a bit fuzzy on this,
            # but it seems not applicable to our use case.
            home_assistant_start = False # TODO - supp
            # A chunk of this is based on homeassistant/components/automation/__init__.py::_async_attach_triggers
            this = None
            self.async_write_ha_state()
            if state := self.hass.states.get(self.entity_id):
                this = state.as_dict()
            variables = {"this": this}
            self.detach_trigger = await async_initialize_triggers(
                self.hass,
                self.config['trigger'],
                self.async_trigger,
                self.alDomain,
                str(self.name),
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
        _LOGGER.info("Alert Automation %s triggered%s", self.name, reason)

        this = self.state
        variables: dict[str, Any] = {"this": this, **(run_variables or {})}
        if self.extraVariables:
            variables.update(self.extraVariables)
        
        _LOGGER.debug(f'  variables are {variables["trigger"]}')
        try:
            # self._condition_template ok to reference cause condition required in the config schema for events
            rez = self._condition_template.async_render(variables, parse_result=False)
        except TemplateError as err:
            report(DOMAIN, 'error', f'{self.name} Condition template: {err}')
            return
        _LOGGER.debug(f'Got result: {rez}')
        try:
            brez = template_helper.result_as_boolean(rez)
        except vol.Invalid as err:
            report(DOMAIN, 'error', f'{self.name} condition template rendered to "{rez}", which is not truthy')
            return

        #_LOGGER.warning(f' cond={self._condition_template.template} and is {rez} {type(rez)} {brez}')
        _LOGGER.debug(f'  that became a bool: {brez}')

        if brez:
            _LOGGER.debug(f'  and event fired')
            msg = ''
            if self._message_template is not None:
                try:
                    msg = self._message_template.async_render(variables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'error', f'{self.name} Message template: {err}')
                    return
            await self.record_event(msg)
        else:
            _LOGGER.debug(f'  and event did not fire')
        
    async def record_event(self, message: str):
        now = dt.now()
        msg = message
        didNotify = self._notify(now, NotificationReason.Fire, message)
        if didNotify:
            self.reminder_check(now) # To schedule reminder - the only reminder I think that could be needed is if throttled, a notificaiton that throttling has turned off
        self.async_write_ha_state()
    
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
        # Might not notify cuz is summary
        #if not didNotify:
        #    report(DOMAIN, 'error', f'{gAssertMsg} notify_timer_cb, didNotify was false for {self.name}')
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
class ConditionAlertBase(AlertBase):
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

    def destroy(self):
        super().destroy()
        if self.cond_true_task:
            cancel_task(DOMAIN, self.cond_true_task)
            self.cond_true_task = None
            self.cond_true_time = None
        
        
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
                    _LOGGER.debug(f'{self.name}, starting delay of {self.delay_on_secs} until turning on')
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
                _LOGGER.debug(f'{self.name}, stopping turn-on delay')
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
                if self._notify(now, NotificationReason.Fire, msg):
                    self.reminder_check(now) # To schedule reminder
                else:
                    # did not notify, reminder already scheduled
                    pass
            else:
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
                                         #override_timing=self.notified_on,
                                         skip_notify=is_acked) # presumably, this means alert ended shortly after we tried notifying, so schedule one more notify for last interval of alert
                #if didNotify:
                #    self.notified_on = False
        self.async_write_ha_state()

        
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
        if not didNotify and reason == NotificationReason.ReminderOn:
            report(DOMAIN, 'error', f'{gAssertMsg} notify_timer_cb, didNotify for ReminderOn was false for {self.name}. {reason}')
        self.reminders_since_fire += 1
        #if didNotify:
        #    if is_on:
        #        self.notified_on = True
        #    else:
        #        self.notified_on = False
        self.async_write_ha_state()
        self.reminder_check(now)  # to set up next reminder (eg if alert is still on)
    
    def sub_ack_int(self):
        # So we update last_ack_time if state is on
        if self.state == 'on':
            return True
        return self.last_off_time and (not self.last_ack_time or self.last_ack_time <= self.last_off_time)
    
    def sub_need_reminder(self):
        #_LOGGER.warning(f'in sub_need_reminder. self.state={self.state} self.last_ack_time={self.last_ack_time}')
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

# From BinarySensorTemplate
class ConditionAlert(ConditionAlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults,
            genVars = None
    ) -> None:
        ConditionAlertBase.__init__(self, hass, alertData, config=config, defaults=defaults, genVars=genVars)
        self._threshold_value_template = config['threshold']['value'] if 'threshold' in config else None
        if self._threshold_value_template is not None:
            self._threshold_value_template.hass = hass
            self.threshold_max = config['threshold']['maximum'] if 'maximum' in config['threshold'] else None
            self.threshold_min = config['threshold']['minimum'] if 'minimum' in config['threshold'] else None
            self.threshold_hysteresis = config['threshold']['hysteresis'] if 'hysteresis' in config['threshold'] else None
            self.threshold_exceeded = ThresholdExeeded.Init # to record if we crossed min or max
        self.earlyStart = config['early_start'] if 'early_start' in config else False
        self.templateTrackerInfo = None
        self._self_ref_update_count = 0  # To detect template self-referencing loops
        
    async def async_added_to_hass(self) -> None:
        """Restore state and register callbacks."""
        await ConditionAlertBase.async_added_to_hass(self)
        if self.earlyStart or self.alertData.haStarted:
            self.startWatching()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.startWatchingEv)

    def startWatchingEv(self, event):
        self.hass.loop.call_soon_threadsafe(self.startWatching)
            
    def startWatching(self):
        self.reminder_check()
        trackers = []
        if self._condition_template is not None:
            trackers.append(TrackTemplate(self._condition_template, variables=self.extraVariables))
        if self._threshold_value_template is not None:
            trackers.append(TrackTemplate(self._threshold_value_template, variables=self.extraVariables))

        # We use async_track_template_result rather than a higher-level form, components/template/template_entity:TemplateEntity
        # because TemplateEntity only starts working once HA has completely started and we'd like to be able to alert while
        # HA is starting.
        info = async_track_template_result(
            self.hass,
            trackers,
            self._tracker_result_cb,
        )
        self.templateTrackerInfo = info
        #self.async_on_remove(info.async_remove)  # stop template listeners if ConditionAlert is removed from hass. from helpers/entity.py
        info.async_refresh() # components/template/temlate_entity.py does this, so I guess we will, though this may not be necessary per docs of async_track_template_result

    async def async_will_remove_from_hass(self) -> None:
        if self.templateTrackerInfo is not None:
            self.templateTrackerInfo.async_remove()
            self.templateTrackerInfo = None
    async def async_update(self) -> None:
        if self.templateTrackerInfo is not None:
            self.templateTrackerInfo.async_refresh()
        
    @callback
    def _tracker_result_cb(self, 
                           event: Event[EventStateChangedData] | None,
                           updates: list[TrackTemplateResult]):
        self._attr_available = False  # Updated to True, below, if we successfully process the updates
        if event:
            self.async_set_context(event.context)
        entity_id = event and event.data["entity_id"]
        _LOGGER.debug(f'Result cb for name={self.name}, self.entity_id={self.entity_id} entity_id={entity_id}')
        if entity_id and entity_id == self.entity_id:
            self._self_ref_update_count += 1
        else:
            self._self_ref_update_count = 0
        # 2 since we track condition and threshold templates. I would have thought 1 would be fine but maybe
        # _tracker_result_cb gets called multiple times for same entity_id.
        # This is how componnents/template/template_entity.py does it.
        if self._self_ref_update_count > 2:
            report(DOMAIN, 'error', f'{self.name} Detected template loop. event={event}. Skipping render')
            return

        has_condition = False
        has_threshold = False
        condition_result = None
        thresh_result = None
        for update in updates:
            template = update.template
            result = update.result
            if isinstance(result, TemplateError):
                report(DOMAIN, 'error', f'{self.name} template {template}: {result}')
                return
            if template is None:
                report(DOMAIN, 'error', f'{gAssertMsg} template is None for {self.name}: {result}')
            elif template == self._condition_template:
                has_condition = True
                condition_result = result
            elif template == self._threshold_value_template:
                has_threshold = True
                thresh_result = result
            else:
                report(DOMAIN, 'error', f'{gAssertMsg} template cb for {self.name} returned unexpected template rez={result} template={template}')
            
        if not has_condition:
            if self._condition_template is not None:
                has_condition = True
                try:
                    condition_result = self._condition_template.async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'error', f'{self.name} Condition template: {err}')
                    return
        condition_bool = None
        if has_condition:
            try:
                condition_bool = template_helper.result_as_boolean(condition_result)
            except vol.Invalid as err:
                report(DOMAIN, 'error', f'{self.name} condition template rendered to "{condition_result}", which is not truthy')
                return
                
        if not has_threshold:
            if self._threshold_value_template is not None:
                has_threshold = True
                try:
                    thresh_result = self._threshold_value_template.async_render(variables=self.extraVariables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'error', f'{self.name} Threshold value template: {err}')
                    return
        thresh_val = None
        if has_threshold:
            try:
                thresh_val = float(thresh_result)
            except ValueError:
                report(DOMAIN, 'error', f'{self.name} Threshold value returned "{thresh_result}" rather than a float')
                return
            
        # Now we have a condition_bool|None and a thresh_val|None
        # Figure out new state
        #
        self._attr_available = True
        if not has_threshold:
            if not has_condition:
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

class ConditionAlertManual(ConditionAlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults
    ) -> None:
        ConditionAlertBase.__init__(self, hass, alertData, config=config, defaults=defaults)
        
    async def async_added_to_hass(self) -> None:
        """Restore state and register callbacks."""
        await super().async_added_to_hass()
        self.reminder_check()

    # Note that async_added_to_hass may be called after
    # the setup of any component, so it may overwrite state.
    def set_state(self, newState:bool):
        if isinstance(newState, bool):
            self.update_state_internal(newState)
        else:
            report(DOMAIN, 'error', f'{gAssertMsg} ConditionAlertManual::set_state ignoring call with non-bool: {newState} with type={type(newState)} for {self.name}')
