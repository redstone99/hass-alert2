#!/usr/bin/python3
#
# run from repository root directory
import unittest
import re
from unittest.mock import AsyncMock, Mock
import sys
import asyncio
import datetime as dt
import voluptuous as vol
import logging
_LOGGER = logging.getLogger(None) # get root logger
_LOGGER.setLevel(logging.DEBUG)
from types import SimpleNamespace

class FakeConst:
    MAJOR_VERSION = 2024
    MINOR_VERSION = 9
    EVENT_HOMEASSISTANT_STOP = 3
    EVENT_HOMEASSISTANT_STARTED = 4
sys.modules['homeassistant.const'] = FakeConst
class FakeCore:
    class HomeAssistant:
        pass
    @staticmethod
    def callback(func):
        return func
    class Context:
        pass
    class Event[_T]:
        pass
    class EventStateChangedData:
        pass
sys.modules['homeassistant.core'] = FakeCore
class FakeExceptions:
    class TemplateError(Exception):
        pass
sys.modules['homeassistant.exceptions'] = FakeExceptions
class FakeHelpers:
    class template:
        @staticmethod
        def result_as_boolean(rez):
            return bool(rez)
        pass
    class discovery:
        pass
sys.modules['homeassistant.helpers'] = FakeHelpers
def fake_template(value):
    class FakeTemplate:
        def __init__(self, value):
            self.hass = None
            self.rawStr = value
        def async_render(self, vvars=None, parse_result=False):
            return self.rawStr
        def set_value(self, new):
            self.rawStr = new
    if value is None or isinstance(value, (list, dict, FakeTemplate)):
        raise vol.Invalid(f'{value} is not a string for template')
    return FakeTemplate(str(value))

