#
# Alert2 supports two types of alerts: condition alerts and event alerts.
# Condition alerts are considered 'firing' when the condition associated with them is true.
#    E.g., a temperature is too high
# Event alerts are considered firing for the single moment when the event occurs.
#    E.g., a certain MQTT message arrives
#
import asyncio
import datetime
from io import StringIO
import html
import json
import logging
import time
from typing import Any, final
import voluptuous as vol

from homeassistant.components.template.template_entity import TemplateEntity
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    EVENT_HOMEASSISTANT_STOP
)
from homeassistant.core import HomeAssistant, callback, Context, Event
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import template, discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.trigger import async_initialize_triggers
from homeassistant.helpers.typing import ConfigType
import homeassistant.util.dt as dt

_LOGGER = logging.getLogger(__name__)
DOMAIN = "alert2"
EVENT_TYPE = 'alert2_report'
NOTIFICATIONS_ENABLED  = 'enabled'
NOTIFICATIONS_DISABLED = 'disabled'
global_hass = None
global_tasks = set()

# report() - report that an event alert has fired
# 
def report(domain: str, name: str, message: str | None = None, isException: bool = False) -> None:
    data = { 'domain' : domain, 'name' : name }
    if message is not None:
        data['message'] = message
    #if global_hass:
    global_hass.bus.async_fire(EVENT_TYPE, data)
    #else:
    if isException:
        _LOGGER.exception(f'Err reported: {data}')
    else:
        _LOGGER.error(f'Err reported: {data}')

async def declareEventMulti(arr):
    await global_hass.data[DOMAIN].declareEventMulti(arr)
        
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

# create_task() - similar to hass.async_create_task() but it also report exceptions if they happen so the task doesn't die silently.
# Task will be cancelled when HA shutsdown
# returns a task object.
def create_task(hass, domain, afut):
    global global_tasks
    atask = hass.loop.create_task( afut )
    cb = lambda ttask: taskDone(domain, ttask)
    atask.add_done_callback(cb)
    _LOGGER.debug(f'create_task called for domain {domain}, {atask}')
    global_tasks.add(atask)
    return atask

# Cancel a task created with create_task().  atask is the task returned by create_task()
def cancel_task(domain, atask):
    global global_tasks
    _LOGGER.debug(f'Calling cancel_task for {domain} and {atask}')
    # I think cancelling a task means its done handler is called
    #if atask in global_tasks:
    #    global_tasks.remove(atask)
    #else:
    #    report(DOMAIN, 'assert', f'taskDone called2 for domain {domain},  {atask} but is not in global_tasks')
    atask.cancel()

