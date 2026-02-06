import ast
import copy
import asyncio
import logging
import types
from aiohttp import web
from typing import Any
import voluptuous as vol
from   homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
from   homeassistant.helpers import template as template_helper
from   homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED
)
from homeassistant.core import callback
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.data_validator import RequestDataValidator
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers.storage import Store
from homeassistant.util.yaml import parse_yaml
import homeassistant.util.dt as dt
from .util import (
    create_task,
    create_background_task,
    cancel_task,
    report,
    DOMAIN,
    gAssertMsg,
    isAlert2Internal
)
from .config import ( TOP_LEVEL_SCHEMA, DEFAULTS_SCHEMA, SINGLE_TRACKED_SCHEMA_PRE_NAME,
                      SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME, SINGLE_TRACKED_SCHEMA,
                      SINGLE_ALERT_SCHEMA_EVENT, SINGLE_ALERT_SCHEMA_CONDITION, THRESHOLD_SCHEMA,
                      GENERATOR_SCHEMA, NO_GENERATOR_SCHEMA, SUPERSEDES_GEN )
from .util import (     GENERATOR_DOMAIN )
from .entities import (notifierTemplateToList, renderResultToList, generatorElemToVars, AlertGenerator, Tracker,
                       processSupersedes, getField, expandDataDict, NotificationReason, entNameFromDN, AlertBase,
                       getPreferredEntityId)
from homeassistant.components.websocket_api import (decorators, async_register_command)
_LOGGER = logging.getLogger(__name__)

def prepLoadTopConfig(uiMgr):
    uiCfg = uiMgr.getRawTopConfig()
    resp = { 'rawYaml': uiMgr._alertData.rawYamlBaseTopConfig,
             'raw':     uiMgr._alertData.rawTopConfig,
             'rawUi': uiCfg }
    return resp

class ManageAlertView(HomeAssistantView):
    def __init__(self, uimgr):
        self.uiMgr = uimgr
    url = "/api/alert2/manageAlert"
    name = "api:alert2:manageAlert"
    @RequestDataValidator(vol.Schema({
        vol.Exclusive('load', 'op'): { vol.Required('uiId'): int },
        vol.Exclusive('delete', 'op'): { vol.Required('uiId'): int },
        vol.Exclusive('validate', 'op'): dict,
        vol.Exclusive('update', 'op'): { vol.Required('uiId'): int, vol.Required('cfg'): dict },
        vol.Exclusive('create', 'op'): dict,
        vol.Exclusive('search', 'op'): { vol.Required('str'): cv.string },
    }, extra=vol.ALLOW_EXTRA))
    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        if 'load' in data: 
            rez = self.uiMgr.loadAlert(data['load']['uiId'])
            return self.json(rez)
        if 'create' in data:
            rez = await self.uiMgr.createAlert(data['create'])
            return self.json(rez)
        if 'delete' in data:
            rez = await self.uiMgr.deleteAlert(data['delete']['uiId'])
            return self.json(rez)
        if 'update' in data:
            rez = await self.uiMgr.updateAlert(data['update']['uiId'], data['update']['cfg'])
            return self.json(rez)
        if 'validate' in data:
            rez = await self.uiMgr.validateAlert(data['validate'])
            if isinstance(rez, str):
                return self.json({ 'error': rez })
            else:
                return self.json({})
        if 'search' in data:
            return self.json({'results': self.uiMgr.search(data['search']['str'])})
        msg = f'{gAssertMsg} unknown manageAlert op "{data}"'
        report(DOMAIN, 'error', msg)
        return self.json({ 'error': msg })
    
class LoadDefaultsView(HomeAssistantView):
    def __init__(self, uimgr):
        self.uiMgr = uimgr
    url = "/api/alert2/loadTopConfig"
    name = "api:alert2:loadTopConfig"
    @RequestDataValidator(vol.Schema({ }, extra=vol.ALLOW_EXTRA)) # For some HA auth stuff i think
    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        resp = prepLoadTopConfig(self.uiMgr)
        return self.json(resp)
class SaveDefaultsView(HomeAssistantView):
    def __init__(self, uimgr):
        self.uiMgr = uimgr
    url = "/api/alert2/saveTopConfig"
    name = "api:alert2:saveTopConfig"
    @RequestDataValidator(vol.Schema({ vol.Required('topConfig'): dict }, extra=vol.ALLOW_EXTRA))
    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        errOrConfig = self.uiMgr.saveTopConfig(data['topConfig'])
        return self.json(errOrConfig)

