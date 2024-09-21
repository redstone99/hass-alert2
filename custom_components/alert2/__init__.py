#
# Alert2
#
# Basic documentation on this integration is at https://github.com/redstone99/hass-alert2/tree/master
#
# TODO - document more completely
#
import asyncio
import copy
import datetime as rawdt
from   enum import Enum
from   io import StringIO
import logging
from   typing import Any
import voluptuous as vol
from   homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    EVENT_HOMEASSISTANT_STARTED
)
from   homeassistant.core import HomeAssistant, callback, Context, Event, EventStateChangedData
from   homeassistant.exceptions import TemplateError
from   homeassistant.helpers import template as template_helper, discovery
import homeassistant.helpers.config_validation as cv
from   homeassistant.helpers.entity_component import EntityComponent
from   homeassistant.helpers.event import async_track_template_result, TrackTemplate, TrackTemplateResult
from   homeassistant.helpers.restore_state import RestoreEntity
from   homeassistant.helpers.trigger import async_initialize_triggers
from   homeassistant.helpers.typing import ConfigType
import homeassistant.util.dt as dt

from .config import (
    DEFAULTS_SCHEMA,
    SINGLE_TRACKED_SCHEMA,
    SINGLE_ALERT_SCHEMA_BASE,
    SINGLE_ALERT_SCHEMA_EVENT,
    SINGLE_ALERT_SCHEMA_CONDITION,
    TOP_LEVEL_SCHEMA
)

_LOGGER = logging.getLogger(__name__)
DOMAIN = "alert2"
EVENT_TYPE = 'alert2_report'
NOTIFICATIONS_ENABLED  = 'enabled'
NOTIFICATIONS_DISABLED = 'disabled'
global_hass = None
global_tasks = set()

# The notify component loads asynchronously, so we don't know when the notify legacy platforms
# will have finished loading. So wait a few seconds before throwing errors for missing notifiers
moduleLoadTime = dt.now()
kNotifierInitGraceSecs = 120

##########################################################
#
# BEGIN - Utility functions for developers to call
#
#

#
# report() - report that an event alert has fired
# 
def report(domain: str, name: str, message: str | None = None, isException: bool = False) -> None:
    data = { 'domain' : domain, 'name' : name }
    if message is not None:
        data['message'] = message
    if isException:
        _LOGGER.exception(f'Err reported: {data}')
    else:
        _LOGGER.error(f'Err reported: {data}')
    if global_hass:
        global_hass.bus.async_fire(EVENT_TYPE, data)
    else:
        _LOGGER.error('report() called before Alert2 has initialized. reporting skipped.')
        
#
# declareEventMulti - takes array of config entries. E.g.:
#
#    declareEventMulti([  { 'domain': 'mydomain', 'name': 'some err 1' },
#                         { 'domain': 'mydomain', 'name': 'some err 2' } ])
#
async def declareEventMulti(arr):
    await global_hass.data[DOMAIN].declareEventMulti(arr)

#
# create_task() - similar to hass.async_create_task() but it also report exceptions if they happen so the task doesn't die silently.
#                 Task will be cancelled when HA shuts down. 
# afut is a future
# returns a task object.
#
def create_task(hass, domain, afut):
    global global_tasks
    atask = hass.loop.create_task( afut )
    cb = lambda ttask: taskDone(domain, ttask)
    atask.add_done_callback(cb)
    _LOGGER.debug(f'create_task called for domain {domain}, {atask}')
    global_tasks.add(atask)
    return atask

#
# cancel_task - cancel a task created with create_task().  atask is the task returned by create_task()
#
def cancel_task(domain, atask):
    global global_tasks
    _LOGGER.debug(f'Calling cancel_task for {domain} and {atask}')
    # Cancelling a task means its done handler is called, so no need to remove task from global_tasks
    atask.cancel()


##########################################################
#
# END of utility functions. Below this is Alert2 internal code.
#
    
class NotificationReason(Enum):
    Fire = 1
    StopFiring = 2
    Reminder = 3

# return a string x, st, jinja2.Template(x).render() == astr
# message field in components/notify/const.py:NOTIFY_SERVICE_SCHEMA is a template and will be rendered
# That is, even though notifications comopnent complains about passing templates to notify, it still calls render()
# and so to get a straight message through you have to jinja2Escape it.
def jinja2Escape(astr):
    a2str = astr.replace('{%', '{% endraw %}{{"{%"}}{% raw %}')
    return '{% raw %}' + a2str + '{% endraw %}'
    
