#
# JTESTDIR=/home/redstone/home-monitoring/homeassistant  venv/bin/pytest --show-capture=no
#

from homeassistant.setup import async_setup_component
import os
import sys
import logging
from unittest.mock import patch
_LOGGER = logging.getLogger(None) # get root logger
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])

from custom_components.alert2 import (DOMAIN, Alert2Data)

async def test_cfg1(hass):
    assert await async_setup_component(hass, DOMAIN, { 'alert2': {} })
    await hass.async_block_till_done()
    assert isinstance(hass.data[DOMAIN], Alert2Data)

async def test_cfg2(hass):
    with patch('homeassistant.core.ServiceRegistry.async_call') as mock_service_call:
        assert await async_setup_component(hass, DOMAIN, { 'alert2': { 'foo' : 3 } })
        await hass.async_block_till_done()
        mock_service_call.assert_called_once()
        assert mock_service_call.call_count == 1
        assert len(mock_service_call.await_args_list) == 1
        assert mock_service_call.await_args_list[0].args[0] == 'notify'
        assert mock_service_call.await_args_list[0].args[1] == 'persistent_notification'
        assert 'extra keys not allowed' in mock_service_call.await_args_list[0].args[2]['message']
        _LOGGER.info(mock_service_call.await_args_list[0].args)
        #self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2a.*unexpected end of template')
        #_with('notify', 'persistent_notification', {'entity_id': 'light.my_light'})
