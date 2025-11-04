#
# must set JTEST_JS_DIR when running to be root of hass-alert2-ui
#
# For instructions on how to run, see
#    https://github.com/redstone99/hass-alert2#testing
#
#
import asyncio
import logging
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger('dummy_server') # or None for root logger
import sys
import os
from homeassistant.setup import async_setup_component
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])
from custom_components.alert2 import (DOMAIN, Alert2Data)
import custom_components.alert2 as alert2
import custom_components.alert2.entities as a2Entities
import custom_components.alert2.ui as a2Ui
from homeassistant.components import http
from aiohttp.web import middleware
from homeassistant import config as conf_util
#import homeassistant.auth as hauth
from homeassistant.components import history
from homeassistant.components.http.const import KEY_AUTHENTICATED
from homeassistant.components.http import HomeAssistantView
import homeassistant.components.websocket_api.auth as wsauth
from homeassistant.components.http.data_validator import RequestDataValidator
import voluptuous as vol
from aiohttp import web
from typing import Any
import pytest

@pytest.fixture(autouse=True)
def set_module_log_level(caplog):
    #caplog.set_level(logging.INFO, logger=None)
    global _LOGGER
    #logging.basicConfig(level=logging.WARNING)
    rootLogger = logging.getLogger(None) # get root logger
    rootLogger.setLevel(logging.INFO)
    _LOGGER = logging.getLogger('dummy_server')
    _LOGGER.setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
#from tests.components.recorder.common import (
#    async_wait_recording_done,
#)

done = asyncio.Condition()

class FakeStore:
    def __init__(self, data):
        self.data = data
    async def async_load(self):
        return self.data
    def async_delay_save(self, data_to_save, delaytime):
        pass
    
class JTestView(HomeAssistantView):
    def __init__(self, hass, hass_storage, monkeypatch):
        self.hass = hass
        self.hass_storage = hass_storage
        self.monkeypatch = monkeypatch
        self.realStore = None
    url = "/api/alert2test/tcheck"
    name = "api:alert2test:tcheck"
    @RequestDataValidator(vol.Schema({
        vol.Exclusive('stage', 'op'): str
    }, extra=vol.ALLOW_EXTRA))
    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        gad = self.hass.data[DOMAIN]
        if 'stage' in data:
            if data['stage'] == 'getUiData':
                await self.hass.async_block_till_done()
                return self.json(gad.uiMgr.data)
            elif data['stage'] == 'reset':
                await self.hass.async_block_till_done()
                uiCfg = { 'defaults': {} }
                if 'uiYaml' in data and isinstance(data['uiYaml'], dict):
                    # There's one test that uses uiYaml to set up an invalid config.
                    # We need to temporarily override the store used inside uiMgr to make it work.
                    # So we keep around the original store used in the var realStore to restore things afterwards so subsequent tests work.
                    uiCfg = data['uiYaml']
                    _LOGGER.info(f'Setting uiCfg to {uiCfg}')
                    assert self.realStore == None
                    self.realStore = gad.uiMgr._store
                    gad.uiMgr._store = FakeStore({ 'config': uiCfg })
                else:
                    if self.realStore != None:
                        gad.uiMgr._store = self.realStore
                        self.realStore = None
                self.hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                                        'data': { 'config': uiCfg } }
                #if 'uiYaml' in data and isinstance(data['uiYaml'], dict):
                #gad.uiMgr.saveTopConfig({ 'defaults': {} })
                cfg = {'alert2': {}}
                if 'yaml' in data and isinstance(data['yaml'], dict):
                    cfg['alert2'] = data['yaml']
                async def fake_cfg(thass):
                    return cfg
                with self.monkeypatch.context() as m:
                    m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
                    await gad.reload_service_handler(None)
            elif data['stage'] == 'setEnt':
                _LOGGER.info(f'test server setting ent {data["entity_id"]} to {data["state"]}')
                self.hass.states.async_set(data['entity_id'], data['state'])
            elif data['stage'] == 'exit':
                async with done:
                    await done.notify()
            else:
                _LOGGER.error(f'Got bad tcheck stage data={data}')
                assert False
        else:
            _LOGGER.error(f'Got bad tcheck missing stage data={data}')
            assert False
        return self.json({})


async def test_server(recorder_mock, enable_custom_integrations, hass, hass_storage, monkeypatch, hass_access_token):
    _LOGGER.warning('fuck..........')
    cfg = {'alert2': {},
           http.DOMAIN: {http.CONF_SERVER_PORT: 50005}
           }

    oldAsyncHandle = wsauth.AuthPhase.async_handle
    async def fake_handle(obj, msg):
        #_LOGGER.warning(f'replacing {msg["access_token"]} with {hass_access_token}')
        msg['access_token'] = hass_access_token
        return await oldAsyncHandle(obj, msg)
    monkeypatch.setattr(wsauth.AuthPhase, 'async_handle', fake_handle)

    assert await async_setup_component(hass, DOMAIN, cfg)
    history_config = history.CONFIG_SCHEMA(
        { history.DOMAIN: {
        } } )
    assert await async_setup_component(hass, history.DOMAIN, history_config)
    await async_setup_component(
        hass,
        http.DOMAIN,
        cfg )
    assert await async_setup_component(hass, "websocket_api", {})

    #hass.states.async_set('alert2.d_nn', 'off')
    #await async_wait_recording_done(hass)

    #        {http.DOMAIN: {http.CONF_SERVER_PORT: 50005}},  )
    cfg = { 'alert2': {} }
    assert await async_setup_component(hass, DOMAIN, cfg)
    jsdir = os.environ.get('JTEST_JS_DIR')
    assert isinstance(jsdir, str) and len(jsdir) > 0
    await hass.http.async_register_static_paths([
        http.StaticPathConfig('/jtest', jsdir, False)])
    # Override http/auth.py::auth_middleware authentication to say everything's authenticated.
    @middleware
    async def auth_middleware(request, handler):
        request[KEY_AUTHENTICATED] = True
        return await handler(request)
    hass.http.app.middlewares.append(auth_middleware)
    hass.http.register_view(JTestView(hass, hass_storage, monkeypatch))
    await hass.async_start()
    async with done:
        await done.wait()
