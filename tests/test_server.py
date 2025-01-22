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
from homeassistant.components.http.const import KEY_AUTHENTICATED
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.data_validator import RequestDataValidator
import voluptuous as vol
from aiohttp import web
from typing import Any

class TestView(HomeAssistantView):
    def __init__(self, hass):
        self.hass = hass
    url = "/api/alert2test/tcheck"
    name = "api:alert2test:tcheck"
    @RequestDataValidator(vol.Schema({
        vol.Exclusive('stage', 'op'): str
    }, extra=vol.ALLOW_EXTRA))
    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        gad = self.hass.data[DOMAIN]
        if 'stage' in data:
            if data['stage'] == 't1':
                assert gad.uiMgr.data == { 'config': { 'defaults': {} } }
            else:
                assert False
        else:
            assert False
        return self.json({})


async def test_server(hass, monkeypatch): #, unused_tcp_port_factory):
    await async_setup_component(
        hass,
        http.DOMAIN,
        {http.DOMAIN: {http.CONF_SERVER_PORT: 50005}},
    )
    cfg = { 'alert2': {} }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.http.async_register_static_paths([
        http.StaticPathConfig('/jtest',
                         '/home/redstone/tmp/hass-alert2-ui',
                         False)])
    # Override http/auth.py::auth_middleware authentication to say everything's authenticated.
    @middleware
    async def auth_middleware(request, handler):
        request[KEY_AUTHENTICATED] = True
        return await handler(request)
    hass.http.app.middlewares.append(auth_middleware)
    hass.http.register_view(TestView(hass))
    await hass.async_start()
    await asyncio.sleep(55555555)
    