def taskDone(domain, atask):
    _LOGGER.debug(f'Calling taskDone for {domain} and {atask}')
    global global_tasks
    if atask in global_tasks:
        _LOGGER.debug(f'taskDone.. called for domain {domain}, {atask}')
        global_tasks.remove(atask)
    else:
        report(DOMAIN, 'assert', f'taskDone called for domain {domain}, {atask} but is not in global_tasks')
    if atask.cancelled():
        _LOGGER.debug(f'taskDone: task was cancelled: {atask}')
        return
    ex = atask.exception()
    if ex:
        output = StringIO()
        atask.print_stack(file=output)
        astack = output.getvalue()
        _LOGGER.error(f'unhandled_exception with stack {astack}')
        report(domain, 'unhandled_exception', str(ex))


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
            report(DOMAIN, 'assert', f'MovingAvg no lastAdvanceTime but buckets not empty {currSum}')
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
            report(DOMAIN, 'assert', f'MovingAvg bucket update logic produced wrong length {self.numBuckets} vs {self.buckets}')
            self.buckets = [0]*self.numBuckets
        newSum = sum(self.buckets)
        if newSum == 0:
            self.lastAdvanceTime = None
            return
        self.lastAdvanceTime = self.lastAdvanceTime + rawdt.timedelta(seconds=(bucketAdvancesSinceLastInt*self.singleBucketSecs))
        if (now - self.lastAdvanceTime).total_seconds() > self.singleBucketSecs:
            report(DOMAIN, 'assert', f'MovingAvg _updateBuckets left more than a single bucket interval of time left')
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
            report(DOMAIN, 'assert', f'MovingAvg not empty but somehow missing bucketAdvanceTime')
            return 0
        intervalSecsElapsed = (now - self.lastAdvanceTime).total_seconds()
        secsToWait = secsToWait - intervalSecsElapsed
        #secsToWait = secsToWait + 5
        if secsToWait < 0:
            report(DOMAIN, 'assert', f'MovingAvg secsToWait produced negative: {secsToWait}')
            return 60
        _LOGGER.debug(f'remainingSecs: ret={secsToWait},  {self.buckets}')
        return secsToWait

    