def getField(fieldName, config, defaults):
    if fieldName in config:
        return config[fieldName]
    elif fieldName in defaults:
        return defaults[fieldName]
    else:
        raise vol.Invalid(f'Alert {config["domain"]},{config["name"]} config or defaults must specify {fieldName}')

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
        self._template = config['condition'] if 'condition' in config else None
        self._message_template = config['message'] if 'message' in config else None
        if self._message_template is not None:
            self._message_template.hass = hass
        self.notification_frequency_mins = getField('notification_frequency_mins', config, defaults)

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
            'fires_since_last_notify': self.fires_since_last_notify,
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
        self, enable: bool, snooze_until: datetime.datetime | None = None
    ) -> None:
        _LOGGER.info(f'{self.name} got async_notification_control with enable={enable} and snooze_until={snooze_until}')
        if enable:
            if snooze_until:
                assert snooze_until.tzinfo is not None and snooze_until.tzinfo.utcoffset(snooze_until) is not None, snooze_until
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
        if self.sub_ack_int():
            needWrite = True
        if needWrite:
            _LOGGER.info(f'{self.name} ack_int')
            self.last_ack_time = now
            self.async_write_ha_state()

    # idempotent, can call many times
    # Used to be check_notify
    def reminder_check(self, now = None):
        if not now:
            now = dt.now()
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None
        need_reminder = (self.fires_since_last_notify > 0) or self.sub_need_reminder()
        if need_reminder:
            remaining_secs = self.can_notify_now(now)
            if remaining_secs == False:
                return
            if remaining_secs == True:
                self.notify_timer_cb(now)
            else:
                assert (isinstance(remaining_secs, int) or isinstance(remaining_secs, float)) and remaining_secs > 0
                self.schedule_reminder(remaining_secs)
        
    # Return False if disabled
    #        True if can do immediately
    #        float seconds remaining till can notify otherwise
    # override_timing overrides time since last notify, but does not override
    #    snooze or disabled
    def can_notify_now(self, now, override_timing=False):
        if self.last_notified_time and self.notification_frequency_mins > 0:
            if self.last_ack_time and self.last_ack_time > self.last_notified_time:
                # If we've acked since last notification, it resets the last_notified_time effectively
                remaining_secs = 0
            else:
                secs_since_last = (now - self.last_notified_time).total_seconds()
                next_secs = self.notification_frequency_mins * 60.0
                remaining_secs = next_secs - secs_since_last
        else:
            remaining_secs = 0
        if self.notification_control == NOTIFICATIONS_DISABLED:
            return False
        if self.notification_control != NOTIFICATIONS_ENABLED:
            future_secs = (self.notification_control - now).total_seconds()
            if future_secs <= 0:
                self.notification_control = NOTIFICATIONS_ENABLED
                self.async_write_ha_state()
                self.alertData.noteChange()
            else:
                if future_secs > remaining_secs:
                    remaining_secs = future_secs
        if override_timing and self.notification_control == NOTIFICATIONS_ENABLED:
            return True
        if remaining_secs > 0:
            return remaining_secs
        return True
            
    def schedule_reminder(self, remaining_secs):
        async def foo():
            try:
                # + 1 so that the call to reminder_check is highly likely to see
                # can_notify_now is True
                await asyncio.sleep(remaining_secs + 1)
                assert asyncio.current_task() == self.future_notification_info['task']
                self.future_notification_info = None
                self.reminder_check()
            except asyncio.CancelledError:
                _LOGGER.debug(f'Skipping cancel exception for task {asyncio.current_task()}')
            except Exception as ex:
                msg = f'{self.name} In schedule_reminder/foo got exception: {ex.__class__}, {ex}'
                report(DOMAIN, 'exception', msg, isException=True)
        assert self.future_notification_info == None
        atask = create_task(self.hass, DOMAIN, foo())
        self.future_notification_info = { 'task': atask }
        
    # Assuming we want to notify
    # Does not write out state updates
    def _notify(self, now, is_fire, message, override_timing=False, skip_notify=False):
        if self.future_notification_info is not None:
            cancel_task(DOMAIN, self.future_notification_info['task'])
        self.future_notification_info = None  # TODO - could avoid recreates if we keep it around.

        remaining_secs = self.can_notify_now(now, override_timing)
        doNotify = remaining_secs == True
        if skip_notify:
            doNotify = False
        
        msg = f'{self.alDomain} {self.alName}'
        if doNotify and self.fires_since_last_notify > 0:
            secs_since_last = (now - self.last_fired_time).total_seconds()
            msg += f' +{self.fires_since_last_notify}x (most recently {agoStr(secs_since_last)} ago)'
            self.fires_since_last_notify = 0
        if len(message) > 0:
            msg += f': {message}'
        _LOGGER.warning(f'Alert2 {msg}')
            
        if doNotify:
            self.last_notified_time = now
            if not self.hass.services.has_service('notify', self.notifier):
                report(DOMAIN, 'notify_failed', f'no notifier {self.notifier}')
                return
            async def foo():
                tmsg = str(f'Alert2 {msg}')
                if len(tmsg) > 600:
                    tmsg = tmsg[:600] + '...'
                _LOGGER.warning(f'Notifying: {tmsg}')
                await self.hass.services.async_call(
                    'notify', self.notifier, # eg 'raw_jtelegram'
                    {'message': html.escape(tmsg),
                     'data': { 'parse_mode': 'html' },
                     })
            atask = create_task(self.hass, DOMAIN, foo())
        else:
            if is_fire:
                self.fires_since_last_notify += 1

            tillmsg = ''
            if remaining_secs != False:
                tillmsg = f', next notify is {remaining_secs} secs away'
            if remaining_secs == False:
                cause = 'disabled '
            elif self.notification_control not in [ NOTIFICATIONS_ENABLED, NOTIFICATIONS_DISABLED ]:
                cause = 'snoozed '
            else:
                cause = ''
            smsg = f'  Skipping notify for {cause}alert {self.alDomain}:{self.alName}{tillmsg}'
            _LOGGER.warning(smsg)
            if remaining_secs != False:
                self.schedule_reminder(remaining_secs)
                
        if is_fire:
            self.last_fired_message = message
            self.last_fired_time = now
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
        assert self._template
        try:
            rez = self._template.async_render(variables, parse_result=False)
        except TemplateError as err:
            report(DOMAIN, 'template_error', f'Condition template for {self.name}: {err}')
            return
        _LOGGER.debug(f'Got result: {rez}')
        brez = template.result_as_boolean(rez)
        _LOGGER.debug(f'  that became a bool: {brez}')

        if brez:
            _LOGGER.debug(f'  and event fired')
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
        didNotify = self._notify(now, True, message)
        self.async_write_ha_state()
        self.alertData.noteChange()
    
    def notify_timer_cb(self, now):
        assert self.fires_since_last_notify > 0
        msg = f'Last msg: {self.last_fired_message}'
        didNotify = self._notify(now, False, msg)
        assert didNotify
        self.async_write_ha_state()
        self.alertData.noteChange()
    def sub_ack_int(self):
        return self.last_fired_time and (not self.last_ack_time or self.last_ack_time <= self.last_fired_time)
    def sub_need_reminder(self):
        return False

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
        
        self.last_on_time = None
        self.last_off_time = None
        # Did we notify or reminder notify that the current alert is on.
        # used so we can then notify it turned off.
        self.notified_on = False
        self.added_to_hass_called = False
        
    @property
    def state(self) -> str:
        if self.last_on_time and ( (not self.last_off_time) or self.last_on_time > self.last_off_time):
            return "on"
        else:
            return "off"
    def more_state_attributes(self):
        return {
            'last_on_time': self.last_on_time,
            'last_off_time': self.last_off_time,
            'notified_on': self.notified_on,
        }
    async def async_added_to_hass(self) -> None:
        """Restore state and register callbacks."""
        await AlertBase.async_added_to_hass(self)

        last_state = await self.async_get_last_state()
        if last_state:
            # First part of 'if' is just for migration I think
            if ('last_on_time' in last_state.attributes) and last_state.attributes['last_on_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_on_time'])
                if self.last_on_time is None or tdate > self.last_on_time:
                    self.last_on_time = tdate
                    if 'notified_on' in last_state.attributes:
                        val = last_state.attributes['notified_on']
                        if not isinstance(val, bool):
                            low = val.lower()
                            if low not in ['true', 'false']:
                                _LOGGER.error(f'Got bad val for notified_on: {low} {type(low)}')
                            val = low == 'true'
                        self.notified_on = val
            if ('last_off_time' in last_state.attributes) and last_state.attributes['last_off_time']:
                tdate = dt.parse_datetime(last_state.attributes['last_off_time'])
                if self.last_off_time is None or tdate > self.last_off_time:
                    self.last_off_time = tdate

        self.reminder_check()
        self.added_to_hass_called = True

    def update_state_internal(self, state:bool):
        if (self.state == "on") == state:
            # no change
            # TODO - for keeping track of extremum of offending values, may want to run some update checking code.
            return

        now = dt.now()
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
                if self._message_template is not None:
                    try:
                        msg = self._message_template.async_render(parse_result=False)
                    except TemplateError as err:
                        report(DOMAIN, 'template_error', f'Condition template for {self.name}: {err}')
                        return
                self.notified_on = self._notify(now, True, msg)
                if self.notified_on:
                    self.reminder_check(now) # To schedule reminder
            else:
                is_acked = self.last_ack_time and self.last_on_time and self.last_ack_time > self.last_on_time
                secs_on = (self.last_off_time - self.last_on_time).total_seconds()
                didNotify = self._notify(now, False, f'turned off after {agoStr(secs_on)}.',
                                         override_timing=self.notified_on,
                                         skip_notify=is_acked) # presumably, this means alert ended shortly after we tried notifying, so schedule one more notify for last interval of alert
                if didNotify:
                    self.notified_on = False
        self.async_write_ha_state()
        self.alertData.noteChange()

        
    def notify_timer_cb(self, now):
        msg = ''
        is_on = self.state == 'on'
        if is_on:
            assert self.last_on_time
            secs_on = (now - self.last_on_time).total_seconds()
            msg += f' on for {agoStr(secs_on)}'
        else:
            secs_off = (now - self.last_off_time).total_seconds()
            secs_on = (self.last_off_time - self.last_on_time).total_seconds()
            msg += f' turned off {agoStr(secs_off)} ago after being on for {agoStr(secs_on)}'
        didNotify = self._notify(now, False, msg)
        assert didNotify
        if didNotify:
            if is_on:
                self.notified_on = True
            else:
                self.notified_on = False
        self.async_write_ha_state()
        self.alertData.noteChange()
        self.reminder_check(now)  # to set up next reminder (eg if alert is still on)
    
    def sub_ack_int(self):
        if self.notified_on:
            self.notified_on = False
            return True
        # So we update last_ack_time if state is on
        if self.state == 'on':
            return True
        return self.last_off_time and (not self.last_ack_time or self.last_ack_time <= self.last_off_time)
    
    def sub_need_reminder(self):
        #_LOGGER.warning(f'in sub_need_reminder. self.state={self.state} self.last_ack_time={self.last_ack_time}')
        if self.state == 'on':
            if not self.last_ack_time or self.last_ack_time < self.last_on_time:
                return True
            return False
        # Alert is off
        return self.notified_on