# Throws HomeAssistantError
# converts raw input txt string to val as if it were coming from YAML, so ready for validation
def prepStrConfigField(fname, tval, doReport=True):
    if fname in [ 'notifier', 'summary_notifier', 'done_notifier', 'reminder_frequency_mins',
                  'throttle_fires_per_mins',
                  'generator', 'defer_startup_notifications' ]:
        if template_helper.is_template_string(tval):
            return tval
        return parse_yaml(tval)
    elif fname in [ 'data' ]:
        tt = tval.strip()
        if len(tt) > 2 and template_helper.is_template_string(tt[0:2]):
            # If data starts with template characters, then it can't parse to a yaml dict.
            # So if it's legal, it must be a template string that should produce a dict.
            return tval
        # data must be a dictionary, so need to parse yaml to get the dict
        return parse_yaml(tval)
    elif fname in [ 'supersedes' ]:
        stripped_tval = tval.strip()
        if stripped_tval.startswith('{%') or stripped_tval.startswith('{{') or stripped_tval.startswith('{#') :
            return tval
        return parse_yaml(tval)
    elif fname in [ 'trigger', 'trigger_on', 'trigger_off', 'exception_ignore_regexes' ]:
        return parse_yaml(tval)
    elif fname in [ 'annotate_messages', 'ack_required', 'manual_off', 'manual_on', 'priority', 'icon', 'friendly_name',
                    'title', 'target', 'domain', 'name', 'message', 'done_message',
                    'ack_reminder_message', 'ack_reminders_only',
                    'condition', 'condition_on', 'condition_off', 'early_start', 'supersede_debounce_secs',
                    'persistent_notifier_grouping',
                    # We have entries for both "threshold." prefixed values
                    # as well as the values without prefix.
                    # Prefix version is used by renderValue
                    # non-prefixed version is used by prepStrConfig
                    'threshold.hysteresis', 'threshold.maximum', 'threshold.minimum', 'threshold.value',
                    'hysteresis', 'maximum', 'minimum', 'value',
                    'delay_on_secs',
                    'generator_name', 'skip_internal_errors', 'notifier_startup_grace_secs' ]:
        # Should not need yaml parsing
        return tval
    elif fname in [ 'display_msg', 'reminder_message' ]:
        stripped_tval = tval.strip()
        if stripped_tval == 'null':
            return parse_yaml(tval)
        return tval
    else:
        msg = f'{gAssertMsg} prepStrConfigField got unrecognized field: "{fname}"'
        if doReport:
            report(DOMAIN, 'error', msg)
        else:
            raise HomeAssistantError(msg)
        return tval
    
dummyTriggerDict = { 'trigger': 'homeassistant', 'event': 'start' }
    