# Functionality common to both event alerts and condition alerts
class AlertBase(RestoreEntity):
    _attr_should_poll = False
    _attr_device_class = 'problem'
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults: dict[str, Any],
    ):
        super().__init__()
        self.hass = hass
        self.alDomain = config['domain']
        self.alName = config['name']
        self._attr_name = f'{self.alDomain}_{self.alName}'

        # config stuff
        self.notifier = getField('notifier', config, defaults)
        self.alertData = alertData
        self._condition_template = config['condition'] if 'condition' in config else None
        self._message_template = config['message'] if 'message' in config else None
        self._done_message_template = config['done_message'] if 'done_message' in config else None
        self._title_template = config['title'] if 'title' in config else None
        self._data = config['data'] if 'data' in config else None
        self._target = config['target'] if 'target' in config else None
        self._friendly_name = config['friendly_name'] if 'friendly_name' in config else None
        if self._message_template is not None:
            self._message_template.hass = hass
        if self._done_message_template is not None:
            self._done_message_template.hass = hass
        if self._title_template is not None:
            self._title_template.hass = hass
        self.annotate_messages = getField('annotate_messages', config, defaults)
        throttle_fires_per_mins = getField('throttle_fires_per_mins', config, defaults, requireDefault=False)
        self.movingSum = None
        if throttle_fires_per_mins is not None:
            self.movingSum = MovingSum(throttle_fires_per_mins[0], throttle_fires_per_mins[1])
        self.notified_max_on = False
        
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
                    report(DOMAIN, 'assert', f'Notification control call has snooze time specified without timezone info: {snooze_until} for {self.name}')
                new_snooze = snooze_until
            else:
                new_snooze = NOTIFICATIONS_ENABLED
        else:
            new_snooze = NOTIFICATIONS_DISABLED
        self.notification_control = new_snooze
        self.async_write_ha_state()
        self.alertData.noteChange()
        now = dt.now()
        self.reminder_check(now)
    
    async def async_ack(self):
        _LOGGER.info(f'{self.name} got ack')
        now = dt.now()
        self.ack_int(now)
        self.alertData.noteChange()

    # Caller must call alertData.noteChange()
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
            _LOGGER.info(f'{self.name} ack_int')
            self.last_ack_time = now
            self.async_write_ha_state()

    # idempotent, can call many times
    def reminder_check(self, now = None):
        if not now:
            now = dt.now()
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None
        need_reminder = (self.fires_since_last_notify > 0) or self.notified_max_on or self.sub_need_reminder()
        if need_reminder:
            remaining_secs, rem_reason = self.can_notify_now(now, NotificationReason.Reminder)
            if rem_reason == NOTIFICATIONS_DISABLED:
                return
            if remaining_secs == 0:
                self.notify_timer_cb(now)
            else:
                if not (isinstance(remaining_secs, int) or isinstance(remaining_secs, float)) or remaining_secs <= 0:
                    report(DOMAIN, 'assert', f'In reminder_check, remaining_secs={remaining_secs} of type={type(remaining_secs)} for {self.name}')
                    return
                self.schedule_reminder(remaining_secs)

    def sub_calc_next_reminder_frequency_mins(self, now):
        assert False, "Not Implemented"
        
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
            snooze_remaining_secs = (self.notification_control - now).total_seconds()
            if snooze_remaining_secs <= 0:
                self.notification_control = NOTIFICATIONS_ENABLED
                self.async_write_ha_state()
                self.alertData.noteChange()
                snooze_remaining_secs = 0

        max_limit_remaining_secs = self.movingSum.remainingSecs(now) if self.movingSum is not None else 0

        normal_remaining_secs = 0
        if reason == NotificationReason.Reminder:
            reminder_frequency_mins = self.sub_calc_next_reminder_frequency_mins(now)
            if self.last_notified_time and reminder_frequency_mins > 0:
                secs_since_last = (now - self.last_notified_time).total_seconds()
                next_secs = reminder_frequency_mins * 60.0
                normal_remaining_secs = max(0, next_secs - secs_since_last)

        startup_remaining_secs = 0
        if not self.hass.services.has_service('notify', self.notifier):
            uptimeSecs = (dt.now() - moduleLoadTime).total_seconds()
            graceRemainSecs = kNotifierInitGraceSecs - uptimeSecs
            if graceRemainSecs > 0:
                # HA still may be initializing and hasn't gotten around to loading the notifiers yet.
                startup_remaining_secs = 10
            # Otherwise, do the notify, which will fail and fire the notify_failed alert

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
        if startup_remaining_secs > remaining_secs:
            remaining_secs = startup_remaining_secs
            freas = 'delayed_init'
        if normal_remaining_secs > remaining_secs:
            remaining_secs = normal_remaining_secs
            freas = 'reminder'
            _LOGGER.debug(f'    reminder_frequency_mins = {reminder_frequency_mins}')
        #remaining_secs = max(max_limit_remaining_secs, snooze_remaining_secs,
        #                     startup_remaining_secs, normal_remaining_secs)
        _LOGGER.debug(f'can_notify_now {self.name}, snooze_remaining_secs={snooze_remaining_secs} max_limit_remaining_secs={max_limit_remaining_secs} normal_remaining_secs={normal_remaining_secs} startup_remaining_secs={startup_remaining_secs} remaining_secs={remaining_secs} freas={freas}')
        return (remaining_secs, freas)
            
            
    def schedule_reminder(self, remaining_secs):
        async def foo():
            try:
                # + 1 so that the call to reminder_check is highly likely to see
                # can_notify_now is True
                await asyncio.sleep(remaining_secs + 1)
                if asyncio.current_task() != self.future_notification_info['task']:
                    report(DOMAIN, 'assert', f'In schedule_reminder remindar somehow is not correct task: {asyncio.current_task()} vs {self.future_notification_info["task"]} for {self.name}')
                    return
                self.future_notification_info = None
                self.reminder_check()
            except asyncio.CancelledError:
                _LOGGER.debug(f'Skipping cancel exception for task {asyncio.current_task()}')
            except Exception as ex:
                msg = f'{self.name} In schedule_reminder/foo got exception: {ex.__class__}, {ex}'
                report(DOMAIN, 'exception', msg, isException=True)
        if self.future_notification_info is not None:
            report(DOMAIN, 'assert', f'In schedule_reminder, ignoring since an outstanding reminder already exists: {self.future_notification_info} for {self.name}')
            return
        atask = create_task(self.hass, DOMAIN, foo())
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
        if skip_notify:
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
                report(DOMAIN, 'assert', f'{self.name}: saw throttling start, but not notifying. Seems impossible. {max_limit_remaining_secs} ')
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
            if not doNotify and remaining_reason not in [ NOTIFICATIONS_DISABLED, 'snoozed' ]:
                report(DOMAIN, 'assert', f'{self.name}: saw throttling stop, but not notifyign, seems impossible. {remaining_secs}, {remaining_reason}')

                
        addedName = False
        if self.annotate_messages or reason == NotificationReason.Reminder:
            addedName = True
            if self._friendly_name is None:
                msg += f'Alert2 {self.name}'
            else:
                msg += self._friendly_name
            
        if doNotify and self.fires_since_last_notify > 0:
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
            notifier = self.notifier
            if self.alDomain == DOMAIN and self.alName == 'notify_failed':
                if self.hass.services.has_service('notify', notifier):
                    pass
                elif self.hass.services.has_service('notify', self.alertData.defaults['notifier']):
                    notifier = self.alertData.defaults['notifier']
                elif self.hass.services.has_service('notify', 'notify'):
                    notifier = 'notify'
                else:
                    _LOGGER.error(f'No notifier found to notify notify_failed')
                    return True
            else:
                if self.hass.services.has_service('notify', notifier):
                    pass
                else:
                    # If the notifier isn't available, we fire an alert for that.
                    # At that point, our obligation to notify on the current alert is done.
                    report(DOMAIN, 'notify_failed', f'no notifier {self.notifier} to notify {self.alDomain}:{self.alName}')
                    return True

            tmsg = msg
            if len(tmsg) > 600:
                tmsg = tmsg[:600] + '...'
            _LOGGER.warning(f'Notifying {self.notifier}: {tmsg}')
            # message field in components/notify/const.py:NOTIFY_SERVICE_SCHEMA is a template and will be rendered
            args = {'message': jinja2Escape(tmsg) }
            if self._data is not None:
                args['data'] = self._data
            if self._target is not None:
                args['target'] = self._target
            if self._title_template is not None:
                try:
                    args['title'] = self._title_template.async_render(parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'template_error', f'Title template for {self.name}: {err}')
                    # Continue and notify anyways
            async def foo():
                await self.hass.services.async_call(
                    'notify', self.notifier, # eg 'raw_jtelegram'
                    args)
                _LOGGER.debug(f'Notifying done: {self.notifier}')
            atask = create_task(self.hass, DOMAIN, foo())
        else:
            if reason == NotificationReason.Fire:
                self.fires_since_last_notify += 1

            if remaining_reason == NOTIFICATIONS_DISABLED:
                tillmsg = 'disabled'
            else:
                tillmsg = f', {remaining_reason} next notify is {remaining_secs} secs away'
            smsg = f'  Skipping notify for {self.alDomain}.{self.alName} {tillmsg}'
            _LOGGER.warning(smsg)
            if remaining_reason != NOTIFICATIONS_DISABLED:
                if remaining_secs == 0:
                    report(DOMAIN, 'assert', f'{self.name}, not notifying but remaining time is 0')
                    remaining_secs = 60
                self.schedule_reminder(remaining_secs)
                
        if reason == NotificationReason.Fire:
            self.last_fired_message = message
            self.last_fired_time = now
        #_LOGGER.warning('')
        return doNotify

