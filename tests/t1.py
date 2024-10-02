#!/usr/bin/python3
import unittest
import re
from unittest.mock import AsyncMock, Mock
import sys
import asyncio
import datetime as dt
import logging
_LOGGER = logging.getLogger(None) # get root logger
_LOGGER.setLevel(logging.DEBUG)
from types import SimpleNamespace
sys.path.append('/home/redstone/home-monitoring/homeassistant')
class FakeConst:
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
        def async_render(self, parse_result=False):
            return self.rawStr
        def set_value(self, new):
            self.rawStr = new
    if not isinstance(value, str):
        raise vol.Invalid(f'{value} is not a string for template')
    return FakeTemplate(value)
    
class FakeHA:
    class helpers:
        class config_validation:
            string = str
            boolean = bool
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
            def async_initialize_triggers():
                pass
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
sys.modules['homeassistant'] = FakeHA
sys.modules['homeassistant.helpers.config_validation'] = FakeHA.helpers.config_validation
sys.modules['homeassistant.helpers.entity_component'] = FakeHA.helpers.entity_component
sys.modules['homeassistant.helpers.event'] = FakeHA.helpers.event
sys.modules['homeassistant.helpers.restore_state'] = FakeHA.helpers.restore_state
sys.modules['homeassistant.helpers.trigger'] = FakeHA.helpers.trigger
sys.modules['homeassistant.helpers.typing'] = FakeHA.helpers.typing
sys.modules['homeassistant.util.dt'] = FakeHA.util.dt
import custom_components.alert2 as alert2
alert2.kNotifierInitGraceSecs = 3
alert2.kStartupWaitPollSecs   = 1

def doConditionUpdate(aler, rez):
    assert isinstance(rez, bool)
    aler._tracker_result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._condition_template, result=rez) ])
def doValueUpdate(aler, rez):
    assert float(rez) == rez
    aler._tracker_result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._threshold_value_template, result=rez) ])
def setValue(aler, rez):
    aler._threshold_value_template.set_value(rez)

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
        ], } }
        await self.initCase(cfg)
        t10 = self.gad.alerts['test']['t10']
        t11 = self.gad.alerts['test']['t11']
        t12 = self.gad.alerts['test']['t12']
        t13 = self.gad.alerts['test']['t13']
        t14 = self.gad.alerts['test']['t14']
        t15 = self.gad.alerts['test']['t15']
        t16 = self.gad.alerts['test']['t16']
        allt = [ t10, t11, t12, t13, t14, t15, t16 ]
        for at in allt:
            doConditionUpdate(at, True)
            await asyncio.sleep(0.05) # so reminders are ordered
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], '^{% raw %}Alert2 test_t10: turned on{% endraw %}$')
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
        ], } }
        await self.initCase(cfg)
        t18 = self.gad.alerts['test']['t18']
        nn = self.hass.servHandlers['notify.persistent_notification']

        hrm, what is value during startup?
        self.assertEqual(t18.state, 'off')
        doConditionUpdate(t18, True)  # condition true by itself not enough
        self.assertEqual(t18.state, 'off')

        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 0)

        setValue(t18, '3')
        
        
if __name__ == '__main__':
    unittest.main()