# Copied from homeassistant/helpers/config_validation.py
def vboolean(value):
    """Validate and coerce a boolean value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.lower().strip()
        if value in ("1", "true", "yes", "on", "enable"):
            return True
        if value in ("0", "false", "no", "off", "disable"):
            return False
    elif isinstance(value, Number):
        # type ignore: https://github.com/python/mypy/issues/3186
        return value != 0  # type: ignore[comparison-overlap]
    raise vol.Invalid(f"invalid boolean value {value}")

class FakeHA:
    const = FakeConst
    class helpers:
        class config_validation:
            string = str
            boolean = vboolean
            ensure_list = lambda value: value if isinstance(value, list) else [value]
            make_entity_service_schema = lambda f: f
            template = fake_template
            TRIGGER_SCHEMA = str
            datetime = dt.datetime
            pass
        class entity_component:
            class EntityComponent[_T]:
                def __init__(self, logger, domain, hass):
                    pass
                async def async_add_entities(self, ents):
                    for ent in ents: # usualy done by Entity::_async_process_registry_update_or_remove
                        assert ent is not None
                        ent.entity_id = f'alert2.{ent.name}'
                        await ent.async_added_to_hass()
                    pass
                def async_register_entity_service(self, n1, ss, n2):
                    pass
        class event:
            @staticmethod
            def async_track_template_result(hass, trackers, cb):
                return SimpleNamespace(async_refresh = lambda: None)
            class TrackTemplate:
                def __init__(self, a, b):
                    pass
            class TrackTemplateResult:
                pass
        class restore_state:
            class RestoreEntity:
                def __init__(self):
                    self.async_write_ha_state = Mock(name='write_ha_state', spec_set=[])
                @property
                def name(self):
                    return self._attr_name
                #def async_write_ha_state(self):
                #    pass
                def async_set_context(self, ctx):
                    pass
                async def async_added_to_hass(self):
                    pass
                async def async_get_last_state(self):
                    return None
        class trigger:
            @staticmethod
            async def async_initialize_triggers(*args):
                return None
        class typing:
            class ConfigType:
                pass
    class util:
        class dt:
            @staticmethod
            def now():
                return dt.datetime.now() 
            pass
class FakeHass:
    def __init__(self):
        self.bus = SimpleNamespace(async_listen_once = lambda a,b: None,
                                   async_listen = lambda ev,fun: self.bus_async_listen(ev, fun),
                                   async_fire = lambda a, b: self.bus_async_fire(a, b)
                                   )
        self.services = SimpleNamespace(async_register = lambda a, meth, func: self.service_async_register(a, meth, func),
                                        has_service = lambda dom, nm: f'{dom}.{nm}' in self.servHandlers,
                                        async_call = lambda dom, nm, args: self.service_async_call(dom, nm, args)
                                        )
        self.evHandlers = {  }
        self.servHandlers = { 'notify.persistent_notification': AsyncMock(name='persist', spec_set=[]) }
        self.loop = asyncio.get_running_loop()
        self.states = {}
    def verify_event_loop_thread(self, msg):
        return True
    def service_async_register(self, dom, nm, fun):
        self.servHandlers[f'{dom}.{nm}'] = fun
    def bus_async_listen(self, ev, fun):
        self.evHandlers[ev] = fun
    def bus_async_fire(self, ev, data):
        obj = SimpleNamespace(data = data)
        asyncio.get_running_loop().create_task(self.evHandlers[ev](obj))
    async def service_async_call(self, dom, nm, args):
        call = SimpleNamespace(data = args)
        await self.servHandlers[f'{dom}.{nm}'](call)
    def async_create_task(self, afut, eager_start=False ):
        return asyncio.get_running_loop().create_task(afut)
    def async_create_background_task(self, afut, name, eager_start=False ):
        return asyncio.get_running_loop().create_task(afut)
        
sys.modules['homeassistant'] = FakeHA
sys.modules['homeassistant.helpers.config_validation'] = FakeHA.helpers.config_validation
sys.modules['homeassistant.helpers.entity_component'] = FakeHA.helpers.entity_component
sys.modules['homeassistant.helpers.event'] = FakeHA.helpers.event
sys.modules['homeassistant.helpers.restore_state'] = FakeHA.helpers.restore_state
sys.modules['homeassistant.helpers.trigger'] = FakeHA.helpers.trigger
sys.modules['homeassistant.helpers.typing'] = FakeHA.helpers.typing
sys.modules['homeassistant.util.dt'] = FakeHA.util.dt

import inspect
import os.path
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir) 
import custom_components.alert2 as alert2
alert2.kNotifierInitGraceSecs = 3
alert2.kStartupWaitPollSecs   = 1

def doConditionUpdate(aler, rez):
    #assert isinstance(rez, bool)
    aler._tracker_result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._condition_template, result=rez) ])
    setCondition(aler, rez)
def doValueUpdate(aler, rez):
    aler._tracker_result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._threshold_value_template, result=rez) ])
    setValue(aler, rez)
def doCondValueUpdate(aler, condRez, valRez):
    aler._tracker_result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._threshold_value_template, result=valRez),
                                 SimpleNamespace(template=aler._condition_template, result=condRez) ])
    setCondition(aler, condRez)
    setValue(aler, valRez)
    
def setValue(aler, rez):
    aler._threshold_value_template.set_value(rez)
def setCondition(aler, rez):
    aler._condition_template.set_value(rez)

class FooTest(unittest.IsolatedAsyncioTestCase):
    async def waitForAllBut(self, oldTasks):
        count = 0
        while True:
            newTasks = asyncio.all_tasks()
            sawOne = False
            for k in newTasks:
                if not k in oldTasks:
                    sawOne = True
                    count += 1
                    #print(f'about to wait_for {k}')
                    try:
                        await asyncio.wait_for(k, None)
                    except asyncio.CancelledError:
                        pass
            if not sawOne:
                break
        return count
    async def initCase(self, cfg):
        print('setting up')
        self.oldTasks = asyncio.all_tasks()
        self.hass = FakeHass()
        alert2.global_hass = self.hass
        self.gad = alert2.Alert2Data(self.hass, cfg)
        await self.gad.init2()
        for dom in self.gad.alerts:
            for name in self.gad.alerts[dom]:
                self.gad.alerts[dom][name].startWatchingEv(None) # normally called when EVENT_HOMEASSISTANT_STARTED happens
    #def setup(self):
    #    pass
    async def test_badarg1(self):
        cfg = { 'alert2' : {
            'defaults' : {
                'notifierz' : 'foobar'
            },
        } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        nn.assert_awaited_once()
        self.assertIsNotNone(re.search('defaults section.*extra keys', nn.await_args_list[0].args[0].data['message']))

        
    async def test_ack(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't1', 'condition': '{{ true }}' },
        ], } }
        await self.initCase(cfg)
        t1 = self.gad.alerts['test']['t1']
        nn = self.hass.servHandlers['notify.persistent_notification']

        self.assertEqual(t1.async_write_ha_state.call_count, 0)
        
        # First let's try condition on then off
        doConditionUpdate(t1, True)
        self.assertEqual(t1.state, 'on')
        self.assertEqual(t1.async_write_ha_state.call_count, 1)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t1.*turned on')
        # turning it on again should have no effect
        doConditionUpdate(t1, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertEqual(t1.async_write_ha_state.call_count, 1)
        # turn off
        doConditionUpdate(t1, False)
        self.assertEqual(t1.state, 'off')
        self.assertEqual(t1.async_write_ha_state.call_count, 2)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t1.*turned off')
        await asyncio.sleep(0.05)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)  # should be nothing left waiting
        # turn off again shouldn't change anything
        doConditionUpdate(t1, False)
        await asyncio.sleep(0.05)
        self.assertEqual(t1.async_write_ha_state.call_count, 2)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)  # should be nothing left waiting
        self.assertEqual(len(nn.await_args_list), 2)

        
        # Now let's try condition on, ack, off
        doConditionUpdate(t1, True)
        self.assertEqual(t1.async_write_ha_state.call_count, 3)
        await t1.async_ack()
        self.assertEqual(t1.async_write_ha_state.call_count, 4)
        doConditionUpdate(t1, False)
        self.assertEqual(t1.async_write_ha_state.call_count, 5)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t1.*turned on')

        # and let's try ack_all
        doConditionUpdate(t1, True)
        self.assertEqual(t1.async_write_ha_state.call_count, 6)
        await self.hass.services.async_call('alert2','ack_all', {})
        self.assertEqual(t1.async_write_ha_state.call_count, 7)
        doConditionUpdate(t1, False)
        self.assertEqual(t1.async_write_ha_state.call_count, 8)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t1.*turned on')
        

    async def test_reminder(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't2', 'condition': '{{ true }}', 'reminder_frequency_mins': [0.01, 0.05] },
            { 'domain': 'test', 'name': 't5', 'condition': '{{ true }}' },
        ], } }
        await self.initCase(cfg)

        # And how about a reminder, checking successive values. so should only see two reminders, not more
        t2 = self.gad.alerts['test']['t2']
        doConditionUpdate(t2, True)
        self.assertEqual(t2.async_write_ha_state.call_count, 1)
        await asyncio.sleep(6) # reminder interval is 1 + specified interval
        self.assertEqual(t2.async_write_ha_state.call_count, 3) # even though no notify, still record last fire time
        doConditionUpdate(t2, False)
        self.assertEqual(t2.async_write_ha_state.call_count, 4)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t2.*turned on')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t2.* on for ')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t2.* on for ')
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t2.*turned off')

        # And what about if ack'd before reminder time.  Should only see turn-on notification
        self.assertEqual(t2.async_write_ha_state.call_count, 4)
        doConditionUpdate(t2, True)
        self.assertEqual(t2.async_write_ha_state.call_count, 5)
        await t2.async_ack()
        self.assertEqual(t2.async_write_ha_state.call_count, 6)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        self.assertEqual(t2.async_write_ha_state.call_count, 6)
        doConditionUpdate(t2, False)
        self.assertEqual(t2.async_write_ha_state.call_count, 7)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(t2.async_write_ha_state.call_count, 7)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'test_t2.*turned on')

        # and default remimder time is long, so no reminders
        t2 = self.gad.alerts['test']['t5']
        doConditionUpdate(t2, True)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        doConditionUpdate(t2, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'test_t5.*turned on')
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'test_t5.*turned off')

        
    async def test_reminder2(self):
        # Check that default value of reminder is overridden and is used
        cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 10 },
                             'alerts' : [
            { 'domain': 'test', 'name': 't3', 'condition': '{{ true }}', 'reminder_frequency_mins': [0.01, 0.05] },
            { 'domain': 'test', 'name': 't4', 'condition': '{{ true }}' },
        ], } }
        await self.initCase(cfg)

        tal = self.gad.alerts['test']['t3']
        doConditionUpdate(tal, True)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t3.*turned on')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t3.* on for ')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t3.*turned off')

        tal = self.gad.alerts['test']['t4']
        doConditionUpdate(tal, True)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t4.*turned on')
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'test_t4.*turned off')

    async def test_reminder3(self):
        # Check that default value of reminder is used
        cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 },
                             'alerts' : [
            { 'domain': 'test', 'name': 't6', 'condition': '{{ true }}' },
        ], } }
        await self.initCase(cfg)
        tal = self.gad.alerts['test']['t6']

        doConditionUpdate(tal, True)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t6.*turned on')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t6.* on for ')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t6.*turned off')

    async def test_notifiers(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't7', 'condition': '{{ true }}', 'notifier': 'foo' },
        ], } }
        alert2.moduleLoadTime = dt.datetime.now()
        await self.initCase(cfg)
        tal = self.gad.alerts['test']['t7']
        
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)

        await asyncio.sleep(1)
        # We're in startup grace period, so notifications should have happened
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 0)
        self.assertTrue('notify.foo' not in self.hass.servHandlers)
        
        await asyncio.sleep(5)
        # We're out of grace period, so should see notification to default notifier
        self.assertTrue('notify.foo' not in self.hass.servHandlers)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t7.*Notifier notify.foo not available. Falling back to notify.persistent_notification')

        # There should be nothing more waiting around
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)

        # Now register foo, and notifications should work
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        nn2 = self.hass.servHandlers['notify.foo']
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1) # no new notifications
        self.assertEqual(len(nn2.await_args_list), 2) # start + stop
        self.assertRegex(nn2.await_args_list[0].args[0].data['message'], 'test_t7.*turned on')
        self.assertRegex(nn2.await_args_list[1].args[0].data['message'], 'test_t7.*turned off')
        
    async def test_notifiers2(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'defaults': { 'notifier': 'foo' }, 'alerts' : [
            { 'domain': 'test', 'name': 't8', 'condition': '{{ true }}' },
        ], } }
        await self.initCase(cfg)
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        tal = self.gad.alerts['test']['t8']
        
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 0)
        nn2 = self.hass.servHandlers['notify.foo']
        self.assertEqual(len(nn2.await_args_list), 2) # start + stop
        self.assertRegex(nn2.await_args_list[0].args[0].data['message'], 'test_t8.*turned on')
        self.assertRegex(nn2.await_args_list[1].args[0].data['message'], 'test_t8.*turned off')

    async def test_throttle(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
            { 'domain': 'test', 'name': 't9', 'condition': '{{ true }}', 'throttle_fires_per_mins': [2, 0.05], 'reminder_frequency_mins':0.01 },
        ], } }
        await self.initCase(cfg)
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        tal = self.gad.alerts['test']['t9']

        # 2 fires are fine
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t9.*turned on')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t9.*turned off')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t9.*turned on')
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t9.*turned off')

        # 3rd fire should have throttle sign and no turn off or reminders
        doConditionUpdate(tal, True)
        await asyncio.sleep(2)
        doConditionUpdate(tal, False)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'Throttling started.*test_t9.*turned on')
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        await asyncio.sleep(0.2)
        self.assertEqual(len(nn.await_args_list), 5)
        await asyncio.sleep(2)
        # throttle window done
        self.assertEqual(len(nn.await_args_list), 6)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'Throttling ending.*test_t9 fired 1x.*turned off.*after being on')
    async def test_annotate(self):
        cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 },  'alerts' : [
            { 'domain': 'test', 'name': 't10', 'condition': '{{ true }}' },
            { 'domain': 'test', 'name': 't11', 'condition': '{{ true }}', 'message': 'ick-t11' },
            { 'domain': 'test', 'name': 't12', 'condition': '{{ true }}', 'message': 'ick-t12', 'done_message': 'ick-t12 done' },
            { 'domain': 'test', 'name': 't13', 'condition': '{{ true }}', 'message': 'ick-t13', 'annotate_messages': False },
            { 'domain': 'test', 'name': 't14', 'condition': '{{ true }}', 'message': 'ick-t14', 'annotate_messages': False, 'done_message': 'ick-t14 done' },
            { 'domain': 'test', 'name': 't15', 'condition': '{{ true }}', 'friendly_name': 'friend_t15' },
            { 'domain': 'test', 'name': 't16', 'condition': '{{ true }}', 'message': 'ick-t16', 'annotate_messages': False, 'friendly_name': 'friend_t16' },
        ], 'tracked': [ { 'domain': 'test', 'name': 't16a' } ] } }
        await self.initCase(cfg)
        t10 = self.gad.alerts['test']['t10']
        t11 = self.gad.alerts['test']['t11']
        t12 = self.gad.alerts['test']['t12']
        t13 = self.gad.alerts['test']['t13']
        t14 = self.gad.alerts['test']['t14']
        t15 = self.gad.alerts['test']['t15']
        t16 = self.gad.alerts['test']['t16']
        t16a = self.gad.tracked['test']['t16a']
        allt = [ t10, t11, t12, t13, t14, t15, t16 ]
        alert2.haConst.MAJOR_VERSION = 2024
        alert2.haConst.MINOR_VERSION = 9
        for at in allt:
            doConditionUpdate(at, True)
            await asyncio.sleep(0.05) # so reminders are ordered
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertEqual(nn.await_args_list[0].args[0].data['message'], '{% raw %}Alert2 test_t10: turned on{% endraw %}')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Alert2 test_t11: ick-t11')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t12: ick-t12')
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'ick-t13')
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'ick-t14')
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'friend_t15: turned on')
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'ick-t16')

        # reminders
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), 14)
        self.assertRegex(nn.await_args_list[7].args[0].data['message'], 'Alert2 test_t10: on for')
        self.assertRegex(nn.await_args_list[8].args[0].data['message'], 'Alert2 test_t11: on for')
        self.assertRegex(nn.await_args_list[9].args[0].data['message'], 'Alert2 test_t12: on for')
        self.assertRegex(nn.await_args_list[10].args[0].data['message'], 'Alert2 test_t13: on for')
        self.assertRegex(nn.await_args_list[11].args[0].data['message'], 'Alert2 test_t14: on for')
        self.assertRegex(nn.await_args_list[12].args[0].data['message'], 'friend_t15: on for')
        self.assertRegex(nn.await_args_list[13].args[0].data['message'], 'friend_t16: on for')
        
        for at in allt:
            doConditionUpdate(at, False)
            await asyncio.sleep(0.05) # so offs are ordered
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 21)

        self.assertRegex(nn.await_args_list[14].args[0].data['message'], 'Alert2 test_t10: turned off after')
        self.assertRegex(nn.await_args_list[15].args[0].data['message'], 'Alert2 test_t11: turned off after')
        self.assertRegex(nn.await_args_list[16].args[0].data['message'], 'Alert2 test_t12: ick-t12 done{% endraw')
        self.assertRegex(nn.await_args_list[17].args[0].data['message'], 'turned off after')
        self.assertRegex(nn.await_args_list[18].args[0].data['message'], 'ick-t14 done')
        self.assertRegex(nn.await_args_list[19].args[0].data['message'], 'friend_t15: turned off after')
        self.assertRegex(nn.await_args_list[20].args[0].data['message'], 'turned off after')

        # As of 2024.10, HA no longer does template interpretation of message arg to notify
        alert2.haConst.MAJOR_VERSION = 2024
        alert2.haConst.MINOR_VERSION = 9
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm1'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 22)
        self.assertEqual(nn.await_args_list[21].args[0].data['message'], '{% raw %}Alert2 test_t16a: m1{% endraw %}')
        alert2.haConst.MAJOR_VERSION = 2023
        alert2.haConst.MINOR_VERSION = 11
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm2'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 23)
        self.assertEqual(nn.await_args_list[22].args[0].data['message'], '{% raw %}Alert2 test_t16a: m2{% endraw %}')
        alert2.haConst.MAJOR_VERSION = 2024
        alert2.haConst.MINOR_VERSION = 10
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm3'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 24)
        self.assertEqual(nn.await_args_list[23].args[0].data['message'], 'Alert2 test_t16a: m3')
        alert2.haConst.MAJOR_VERSION = 2025
        alert2.haConst.MINOR_VERSION = 5
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm4'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 25)
        self.assertEqual(nn.await_args_list[24].args[0].data['message'], 'Alert2 test_t16a: m4')

        
    async def test_delay_on(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't17', 'condition': '{{ true }}', 'delay_on_secs': 1, 'reminder_frequency_mins': 0.01 },
        ], } }
        await self.initCase(cfg)
        t17 = self.gad.alerts['test']['t17']
        nn = self.hass.servHandlers['notify.persistent_notification']
        
        doConditionUpdate(t17, True)
        await asyncio.sleep(0.1)
        # alert should not have fired
        self.assertEqual(len(nn.await_args_list), 0)
        self.assertEqual(t17.state, 'off')

        # it should fire after 0.9 secs more of sleeping + 1 sec bufer time
        await asyncio.sleep(2)
        self.assertEqual(t17.state, 'on')
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t17.*turned on')

        # reminder counts from when turned on, so should be 0.1s into reminder time of 0.6s
        # so sleeping a bit more shouldn't trigger reminder
        await asyncio.sleep(0.2)
        self.assertEqual(len(nn.await_args_list), 1)
        
        doConditionUpdate(t17, False)
        self.assertEqual(t17.state, 'off')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t17.*turned off')
        
    async def test_threshold(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't18', 'condition': '{{ xxx }}', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'minimum': 0 } },
            { 'domain': 'test', 'name': 't19', 'condition': '{{ xxx }}', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'maximum': 10 } },
            { 'domain': 'test', 'name': 't20', 'condition': '{{ xxx }}', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'minimum': 0, 'maximum': 10 } },
        ], } }
        await self.initCase(cfg)
        t18 = self.gad.alerts['test']['t18']
        t19 = self.gad.alerts['test']['t19']
        t20 = self.gad.alerts['test']['t20']
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(t18.state, 'off')
        self.assertEqual(t19.state, 'off')
        self.assertEqual(t20.state, 'off')

        doConditionUpdate(t18, True)  # cond updating causes value to be evaluated, which returns zzz:
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'Threshold.*zzz.*rather than a float')
        self.assertEqual(t18.state, 'off')

        doConditionUpdate(t18, True)  # cond updating causes value to be evaluated, which returns zzz:
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Threshold.*zzz.*rather than a float')
        self.assertEqual(t18.state, 'off')

        # condition updates can never fail - i.e., helpers.result_as_boolean never fails
        setValue(t18, '3')
        doConditionUpdate(t18, True)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertEqual(t18.state, 'off')

        # Now try value update with false condition
        setCondition(t18, False)
        doValueUpdate(t18, 'zz2')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Threshold.*zz2.*rather than a float')
        self.assertEqual(t18.state, 'off')
        
        # Now try false, false in various combinations
        #
        setCondition(t18, False)
        doValueUpdate(t18, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '3')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, False, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')

        # Now try cond true, val false
        #
        setCondition(t18, True)
        doValueUpdate(t18, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '3')
        doConditionUpdate(t18, True)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, True, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')

        # Now try false, True in various combinations
        #
        setCondition(t18, False)
        doValueUpdate(t18, '-1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '-1')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, False, '-1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(t18.state, 'off')

        # Now try with both true
        setCondition(t18, True)
        doValueUpdate(t18, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '-1')
        doConditionUpdate(t18, True)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 6)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, True, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 8)
        self.assertRegex(nn.await_args_list[7].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 9)
        self.assertRegex(nn.await_args_list[8].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        
        # Now check hysteresis
        doCondValueUpdate(t18, True, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 10)
        self.assertRegex(nn.await_args_list[9].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        # going positive but still less than 3
        doValueUpdate(t18, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 10)
        self.assertEqual(t18.state, 'on')
        # 3 counts from 0, not -1
        doValueUpdate(t18, '2.5')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 10)
        self.assertEqual(t18.state, 'on')
        # now turns off
        doValueUpdate(t18, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 11)
        self.assertRegex(nn.await_args_list[10].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')

        # Check turning off due to condition going false
        setValue(t18, '-2')
        doCondValueUpdate(t18, True, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 12)
        self.assertRegex(nn.await_args_list[11].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 13)
        self.assertRegex(nn.await_args_list[12].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        
        # Check max hysteresis
        doCondValueUpdate(t19, True, '9')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 13)
        self.assertEqual(t19.state, 'off')
        doCondValueUpdate(t19, True, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 13)
        self.assertEqual(t19.state, 'off')
        # turn on
        doCondValueUpdate(t19, True, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 14)
        self.assertRegex(nn.await_args_list[13].args[0].data['message'], 'test_t19: turned on')
        self.assertEqual(t19.state, 'on')
        doValueUpdate(t19, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 14)
        self.assertEqual(t19.state, 'on')
        doValueUpdate(t19, '8')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 14)
        self.assertEqual(t19.state, 'on')
        doValueUpdate(t19, '7')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 15)
        self.assertRegex(nn.await_args_list[14].args[0].data['message'], 'test_t19: turned off')
        self.assertEqual(t19.state, 'off')
        
        # Check min,max hysteresis
        doCondValueUpdate(t20, True, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 15)
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 16)
        self.assertRegex(nn.await_args_list[15].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '8')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 16)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '7')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 17)
        self.assertRegex(nn.await_args_list[16].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '0')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 17)
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 18)
        self.assertRegex(nn.await_args_list[17].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '2')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 18)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 19)
        self.assertRegex(nn.await_args_list[18].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        # Check if turn off by going into hysteresis region of opposite side
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 20)
        self.assertRegex(nn.await_args_list[19].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '9')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 21)
        self.assertRegex(nn.await_args_list[20].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')
        # and in other direction
        doValueUpdate(t20, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 22)
        self.assertRegex(nn.await_args_list[21].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 23)
        self.assertRegex(nn.await_args_list[22].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        # And test if jump from pole to pole
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 24)
        self.assertRegex(nn.await_args_list[23].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 24)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '9')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 24)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 24)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '5')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 25)
        self.assertRegex(nn.await_args_list[24].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        # check threshold tracking even when condition is false
        setCondition(t20, False)
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 25)
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 25)
        self.assertEqual(t20.state, 'off')

        doConditionUpdate(t20, True)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 26)
        self.assertRegex(nn.await_args_list[25].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')

        doCondValueUpdate(t20, False, '11')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 27)
        self.assertRegex(nn.await_args_list[26].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        doCondValueUpdate(t20, False, '9')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 27)
        self.assertEqual(t20.state, 'off')

        doConditionUpdate(t20, True)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 28)
        self.assertRegex(nn.await_args_list[27].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')

        # Lastly a temlate error
        doConditionUpdate(t20, FakeExceptions.TemplateError('foobar error'))
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 29)
        self.assertRegex(nn.await_args_list[28].args[0].data['message'], 'err')
        self.assertEqual(t20.state, 'on')

        doConditionUpdate(t20, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 30)
        self.assertRegex(nn.await_args_list[29].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')
        
    async def test_threshold2(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't21', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'minimum': 0 } },
        ], } }
        await self.initCase(cfg)
        t21 = self.gad.alerts['test']['t21']
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(t21.state, 'off')

        # Test hysteresis without a condition
        doValueUpdate(t21, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 0)
        self.assertEqual(t21.state, 'off')

        doValueUpdate(t21, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t21: turned on')
        self.assertEqual(t21.state, 'on')

        doValueUpdate(t21, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertEqual(t21.state, 'on')

        doValueUpdate(t21, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t21: turned off')
        self.assertEqual(t21.state, 'off')

    async def test_event(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'tracked' : [
            { 'domain': 'test', 'name': 't22' },
            { 'domain': 'test', 'name': 't23', 'friendly_name': 'friendlyt23' },
            { 'domain': 'test', 'name': 't24', 'title': 'title24' },
            { 'domain': 'test', 'name': 't25', 'target': 'targett25' },
            { 'domain': 'test', 'name': 't26', 'data': { 'd1': 'data-d1' } },
        ], } }
        await self.initCase(cfg)
        t22 = self.gad.tracked['test']['t22']
        t23 = self.gad.tracked['test']['t23']
        t24 = self.gad.tracked['test']['t24']
        t25 = self.gad.tracked['test']['t25']
        t26 = self.gad.tracked['test']['t26']
        nn = self.hass.servHandlers['notify.persistent_notification']

        await self.hass.services.async_call('alert2','report', {})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'alert2_error.*malformed')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t22'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Alert2 test_t22')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t22', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t22: foo')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t23', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'friendlyt23: foo')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t24', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'test_t24.*foo')
        self.assertRegex(nn.await_args_list[4].args[0].data['title'],   'title24')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t25', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 6)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'test_t25.*foo')
        self.assertRegex(nn.await_args_list[5].args[0].data['target'],   'targett25')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t26', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'test_t26.*foo')
        self.assertDictEqual(nn.await_args_list[6].args[0].data['data'], { 'd1': 'data-d1' })

    async def test_event2(self):
        # Check throttling
        cfg = { 'alert2' : { 'tracked' : [
            { 'domain': 'test', 'name': 't27', 'throttle_fires_per_mins': [2, 0.01] },
        ], } }
        await self.initCase(cfg)
        t27 = self.gad.tracked['test']['t27']
        nn = self.hass.servHandlers['notify.persistent_notification']

        # First two should notify fine
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t27'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'Alert2 test_t27')
        #
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t27'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Alert2 test_t27')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t27'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Throttling started.*test_t27')

        # Two more fires shouldn't notify
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t27'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 3)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t27'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), 3)

        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'Throttling ending.*test_t27 fired 2x')
        
    async def test_event3(self):
        # Check throttling
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't28',  'trigger': 'foo', 'condition': '{{ zzz }}' },
            { 'domain': 'test', 'name': 't29',  'trigger': 'foo', 'condition': '{{ zzz }}', 'friendly_name': 'friendly-t29'  },
        ], } }
        await self.initCase(cfg)
        t28 = self.gad.tracked['test']['t28']
        t29 = self.gad.tracked['test']['t29']
        nn = self.hass.servHandlers['notify.persistent_notification']

        # condition is false, so no alert
        setCondition(t28, False)
        await t28.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 0)

        # condition is now true
        setCondition(t28, True)
        await t28.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'Alert2 test_t28')

        setCondition(t29, True)
        await t29.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'friendly-t29')

        # and let's try reporting.  Reporting bypasses any conditions
        setCondition(t28, False)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t28'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t28')

        # and report a non-existent alert
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t28-no'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'Alert2 test_t28-no')
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'Alert2 alert2_error: undeclared event')
        

    async def test_condition(self):
        # test pssing entity name instead of template for condition or threshold value
        cfg = { 'alert2' : { 'tracked': [
            { 'domain': 'test', 'name': 't30', 'friendly_name': 'happyt30' },
            { 'domain': 'test', 'name': 't30' }, # duplicate
        ], 'alerts' : [
            { 'domain': 'test', 'name': 't31', 'condition': 3 },
            { 'domain': 'test', 'name': 't31', 'condition': 3.1 }, # duplicate declaration
            { 'domain': 'test', 'name': 't32', 'condition': 3.2, 'trigger': 'fff' }, 
            { 'domain': 'test', 'name': 't32', 'condition': 3.3, 'trigger': 'fff2' },  # duplicate
            { 'domain': 'test', 'name': 't33', 'condition': 'foo.bar' },
            { 'domain': 'test', 'name': 't34', 'condition': '{{ ick }}' },
            { 'domain': 'test', 'name': 't35', 'threshold': 4 },
            { 'domain': 'test', 'name': 't36', 'threshold': { 'value': 5, 'hysteresis': 6, 'minimum':7 } },
            { 'domain': 'test', 'name': 't37', 'threshold': { 'value': 'foo.bar2', 'hysteresis': 8, 'minimum':9 } },
            { 'domain': 'test', 'name': 't38', 'threshold': { 'value': '{{ ick2 }}', 'hysteresis': 10, 'minimum':11 } },
        ], } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'Duplicate.*t30')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Duplicate.*t31')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Duplicate.*t32')
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'expected dictionary.*t35')

        self.assertEqual(self.gad.tracked['test']['t30']._friendly_name, 'happyt30')
        self.assertEqual(self.gad.alerts['test']['t31']._condition_template.rawStr, '3')
        self.assertEqual(self.gad.tracked['test']['t32']._condition_template.rawStr, '3.2')
        self.assertEqual(self.gad.alerts['test']['t33']._condition_template.rawStr, '{{ states("foo.bar") }}')
        self.assertEqual(self.gad.alerts['test']['t34']._condition_template.rawStr, '{{ ick }}')
        self.assertNotIn('35', self.gad.alerts['test'])
        self.assertEqual(self.gad.alerts['test']['t36']._threshold_value_template.rawStr, '5')
        self.assertEqual(self.gad.alerts['test']['t37']._threshold_value_template.rawStr, '{{ states("foo.bar2") }}')
        self.assertEqual(self.gad.alerts['test']['t38']._threshold_value_template.rawStr, '{{ ick2 }}')
        
if __name__ == '__main__':
    unittest.main()
