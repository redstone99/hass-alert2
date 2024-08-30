import voluptuous as vol
import homeassistant.helpers.config_validation as cv
def has_atleast_oneof(alist: list, aschema):
    """Validate that at least one of the keys in alist exist."""

    if not isinstance(alist, list):
        raise vol.Invalid("expected list")
    aset = set(alist)

    def validate(obj: dict) -> dict:
        """Test at least one key in alist is in zero keys exist or one key exists in dict."""
        if not isinstance(obj, dict):
            raise vol.Invalid("expected dictionary")
        obj2 = aschema(obj)
        if len(aset & set(obj2)) < 1 :
            expected = ", ".join(str(k) for k in alist)
            raise vol.Invalid(f"must contain at least one of {expected}.")
        return obj2
    return validate

SINGLE_TRACKED_SCHEMA = vol.Schema({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('notification_frequency_mins'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
    vol.Optional('notifier'): cv.string,
})
SINGLE_ALERT_SCHEMA_BASE = vol.Schema({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('message'): cv.template,
    vol.Optional('notification_frequency_mins'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
    vol.Optional('notifier'): cv.string
})
SINGLE_ALERT_SCHEMA_EVENT = SINGLE_ALERT_SCHEMA_BASE.extend({
        vol.Required('trigger'): cv.TRIGGER_SCHEMA,
        vol.Required('condition'): cv.template,
    })
SINGLE_ALERT_SCHEMA_CONDITION = has_atleast_oneof(['condition', 'threshold'], SINGLE_ALERT_SCHEMA_BASE.extend({ 
        vol.Optional('condition'): cv.template,
        vol.Optional('threshold'): has_atleast_oneof(['minimum', 'maximum'], vol.Schema({
            vol.Required('value'): cv.template,
            vol.Required('hysteresis'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
            vol.Optional('minimum'): vol.Coerce(float),
            vol.Optional('maximum'): vol.Coerce(float),
            })),
        vol.Optional('early_start'): bool,
    }))
                                 
DEFAULTS_SCHEMA = vol.Schema({
        vol.Optional('notification_frequency_mins'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
        vol.Optional('notifier'): cv.string,
})

TOP_LEVEL_SCHEMA = vol.Schema({
    vol.Optional('defaults'): dict,
    vol.Optional('tracked'): list,
    vol.Optional('alerts'): list
})
