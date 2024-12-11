from . import DOMAIN, moduleLoadTime
import homeassistant.util.dt as dt
from homeassistant.components.binary_sensor import BinarySensorEntity
import homeassistant.loader as loader
import logging
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, _config_entry, async_add_entities):
    _LOGGER.debug(f'async_setup_entry for binary_sensor called')

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    _LOGGER.debug(f'async_setup_platform for binary_sensor called')
    aSensor = BinarySensorEntity()
    aSensor._attr_is_on = False
    aSensor._attr_name = 'alert2 ha_startup_done'
    aSensor._attr_should_poll = False
    aSensor._attr_device_class = None

    try:
        inte = loader.async_get_loaded_integration(hass, DOMAIN)
        manifestVer = inte.version
    except Exception:
        manifestVer = "unknown"
    aSensor._attr_extra_state_attributes = { 'start_time' : moduleLoadTime,
                                             'manifest_version': manifestVer
                                            }
    async_add_entities([ aSensor ])
    hass.data[DOMAIN].setBinarySensorDict({ 'hastarted' : aSensor })