# From BinarySensorTemplate
class ConditionAlert(TemplateEntity, ConditionAlertBase):
    def __init__(
            self,
            hass: HomeAssistant,
            alertData,
            config: dict[str, Any],
            defaults
    ) -> None:
        TemplateEntity.__init__(self, hass)
        ConditionAlertBase.__init__(self, hass, alertData, config=config, defaults=defaults)
                
    async def async_added_to_hass(self) -> None:
        """Restore state and register callbacks."""
        await TemplateEntity.async_added_to_hass(self)
        await ConditionAlertBase.async_added_to_hass(self)

        # TODO - is there a better way to register a func to be called when a template changes?
        # Could just directly call helpers/event.py:async_track_template_result
        #
        # Note I think this calls the callback once initially, then for subsequent changes
        self.add_template_attribute("_bogusState", self._template, None, self._update_state)
        
    @callback
    def _update_state(self, result):
        # Picks templateentity since it's the only one that implement this.
        super()._update_state(result)

        if isinstance(result, TemplateError):
            # TODO - act like condition terminated
            state = False
        else:
            state = template.result_as_boolean(result)
        _LOGGER.debug(f'_update_state called for {self._attr_name}: {state}')

        self.update_state_internal(state)

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
        await ConditionAlertBase.async_added_to_hass(self)

    # Note that async_added_to_hass may be called after
    # the setup of any component, so it may overwrite state.
    def set_state(self, newState:bool):
        self.update_state_internal(newState)


        
