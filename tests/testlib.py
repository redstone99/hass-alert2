import logging
logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(None) # get root logger
_LOGGER.setLevel(logging.INFO)
#_LOGGER.setLevel(logging.DEBUG)
_LOGGER.handlers[0].setFormatter(logging.Formatter("%(message)s"))

import sys
import os
import unittest
import re
from unittest.mock import AsyncMock, Mock
from numbers import Number
import asyncio
import datetime as rawdt
import voluptuous as vol
import jinja2
from types import SimpleNamespace

sys.path.append('/home/redstone/tmp/home-assistant-core')
import homeassistant
from homeassistant.components.http import HomeAssistantView
#from jinja2.sandbox import ImmutableSandboxedEnvironment


gHass = None
def setGhass(ahass):
    global gHass
    gHass = ahass
class FakeConst:
    MAJOR_VERSION = 2024
    MINOR_VERSION = 10
    EVENT_HOMEASSISTANT_STOP = 3
    EVENT_HOMEASSISTANT_STARTED = 4
    SERVICE_RELOAD = 5
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
    class ServiceNotFound(Exception):
        pass
    class HomeAssistantError(Exception):
        pass
sys.modules['homeassistant.exceptions'] = FakeExceptions
class FakeConfigEntries:
    class ConfigEntry:
        pass
sys.modules['homeassistant.config_entries'] = FakeConfigEntries

class FakeBinarySensor:
    class BinarySensorDeviceClass:
        PROBLEM = 'problem'
sys.modules['homeassistant.components.binary_sensor'] = FakeBinarySensor

#class FakeHttp:
#    class HomeAssistantView:
#        pass
#sys.modules['homeassistant.components.http'] = FakeHttp

class FakeTemplate:
    def __init__(self, value, hass=None):
        self.hass = hass or gHass
        self.template = value
        #self.env = jinja2.Environment
    @property
    def _env(self):
        e = jinja2.Environment()
        e.globals['states'] = self.hass.states
        return e
    def async_render(self, variables=None, parse_result=False):
        rez = None
        #variables = {"states": lambda x: x, **(variables or {})}
        variables = { **(variables or {}) }
        try:
            #rez = jinja2.Template(self.template).render(variables)
            rez = self._env.from_string(self.template).render(variables)
            #if variables is None:
            #    rez = jinja2.Template(self.template).render()
            #else:
            #    rez = jinja2.Template(self.template).render(variables)
        except Exception as err:
            raise FakeExceptions.TemplateError(err) from err
        return rez
        #return self.template
    def set_value(self, new):
        self.template = new
    def ensure_valid(self):
        try:
            self._env.from_string(self.template) # try compiling
            #jinja2.Template(self.template) # try compiling
        except Exception as err:
            raise FakeExceptions.TemplateError(err) from err
    def __repr__(self) -> str:
        """Representation of Template."""
        return f"FakeTemplate<template=({self.template})>"
class FakeHelpers:
    class template:
        @staticmethod
        def result_as_boolean(value):  # copied from helpers/config_validation.py:boolean()
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
            return False
            #raise vol.Invalid(f"invalid boolean value {value}")
        Template = FakeTemplate
        @staticmethod
        def is_template_string(astr):
            return "{%" in astr or "{{" in astr or "{#" in astr
    class discovery:
        @staticmethod
        def async_load_platform(*args):
            async def foo():
                pass
            return foo()
    class trigger:
        @staticmethod
        def async_validate_trigger_config(hass, acfg):
            return acfg
