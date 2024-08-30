from . import DOMAIN
import homeassistant.util.dt as dt
from homeassistant.components.sensor import SensorEntity

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    aSensor = SensorEntity()
    aSensor._attr_name = 'alert2 change count'
    aSensor._attr_should_poll = False
    aSensor._attr_device_class = None
    aSensor._attr_state_class = 'total_increasing'
    aSensor._attr_native_value = 0
    aSensor._attr_native_unit_of_measurement = None
    aSensor._attr_extra_state_attributes = None
    async_add_entities([ aSensor ])
    hass.data[DOMAIN].setSensorDict({ 'evCount': aSensor })