def agoStr(secondsAgo):
    if secondsAgo < 1.5*60:
        astr = f'{round(secondsAgo)}s'
    elif secondsAgo < 1.5*60*60:
        astr = f'{round(secondsAgo/60)}m'
    elif secondsAgo < 1.5*24*60*60:
        astr = f'{round(secondsAgo/(60*60))}h'
    else:
        astr = f'{round(secondsAgo/(24*60*60))}d'
    return astr

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
        self.reminder_check()
        
        if 'trigger' in self.config:
            def log_cb(level: int, msg: str, **kwargs: Any) -> None:
                _LOGGER.log(level, "%s %s", msg, self.name, **kwargs)
            # TODO - support triggering on HA start, like components/automation/__init__.py:async_enable does
            home_assistant_start = False # TODO - supp
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
        
        _LOGGER.debug(f'  variables are {variables["trigger"]}')
        try:
            # self._condition_template ok to reference cause condition required in the config schema for events
            rez = self._condition_template.async_render(variables, parse_result=False)
        except TemplateError as err:
            report(DOMAIN, 'template_error', f'Condition template for {self.name}: {err}')
            return
        _LOGGER.debug(f'Got result: {rez}')
        brez = template_helper.result_as_boolean(rez)
        _LOGGER.debug(f'  that became a bool: {brez}')

        if brez:
            _LOGGER.debug(f'  and event fired')
            msg = ''
            if self._message_template is not None:
                try:
                    msg = self._message_template.async_render(variables, parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'template_error', f'Message template for {self.name}: {err}')
                    return
            await self.record_event(msg)
        else:
            _LOGGER.debug(f'  and event did not fire')
        
    async def record_event(self, message: str):
        now = dt.now()
        msg = message
        didNotify = self._notify(now, NotificationReason.Fire, message)
        self.async_write_ha_state()
        self.alertData.noteChange()
    
    def notify_timer_cb(self, now):
        if self.fires_since_last_notify <= 0:
            report(DOMAIN, 'assert', f'in notify_timer_cb, fires_since_last_notify is not positive, is {self.fires_since_last_notify} for {self.name}')
        msg = f'Last msg: {self.last_fired_message}'
        didNotify = self._notify(now, NotificationReason.Reminder, msg)
        if not didNotify:
            report(DOMAIN, 'assert', f'in notify_timer_cb, didNotify was false for {self.name}')
        self.async_write_ha_state()
        self.alertData.noteChange()
        return didNotify
    def sub_ack_int(self):
        return self.last_fired_time and (not self.last_ack_time or self.last_ack_time <= self.last_fired_time)
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
            defaults
    ) -> None:
        AlertBase.__init__(self, hass, alertData, config=config, defaults=defaults)

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

        self.reminder_check()
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
                    self.cond_true_task = create_task(self.hass, DOMAIN, dodelay())
                else:
                    report(DOMAIN, 'assert', f'for {self.name} turning on but already have delayed wait set')
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
            report(DOMAIN, 'assert', f'update_state_internal ignoring call with non-bool {state} type={type(state)} for {self.name}')
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
                        msg = self._message_template.async_render(parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'template_error', f'Condition template for {self.name}: {err}')
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
                        msg = self._done_message_template.async_render(parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'template_error', f'done_message template for {self.name}: {err}')
                        msg = f'turned off after {agoStr(secs_on)}. [done_message template error]'
                didNotify = self._notify(now, NotificationReason.StopFiring, msg,
                                         #override_timing=self.notified_on,
                                         skip_notify=is_acked) # presumably, this means alert ended shortly after we tried notifying, so schedule one more notify for last interval of alert
                #if didNotify:
                #    self.notified_on = False
        self.async_write_ha_state()
        self.alertData.noteChange()

        
    def notify_timer_cb(self, now):
        msg = ''
        is_on = self.state == 'on'
        if is_on:
            if not self.last_on_time:
                report(DOMAIN, 'assert', f'in notify_timer_cb, is_on=True but no self.last_on_time={self.last_on_time} for {self.name}')
            else:
                secs_on = (now - self.last_on_time).total_seconds()
                msg += f'on for {agoStr(secs_on)}'
        else:
            secs_off = (now - self.last_off_time).total_seconds()
            secs_on = (self.last_off_time - self.last_on_time).total_seconds()
            msg += f'turned off {agoStr(secs_off)} ago after being on for {agoStr(secs_on)}'
        didNotify = self._notify(now, NotificationReason.Reminder, msg)
        if not didNotify:
            report(DOMAIN, 'assert', f'in notify_timer_cb, didNotify was false for {self.name}')
        self.reminders_since_fire += 1
        #if didNotify:
        #    if is_on:
        #        self.notified_on = True
        #    else:
        #        self.notified_on = False
        self.async_write_ha_state()
        self.alertData.noteChange()
        self.reminder_check(now)  # to set up next reminder (eg if alert is still on)
        #return didNotify
    
    def sub_ack_int(self):
        # So we update last_ack_time if state is on
        if self.state == 'on':
            return True
        return self.last_off_time and (not self.last_ack_time or self.last_ack_time <= self.last_off_time)
    
    def sub_need_reminder(self):
        #_LOGGER.warning(f'in sub_need_reminder. self.state={self.state} self.last_ack_time={self.last_ack_time}')
        return self.state == 'on' and (not self.last_ack_time or self.last_ack_time < self.last_on_time)
        #if self.state == 'on':
        #    if not self.last_ack_time or self.last_ack_time < self.last_on_time:
        #        return True
        #    return False
        # # Alert is off
        #return self.notified_on
    
    def sub_calc_next_reminder_frequency_mins(self, now):
        # alert may be off and this may be called as part of can_notify_now() after throttling ended.
        if self.state != 'on' and not self.notified_max_on:
            report(DOMAIN, 'assert', f'in sub_calc_next_reminder_frequency_mins, weird to ask when alert is not on. {self.name}')
            # keep going
        if not self.last_on_time:
            report(DOMAIN, 'assert', f'in sub_calc_next_reminder_frequency_mins, can not calc reminder time since alert is not on. {self.name}')
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
            defaults
    ) -> None:
        ConditionAlertBase.__init__(self, hass, alertData, config=config, defaults=defaults)
        self._threshold_value_template = config['threshold']['value'] if 'threshold' in config else None
        if self._threshold_value_template is not None:
            self._threshold_value_template.hass = hass
            self.threshold_max = config['threshold']['maximum'] if 'maximum' in config['threshold'] else None
            self.threshold_min = config['threshold']['minimum'] if 'minimum' in config['threshold'] else None
            self.threshold_hysteresis = config['threshold']['hysteresis'] if 'hysteresis' in config['threshold'] else None
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
        #_LOGGER.debug(f'Starting watching {self.name}')
        trackers = []
        if self._condition_template is not None:
            trackers.append(TrackTemplate(self._condition_template, None))
        if self._threshold_value_template is not None:
            trackers.append(TrackTemplate(self._threshold_value_template, None))

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
            report(DOMAIN, 'template_error', f'Detected template loop in {self.name}. event={event}. Skipping render')
            return

        has_condition = False
        has_threshold = False
        condition_bool = None
        thresh_result = thresh_val = None
        for update in updates:
            template = update.template
            result = update.result
            if isinstance(result, TemplateError):
                report(DOMAIN, 'template_error', f'template {template} for {self.name}: {result}')
                return
            if template is None:
                report(DOMAIN, 'assert', f'template is None for {self.name}: {result}')
            elif template == self._condition_template:
                has_condition = True
                condition_bool = template_helper.result_as_boolean(result)
            elif template == self._threshold_value_template:
                has_threshold = True
                thresh_result = result
            else:
                report(DOMAIN, 'assert', f'template cb for {self.name} returned unexpected template rez={result} template={template}')
        if not has_condition:
            if self._condition_template is not None:
                try:
                    rez = self._condition_template.async_render(parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'template_error', f'Condition template err for {self.name}: {err}')
                    return
                condition_bool = template_helper.result_as_boolean(rez)
                
        if not has_threshold:
            if self._threshold_value_template is not None:
                try:
                    thresh_result = self._threshold_value_template.async_render(parse_result=False)
                except TemplateError as err:
                    report(DOMAIN, 'template_error', f'Threshold value template for {self.name}: {err}')
                    return
        if thresh_result is not None:
            try:
                thresh_val = float(thresh_result)
            except ValueError:
                report(DOMAIN, 'template_error', f'Threshold value of {self.name} returned "{thresh_result}" rather than a float')
                return
            
        # Now we have a condition_bool|None and a thresh_val|None
        # Figure out new state
        #
        self._attr_available = True
        if condition_bool in [ None, True ]:
            if thresh_val is None:
                if condition_bool is not True:
                    # Config valudation should prevent this
                    report(DOMAIN, 'assert', f'template for {self.name} appears to have neither condition nor threshold test specified')
                newState = True
            else:
                aboveMax = self.threshold_max is not None and thresh_val > self.threshold_max
                belowMin = self.threshold_min is not None and thresh_val < self.threshold_min
                if aboveMax or belowMin:
                    newState = True
                else:
                    if self.threshold_hysteresis is None:
                        newState = False
                    else:
                        if self.state == 'on':
                            # >=, <= so that if hysteresis is 0, it behaves as if hysteresis wasn't specified
                            aboveMaxHyst = self.threshold_max is not None and thresh_val > (self.threshold_max - self.threshold_hysteresis)
                            belowMinHyst = self.threshold_min is not None and thresh_val < (self.threshold_min + self.threshold_hysteresis)
                            newState = aboveMaxHyst or belowMinHyst
                        else:
                            newState = False
        else:
            if condition_bool is not False:
                report(DOMAIN, 'assert', f'template for {self.name}: condition_bool is neither None or bool. Is {condition_bool} {type(condition_bool)}')
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

    # Note that async_added_to_hass may be called after
    # the setup of any component, so it may overwrite state.
    def set_state(self, newState:bool):
        if isinstance(newState, bool):
            self.update_state_internal(newState)
        else:
            report(DOMAIN, 'assert', f'ConditionAlertManual::set_state ignoring call with non-bool: {newState} with type={type(newState)} for {self.name}')

        