class RenderValueView(HomeAssistantView):
    def __init__(self, uimgr):
        self.uiMgr = uimgr
    url = "/api/alert2/renderValue"
    name = "api:alert2:renderValue"
    @RequestDataValidator(vol.Schema({
        vol.Required('name'): cv.string,
        vol.Required('txt'): cv.string,
        # extraVars can be None if generator is empty (eg [] )
        vol.Optional('extraVars'): vol.Any(None, dict),
    }, extra=vol.ALLOW_EXTRA)) # For some HA auth stuff i think

    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        #_LOGGER.warning(f'Rendervalue: {data["extraVars"]}, {type(data["extraVars"])}')
        ttxt  = data['txt']
        name = data['name']
        extraVars = data['extraVars'] if 'extraVars' in data and data['extraVars'] else {}
        simple = False
        addNotificationVars = False

        try:
            ttxt = prepStrConfigField(name, ttxt)
        except HomeAssistantError as ex:
            return self.json({ 'error': f'YAML parse error: {ex}'})
                
        def generatorListToResult(aList):
            kMaxToReturn = 5
            if len(aList) == 0:
                return {'list': [], 'len':0, 'firstElemVars': None }
            fvars = generatorElemToVars(self.uiMgr._hass, aList[0], 0, None)
            return {'list': aList[:kMaxToReturn], 'len':len(aList), 'firstElemVars': fvars }
            
        try:
            if name in ['notifier','summary_notifier', 'done_notifier']:
                tval = DEFAULTS_SCHEMA({ name: ttxt })[name]
                ttype = 'notifier_list'
                addNotificationVars = True
                if isinstance(tval, bool):
                    simple = True
            elif name in ['exception_ignore_regexes']:
                tval = SINGLE_TRACKED_SCHEMA({ 'domain': 'alert2', 'name': 'global_exception', name: ttxt })[name]
                simple = True
            elif name in ['annotate_messages', 'reminder_frequency_mins', 'throttle_fires_per_mins',
                          'supersede_debounce_secs', 'icon', 'persistent_notifier_grouping']:
                tval = DEFAULTS_SCHEMA({ name: ttxt })[name]
                simple = True
            elif name in ['supersedes']:
                if extraVars:
                    obj = { 'domain': 'foo', 'name': 'bar', 'generator':'f2', 'generator_name': 'f3' }
                    obj[name] = ttxt
                    tval = GENERATOR_SCHEMA(obj)[name]
                    (err, rez) = processSupersedes(tval, extraVars)
                    if err:
                        raise vol.Invalid(err)
                    obj = { 'domain': 'foo', 'name': 'bar' }
                    obj[name] = rez
                    tval = NO_GENERATOR_SCHEMA(obj)[name]
                    #tval = rez
                    simple = True
                else:
                    obj = { 'domain': 'foo', 'name': 'bar' }
                    obj[name] = ttxt
                    tval = NO_GENERATOR_SCHEMA(obj)[name]
                    simple = True
            elif name in ['friendly_name']:
                tval = SINGLE_TRACKED_SCHEMA_PRE_NAME({ name: ttxt })[name]
                ttype = 'string'
            elif name in ['title', 'target']:
                tval = SINGLE_TRACKED_SCHEMA_PRE_NAME({ name: ttxt })[name]
                addNotificationVars = True
                ttype = 'string'
            elif name in ['message', 'done_message', 'reminder_message', 'ack_reminder_message' ]:
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME({ name: ttxt})[name]
                addNotificationVars = True
                ttype = 'string'
            elif name in ['display_msg' ]:
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME({ name: ttxt})[name]
                if tval is None:
                    simple = True
                else:
                    ttype = 'string'
            elif name in ['data']:
                tval = SINGLE_TRACKED_SCHEMA_PRE_NAME({ name: ttxt})[name]
                addNotificationVars = True
                ttype = 'data-dict'
            elif name in ['priority']:
                if extraVars:
                    obj = { 'domain': 'foo', 'name': 'bar', 'generator':'f2', 'generator_name': 'f3' }
                    obj[name] = ttxt
                    tval = GENERATOR_SCHEMA(obj)[name]
                    ttype = 'string'
                else:
                    tval = DEFAULTS_SCHEMA({ name: ttxt })[name]
                    simple = True
            elif name in ['domain', 'name']:
                obj = { 'domain': 'foo', 'name': 'bar', 'generator':'f2', 'generator_name': 'f3' }
                obj[name] = ttxt
                # so for rendering, we're lax and allow templates in case it's in a generator.
                # when we validate/create, it'll get proper validation that restricts template to only
                # when used with a generator
                tval = GENERATOR_SCHEMA(obj)[name]
                ttype = 'string'
                #simple = True
            elif name in ['trigger']:
                obj = { 'domain': 'foo', 'name': 'bar', name: ttxt }
                # Triggers can puke with TypeError :(
                try:
                    tval = SINGLE_ALERT_SCHEMA_EVENT(obj)[name]
                except TypeError as v:
                    return self.json({ 'error': f'parse error: {str(v)}' })
                simple = True
            elif name in ['trigger_on','trigger_off']:
                obj = { name: ttxt }
                # Triggers can puke with TypeError :(
                try:
                    tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME(obj)[name]
                except TypeError as v:
                    return self.json({ 'error': f'parse error: {str(v)}' })
                simple = True
            elif name in ['condition','condition_on','condition_off']:
                #obj = { 'domain': 'foo', 'name': 'bar', 'trigger': dummyTriggerDict, name: ttxt }
                #tval = SINGLE_ALERT_SCHEMA_EVENT(obj)[name]
                obj = { name: ttxt }
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME(obj)[name]
                ttype = 'bool'
            elif name in ['early_start']:
                obj = { 'domain': 'foo', 'name': 'bar', 'trigger': dummyTriggerDict, name: ttxt }
                tval = SINGLE_ALERT_SCHEMA_EVENT(obj)[name]
                simple = True
            elif name in ['manual_on', 'manual_off', 'ack_required', 'ack_reminders_only']:
                obj = { name: ttxt }
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME(obj)[name]
                simple = True
            elif name in ['threshold.value', 'threshold.hysteresis', 'threshold.minimum', 'threshold.maximum']:
                subname = name[10:] # strip "threshold."
                obj = { 'value': 7, 'hysteresis': 3 }
                obj[subname] = ttxt
                tval = THRESHOLD_SCHEMA(obj)[subname]
                if isinstance(tval, float):
                    simple = True
                else:
                    ttype = 'float'
            elif name in ['delay_on_secs']:
                obj = { name: ttxt }
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME(obj)[name]
                if isinstance(tval, float):
                    simple = True
                else:
                    ttype = 'float'
            elif name in ['generator']:
                obj = { 'domain': 'foo', 'name': 'bar', 'generator_name': 'ick', name: ttxt }
                tval = GENERATOR_SCHEMA(obj)[name]
                ttype = 'generator'
                if isinstance(tval, list):
                    tval = generatorListToResult(tval)
                    simple = True
            elif name in ['generator_name']:
                obj = { 'domain': 'foo', 'name': 'bar', 'generator': 'ick', name: ttxt }
                tval = GENERATOR_SCHEMA(obj)[name]
                simple = True
            elif name in ['skip_internal_errors', 'notifier_startup_grace_secs', 'defer_startup_notifications']:
                tval = TOP_LEVEL_SCHEMA({name: ttxt})[name]
                simple = True
            else:
                msg = f'{gAssertMsg} unknown field name "{name}"'
                report(DOMAIN, 'error', msg)
                return self.json({ 'error': msg})
            
        except vol.Invalid as v:
            return self.json({ 'error': f'parse error: {str(v)}' })

        if simple:
            return self.json({ 'rez': tval })
            
        if addNotificationVars:
            fakeEnt = types.SimpleNamespace(extraVariables=extraVars, entity_id='fake_entity_id', alDomain='dom', alName='nam')
            notificationVars = AlertBase.getNotificationVars(fakeEnt, NotificationReason.Fire)
            if name == 'reminder_message':
                notificationVars['get_message'] = lambda : '[ message placeholder ]'
        else:
            notificationVars = extraVars
        
        if ttype == 'notifier_list':
            (notifiers, errors, debugInfo) = notifierTemplateToList(self.uiMgr._hass, notificationVars, tval, 'notifier')
            if errors:
                errStr = ','.join(errors)
                return self.json({ 'error': f'Notifier list error: {errStr}', 'rez': notifiers })
            result = notifiers
        elif ttype in [ 'string', 'bool', 'float', 'generator', 'supersedes' ]:
            if not isinstance(tval, template_helper.Template):
                msg = f'{gAssertMsg} somehow tval for {name} is not a template: tval={tval} type={type(tval)}'
                report(DOMAIN, 'error', msg)
                return self.json({ 'error': f'Server error: {msg}' })
            try:
                aresult = tval.async_render(parse_result=False, variables=notificationVars)
            except TemplateError as err:
                return self.json({ 'error': f'render error: {str(err)}' })
            if ttype in ['string']:
                result = aresult
            elif ttype == 'bool':
                try:
                    abool = cv.boolean(aresult)
                except vol.Invalid as err:
                    return self.json({ 'error': f'not truthy (e.g., "true", "on" or opposites): "{aresult}"'})
                result = abool
            elif ttype == 'float':
                try:
                    afloat = float(aresult)
                except ValueError:
                    return self.json({ 'error': f'not a float: "{aresult}"'})
                result = afloat
            elif ttype in ['generator']:
                aList = renderResultToList(aresult)
                #_LOGGER.warning(f'generator {aresult} -> {aList}, {type(aList)}')
                result = generatorListToResult(aList)
            elif ttype in ['supersedes']:
                try:
                    result = ast.literal_eval(aresult)
                except Exception as ex:  # literal_eval can throw various kinds of exceptions
                    return self.json({ 'error': f'eval of template failed: "{aresult}" produced {ex}'})
                    
        elif ttype in [ 'data-dict' ]:
            # data may contain multiple templates. Also, it needs to merge in defaults
            defaults = self.uiMgr._alertData.topConfig # from
            mergedVal = getField(name, { 'domain':'foo', 'name':'bar', name: tval }, defaults)
            try:
                result = expandDataDict(mergedVal, notificationVars)
            except HomeAssistantError as err:
                return self.json({ 'error': f'data template {err}'})
        else:
            msg = f'{gAssertMsg} validate unknown ttype={ttype} for name={name}'
            report(DOMAIN, 'error', msg)
            return self.json({ 'error': msg})
        return self.json({ 'rez': result })

