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
class FakeHA:
    class helpers:
        class config_validation:
            string = str
            boolean = bool
            ensure_list = lambda value: value if isinstance(value, list) else [value]
            make_entity_service_schema = lambda f: f
            template = str
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
                @property
                def name(self):
                    return self._attr_name
                def async_write_ha_state(self):
                    pass
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
        tal = self.gad.alerts['test']['t1']
        
        # First let's try condition on then off
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t1.*turned on')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t1.*turned off')

        # Now let's try condition on, ack, off
        doConditionUpdate(tal, True)
        await tal.async_ack()
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t1.*turned on')

        # and let's try ack_all
        doConditionUpdate(tal, True)
        await self.hass.services.async_call('alert2','ack_all', {})
        doConditionUpdate(tal, False)
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
        tal = self.gad.alerts['test']['t2']
        doConditionUpdate(tal, True)
        await asyncio.sleep(6) # reminder interval is 1 + specified interval
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t2.*turned on')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t2.* on for ')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t2.* on for ')
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t2.*turned off')

        # And what about if ack'd before reminder time.  Should only see turn-on notification
        doConditionUpdate(tal, True)
        await tal.async_ack()
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'test_t2.*turned on')

        # and default remimder time is long, so no reminders
        tal = self.gad.alerts['test']['t5']
        doConditionUpdate(tal, True)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        doConditionUpdate(tal, False)
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
        
if __name__ == '__main__':
    unittest.main()
