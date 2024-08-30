from . import DOMAIN, moduleLoadTime
import homeassistant.util.dt as dt
from homeassistant.components.binary_sensor import BinarySensorEntity

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    aSensor = BinarySensorEntity()
    aSensor._attr_is_on = False
    aSensor._attr_name = 'alert2 ha_startup_done'
    aSensor._attr_should_poll = False
    aSensor._attr_device_class = None
    aSensor._attr_extra_state_attributes = { 'start_time' : moduleLoadTime }
    async_add_entities([ aSensor ])
    hass.data[DOMAIN].setBinarySensorDict({ 'hastarted' : aSensor })
