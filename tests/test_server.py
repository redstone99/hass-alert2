#
# must set JTEST_JS_DIR when running to be root of hass-alert2-ui
#

import asyncio
import logging
import sys
import os
from homeassistant.setup import async_setup_component
_LOGGER = logging.getLogger(None) # get root logger
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])
from custom_components.alert2 import (DOMAIN, Alert2Data)
import custom_components.alert2 as alert2
import custom_components.alert2.entities as a2Entities
import custom_components.alert2.ui as a2Ui
from homeassistant.components import http
from aiohttp.web import middleware
from homeassistant import config as conf_util
from homeassistant.components.http.const import KEY_AUTHENTICATED
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.data_validator import RequestDataValidator
import voluptuous as vol
from aiohttp import web
from typing import Any

class TestView(HomeAssistantView):
    def __init__(self, hass, hass_storage, monkeypatch):
        self.hass = hass
        self.hass_storage = hass_storage
        self.monkeypatch = monkeypatch
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
                self.hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                                        'data': { 'config': uiCfg } }
                #gad.uiMgr.saveTopConfig({ 'defaults': {} })
                cfg = {'alert2': {}}
                if 'yaml' in data and isinstance(data['yaml'], dict):
                    cfg['alert2'] = data['yaml']
                async def fake_cfg(thass):
                    return cfg
                with self.monkeypatch.context() as m:
                    m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
                    await gad.reload_service_handler(None)
            else:
                assert False
        else:
            assert False
        return self.json({})


async def test_server(hass, hass_storage, monkeypatch): #, unused_tcp_port_factory):
    cfg = {'alert2': {},
           http.DOMAIN: {http.CONF_SERVER_PORT: 50005}
           }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await async_setup_component(
        hass,
        http.DOMAIN,
        cfg )
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
    hass.http.register_view(TestView(hass, hass_storage, monkeypatch))
    await hass.async_start()
    await asyncio.sleep(55555555)
    