def fake_template(value):
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
            datetime = rawdt.datetime
            _async_get_hass_or_none = lambda : gHass
            pass
        class entity_component:
            class EntityComponent[_T]:
                def __init__(self, logger, domain, hass):
                    self.domain = domain
                    self.hass = hass
                    self.newCfg = None
                    pass
                async def async_add_entities(self, ents):
                    for ent in ents: # usualy done by Entity::_async_process_registry_update_or_remove
                        assert ent is not None
                        ent.entity_id = f'{self.domain}.{ent.name}'
                        self.hass.states.set(ent.entity_id, ent)
                        await ent.async_added_to_hass()
                    pass
                async def async_remove_entity(self, entid):
                    ent = self.hass.states.get(entid)
                    #_LOGGER.warning(f'async_remove_entity: {entid} -> {ent}')
                    assert ent, entid
                    if hasattr(ent, 'async_will_remove_from_hass'):
                        await ent.async_will_remove_from_hass()
                    self.hass.states.erase(entid)
                def async_register_entity_service(self, n1, ss, n2):
                    pass
                async def async_prepare_reload(self, skip_reset=True):
                    return self.newCfg
        class event:
            @staticmethod
            def async_track_template_result(hass, trackers, action):
                # fire initial result of templates
                event = None
                updates = []
                #updates = [ SimpleNamespace(template=x.template, result=x.template.async_render(variables=x.variables)) for x in trackers ]
                for x in trackers:
                    try:
                        rez = SimpleNamespace(template=x.template, result=x.template.async_render(variables=x.variables))
                    except FakeExceptions.TemplateError as err:
                        rez = SimpleNamespace(template=x.template, result=err)
                    updates.append(rez)
                action(event, updates)
                #asyncio.get_running_loop().create_task(action(event, updates))
                return SimpleNamespace(async_refresh = lambda: None, async_remove = lambda: None)
            class TrackTemplate:
                def __init__(self, template, variables, rate_limit=None):
                    self.template = template
                    self.variables = variables
            class TrackTemplateResult:
                pass
        class entity:
            class Entity:
                def __init__(self):
                    self.async_write_ha_state = Mock(name='write_ha_state', spec_set=[])
                @property
                def name(self):
                    return self._attr_name
                entity_id = 'some id'
                def async_set_context(self, context):
                    pass
                async def async_remove(self, *, force_remove = False):
                    pass
                async def async_added_to_hass(self):
                    pass
                async def async_will_remove_from_hass(self):
                    pass
                def as_dict(self):
                    # Hack - this is needed only because we don't model States accurately,
                    # storing the ent in it rather than a real State object.
                    return { 'entity_id': self.entity_id, 'state': self.state }
        class restore_state:
            pass
        class trigger:
            @staticmethod
            async def async_initialize_triggers(*args):
                return None
        class typing:
            class ConfigType:
                pass
        class storage:
            class Store:
                pass
        class service:
            @staticmethod
            def async_register_admin_service(hass, domain, meth, func):
                pass
    class util:
        class dt:
            @staticmethod
            def now():
                return rawdt.datetime.now(rawdt.UTC)
            @staticmethod
            def as_local(atime):
                return atime
        class yaml:
            def parse_yaml(atxt):
                return None
class FakeSensor:
    class SensorDeviceClass:
        DATA_SIZE = 'data_size'
    class SensorEntity(FakeHA.helpers.entity.Entity):
        def __init__(self):
            super().__init__()
sys.modules['homeassistant.components.sensor'] = FakeSensor
            
class RestoreEntity(FakeHA.helpers.entity.Entity):
    def __init__(self):
        super().__init__()
    async def async_added_to_hass(self):
        pass
    async def async_get_last_state(self):
        return None
FakeHA.helpers.restore_state.RestoreEntity = RestoreEntity
            
class States:
    def __init__(self):
        self.data = {}
    def erase(self, n):
        del self.data[n]
    def set(self, n, v):
        self.data[n] = v
    def get(self, n):
        return self.data[n] if n in self.data else None
    def __iter__(self):
        for x in self.data:
            #yield SimpleNamespace(entity_id=x)
            yield self.data[x]
    def __call__(self, entity_id):
        # Hack, this is not how it actually works in HA. In HA uses AllStates with tolerates
        # a missing entity
        ent = self.get(entity_id)
        if ent:
            return ent.state
        else:
            return ''
        
