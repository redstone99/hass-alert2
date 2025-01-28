import logging
from aiohttp import web
from typing import Any
import voluptuous as vol
from   homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
from   homeassistant.helpers import template as template_helper
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.data_validator import RequestDataValidator
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util.yaml import parse_yaml
from .util import (
    create_task,
    cancel_task,
    report,
    DOMAIN,
    gAssertMsg
)
from .config import ( TOP_LEVEL_SCHEMA, DEFAULTS_SCHEMA, SINGLE_TRACKED_SCHEMA_PRE_NAME,
                      SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME, SINGLE_TRACKED_SCHEMA,
                      SINGLE_ALERT_SCHEMA_EVENT, SINGLE_ALERT_SCHEMA_CONDITION, THRESHOLD_SCHEMA,
                      GENERATOR_SCHEMA )
from .util import (     GENERATOR_DOMAIN )
from .entities import (notifierTemplateToList, renderResultToList, generatorElemToVars, AlertGenerator)
_LOGGER = logging.getLogger(__name__)

def prepLoadTopConfig(uiMgr):
    # Extract dict with just top config keys from data
    rawUiTopConfig = {key: uiMgr.data['config'][key]
                      for key in uiMgr._alertData.rawYamlBaseTopConfig.keys() if key in uiMgr.data['config'] }
    resp = { 'rawYaml': uiMgr._alertData.rawYamlBaseTopConfig,
             'raw':     uiMgr._alertData.rawTopConfig,
             'rawUi': rawUiTopConfig }
    return resp

class ManageAlertView(HomeAssistantView):
    def __init__(self, uimgr):
        self.uiMgr = uimgr
    url = "/api/alert2/manageAlert"
    name = "api:alert2:manageAlert"
    @RequestDataValidator(vol.Schema({
        vol.Exclusive('load', 'op'): { vol.Required('domain'): cv.string, vol.Required('name'): cv.string },
        vol.Exclusive('delete', 'op'): { vol.Required('domain'): cv.string, vol.Required('name'): cv.string },
        vol.Exclusive('validate', 'op'): dict,
        vol.Exclusive('update', 'op'): vol.Schema({ vol.Required('domain'): cv.string, vol.Required('name'): cv.string }, extra=vol.ALLOW_EXTRA),
        vol.Exclusive('create', 'op'): dict,
        vol.Exclusive('search', 'op'): { vol.Required('str'): cv.string },
    }, extra=vol.ALLOW_EXTRA))
    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        if 'load' in data: 
            rez = self.uiMgr.loadAlert(data['load']['domain'], data['load']['name'])
            #_LOGGER.warning(f'load of {data["load"]} produced {rez}')
            return self.json(rez)
        if 'create' in data:
            rez = await self.uiMgr.createAlert(data['create'])
            return self.json(rez)
        if 'delete' in data:
            rez = await self.uiMgr.deleteAlert(data['delete']['domain'], data['delete']['name'])
            return self.json(rez)
        if 'update' in data:
            rez = await self.uiMgr.updateAlert(data['update'])
            return self.json(rez)
        if 'validate' in data:
            rez = await self.uiMgr.validateAlert(data['validate'])
            return self.json(rez)
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
def prepStrConfigField(fname, tval):
    parseYaml = True
    if fname == 'trigger':
        pass # Always yaml eval, even if has template chars
    elif template_helper.is_template_string(tval):
        return tval
    #    parseYaml = True
    val = tval
    if parseYaml:
        val = parse_yaml(tval)
    return val
    
dummyTriggerDict = { 'trigger': 'homeassistant', 'event': 'start' }
    