NOTIFICATION_CONTROL_SCHEMA = {
    vol.Required("enable"): cv.boolean, #vol.Any(STATE_ON, STATE_OFF, NOTIFICATION_SNOOZE),
    vol.Optional("snooze_until"): cv.datetime,
}
ACK_SCHEMA = {
}
    
async def async_setup(hass, config: ConfigType):
    global global_hass
    global_hass = hass
    data = Alert2Data(hass, config)
    hass.data[DOMAIN] = data

    # TODO - vol validate.
    entities = []
    entities.append(data.declareEvent(DOMAIN, 'undeclared_event'))
    entities.append(data.declareEvent(DOMAIN, 'unhandled_exception'))
    entities.append(data.declareEvent(DOMAIN, 'notify_failed'))
    entities.append(data.declareEvent(DOMAIN, 'template_error'))
    entities.append(data.declareEvent(DOMAIN, 'malformed_call'))
    entities.append(data.declareEvent(DOMAIN, 'exception'))
    entities.append(data.declareEvent(DOMAIN, 'assert'))

    if 'tracked' in config[DOMAIN]:
        for obj in config[DOMAIN]['tracked']:
            entities.append(data.declareEventInt(obj))

    if 'alerts' in config[DOMAIN]:
        for obj in config[DOMAIN]['alerts']:
            if 'trigger' in obj:
                entities.append(data.declareEventInt(obj))
            else:
                entities.append(data.declareCondition(obj, False))

    await data.component.async_add_entities(entities)

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
    )
    return True

