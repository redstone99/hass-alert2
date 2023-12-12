"""Support for reading data from a serial port for Napco device."""
from . import DOMAIN
import logging
_LOGGER = logging.getLogger(__name__)
import sys
sys.path.append('/config/custom_components/')
from allCommon import *
from allHAcommon import *

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    sensorDict = {
        'evCount' : SimpleSensor('alert2 change count', None, 'total_increasing', None)
    }
    sensorDict['evCount']._attr_native_value = 0
    entities = [ sensorDict[key] for key in sensorDict ]
    async_add_entities( entities )
    hass.data[DOMAIN].setSensorDict(sensorDict)