class FakeHass:
    def __init__(self):
        self.bus = SimpleNamespace(async_listen_once = lambda ev,fun: self.bus_async_listen_once(ev, fun),
                                   async_listen = lambda ev,fun: self.bus_async_listen(ev, fun),
                                   async_fire = lambda a, b: self.bus_async_fire(a, b)
                                   )
        self.services = SimpleNamespace(async_register = lambda a, meth, func: self.service_async_register(a, meth, func),
                                        has_service = lambda dom, nm: f'{dom}.{nm}' in self.servHandlers,
                                        async_call = lambda dom, nm, args: self.service_async_call(dom, nm, args)
                                        )
        self.evHandlers = {  }
        self.evOnceHandlers = {  }
        self.servHandlers = { 'notify.persistent_notification': AsyncMock(name='persist', spec_set=[]) }
        self.loop = asyncio.get_running_loop()
        self.states = States()
        self.data = {}
    def verify_event_loop_thread(self, msg):
        return True
    def service_async_register(self, dom, nm, fun):
        self.servHandlers[f'{dom}.{nm}'] = fun
    def bus_async_listen(self, ev, fun):
        _LOGGER.debug(f'bus_async_listen for {ev}')
        if not ev in self.evHandlers:
            self.evHandlers[ev] = []
        self.evHandlers[ev].append(fun)
    def bus_async_listen_once(self, ev, fun):
        _LOGGER.debug(f'bus_async_listen once for {ev}')
        if not ev in self.evOnceHandlers:
            self.evOnceHandlers[ev] = []
        self.evOnceHandlers[ev].append(fun)
    def bus_async_fire(self, ev, data):
        obj = SimpleNamespace(data = data)
        _LOGGER.debug(f'bus_async_fire for {ev}')
        if ev in self.evHandlers:
            for aco in self.evHandlers[ev]:
                asyncio.get_running_loop().create_task(aco(obj))
        if ev in self.evOnceHandlers:
            for afun in self.evOnceHandlers[ev]:
                afun(obj)
                #asyncio.get_running_loop().call_soon_threadsafe(lambda : self.evOnceHandlers[ev](obj))
            del self.evOnceHandlers[ev]
    async def service_async_call(self, dom, nm, args):
        call = SimpleNamespace(data = args)
        fulln = f'{dom}.{nm}'
        if not fulln in self.servHandlers:
            raise FakeExceptions.ServiceNotFound(f'not found {fulln}')
        await self.servHandlers[fulln](call)
    def async_create_task(self, afut, eager_start=False ):
        return asyncio.get_running_loop().create_task(afut)
    def async_create_background_task(self, afut, name, eager_start=False ):
        return asyncio.get_running_loop().create_task(afut)
        
sys.modules['homeassistant'] = FakeHA
sys.modules['homeassistant.helpers.config_validation'] = FakeHA.helpers.config_validation
sys.modules['homeassistant.helpers.entity_component'] = FakeHA.helpers.entity_component
sys.modules['homeassistant.helpers.event'] = FakeHA.helpers.event
sys.modules['homeassistant.helpers.restore_state'] = FakeHA.helpers.restore_state
sys.modules['homeassistant.helpers.entity'] = FakeHA.helpers.entity
sys.modules['homeassistant.helpers.service'] = FakeHA.helpers.service
sys.modules['homeassistant.helpers.template'] = FakeHelpers.template
sys.modules['homeassistant.helpers.trigger'] = FakeHA.helpers.trigger
sys.modules['homeassistant.helpers.typing'] = FakeHA.helpers.typing
sys.modules['homeassistant.helpers.storage'] = FakeHA.helpers.storage
sys.modules['homeassistant.util.dt'] = FakeHA.util.dt
sys.modules['homeassistant.util.yaml'] = FakeHA.util.yaml
sys.modules['homeassistant.helpers'] = FakeHelpers

def resetModuleLoadTime():
    alert2.moduleLoadTime = rawdt.datetime.now(rawdt.UTC)

import custom_components.alert2 as alert2
import custom_components.alert2.entities as a2Entities
alert2.kNotifierStartupGraceSecs = 3

def getCondTracker(aler):
    if isinstance(aler, a2Entities.AlertGenerator):
        return aler.tracker
    else:
        assert isinstance(aler, a2Entities.ConditionAlert)
        return aler.condValTracker
    assert False