REPORT_SCHEMA = {
    vol.Required("domain"): cv.string,
    vol.Required("name"): cv.string,
    vol.Optional("message"): cv.string,
}

class Alert2Data:
    def __init__(self, hass, config):
        self._hass = hass
        self._config = config[DOMAIN]
        self.tracked = {}
        self.alerts = {}
        self.component = EntityComponent[EventAlert](_LOGGER, DOMAIN, hass)
        self.sensorDict = None
        self.evCount = 0
        
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
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.startShutdown)
        
        # Maps event name to { dt: datetime when last sent notification, count: events since last notification }
        self.lastNotifyDict = {}
        self.validator = vol.Schema(REPORT_SCHEMA)
        hass.bus.async_listen(EVENT_TYPE, self.handle_report)
        hass.services.async_register(DOMAIN, 'report', self.doreport)
        hass.services.async_register(DOMAIN, 'ack_all', self.ackAll)
        hass.services.async_register(DOMAIN, 'log', self.dolog)
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

    def startShutdown(self, event):
        self._hass.loop.call_soon_threadsafe(self.shutdown)
    def shutdown(self):
        for adomain in self.tracked:
            for alName in self.tracked[adomain]:
                entity = self.tracked[adomain][alName]
                entity.shutdown()
        for atask in global_tasks:
            atask.cancel()
        # I think we need to go back into event loop to process task cancellations and call the done callback. So too early to clear global_tasks
        #global_tasks.clear()
    def setSensorDict(self, adict):
        self.sensorDict = adict
    # noteChange is really more just counting changes in state of any alert, so lovelace alert overview card can efficiently update.
    def noteChange(self):
        self.evCount += 1
        if self.sensorDict:
            self.sensorDict['evCount'].set(self.evCount)
    # Declare a single event alert
    def declareEvent(self, domain, name):
        tmp_config = { 'domain' : domain, 'name': name }
        return self.declareEventInt(tmp_config)
    # Internal helper
    def declareEventInt(self, config):
        entity = EventAlert(self._hass, self, config, self._config['defaults'])
        if not entity.alDomain in self.tracked:
            self.tracked[entity.alDomain] = {}
        assert not entity.alName in self.tracked[entity.alDomain], f'domain={alDomain} name={alName}'
        self.tracked[entity.alDomain][entity.alName] = entity
        return entity
    # declare single condition alert
    def declareCondition(self, config, isManual=False):
        domain = config['domain']
        name = config['name']
        if isManual:
            entity = ConditionAlertManual(self._hass, self, config, self._config['defaults'])
        else:
            entity = ConditionAlert(self._hass, self, config, self._config['defaults'])
        if not domain in self.alerts:
            self.alerts[domain] = {}
        assert not name in self.alerts[domain], f'domain={domain} name={name}'
        self.alerts[domain][name] = entity
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
        
    async def dolog(self, call):
        logLevel = 'info'
        if 'level' in call.data and call.data['level'] in [ 'debug', 'info', 'warning', 'error', 'critical' ]:
            logLevel = call.data['level']
        txt = call.data['message'] if 'message' in call.data else None
        getattr(_LOGGER, logLevel)(f'Log: {txt}')
    async def doreport(self, call):
        txt = call.data['message'] if 'message' in call.data else None
        report(call.data['domain'], call.data['name'], txt)
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
        

    async def handle_report(self, ev: Event):
        data = ev.data
        try:
            self.validator(data)
        except vol.error.Error as ex:
            msg = f'Invalid event data: {str(ex)} data={data}'
            _LOGGER.warning(msg)
            report(DOMAIN, 'malformed_call', msg, isException=True)
        domain = data['domain']
        name = data['name']
        if domain not in self.tracked or name not in self.tracked[domain]:
            errmsg = f'event for {domain} and {name} not declared'
            _LOGGER.warning(errmsg)
            report(DOMAIN, 'undeclared_event', errmsg)
            entity = self.declareEvent(domain, name)
            await self.component.async_add_entities([entity])
        entity = self.tracked[domain][name]
        message = data['message'] if 'message' in data else ''
        await entity.record_event(message)

        self.inHandler = False
