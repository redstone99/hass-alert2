#
# JTESTDIR=/home/redstone/home-monitoring/homeassistant  venv/bin/pytest --show-capture=no
#
#from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import os
import sys
import asyncio
import logging
_LOGGER = logging.getLogger(None) # get root logger
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])

from custom_components.alert2 import (DOMAIN, Alert2Data)

async def test_cfg1(hass):
    assert await async_setup_component(hass, DOMAIN, { 'alert2': {} })
    await hass.async_block_till_done()
    assert isinstance(hass.data[DOMAIN], Alert2Data)

async def test_badarg1(hass, service_calls):
    cfg = { 'alert2' : {
        'defaults' : {
            'notifierz' : 'foobar'
        },
    } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    service_calls.popNotify('persistent_notification', r'extra keys not allowed')
    assert service_calls.isEmpty()

async def test_ack(hass, service_calls):
    cfg = { 'input_boolean': { 'b1': { 'name': 'b1' } } }
    assert await async_setup_component(hass, 'input_boolean', cfg)

    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'input_boolean.b1' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]

    t1 = gad.alerts['test']['t1']
    #eawait hass.services.async_call
    hass.states.async_set("input_boolean.b1", "on")
    await hass.async_block_till_done()
    _LOGGER.warning(f' state is now {hass.states.get("input_boolean.b1").state}')
    await hass.async_start()
    await hass.async_block_till_done()
    await asyncio.sleep(3)
    