# strips all values. removes empty string keys, but leaves empty dicts
def removeEmpty(adict):
    keys = list(adict.keys())
    for key in keys:
        if isinstance(adict[key], str):
            adict[key] = adict[key].strip()
            if adict[key]:
                pass # key stays
            else:
                del adict[key]
        elif isinstance(adict[key], dict):
            removeEmpty(adict[key])
        else:
            raise vol.Invalid(f'key "{key}" has non-string value "{adict[key]}" of type {type(adict[key])}')
# report - either report or raise on error
def prepStrConfig(adict, doReport=True):
    newDict = {}
    keys = adict.keys()
    for key in keys:
        if isinstance(adict[key], str):
            newDict[key] = prepStrConfigField(key, adict[key], doReport=doReport)
        elif isinstance(adict[key], dict):
            newDict[key] = prepStrConfig(adict[key])
        elif key == 'alerts' and isinstance(adict[key], list):
            # We're processing a whole alert2 config, not just the config of a single alert
            newDict[key] = [ prepStrConfig(x) for x in adict[key] ]
        elif key == 'tracked' and isinstance(adict[key], list):
            # We're processing a whole alert2 config, not just the config of a single alert
            newDict[key] = [ prepStrConfig(x) for x in adict[key] ]
        else:
            if doReport:
                msg = f'somehow key "{key}" has non-string val "{adict[key]}" of type "{type(adict[key])}" in dict {adict}'
                report(DOMAIN, 'error', msg)
            else:
                raise vol.Invalid(msg)
            return newDict
    return newDict
# Throws vol.Invalid
def prepForValidation(acfg):
    # filter out empty fields recursively
    removeEmpty(acfg)
    # Does yaml processing to convert the pure string config to one ready for validation
    try:
        preppedConfig = prepStrConfig(acfg)
    except HomeAssistantError as ex:
        raise vol.Invalid(str(ex)) from ex
    return preppedConfig


def debounce(hass, waitSecs, function):
    def debounced(*args, **kwargs):
        async def call_function():
            await asyncio.sleep(waitSecs)
            debounced._timerTask = None
            return function(*args, **kwargs)
        if debounced._timerTask is not None:
            cancel_task(DOMAIN, debounced._timerTask)
        debounced._timerTask = create_background_task(hass, DOMAIN, call_function())
    debounced._timerTask = None
    return debounced

