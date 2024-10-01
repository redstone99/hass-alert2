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

def doConditionUpdate(aler, rez):
    assert isinstance(rez, bool)
    aler._tracker_result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._condition_template, result=rez) ])
    

class FooTest(unittest.IsolatedAsyncioTestCase):
    def setup(self):
        pass
    async def waitForAllBut(self, oldTasks):
        while True:
            newTasks = asyncio.all_tasks()
            sawOne = False
            for k in newTasks:
                if not k in oldTasks:
                    sawOne = True
                    print(f'about to wait_for {k}')
                    await asyncio.wait_for(k, None)
            if not sawOne:
                break
    async def test_first(self):
        oldTasks = asyncio.all_tasks()
        cfg = { 'alert2' : {
            'defaults' : {
                'notifierz' : 'foobar'
            },
        } }
        hass = FakeHass()
        alert2.global_hass = hass
        gad = alert2.Alert2Data(hass, cfg)
        await gad.init2()
        await self.waitForAllBut(oldTasks)
        nn = hass.servHandlers['notify.persistent_notification']
        nn.assert_awaited_once()
        self.assertIsNotNone(re.search('defaults section.*extra keys', nn.await_args_list[0].args[0].data['message']))

    async def test_ack(self):
        oldTasks = asyncio.all_tasks()
        cfg = { 'alert2' : {
            'alerts' : [
                {
                    'domain': 'test',
                    'name': 't1',
                    'condition': '{{ true }}',
                }
            ],
        } }
        hass = FakeHass()
        alert2.global_hass = hass
        gad = alert2.Alert2Data(hass, cfg)
        await gad.init2()
        tal = gad.alerts['test']['t1']
        tal.startWatchingEv(None) # normally called when EVENT_HOMEASSISTANT_STARTED happens
        doConditionUpdate(tal, True)

        
        await self.waitForAllBut(oldTasks)
        nn = hass.servHandlers['notify.persistent_notification']
        print(nn.await_args_list)
        nn.assert_awaited_once()
        self.assertIsNotNone(re.search('defaults section.*extra keys', nn.await_args_list[0].args[0].data['message']))

        
if __name__ == '__main__':
    unittest.main()
