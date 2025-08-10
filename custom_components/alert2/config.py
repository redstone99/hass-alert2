import logging
import voluptuous as vol
from   homeassistant.exceptions import TemplateError
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)
import re
from functools import lru_cache
from   homeassistant.core import callback
from   homeassistant.helpers import template as template_helper
from .util import (GENERATOR_DOMAIN)

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


def boolTemplate(cond):
    # we haven't done a voluptuous validation yet, so don't know what type cond is
    if isinstance(cond, str) and not template_helper.is_template_string(cond):
        try:
            x = cv.boolean(cond)
        except (vol.Invalid) as ex:
            # it's not a template and not a truthy, so assume it's an entity
            if '\'' in cond or '"' in cond:
                raise vol.Invalid(f'boolean template is neither a jinja template nor an entity: {cond}') from ex
            # TODO - Not sure if strip() is necessary. Can yaml return extra whitespace?
            cond = '{{ states("' + cond.strip() + '") }}'
    return cv.template(cond)
def floatTemplate(afloat):
    # we haven't done a voluptuous validation yet, so don't know what type afloat is
    if isinstance(afloat, str) and not template_helper.is_template_string(afloat):
        try:
            x = float(afloat)
        except (ValueError) as ex:
            # it's not a template and not a truthy, so assume it's an entity
            if '\'' in afloat or '"' in afloat:
                raise vol.Invalid(f'float template is neither a jinja template nor an entity: {afloat}') from ex
            # TODO - Not sure if strip() is necessary. Can yaml return extra whitespace?
            afloat = '{{ states("' + afloat.strip() + '") }}'
    return cv.template(afloat)
    
#def jtemplate(value: Any | None) -> JTemplate:
def jtemplate(value) -> JTemplate:
    """Similar to helpers/config_validation.py:template()."""
    if value is None:
        raise vol.Invalid("Generator template is None")
    if isinstance(value, list):
        return value #jstringList(value)
    if isinstance(value, (JTemplate, template_helper.Template)):
        raise vol.Invalid("Generator template should be a string")
    if not isinstance(value, str):
        return value
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


def supersedesTemplate(elem):
    if not isinstance(elem, str) or not template_helper.is_template_string(elem):
        raise vol.Invalid('Not a template string')
    return cv.template(elem)


def literalIllegalChar(elem):
    return any(e in elem for e in '[]{}\'",')

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

def check_off(aschema):
    """Validate that the off conditions are legal."""

    def validate(obj: dict) -> dict:
        if not isinstance(obj, dict):
            raise vol.Invalid("expected dictionary")
        obj2 = aschema(obj)
        has_off = any([k in obj2 for k in ['condition_off','trigger_off','manual_off']])
        has_on = any([k in obj2 for k in ['condition_on','trigger_on','manual_on']])
        has_both = any([k in obj2 for k in ['condition','threshold']])
        if has_off ^ has_on:
            raise vol.Invalid(f'Specs with an "off" criteria must also include an "on" criteria')

        if has_on: # and so has_off
            if has_both:
                raise vol.Invalid(f'Can not mix condition/threshold with explicit on/off criteria')
        else:
            if not has_both:
                raise vol.Invalid(f'Must specify either condition, threshold or the on/off criteria')
        return obj2
    return validate

def jstringList(afield):
    alist = cv.ensure_list(afield)
    for elem in alist:
        if isinstance(elem, str):
            if len(elem) == 0:
                raise vol.Invalid(f'Notifier can not be empty string')
            if literalIllegalChar(elem):
                raise vol.Invalid(f'Notifier has illegal chars (e.g., "[", "\'")')
        else:
            raise vol.Invalid(f'Notifier "{elem}" is type {type(elem)} rather than string')
    return alist
def jstringName(afield):
    elem = cv.string(afield)
    if len(elem) == 0:
        raise vol.Invalid(f'Empty string not allowed')
    if literalIllegalChar(elem):
        raise vol.Invalid(f'Illegal characters (e.g., "[", "\'")')
    return elem

def jProtectedTrigger(afield):
    try:
        atrigger = cv.TRIGGER_SCHEMA(afield)
    except TypeError as ty:
        raise vol.Invalid(f'Trigger spec cause type error: {ty}') from ty
    return atrigger

def jDomain(afield):
    dd = jstringName(afield)
    if dd == GENERATOR_DOMAIN:
        raise vol.Invalid(f'"{GENERATOR_DOMAIN}" is a reserved domain')
    return dd

def jDictTemplate(adict):
    if not isinstance(adict, dict):
        raise vol.Invalid(f'"data" field must be a dict')
    newDict = {}
    keys = adict.keys()
    for akey in keys:
        if isinstance(adict[akey], str) and template_helper.is_template_string(adict[akey]):
            newDict[akey] = cv.template(adict[akey])
        else:
            newDict[akey] = adict[akey]
    return newDict

DEFAULTS_SCHEMA = vol.Schema({
    vol.Optional('notifier'): vol.Any(cv.template, jstringList),
    # Can be truthy or template or list of notifiers
    vol.Optional('summary_notifier'): vol.Any(cv.boolean, cv.template, jstringList),
    vol.Optional('done_notifier'): vol.Any(cv.boolean, cv.template, jstringList),
    vol.Optional('annotate_messages'): cv.boolean,
    vol.Optional('reminder_frequency_mins'): vol.All(cv.ensure_list, [vol.Coerce(float)], [vol.Range(min=0.01)]),
    vol.Optional('throttle_fires_per_mins'): vol.Any(
        None, vol.All(vol.ExactSequence([int, vol.Coerce(float)]),
                      vol.ExactSequence([vol.Range(min=1.),vol.Range(min=0.01)]))),
    vol.Optional('priority'): vol.Any('low', 'medium', 'high', msg='must be one of "low", "medium" or "high"'),
    vol.Optional('supersede_debounce_secs'): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional('icon'): cv.icon,
    vol.Optional('data'): jDictTemplate,
})