# Purpose is to support the UI watching for updates to the display_msg template.
class DisplayMsgSocketMgr:
    def __init__(self, hass, alertData):
        self.hass = hass
        self.alertData = alertData
        self.allSubscriptions = {} # indexed by domain/name
        async_register_command(hass, self.async_handle_msg)
        
    def shutdown(self):
        #_LOGGER.warning(f'DisplayMsgSocketMgr shutting down all subscriptions')
        for ad in self.allSubscriptions:
            for an in self.allSubscriptions[ad]:
                for asub in self.allSubscriptions[ad][an]:
                    asub['tracker'].shutdown()
        self.allSubscriptions = {}

    def reloadSingleIfExists(self, domain, name):
        #_LOGGER.warning(f'reloadSingleIfExists {domain} {name}')
        self.hass.verify_event_loop_thread(f'checking loop thread in DisplayMsgSocketMgr::reloadSingleIfExists')
        if domain in self.allSubscriptions and name in self.allSubscriptions[domain]:
            #_LOGGER.warning(f'reloadSingleIfExists found allSubscriptions for {domain} {name} ')
            for asub in self.allSubscriptions[domain][name]:
                asub['tracker'].shutdown()
            newDisplayTemplate = None
            ent = None
            if domain in self.alertData.alerts and name in self.alertData.alerts[domain]:
                ent = self.alertData.alerts[domain][name]
            elif domain in self.alertData.tracked and name in self.alertData.tracked[domain]:
                ent = self.alertData.tracked[domain][name]
            if ent:
                newDisplayTemplate = ent._display_msg_template
                if newDisplayTemplate:
                    for subIdx in range(len(self.allSubscriptions[domain][name])):
                        asub = self.allSubscriptions[domain][name][subIdx]
                        #_LOGGER.warning(f'reloadSingleIfExists recreating tracker for {domain} {name} ')
                        self.async_handle_msg2(asub['connection'], ent, asub['subscribeMsg'], updateIdx=subIdx)
            if not newDisplayTemplate:
                # If config no longer has a diplay message, we delete subscriptions to it.
                # The new entity will have has_display_msg set to False, which will cause
                # the front end to unsubscribe from its end.
                # So then if later, the display_msg appears again, the front end will see has_display_msg
                # turn to true and will re-subscribe
                for asub in self.allSubscriptions[domain][name]:
                    # Don't need to send anything here, but seems like could be useful for diagnostics
                    asub['connection'].send_error(asub['subscribeMsg']['id'], 'no_display_msg', f'Recreate of entity domain={domain} name={name} does not specify display_msg')
                del self.allSubscriptions[domain][name]
                if not self.allSubscriptions[domain]:
                    del self.allSubscriptions[domain]
    
    # Command to watch display_msg for a single alert entity
    @callback
    @decorators.websocket_command(
        {
            vol.Required("type"): 'alert2_watch_display_msg',
            vol.Required('domain'): cv.string,
            vol.Required('name'): cv.string,
        }
    )
    #@decorators.async_response
    #async def async_handle_msg(self, hass, connection, msg):
    def async_handle_msg(self, hass, connection, subscribeMsg):
        self.hass.verify_event_loop_thread(f'checking loop thread in DisplayMsgSocketMgr::async_handle_msg')
        #_LOGGER.warning(f'got watch message {subscribeMsg}')
        if hass != self.hass:
            report(DOMAIN, 'error', f'{gAssertMsg} in DisplayMsgSocketMgr, two "hass" variables are not identical')
        domain = subscribeMsg['domain']
        name = subscribeMsg['name']
        msgId = subscribeMsg['id']

        ent = None
        if domain in self.alertData.alerts and name in self.alertData.alerts[domain]:
            ent = self.alertData.alerts[domain][name]
        elif domain in self.alertData.tracked and name in self.alertData.tracked[domain]:
            ent = self.alertData.tracked[domain][name]
        if not ent:
            connection.send_error(msgId, 'ent_not_found', f'No entity found with domain={domain} and name={name}')
            return
        if not ent._display_msg_template:
            connection.send_error(msgId, 'no_display_msg', f'Entity config for {ent.entity_id} does not specify display_msg')
            return
        self.async_handle_msg2(connection, ent, subscribeMsg)
        connection.send_result(msgId)

    def async_handle_msg2(self, connection, ent, subscribeMsg, updateIdx=None):
        domain = subscribeMsg['domain']
        name = subscribeMsg['name']
        msgId = subscribeMsg['id']
        tracker = None
        def handle_rez(results):
            if len(results) != 1:
                report(DOMAIN, 'error', f'{gAssertMsg} {ent.entity_id} display_msg change tracker got result len={len(results)} results={results}')
                return
            _LOGGER.debug(f'{ent.entity_id} for tracker {id(tracker)} sending event for id {msgId}: {results[0]}')
            connection.send_message({ "id": msgId,
                                      "type": "event",
                                      "event": {  # data to pass with event
                                          'rendered': results[0]
                                      }, } )

        tracker = Tracker(ent, 'display_msg', self.hass, self.alertData,
                          [ { 'fieldName': 'display_msg', 'type': Tracker.Type.StrEmptyOk,
                              'template': ent._display_msg_template } ], handle_rez, extraVariables=ent.extraVariables)
        #_LOGGER.warning(f'{ent.entity_id}: got subscribe msg {msgId} for tracker {id(tracker)}')
        if ent.earlyStart or self.alertData.haStarted:
            tracker.startWatching()
        else:
            async def doStart(ev): # async so that we're called in event loop thread
                #self.hass.verify_event_loop_thread(f'checking loop thread in DisplayMsgSocketMgr::doStart')
                tracker.startWatching()
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, doStart)
        subscriptionEntry = {'tracker':tracker, 'connection': connection, 'subscribeMsg': subscribeMsg }
        if updateIdx is None:
            if not domain in self.allSubscriptions:
                self.allSubscriptions[domain] = {}
            if not name in self.allSubscriptions[domain]:
                self.allSubscriptions[domain][name] = []
            self.allSubscriptions[domain][name].append(subscriptionEntry)
        else:
            self.allSubscriptions[domain][name][updateIdx] = subscriptionEntry
        
        def unsubscribe():
            self.hass.verify_event_loop_thread(f'checking loop thread in DisplayMsgSocketMgr::unsubscribe')
            if domain in self.allSubscriptions and name in self.allSubscriptions[domain]:
                subs = self.allSubscriptions[domain][name]
                idx = next((i for i, item in enumerate(subs) if item['tracker'] is tracker), -1)
                if idx == -1:
                    _LOGGER.warning(f'{domain} {name} display_msg unsubscribe called, msgId={msgId} but no subscription found for tracker')
                else:
                    del subs[idx]
                    if not subs:
                        del self.allSubscriptions[domain][name]
                    if not self.allSubscriptions[domain]:
                        del self.allSubscriptions[domain]
        connection.subscriptions[msgId] = unsubscribe
        return subscriptionEntry


# Guess name, may be inaccurate
def getAlertName(ainfo):
    if ainfo['ent']:
        return ainfo['ent'].entity_id
    acfg = ainfo['info']['cfg']
    if 'generator_name' in acfg:
        domain = GENERATOR_DOMAIN
        name = acfg['generator_name']
    elif 'generator' in acfg:
        domain = GENERATOR_DOMAIN
        name = 'anonymous-generator'
    else:
        domain = acfg['domain'] if 'domain' in acfg else '[missing domain]'
        name = acfg['name'] if 'name' in acfg else '[missing name]'
    return f'domain={domain} name={name}'