NOTIFICATION_CONTROL_SCHEMA = {
    vol.Required("enable"): cv.boolean, #vol.Any(STATE_ON, STATE_OFF, NOTIFICATION_SNOOZE),  ( from homeassistant.const )
    vol.Optional("snooze_until"): cv.datetime,
}
ACK_SCHEMA = {
}
    
async def async_setup(hass, config: ConfigType):
    global global_hass
    global_hass = hass
    _LOGGER.info('Setting up Alert2')

    data = Alert2Data(hass, config)
    hass.data[DOMAIN] = data

    # Load sensor.py wtihout requiring users put an extra line in their configuuration.yaml
    platform_domain = 'sensor'
    hass.async_create_task(
        discovery.async_load_platform(
            hass,
            platform_domain,
            DOMAIN,
            { 'happy': 7 },  # can be None? I think this is the config that gets passed to the sensor module.
            config,
        )
        , eager_start=True)
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
    create_task(hass, DOMAIN, data.slowStartup())
    return True

# NOTE - this must be a single-level Schema.  If nest anything, then fix up copy.copy() shallow copy logic down in
# handle_report_int()
#REPORT_SCHEMA = {
#    vol.Required("domain"): str,
#    vol.Required("name"): str,
#    vol.Optional("message"): str,
#}


