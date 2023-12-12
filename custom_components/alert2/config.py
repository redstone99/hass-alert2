from . import DOMAIN
import voluptuous as vol
from voluptuous.humanize import humanize_error
import homeassistant.helpers.config_validation as cv
import logging
from homeassistant.helpers import config_per_platform, config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
_LOGGER = logging.getLogger(__name__)
#DOMAIN='alert2'
SINGLE_TRACKED_SCHEMA = vol.Schema({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('notification_frequency_mins'): vol.Coerce(float),
    vol.Optional('notifier'): cv.string,
})
SINGLE_ALERT_SCHEMA = vol.Schema({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('trigger'): cv.TRIGGER_SCHEMA,
    vol.Required('condition'): cv.template,
    vol.Required('message'): cv.template,
    vol.Optional('notification_frequency_mins'): vol.Coerce(float),
    vol.Optional('notifier'): cv.string
})

ALERT2_SCHEMA = vol.Schema({
    vol.Optional('defaults'): vol.Schema({
        vol.Optional('notification_frequency_mins'): vol.Coerce(float),
        vol.Optional('notifier'): cv.string,
    }),
    vol.Optional('tracked'): vol.All(
        cv.ensure_list,
        vol.Schema([SINGLE_TRACKED_SCHEMA])),
    vol.Optional('alerts'): vol.All(
        cv.ensure_list,
        vol.Schema([SINGLE_ALERT_SCHEMA]))
}, extra=vol.PREVENT_EXTRA)
CONFIG_SCHEMA = vol.Schema({DOMAIN: ALERT2_SCHEMA}, extra=vol.ALLOW_EXTRA)

async def async_validate_config(hass: HomeAssistant, config: ConfigType) -> ConfigType:
    """Validate config."""
    # config is the whole homeassistant configuration
    # I think config_per_platform gets each config section, like 'alert2 aa:', 'alert2 bb:', ...
    #
    # Purpose of this is to give a more informative error in the alert config
    #
    for section_name, p_config in config_per_platform(config, DOMAIN):
        if 'alerts' in p_config:
            for analert in p_config['alerts']:
                try:
                    SINGLE_ALERT_SCHEMA(analert)
                except vol.Invalid as ex:
                    msg = f'In alert2 { section_name if section_name else ""} alerts '
                    if 'domain' in analert:
                        msg += f' domain={analert["domain"]}'
                    if 'name' in analert:
                        msg += f' name={analert["name"]}'
                    msg += f': {humanize_error(p_config, ex)}'
                    _LOGGER.error(msg)
        if 'tracked' in p_config:
            for analert in p_config['tracked']:
                try:
                    SINGLE_TRACKED_SCHEMA(analert)
                except vol.Invalid as ex:
                    msg = f'In alert2 { section_name if section_name else ""} tracked '
                    if 'domain' in analert:
                        msg += f' domain={analert["domain"]}'
                    if 'name' in analert:
                        msg += f' name={analert["name"]}'
                    msg += f': {humanize_error(p_config, ex)}'
                    _LOGGER.error(msg)
    # Now do the real config validation that won't have such a good error.
    cfg = CONFIG_SCHEMA(config)
    return cfg