class RenderValueView(HomeAssistantView):
    def __init__(self, uimgr):
        self.uiMgr = uimgr
    url = "/api/alert2/renderValue"
    name = "api:alert2:renderValue"
    @RequestDataValidator(vol.Schema({
            vol.Required('name'): cv.string,
            vol.Required('txt'): cv.string,
            vol.Optional('extraVars'): dict,
        }, extra=vol.ALLOW_EXTRA)) # For some HA auth stuff i think

    async def post(self, request: web.Request, data: dict[str, Any]) -> web.Response:
        #_LOGGER.warning("Got get request with %s", data)
        ttxt  = data['txt']
        name = data['name']
        extraVars = data['extraVars'] if 'extraVars' in data and data['extraVars'] else {}
        simple = False

        if False:
            # Do we need to first parse some yaml
            #
            parseYaml = False
            if name in [ 'generator' ]:
                # It can be either a list, or template, but not both.
                parseYaml = not template_helper.is_template_string(ttxt)
            elif name in ['data', 'trigger', 'throttle_fires_per_mins', 'defer_startup_notifications']:
                # may need to first parse yaml
                parseYaml = True
            if parseYaml:
                try:
                    ttxt = parse_yaml(ttxt)
                except HomeAssistantError as ex:
                    return self.json({ 'error': f'YAML parse error: {ex}'})
        try:
            ttxt = prepStrConfigField(name, ttxt)
        except HomeAssistantError as ex:
            return self.json({ 'error': f'YAML parse error: {ex}'})
                
        def generatorListToResult(aList):
            kMaxToReturn = 5
            #_LOGGER.warning(f'  so render got list: {aList}')
            if len(aList) == 0:
                return {'list': [], 'len':0, 'firstElemVars': None }
            fvars = generatorElemToVars(self.uiMgr._hass, aList[0])
            return {'list': aList[:kMaxToReturn], 'len':len(aList), 'firstElemVars': fvars }
            
        #_LOGGER.warning(f'in render ttxt={ttxt} for name={name}')
        try:
            if name in ['notifier','summary_notifier']:
                tval = DEFAULTS_SCHEMA({ name: ttxt })[name]
                ttype = 'notifier_list'
                if isinstance(tval, bool):
                    simple = True
            elif name in ['annotate_messages', 'reminder_frequency_mins', 'throttle_fires_per_mins']:
                tval = DEFAULTS_SCHEMA({ name: ttxt })[name]
                simple = True
            elif name in ['friendly_name', 'title', 'target']:
                tval = SINGLE_TRACKED_SCHEMA_PRE_NAME({ name: ttxt })[name]
                ttype = 'string'
            elif name in ['message', 'done_message']:
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME({ name: ttxt})[name]
                ttype = 'string'
            elif name in ['data']:
                tval = SINGLE_TRACKED_SCHEMA_PRE_NAME({ name: ttxt})[name]
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
            elif name in ['condition']:
                obj = { 'domain': 'foo', 'name': 'bar', 'trigger': dummyTriggerDict, name: ttxt }
                tval = SINGLE_ALERT_SCHEMA_EVENT(obj)[name]
                ttype = 'bool'
            elif name in ['early_start']:
                obj = { 'domain': 'foo', 'name': 'bar', 'trigger': dummyTriggerDict, name: ttxt }
                tval = SINGLE_ALERT_SCHEMA_EVENT(obj)[name]
                simple = True
            elif name in ['threshold.value']:
                obj = { 'value': ttxt, 'hysteresis': 3 }
                tval = THRESHOLD_SCHEMA(obj)['value']
                ttype = 'float'
            elif name in ['threshold.hysteresis', 'threshold.minimum', 'threshold.maximum']:
                subname = name[10:] # strip "threshold."
                obj = { 'value': 7, 'hysteresis': 3 }
                obj[subname] = ttxt
                tval = THRESHOLD_SCHEMA(obj)[subname]
                simple = True
            elif name in ['delay_on_secs']:
                tval = SINGLE_ALERT_SCHEMA_CONDITION_PRE_NAME({ name: ttxt })[name]
                simple = True
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
            

        
        if ttype == 'notifier_list':
            (notifiers, errors, debugInfo) = notifierTemplateToList(self.uiMgr._hass, None, tval, 'notifier')
            if errors:
                errStr = ','.join(errors)
                return self.json({ 'error': f'Notifier list error: {errStr}', 'rez': notifiers })
            result = notifiers
        elif ttype in [ 'string', 'bool', 'float', 'generator' ]:
            #_LOGGER.warning(f'rendering with extraVars={extraVars}')
            if not isinstance(tval, template_helper.Template):
                msg = f'{gAssertMsg} somehow tval for {name} is not a template: {tval} {type(tval)}'
                report(DOMAIN, 'error', msg)
                return self.json({ 'error': f'Server error: {msg}' })
            try:
                aresult = tval.async_render(parse_result=False, variables=extraVars)
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
                result = generatorListToResult(aList)
        else:
            msg = f'{gAssertMsg} validate unknown ttype={ttype} for name={name}'
            report(DOMAIN, 'error', msg)
            return self.json({ 'error': msg})
        return self.json({ 'rez': result })

STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1
SAVE_DELAY = 10
# Looks like Store handles writing before HA shuts down if there are outstanding writes
# "data" is a dict de-serialized from JSON
class MigratableStore(Store):
    async def _async_migrate_func(self, old_version, data: dict):
        return data
# stips all values. removes empty string keys, but leaves empty dicts
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
def prepStrConfig(adict):
    newDict = {}
    keys = adict.keys()
    for key in keys:
        if isinstance(adict[key], str):
            newDict[key] = prepStrConfigField(key, adict[key])
        elif isinstance(adict[key], dict):
            newDict[key] = prepStrConfig(adict[key])
        elif key == 'alerts' and isinstance(adict[key], list):
            # We're processing a whole alert2 config, not just the config of a single alert
            newDict[key] = [ prepStrConfig(x) for x in adict[key] ]
        else:
            report(DOMAIN, 'error', f'somehow key "{key}" has non-string val "{adict[key]}" of type "{type(adict[key])}" in dict {adict}')
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
    
class UiMgr:
    def __init__(self, hass, alertData):
        #_LOGGER.warning('UiMgr initing')
        self._hass = hass
        self._alertData = alertData
        self.views = []
        for av in [ RenderValueView, LoadDefaultsView, SaveDefaultsView, ManageAlertView ]:
            aview = av(self)
            self.views.append(aview)
            hass.http.register_view(aview)
        self._store = MigratableStore(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data = None
        self.entities = []
        
    async def startup(self):
        # Store handles the case where there may be a write pending
        self.data = None # reset in case load throw exception
        self.data = await self._store.async_load()
        if self.data is None:
            self.data = { 'config': { 'defaults': {} } }
    def shutdown(self):
        create_task(self._hass, DOMAIN, self.async_shutdown())
    async def async_shutdown(self):
        for aview in self.views:
            await aview.shutdown()
    # Throws HomeAssistantError
    def getPreppedConfig(self):
        cfg = self.data['config'] if 'config' in self.data else {}
        try:
            preppedConfig = prepStrConfig(cfg)
        except HomeAssistantError as ex:
            msg = f'{gAssertMsg} getPreppedConfig failed from {cfg}: {ex}'
            report(DOMAIN, 'error', msg)
            return None
        return preppedConfig

    async def declareAlerts(self):
        cfg = self.getPreppedConfig()
        if cfg is not None:
            self.entities = await self._alertData.loadAlertBlock(cfg)
        
    def saveTopConfig(self, topConfig):
        #_LOGGER.warning(f'saveTopConfig: received: {topConfig}')
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
            self.data['config']['defaults'] = topConfig['defaults']
        else:
            self.data['config']['defaults'] = {}
        for fname in [ 'skip_internal_errors', 'notifier_startup_grace_secs', 'defer_startup_notifications' ]:
            if fname in topConfig:
                self.data['config'][fname] = topConfig[fname]
            elif fname in self.data['config']:
                del self.data['config'][fname]
                
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        self._alertData.noteUiUpdate()
        return prepLoadTopConfig(self)
    
    async def createAlert(self, acfg):
        try:
            preppedConfig = prepForValidation(acfg)
        except vol.Invalid as v:
            return { 'error': f'data check failed: {v}' }
        newEnt = await self._alertData.declareAlert(preppedConfig, doReport=False)
        if not isinstance(newEnt, Entity):
            return {'error': newEnt}
        if isinstance(newEnt, AlertGenerator):
            if newEnt.alName not in self._alertData.generators:
                _LOGGER.error(self._alertData.generators)
                msg = f'{gAssertMsg}: UI generator alert {newEnt.alName} not in generators category'
                report(DOMAIN, 'error', msg)
                return {'error': msg}
        elif not newEnt.alDomain in self._alertData.alerts or not newEnt.alName in self._alertData.alerts[newEnt.alDomain]:
            msg = f'{gAssertMsg}: UI alert {newEnt.entity_id} not in alerts category'
            report(DOMAIN, 'error', msg)
            return {'error': msg}
        self.entities.append(newEnt)
        if not 'alerts' in self.data['config']:
            self.data['config']['alerts'] = []
        self.data['config']['alerts'].append(acfg)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return {}

    def getDataIndex(self, domain, name):
        return next((i for i, item in enumerate(self.data['config']['alerts']) if \
                     ('generator_name' in item and GENERATOR_DOMAIN == domain and item['generator_name'] == name) or
                     (item['domain'] == domain and item['name'] == name)), -1)
    
    def loadAlert(self, domain, name):
        if 'config' not in self.data:
            return { 'error': 'alert not found' }

        dataIndex = self.getDataIndex(domain, name)
        if dataIndex == -1:
            return { 'error': 'alert not found' }
        return self.data['config']['alerts'][dataIndex]
    
    async def validateAlert(self, acfg):
        try:
            preppedConfig = prepForValidation(acfg)
        except vol.Invalid as v:
            return { 'error': f'data check failed: {v}' }

        rez = await self._alertData.declareAlert(preppedConfig, doReport=False, checkForUpdate=True)
        if rez is not None:
            return {'error': rez}
        return {}

    async def updateAlert(self, acfg):
        domain = acfg['domain']
        name = acfg['name']
        if 'generator_name' in acfg:
            domain = GENERATOR_DOMAIN
            name = acfg['generator_name']

        entIndex = next((i for i, item in enumerate(self.entities) if item.alDomain == domain and item.alName == name), -1)
        if entIndex == -1:
            return { 'error': f'can not find existing UI-created alert in self.entities with domain={domain} and name={name}' }
        dataIndex = self.getDataIndex(domain, name)
        if dataIndex == -1:
            return { 'error': f'can not find existing UI-created alert with domain={domain} and name={name}' }

        # Validate alert before call undeclareAlert so hopefully won't end up returning an error
        # and no alert left over
        vrez = await self.validateAlert(acfg)
        if vrez != {}:
            return vrez
        try:
            preppedConfig = prepForValidation(acfg)
        except vol.Invalid as v:
            return { 'error': f'data check failed: {v}' }
        rez = await self._alertData.undeclareAlert(domain, name, doReport=False)
        if rez is not None:
            report(DOMAIN, 'error', f'{gAssertMsg} updateAlert: domain={domain} name={name} found in UI, but undeclareAlert failed')
            return {'error': 'Can\'t update alert that does not exist' }
        newEnt = await self._alertData.declareAlert(preppedConfig, doReport=False)
        if not isinstance(newEnt, Entity):
            return {'error': newEnt}

        self.entities[entIndex] = newEnt
        self.data['config']['alerts'][dataIndex] = acfg
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return {}
    
    async def deleteAlert(self, domain, name):
        entIndex = next((i for i, item in enumerate(self.entities) if item.alDomain == domain and item.alName == name), -1)
        if entIndex == -1:
            return { 'error': f'can not find existing UI-created alert in self.entities with domain={domain} and name={name}' }
        dataIndex = self.getDataIndex(domain, name)
        if dataIndex == -1:
            return { 'error': f'can not find existing UI-created alert with domain={domain} and name={name}' }

        rez = await self._alertData.undeclareAlert(domain, name, doReport=False)
        if rez is not None:
            report(DOMAIN, 'error', f'{gAssertMsg} deleteAlert: domain={domain} name={name} found in UI, but undeclareAlert failed')
            return {'error': rez}
       
        del self.entities[entIndex]
        del self.data['config']['alerts'][dataIndex]
        if not self.data['config']['alerts']:
            del self.data['config']['alerts']
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        return {}

    def _data_to_save(self):
        return self.data

    def search(self, sTxt):
        #_LOGGER.warning(f'Search for "{sTxt}"')
        terms = sTxt.lower().split()
        results = []
        for ent in self.entities:
            #_LOGGER.warning(f'   looking for {terms} in {ent}')
            anid = ent.entity_id.lower()
            ok = True
            for term in terms:
                if term not in anid:
                    ok = False
                    break
            if ok:
                results.append({ 'id': ent.entity_id, 'domain': ent.alDomain, 'name': ent.alName })
        return results

