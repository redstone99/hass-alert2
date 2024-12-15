import logging
import voluptuous as vol
from   homeassistant.exceptions import TemplateError
import homeassistant.helpers.config_validation as cv

########################## Experimental
_LOGGER = logging.getLogger(__name__)
import re
from functools import lru_cache
from   homeassistant.core import callback
from   homeassistant.helpers import template as template_helper
TemplateVarsType = None
RenderInfo = None

_regex_cache = lru_cache(maxsize=128)(re.compile)

def entity_id_regex_extract(seq, find, ignorecase=False):
    """Match value using regex."""
    flags = re.IGNORECASE if ignorecase else 0
    regex = _regex_cache(find, flags)
    for item in seq:
        entity_id = item.entity_id
        m = regex.match(entity_id)
        if bool(m):
            yield  { "genEntityId": entity_id, "genGroups": list(m.groups()) }
                
class JTemplate(template_helper.Template):
    @callback
    def async_render_to_info(
            self,
            variables: TemplateVarsType = None,
            strict: bool = False,
            log_fn = None, #: Callable[[int, str], None] | None = None,
            **kwargs, #: Any,
    ) -> RenderInfo:
        ri = super().async_render_to_info()
        #_LOGGER.warning(f'Original RenderInfo: {ri}')
        # Move domains to domains_lifecycle. Unfreeze, move, then refreeze
        ri.domains_lifecycle = set(ri.domains_lifecycle)
        ri.domains_lifecycle.update(ri.domains)
        ri.domains = set() # empty set
        # leave ri.entities as is, will get refrozen
        if ri.all_states:
            ri.all_states_lifecycle = True
        ri.all_states = False

        # _freeze() assumes some variables are in an initial state
        # we need to restore those vars to _freeze results in correct vals for them:
        ri.rate_limit = None
        ri.filter_lifecycle = lambda astr: True

        ri._freeze()
        return ri
    @property
    def _env(self):
        env = super()._env
        env.filters['entity_regex'] = entity_id_regex_extract
        return env
            
#def jtemplate(value: Any | None) -> JTemplate:
def jtemplate(value) -> JTemplate:
    """Similar to helpers/config_validation.py:template()."""
    if value is None:
        raise vol.Invalid("Generator template is None")
    if isinstance(value, list):
        return jstringList(value)
    if isinstance(value, (dict, JTemplate, template_helper.Template)):
        raise vol.Invalid("Generator template should be a string")
    if not (hass := cv._async_get_hass_or_none()):
        # pylint: disable-next=import-outside-toplevel
        from .frame import report
        report(
            (
                "validates schema outside the event loop, "
                "which will stop working in HA Core 2025.10"
            ),
            error_if_core=False,
        )

    #template_value = template_helper.Template(str(value), hass)
    template_value = JTemplate(str(value), hass)

    try:
        template_value.ensure_valid()
    except TemplateError as ex:
        #_LOGGER.warning(f'  templ value is {value}  of type {type(value)} with exception {ex}')
        raise vol.Invalid(f"invalid template ({ex})") from ex
    return template_value

##########################

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

def jstringList(afield):
    alist = cv.ensure_list(afield)
    for elem in alist:
        if isinstance(elem, str):
            if len(elem) == 0:
                raise vol.Invalid(f'Notifier can not be empty string')
        else:
            raise vol.Invalid(f'Notifier "{elem}" is type {type(elem)} rather than string')
    return alist
DEFAULTS_SCHEMA = vol.Schema({
    vol.Optional('notifier'): vol.Any(cv.template, jstringList),
    # Can be truthy or template or list of notifiers
    vol.Optional('summary_notifier'): vol.Any(cv.boolean, cv.template, jstringList),
    vol.Optional('annotate_messages'): cv.boolean,
    vol.Optional('reminder_frequency_mins'): vol.All(cv.ensure_list, [vol.Coerce(float)], [vol.Range(min=0.01)]),
    vol.Optional('throttle_fires_per_mins'): vol.Schema(vol.All(vol.ExactSequence([int, vol.Coerce(float)]),
                                                                 vol.ExactSequence([vol.Range(min=1.),vol.Range(min=0.01)]))),
})

SINGLE_TRACKED_SCHEMA_PRE_NAME = vol.Schema({
    vol.Optional('notifier'): vol.Any(cv.template, jstringList),
    vol.Optional('summary_notifier'): vol.Any(cv.boolean, cv.template, jstringList),
    vol.Optional('title'): cv.template,
    vol.Optional('target'): cv.template,
    vol.Optional('data'): dict,
    vol.Optional('throttle_fires_per_mins'): vol.Schema(vol.All(vol.ExactSequence([int, vol.Coerce(float)]),
                                                                 # 0.001 hours is 3.6 seconds
                                                                 vol.ExactSequence([vol.Range(min=1.),vol.Range(min=0.01)]))),
    vol.Optional('annotate_messages'): cv.boolean,
})

# So if 'generator' is present, then 'name' is a template. Otherwise it's a string.
SINGLE_TRACKED_SCHEMA = SINGLE_TRACKED_SCHEMA_PRE_NAME.extend({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('friendly_name'): cv.string,
})

SINGLE_ALERT_SCHEMA_PRE_NAME = SINGLE_TRACKED_SCHEMA_PRE_NAME.extend({
    vol.Optional('message'): cv.template
})

SINGLE_ALERT_SCHEMA_EVENT = SINGLE_ALERT_SCHEMA_PRE_NAME.extend({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('friendly_name'): cv.string,
    vol.Required('trigger'): cv.TRIGGER_SCHEMA,
    vol.Required('condition'): cv.template,
})


SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME = SINGLE_ALERT_SCHEMA_PRE_NAME.extend({
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
})
# If alert is a generator, then 'name' is a template, otherwise 'name' is a string
SINGLE_ALERT_SCHEMA_CONDITION = vol.Any(SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME.extend({
    vol.Required('domain'): cv.template,
    vol.Required('name'): cv.template,
    vol.Optional('friendly_name'): cv.template,
    vol.Required('generator'): jtemplate,
    vol.Required('generator_name'): cv.string,
}), SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME.extend({
    vol.Required('domain'): cv.string,
    vol.Required('name'): cv.string,
    vol.Optional('friendly_name'): cv.string,
}))

TOP_LEVEL_SCHEMA = vol.Schema({
    vol.Optional('defaults'): dict,
    vol.Optional('tracked'): list,
    vol.Optional('alerts'): list,
    # cv.boolean here must match code in Alert2Data.init2()
    vol.Optional('skip_internal_errors'): cv.boolean,
    vol.Optional('notifier_startup_grace_secs'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
    vol.Optional('defer_startup_notifications'): vol.Any(cv.boolean, vol.All(cv.ensure_list, [cv.string])),
})
