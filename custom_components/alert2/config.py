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

DEFAULTS_SCHEMA = vol.Schema({
    vol.Optional('notifier'): cv.string,
    vol.Optional('annotate_messages'): cv.boolean,
    vol.Optional('reminder_frequency_mins'): vol.All(cv.ensure_list, [vol.Coerce(float)], [vol.Range(min=0.01)]),
    vol.Optional('throttle_fires_per_mins'): vol.Schema(vol.All(vol.ExactSequence([int, vol.Coerce(float)]),
                                                                 vol.ExactSequence([vol.Range(min=1.),vol.Range(min=0.01)])))
})
SINGLE_TRACKED_SCHEMA = vol.Schema({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('friendly_name'): cv.string,
    vol.Optional('notifier'): cv.string, #cv.template,
    vol.Optional('title'): cv.template,
    vol.Optional('target'): cv.template,
    vol.Optional('data'): dict,
    vol.Optional('throttle_fires_per_mins'): vol.Schema(vol.All(vol.ExactSequence([int, vol.Coerce(float)]),
                                                                 # 0.001 hours is 3.6 seconds
                                                                 vol.ExactSequence([vol.Range(min=1.),vol.Range(min=0.01)]))),
    vol.Optional('annotate_messages'): cv.boolean,
})
SINGLE_ALERT_SCHEMA_BASE = SINGLE_TRACKED_SCHEMA.extend({
    vol.Optional('message'): cv.template,
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
    vol.Optional('early_start'): cv.boolean,
    vol.Optional('done_message'): cv.template,
    vol.Optional('reminder_frequency_mins'): vol.All(cv.ensure_list, [vol.Coerce(float)], [vol.Range(min=0.01)]),
    vol.Optional('delay_on_secs'): vol.All(vol.Coerce(float), vol.Range(min=0.1)),
}))
                                 

TOP_LEVEL_SCHEMA = vol.Schema({
    vol.Optional('defaults'): dict,
    vol.Optional('tracked'): list,
    vol.Optional('alerts'): list,
    # cv.boolean here must match code in Alert2Data.init2()
    vol.Optional('skip_internal_errors'): cv.boolean
})