class Alert2Data:
    def __init__(self, hass, config):
        self._hass = hass
        self._rawConfig = config[DOMAIN]
        self.tracked = {}
        self.alerts = {}
        self.component = EntityComponent[EventAlert](_LOGGER, DOMAIN, hass)
        self.sensorDict = None
        self.binarySensorDict = None
        self.evCount = 0
        self.defaults = DEFAULTS_SCHEMA({ 'reminder_frequency_mins': [60], 'notifier': 'persistent_notification', 'annotate_messages': True })
        #self.defaults.update({ 'throttle_fires_per_mins': None })
        self.notifiers = set()
        self.notifiers.add(self.defaults['notifier']) # We'll do this again once we processConfig
        self.haStarted = False

        self.defaultsError = None

    async def init2(self):
        # First, initialize enough so that report() will work for internal errors
        #

        # Try processing just the defaults part of the config, so they'll apply to the internal events we declare, below.
        # report() isn't available yet, so defer error reporting until later in init
        if 'defaults' in self._rawConfig:
            try:
                defCfg = DEFAULTS_SCHEMA(self._rawConfig['defaults'])
                self.defaults.update(defCfg)
                self.notifiers.add(self.defaults['notifier'])
            except vol.Invalid as v:
                # Error will be reported later in init.
                self.defaultsError = v
        
        entities = []
        entities.append(self.declareEvent(DOMAIN, 'undeclared_event'))
        entities.append(self.declareEvent(DOMAIN, 'unhandled_exception'))
        # the notifier choice for notify_failed is special logic. The value for notifier specified here is ignored, but
        # put persistent_notification here since it should always be available (once HA starts), in case
        # the config specifies a default notifier that is not available
        entities.append(self.declareEvent(DOMAIN, 'notify_failed', 'persistent_notification'))
        entities.append(self.declareEvent(DOMAIN, 'template_error'))
        entities.append(self.declareEvent(DOMAIN, 'config_error'))
        entities.append(self.declareEvent(DOMAIN, 'malformed_call'))
        entities.append(self.declareEvent(DOMAIN, 'exception'))
        entities.append(self.declareEvent(DOMAIN, 'assert'))
        await self.component.async_add_entities(entities)

        # Now that report() is available, continue init that might use it
        
        loop = asyncio.get_running_loop()
        # Gives traceback info on asyncio 'Unclosed client session' errors
        #loop.set_debug(True)
        oldHandler = loop.get_exception_handler()
        self.inHandler = False
        def newHandler(loop, context):
            _LOGGER.error(f'Exception {context}')
            if self.inHandler:
                return
            self.inHandler = True
            report(DOMAIN, 'exception', str(context))
            if oldHandler:
                oldHandler(loop, context)
            self.inHandler = False
        loop.set_exception_handler(newHandler)
        self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.startShutdown)
        self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self.haStartedEv)
        
        # Maps event name to { dt: datetime when last sent notification, count: events since last notification }
        self.lastNotifyDict = {}
        #self.validator = vol.Schema(REPORT_SCHEMA)
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
        await self.processConfig()
        
    async def processConfig(self):
        # Validate the config in pieces. We want alert2 to successfully initialize no matter how messed up the config is.
        # And if the config has an error, to process the rest of itas much as it can.

        # We already tried processing the defaults section once. Report errors encountered.
        if self.defaultsError is not None:
            report(DOMAIN, 'config_error', f'error in defaults section of config: {self.defaultsError}')
            
        entities = []
        if 'tracked' in self._rawConfig and isinstance(self._rawConfig['tracked'], list):
            for obj in self._rawConfig['tracked']:
                try:
                    trackedCfg = SINGLE_TRACKED_SCHEMA(obj)
                    entities.append(self.declareEventInt(obj))
                except vol.Invalid as v:
                    report(DOMAIN, 'config_error', f'error in tracked section of config: {v}. Relevant section: {obj}')

        if 'alerts' in self._rawConfig and isinstance(self._rawConfig['alerts'], list):
            for obj in self._rawConfig['alerts']:
                try:
                    if 'trigger' in obj:
                        aCfg = SINGLE_ALERT_SCHEMA_EVENT(obj)
                        entities.append(self.declareEventInt(aCfg))
                    else:
                        aCfg = SINGLE_ALERT_SCHEMA_CONDITION(obj)
                        entities.append(self.declareCondition(aCfg, False))
                except vol.Invalid as v:
                    report(DOMAIN, 'config_error', f'error in alerts section of config: {v}. Relevant section: {obj}')
                    
        await self.component.async_add_entities(entities)

        # Now check the rest of the config
        # TODO - this is redoing a bunch of work parsing templates.
        try:
            dCfg = TOP_LEVEL_SCHEMA(self._rawConfig)
        except vol.Invalid as v:
            report(DOMAIN, 'config_error', f'error in top-level alert2 config: {v}')

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
        for adomain in self.tracked:
            for alName in self.tracked[adomain]:
                entity = self.tracked[adomain][alName]
                entity.shutdown()
        for atask in global_tasks:
            atask.cancel()
    async def slowStartup(self):
        uptimeSecs = (dt.now() - moduleLoadTime).total_seconds()
        graceRemainSecs = kNotifierInitGraceSecs - uptimeSecs
        if graceRemainSecs > 0:
            await asyncio.sleep(graceRemainSecs)
        for ann in self.notifiers:
            if not self._hass.services.has_service('notify', ann):
                report(DOMAIN, 'notify_failed', f'notifier notify.{ann} is not avaiable after startup grace period')
    
    def setSensorDict(self, adict):
        _LOGGER.debug(f'called setSensorDict')
        self.sensorDict = adict
    def setBinarySensorDict(self, adict):
        _LOGGER.debug(f'called setBinarySensorDict')
        self.binarySensorDict = adict
    # noteChange is really more just counting changes in state of any alert, so lovelace alert overview card can efficiently update.
    def noteChange(self):
        self.evCount += 1
        if self.sensorDict:
            self.sensorDict['evCount']._attr_native_value = self.evCount
            self.sensorDict['evCount'].async_write_ha_state()

    # Declare a single event alert
    def declareEvent(self, domain, name, notifier=None):
        tmp_config = { 'domain' : domain, 'name': name }
        if notifier is not None:
            tmp_config['notifier'] = notifier
        return self.declareEventInt(tmp_config)
    # Internal helper
    def declareEventInt(self, config):
        domain = config['domain']
        name = config['name']
        if not domain in self.tracked:
            self.tracked[domain] = {}
        if name in self.tracked[domain]:
            report(DOMAIN, 'assert', f'Duplicate declaration of event for domain={domain} name={name}')
            return
        entity = EventAlert(self._hass, self, config, self.defaults)
        self.tracked[domain][name] = entity
        self.notifiers.add(entity.notifier)
        return entity
    # declare single condition alert
    def declareCondition(self, config, isManual=False):
        domain = config['domain']
        name = config['name']
        if not domain in self.alerts:
            self.alerts[domain] = {}
        if name in self.alerts[domain]:
            report(DOMAIN, 'assert', f'Duplicate declaration of condition for domain={domain} name={name}')
            return
        if isManual:
            entity = ConditionAlertManual(self._hass, self, config, self.defaults)
        else:
            entity = ConditionAlert(self._hass, self, config, self.defaults)
        self.alerts[domain][name] = entity
        self.notifiers.add(entity.notifier)
        return entity
    # declare multiple event alerts, and also unhandled_exception
    async def declareEventMulti(self, arr):
        entities = []
        for x in arr:
            entities.append(self.declareEvent(x['domain'], x['name']))
            domain = x['domain']
            if domain not in self.tracked or 'unhandled_exception' not in self.tracked[domain]:
                entities.append(self.declareEvent(x['domain'], 'unhandled_exception'))
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
        self.noteChange()
        

    async def handle_service_report(self, call):
        return await self.handle_report_int(call.data, 'service-call')
    async def handle_event_report(self, ev: Event):
        return await self.handle_report_int(ev.data, 'hass-event')
    async def handle_report_int(self, data, tmsg):
        self._hass.verify_event_loop_thread(f'checking in handle_report_int for {tmsg}')

        # Grrr, have to manually validate data because voluptuous mutates a dict while validating and
        # the data passed with a service call is immutable.
        if not 'domain' in data or not isinstance(data['domain'], str):
            report(DOMAIN, 'malformed_call', f'{tmsg} missing/non-string "domain" {data}')
            return
        if not 'name' in data or not isinstance(data['name'], str):
            report(DOMAIN, 'malformed_call', f'{tmsg} missing/non-string "name" {data}')
            return
        domain = data['domain']
        name = data['name']
        if not domain in self.tracked or not name in self.tracked[domain]:
            errmsg = f'{tmsg} for {domain} and {name}'
            report(DOMAIN, 'undeclared_event', errmsg)
            alertObj = self.declareEvent(domain, name)
            await self.component.async_add_entities([entity])
        else:
            alertObj = self.tracked[domain][name]

        message = ''
        if 'message' in data:
            if not isinstance(data['message'], str):
                report(DOMAIN, 'malformed_call', f'{tmsg} non-string "message" {data}')
                return
            message = data['message']

        await alertObj.record_event(message)
        self.inHandler = False