STORAGE_SCHEMA = vol.Schema({
    vol.Required('nextAlertUiId'): int,
    vol.Required('defaults'): dict,
    vol.Required('alertInfos'): list,
    vol.Required('topLevelOptions'): dict,
    vol.Required('oneTime'): dict })
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 2
SAVE_DELAY = 10
# Looks like Store handles writing before HA shuts down if there are outstanding writes
# "data" is a dict de-serialized from JSON
class MigratableStore(Store):
    async def _async_migrate_func(self, old_version, data: dict):
        _LOGGER.warning(f'_async_migrate_func {old_version} from {data}')
        if old_version == 1:
            # Storage was { 'config': { defaults, alerts, tracked } }
            # Now we switch to
            #   { nextAlertUiId,
            #     defaults
            #     alertInfos: [ { alert_ui_id, cfg } ]
            #   }
            nextUiId = 1
            alertInfos = []
            topLevelOptions = {}
            defaults = {}
            oneTime = {}
            if data is not None and isinstance(data, dict):
                if 'config' in data and isinstance(data['config'], dict):
                    if 'alerts' in data['config']:
                        for acfg in data['config']['alerts']:
                            alertInfos.append({ 'uiId': nextUiId, 'cfg': copy.deepcopy(acfg) })
                            nextUiId += 1
                    if 'defaults' in data['config']:
                        defaults = data['config']['defaults']
                    for fname in [ 'skip_internal_errors', 'notifier_startup_grace_secs', 'defer_startup_notifications' ]:
                        if fname in data['config']:
                            topLevelOptions[fname] = data['config'][fname]
                if 'oneTime' in data:
                    oneTime = data['oneTime']
            newData = { 'nextAlertUiId': nextUiId,
                        'defaults': defaults,
                        'alertInfos': alertInfos,
                        'topLevelOptions': topLevelOptions,
                        'oneTime': oneTime,
                       }
            _LOGGER.warning(f'newData is {newData}')
            try:
                STORAGE_SCHEMA(newData)
            except vol.Invalid as ex:
                errMsg = f'migration in alert2 produced invalid schema: {ex} from {newData}'
                _LOGGER.error(errMsg)
                raise Exception(errMsg)
            #_LOGGER.info(f'alertInfos = {alertInfos}')
            return newData
        else:
            assert old_version == 2, f'{gAssertMsg} UI alert store has unexpected version {old_version}'
            assert isinstance(data, dict)
            return data

# Alert2 internal alerts (eg error, warning, etc) are declared in __init__.py.  In the UI, the entries modifying them
# do not result in actual entities, since those ents already exist via __init__.
# So instead we create a fake ent with just a bit of bookkeeping fields
class InternalAlertPlaceholder(Entity):
    def __init__(self, domain, name):
        super().__init__()
        self.alDomain = domain
        self.alName = name
        self.entity_id = getPreferredEntityId(domain, name)
        