def doGeneratorUpdate(aler, rez):
    setGenerator(aler, rez)
    try:
        crez = aler._generator_template.async_render()
    except FakeExceptions.TemplateError as f:
        crez = f
    aler.tracker._result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                            [ SimpleNamespace(template=aler._generator_template, result=crez) ])

def doFriendlyNameUpdate(aler, rez):
    setFriendlyName(aler, rez)
    templ = aler.friendlyNameTracker.cfgList[0]['template']
    try:
        crez = templ.async_render()
    except FakeExceptions.TemplateError as f:
        crez = f
    aler.friendlyNameTracker._result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                            [ SimpleNamespace(template=templ, result=crez) ])
    
def doConditionUpdate(aler, rez):
    #assert isinstance(rez, bool)
    setCondition(aler, rez)
    try:
        crez = aler._condition_template.async_render()
    except FakeExceptions.TemplateError as f:
        crez = f
    getCondTracker(aler)._result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                                    [ SimpleNamespace(template=aler._condition_template, result=crez) ])
def doValueUpdate(aler, rez):
    setValue(aler, rez)
    try:
        vrez = aler._threshold_value_template.async_render()
    except FakeExceptions.TemplateError as f:
        vrez = f
    getCondTracker(aler)._result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._threshold_value_template, result=vrez) ])
def doCondValueUpdate(aler, condRez, valRez):
    setCondition(aler, condRez)
    setValue(aler, valRez)
    try:
        crez = aler._condition_template.async_render()
    except FakeExceptions.TemplateError as f:
        crez = f
    try:
        vrez = aler._threshold_value_template.async_render()
    except FakeExceptions.TemplateError as f:
        vrez = f
    getCondTracker(aler)._result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                               [ SimpleNamespace(template=aler._threshold_value_template, result=vrez),
                                 SimpleNamespace(template=aler._condition_template, result=crez) ])
    
def setFriendlyName(aler, rez):
    aler.friendlyNameTracker.cfgList[0]['template'].set_value(rez)
def setGenerator(aler, rez):
    aler._generator_template.set_value(rez)
def setValue(aler, rez):
    aler._threshold_value_template.set_value(rez)
def setCondition(aler, rez):
    if isinstance(rez, bool):
        aler._condition_template.set_value("{{ true }} " if rez else "{{ false }}")
    else:
        assert isinstance(rez, str), rez
        #assert '{{' in rez, rez
        aler._condition_template.set_value(rez)


class TestHelper:
    async def waitForAllBut(self, oldTasks):
        await asyncio.sleep(0) # let events fire
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
    
    async def initCase(self, cfg, ahass=None, startWatching=True):
        print('setting up')
        self.oldTasks = asyncio.all_tasks()
        if ahass:
            self.hass = ahass
        else:
            self.hass = FakeHass()
        setGhass(self.hass)
        await alert2.async_setup(self.hass, cfg)
        self.gad = self.hass.data[alert2.DOMAIN]
        self.gad.binarySensorDict = {'hastarted' : SimpleNamespace(_attr_is_on = False,
                                                                 async_write_ha_state = lambda : None ) }
        #self.gad = alert2.Alert2Data(self.hass, cfg)
        #self.hass.data = { alert2.DOMAIN : self.gad }
        #await self.gad.init2()
        #await self.gad.haStartedEv(None)
        if startWatching:
            # normally called when EVENT_HOMEASSISTANT_STARTED happens
            await self.startWatching()
    
    async def startWatching(self):
        self.hass.bus.async_fire(FakeConst.EVENT_HOMEASSISTANT_STARTED, 'happy')
        await asyncio.sleep(0.1)
        return
        self.gad.haStarted = True
        # do generators first so if they create entities, those also will start being watched
        for name in self.gad.generators:
            self.gad.generators[name].startWatchingEv(None)
        await asyncio.sleep(0.1)
        for dom in self.gad.alerts:
            for name in self.gad.alerts[dom]:
                self.gad.alerts[dom][name].startWatchingEv(None) 
        for dom in self.gad.tracked:
            for name in self.gad.tracked[dom]:
                self.gad.tracked[dom][name].startWatchingEv(None)
        await asyncio.sleep(0.1)

        