SINGLE_TRACKED_SCHEMA_PRE_NAME = vol.Schema({
    vol.Optional('notifier'): vol.Any(cv.template, jstringList),
    vol.Optional('summary_notifier'): vol.Any(cv.boolean, cv.template, jstringList),
    vol.Optional('done_notifier'): vol.Any(cv.boolean, cv.template, jstringList),
    vol.Optional('friendly_name'): cv.template,
    vol.Optional('title'): cv.template,
    vol.Optional('target'): cv.template,
    vol.Optional('data'): jDictTemplate,
    vol.Optional('throttle_fires_per_mins'): vol.Schema(vol.All(vol.ExactSequence([int, vol.Coerce(float)]),
                                                                 # 0.001 hours is 3.6 seconds
                                                                 vol.ExactSequence([vol.Range(min=1.),vol.Range(min=0.01)]))),
    vol.Optional('annotate_messages'): cv.boolean,
    vol.Optional('display_msg'): vol.Any(cv.template, None),
    vol.Optional('priority'): vol.Any('low', 'medium', 'high'),
    vol.Optional('icon'): cv.icon,
    vol.Optional('ack_required'): cv.boolean,
    vol.Optional('ack_reminder_message'): cv.template,
    vol.Optional('reminder_frequency_mins'): vol.All(cv.ensure_list, [vol.Coerce(float)], [vol.Range(min=0.01)]),
})

DOMAIN_NAME_DICT = {
    vol.Required('domain'): jDomain,
    vol.Required('name'): jstringName,
}
# So if 'generator' is present, then 'name' is a template. Otherwise it's a string.
SINGLE_TRACKED_SCHEMA = SINGLE_TRACKED_SCHEMA_PRE_NAME.extend(DOMAIN_NAME_DICT)

SINGLE_ALERT_SCHEMA_PRE_NAME = SINGLE_TRACKED_SCHEMA_PRE_NAME.extend({
    vol.Optional('message'): cv.template
})

SINGLE_ALERT_SCHEMA_EVENT = SINGLE_ALERT_SCHEMA_PRE_NAME.extend({
    vol.Required('domain'): jDomain,
    vol.Required('name'): jstringName,
    vol.Required('trigger'): jProtectedTrigger,
    vol.Optional('condition'): boolTemplate,
    vol.Optional('early_start'): cv.boolean,
})

THRESHOLD_SCHEMA = vol.Schema({
    vol.Required('value'): floatTemplate,
    vol.Required('hysteresis'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
    vol.Optional('minimum'): vol.Coerce(float),
    vol.Optional('maximum'): vol.Coerce(float),
})

SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME = SINGLE_ALERT_SCHEMA_PRE_NAME.extend({
    vol.Optional('condition'): boolTemplate,
    vol.Optional('threshold'): has_atleast_oneof(['minimum', 'maximum'], THRESHOLD_SCHEMA),
    vol.Optional('condition_off'): boolTemplate,
    vol.Optional('trigger_off'): jProtectedTrigger,
    vol.Optional('manual_off'): cv.boolean,
    vol.Optional('condition_on'): boolTemplate,
    vol.Optional('trigger_on'): jProtectedTrigger,
    vol.Optional('manual_on'): cv.boolean,
    vol.Optional('reminder_message'): cv.template,
    vol.Optional('done_message'): cv.template,
    vol.Optional('early_start'): cv.boolean,
    vol.Optional('supersede_debounce_secs'): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional('ack_reminders_only'): cv.boolean,
})
DOMAIN_NAME_DICT_GEN = {
    vol.Required('domain'): cv.template,
    vol.Required('name'): cv.template,
}
SUPERSEDES_GEN = vol.Any(None, vol.All(cv.ensure_list, [ DOMAIN_NAME_DICT_GEN ]), supersedesTemplate)
GENERATOR_SCHEMA = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME.extend({
    vol.Required('domain'): cv.template,
    vol.Required('name'): cv.template,
    vol.Required('generator'): jtemplate,
    vol.Required('generator_name'): jstringName,
    vol.Optional('supersedes'): SUPERSEDES_GEN,
    vol.Optional('delay_on_secs'): cv.template,
    # Overrides 'priority'
    vol.Optional('priority'): cv.template,
})
NO_GENERATOR_SCHEMA = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME.extend({
    vol.Required('domain'): jDomain,
    vol.Required('name'): jstringName,
    vol.Optional('supersedes'): vol.Any(None, vol.All(cv.ensure_list, [ DOMAIN_NAME_DICT ])),
    vol.Optional('delay_on_secs'): vol.All(vol.Coerce(float), vol.Range(min=0)),
})

# If alert is a generator, then 'name' is a template, otherwise 'name' is a string
SINGLE_ALERT_SCHEMA_CONDITION = check_off(vol.Any(GENERATOR_SCHEMA, NO_GENERATOR_SCHEMA))

TOP_LEVEL_SCHEMA = vol.Schema({
    vol.Optional('defaults'): DEFAULTS_SCHEMA, #dict,
    vol.Optional('tracked'): list,
    vol.Optional('alerts'): list,
    # IF CHANGE these top-level params, update
    #   Alert2Data.init2()
    #   UiMgr.saveTopConfg()
    vol.Optional('skip_internal_errors'): cv.boolean,
    vol.Optional('notifier_startup_grace_secs'): vol.All(vol.Coerce(float), vol.Range(min=0.)),
    vol.Optional('defer_startup_notifications'): vol.Any(cv.boolean, jstringList),
})