class UiMgr:
    def __init__(self, hass, alertData):
        self._hass = hass
        self._alertData = alertData
        self.views = []
        for av in [ RenderValueView, LoadDefaultsView, SaveDefaultsView, ManageAlertView ]:
            aview = av(self)
            self.views.append(aview)
            hass.http.register_view(aview)
        self._store = MigratableStore(hass, STORAGE_VERSION, STORAGE_KEY)
        self.storeData = None
        self.storeFatalErr = False
        self.alerts = [] # { ent (may be None), info }
        self.displayMsgWsMgr = DisplayMsgSocketMgr(hass, alertData)
        
    async def startup(self):
        # Store handles the case where there may be a write pending
        self.storeData = None # reset in case load throw exception
        try:
            self.storeData = await self._store.async_load()
        except Exception as ex:
            return str(ex)
        defaultData = { 'nextAlertUiId': 1,
                        'defaults': {},
                        'alertInfos': [],
                        'topLevelOptions': {},
                        'oneTime': {} }
        if self.storeData is None:
            self.storeData = defaultData
        try:
            STORAGE_SCHEMA(self.storeData)
        except vol.Invalid as ex:
            self.storeFatalErr = True
            errMsg = f'UI loaded bad storage: {ex} from {self.storeData} ... {type(self.storeData)}'
            self.storeData = defaultData
            return errMsg
        self.alerts = [ {'ent': None, 'info': xx } for xx in self.storeData['alertInfos'] ]
        if self.storeData['alertInfos']:
            uids = [ aa['uiId'] for aa in self.storeData['alertInfos'] ]
            maxUid = max(uids)
            if maxUid >= self.storeData['nextAlertUiId']:
                report(DOMAIN, 'error', f'{gAssertMsg} ui load maxUid={maxUid} but nextAlertUiId={self.storeData["nextAlertUiId"]}')
                self.storeData['nextAlertUiId'] = maxUid + 1
            if len(uids) != len(set(uids)):
                report(DOMAIN, 'error', f'{gAssertMsg} ui load appears to be duplicate uiId: {uids}')
        return None
        
    def shutdown(self):
        #create_task(self._hass, DOMAIN, self.async_shutdown())
        self.displayMsgWsMgr.shutdown()
    #async def async_shutdown(self):
        #for aview in self.views:
        #    await aview.shutdown()

    def uiAlertAlreadyExists(self, acfg):
        if 'generator' in acfg and 'generator_name' not in acfg:
            return None # anonymous generator, no way to tell if existing ones match or not
        for ali in self.alerts:
            tcfg = ali['info']['cfg']
            if 'generator_name' in acfg:
                if 'generator_name' in tcfg and tcfg['generator_name'] == acfg['generator_name']:
                    return f'generator {acfg["generator_name"]}'
            else: # not a generator
                if acfg['domain'] == tcfg['domain'] and acfg['name'] == tcfg['name']:
                    return f'domain={acfg["domain"]} name={acfg["name"]}'
        return None
        
    def getEarlyInternalRawConfig(self, internalType):
        for ae in self.storeData['alertInfos']:
            obj = ae['cfg']
            # can raise HomeAssistantError
            pobj = prepStrConfig(obj, doReport=False)
            if pobj['domain'] == DOMAIN and pobj['name'] == internalType:
                return pobj
        return None
        
    def getRawTopConfig(self):
        cfg = { 'defaults': self.storeData['defaults'] }
        cfg.update(self.storeData['topLevelOptions'])
        return cfg
    def getPreppedConfig(self):
        alerts = []
        tracked = []
        for ae in self.storeData['alertInfos']:
            cfg = ae['cfg']
            isTracked = isAlert2Internal(cfg)
            if isTracked:
                tracked.append(cfg)
            else:
                alerts.append(cfg)
        cfg = { 'defaults': self.storeData['defaults'], 'alerts': alerts, 'tracked': tracked }
        cfg.update(self.storeData['topLevelOptions'])
        try:
            preppedConfig = prepStrConfig(cfg)
        except HomeAssistantError as ex:
            msg = f'{gAssertMsg} getPreppedConfig failed from {cfg}: {ex}'
            report(DOMAIN, 'error', msg)
            return None
        return preppedConfig

    async def declareAlerts(self):
        numSuccess = 0
        for ali in self.alerts:
            preppedConfig = await self.validateAlert(ali['info']['cfg'])
            if isinstance(preppedConfig, str):
                report(DOMAIN, 'error', preppedConfig)
                newEnt = None
            else:
                if isAlert2Internal(preppedConfig):
                    # Alert already declared in __init__, so just report validation errors here
                    newEnt = await self.declareInternalAlert(preppedConfig)
                else:
                    newEnt = await self._alertData.declareAlert(preppedConfig, fromUI=True)
            if isinstance(newEnt, Entity):
                ali['ent'] = newEnt
                numSuccess += 1
            else:
                ali['ent'] = None
        
        _LOGGER.info(f'Lifecycle created {numSuccess} alerts from UI config')
        
    def saveTopConfig(self, topConfig):
        if self.storeFatalErr:
            return {'error': f'UI data store failed to load. Preventing updates to avoid overwriting' }
        try:
            preppedConfig = prepForValidation(topConfig)
        except vol.Invalid as v:
            _LOGGER.warning(f'saveTopConfig validation failed of {topConfig}: {v}')
            return { 'error': f'data check failed: {v}' }
        
        try:
            TOP_LEVEL_SCHEMA(preppedConfig)
        except vol.Invalid as v:
            _LOGGER.warning(f'saveTopConfig validation failed of {topConfig}: {v}')
            return { 'error': f'validation failed: {v}' }

        if 'defaults' in topConfig:
            self.storeData['defaults'] = topConfig['defaults']
        else:
            self.storeData['defaults'] = {}
        for fname in [ 'skip_internal_errors', 'notifier_startup_grace_secs', 'defer_startup_notifications' ]:
            if fname in topConfig:
                self.storeData['topLevelOptions'][fname] = topConfig[fname]
            elif fname in self.storeData['topLevelOptions']:
                del self.storeData['topLevelOptions'][fname]
                
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        self._alertData.noteUiUpdate()
        return prepLoadTopConfig(self)
    
    async def declareInternalAlert(self, preppedConfig, doReport=True):
        # Check validation
        rez = await self._alertData.declareAlert(preppedConfig, doReport=doReport, checkForUpdate=True, isTracked=True, fromUI=True)
        if rez != True:
            return rez # is errMsg
        newEnt = InternalAlertPlaceholder(preppedConfig['domain'], preppedConfig['name'])
        _LOGGER.info(f'Lifecycle created tracked alert {newEnt.entity_id} via UI')
        return newEnt
    
    def loadAlert(self, uiId):
        for info in self.storeData['alertInfos']:
            if info['uiId'] == uiId:
                return info['cfg']
        return { 'error': 'alert not found' }

    # Returns str on error, or preppedConfig
    async def validateAlert(self, acfg):
        try:
            preppedConfig = prepForValidation(acfg)
        except vol.Invalid as v:
            return f'data check failed: {v}'

        isTracked = isAlert2Internal(preppedConfig)
        rez = await self._alertData.declareAlert(preppedConfig, doReport=False, isTracked=isTracked, checkForUpdate=True)
        if rez != True:
            return rez # string
        return preppedConfig
    
    def alertCreated(self, domain, name):
        self.displayMsgWsMgr.reloadSingleIfExists(domain, name)
    
    async def createAlert(self, acfg):
        if self.storeFatalErr:
            return {'error': f'UI data store failed to load. Preventing updates to avoid overwriting' }
        preppedConfig = await self.validateAlert(acfg)
        if isinstance(preppedConfig, str):
            return { 'error': preppedConfig }

        existingName = self.uiAlertAlreadyExists(preppedConfig)
        if existingName is not None:
            return { 'error': f'UI alert already exists: {existingName}' }
        
        if isAlert2Internal(preppedConfig):
            newEnt = await self.declareInternalAlert(preppedConfig, doReport=False)
        else:
            newEnt = await self._alertData.declareAlert(preppedConfig, doReport=False, fromUI=True)
        if not isinstance(newEnt, Entity):
            return {'error': newEnt}

        newInfo = { 'uiId': self.storeData['nextAlertUiId'], 'cfg': acfg }
        self.storeData['alertInfos'].append(newInfo)
        self.storeData['nextAlertUiId'] += 1
        self.alerts.append({ 'ent': newEnt, 'info': newInfo })
        
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return { 'uiId': newInfo['uiId'] }

    async def deleteAlertInt(self, uiId, verb):
        if self.storeFatalErr:
            return {'error': f'UI data store failed to load. Preventing updates to avoid overwriting' }
        storeIdx = next((i for i, item in enumerate(self.storeData['alertInfos']) if (item['uiId'] == uiId)), -1)
        if storeIdx == -1:
            return (None, None, f'UI-created alert does not exist - can\'t {verb}')
        listIdx = next((i for i, item in enumerate(self.alerts) if (item['info']['uiId'] == uiId)), -1)
        if listIdx == -1:
            errMsg = f'{gAssertMsg} Alert uiId={uiId} exists in store but not in alert list during {verb}'
            _LOGGER.error(errMsg)
            return (None, None, errMsg)

        ent = self.alerts[listIdx]['ent']
        if ent is not None and not isinstance(ent, InternalAlertPlaceholder): # If alert was loaded
            _LOGGER.info('undeclaring alert')
            rez = await self._alertData.undeclareAlert(ent.alDomain, ent.alName, doReport=False, removeFromRegistry=True)
            if rez is not None:
                errMsg = f'{gAssertMsg} in {verb}: uiId={uiId} domain={ent.alDomain} name={ent.alName} found in UI, but undeclareAlert failed'
                _LOGGER.error(errMsg)
                return (None, None, errMsg)
        return (storeIdx, listIdx, None)
    
    async def updateAlert(self, uiId, acfg):
        if self.storeFatalErr:
            return {'error': f'UI data store failed to load. Preventing updates to avoid overwriting' }
        # Validate alert before call undeclareAlert so hopefully won't end up returning an error
        # with no alert left over
        preppedConfig = await self.validateAlert(acfg)
        if isinstance(preppedConfig, str):
            return { 'error': preppedConfig }

        (storeIdx, listIdx, errMsg) = await self.deleteAlertInt(uiId, 'update')
        if errMsg:
            return {'error': errMsg}
        
        if isAlert2Internal(preppedConfig):
            newEnt = await self.declareInternalAlert(preppedConfig, doReport=False)
        else:
            newEnt = await self._alertData.declareAlert(preppedConfig, doReport=False, fromUI=True)

        # When updating a generator, we may be changing the set of alerts generated.
        # This could leave orphan entity registry entries.
        self._alertData.delayGcRegistry()

        if not isinstance(newEnt, Entity):
            return {'error': newEnt}

        _LOGGER.info(f'Lifecycle updated alert {newEnt.entity_id} via UI')
        self.storeData['alertInfos'][storeIdx]['cfg'] = acfg
        self.alerts[listIdx]['ent'] = newEnt
        
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return {}

    async def deleteAlert(self, uiId):
        if self.storeFatalErr:
            return {'error': f'UI data store failed to load. Preventing updates to avoid overwriting' }
        (storeIdx, listIdx, errMsg) = await self.deleteAlertInt(uiId, 'delete')
        if errMsg:
            return {'error': errMsg}

        ename = getAlertName(self.alerts[listIdx])
        del self.storeData['alertInfos'][storeIdx]
        del self.alerts[listIdx]
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        _LOGGER.info(f'Lifecycle deleted alert {ename} via UI')
        return {}

    def _data_to_save(self):
        if self.storeFatalErr:
            raise Exception('UI data store failed to load. Preventing updates to avoid overwriting')
        return self.storeData

    def search(self, sTxt):
        terms = sTxt.lower().split()
        results = []
        for ainfo in self.alerts:
            acfg = ainfo['info']['cfg']
            #aname = getAlertName(ainfo)
            ent = ainfo['ent']
            if ent == None:
                # Ent falied to load
                testEntId = getPreferredEntityId(acfg['domain'], acfg['name']).lower()
            #elif ent.entity_id == None:
            #    if not isinstance(ent, AlertGenerator): # must be anonymous generator
            #        report(DOMAIN, 'error', f'{gAssertMsg} in search, ent of class {ent.__class__} missing entity_id')
            #    testEntId = getPreferredEntityId(ent.alDomain, ent.alName)
            else:
                testEntId = ent.entity_id.lower()
            
            ok = True
            for term in terms:
                if term not in testEntId:
                    ok = False
                    break
            if ok:
                if ent == None:
                    results.append({ 'uiId': ainfo['info']['uiId'], 'id': testEntId, 'domain': acfg['domain'], 'name': acfg['name'], 'failedToLoad': True })
                else:
                    results.append({ 'uiId': ainfo['info']['uiId'], 'id': testEntId, 'domain': ent.alDomain, 'name': ent.alName })
        return results

    def setOneTime(self, akey):
        if akey in self.storeData['oneTime']:
            return False
        self.storeData['oneTime'][akey] = dt.now().isoformat()
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return True
