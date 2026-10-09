// VERSION is machine-read, so the following line must not be changed without also
// changing alert2/binary_sensor.py::getUiVersion
const VERSION = '1.23';
const INTERNAL_VERSION = 163;
const VERSION_STR = `${VERSION} (internal version ${INTERNAL_VERSION})`;
console.log(`alert2.js ${VERSION_STR}. HA frontend version ${window.frontendVersion}`);

// notificaiton_control uses same string for enable/disable.  for snooze it uses timestamp
const NOTIFICATIONS_ENABLED  = 'enabled'
const NOTIFICATIONS_DISABLED = 'disabled'
const NOTIFICATIONS_SNOOZED = 'snooze'
const EVENT_ALERT_NEVER_FIRED_STATE = 'has never fired'

// TODDO - maybe in 2028, remove this legacy support.
const useHaInput = window.frontendVersion >= '20260415';
const useRadioGroup = window.frontendVersion >= '20260527'; // HA 2026.6

//
//
// alert2.js is setup from backend, which seems to mean it load early on the
// frontend, even before ha-panel-lovelace is defined.  So we need to delay alert2 setup until
// LitElement is available.
//
//
customElements.whenDefined('ha-panel-lovelace').then(()=>{

//import "https://ka-f.webawesome.com/webawesome@3.8.0/webawesome.loader.js";
//import RadioGroup from "@home-assistant/webawesome/dist/components/radio-group/radio-group";
const LitElement = Object.getPrototypeOf(customElements.get("ha-panel-lovelace"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

function checkJsUpgradeAlert(hass) {
    let mObj = hass.states['binary_sensor.alert2_ha_startup_done'];
    const serverJsVersion = Object.hasOwn(mObj.attributes, 'js_version') ? mObj.attributes.js_version : 'unknown';
    return (serverJsVersion !== VERSION) ? html`<ha-alert alert-type=${"warning"}>New Alert2 frontend version available.  Reload card (${jsVersion} vs ${VERSION})</ha-alert>` : '';
}
    
// From
//   https://github.com/nielsfaber/scheduler-card/blob/main/src/lib/load_ha_form.js
// or
//   https://github.com/KipK/load-ha-components/blob/main/src/load-ha-components.ts
//
// This seems to be the only way to ensure that ha-radio-group is defined :(.
// So hacky!
//
// TODO - we only need this when opening the more-info dialog. We could delay this to when/if that happens.
let haformLoadStarted = false; // so we only request this expensive op once
async function loadHaForm(aHass) {
    //if (haformLoadStarted) { return }
    haformLoadStarted = true;
    console.log('Alert2: loadHaForm starting');
    const hasRadio = useRadioGroup ? customElements.get('ha-radio-group') : customElements.get('ha-radio');
    if (customElements.get("ha-checkbox") &&
        customElements.get("ha-slider") &&
        hasRadio) return;

    await customElements.whenDefined("partial-panel-resolver");
    const ppr = document.createElement('partial-panel-resolver');
    ppr.hass = {
        panels: [{
            url_path: "tmp",
            component_name: "config",
        }],
        auth: aHass.auth
    };
    await ppr._updateRoutes();
    //console.log('Alert2: loadHaForm did _updateRoutes');
    await ppr.routerOptions.routes.tmp.load();

    await customElements.whenDefined("ha-panel-config");
    const cpr = document.createElement("ha-panel-config");
    await cpr.routerOptions.routes.automation.load();
    console.log('Alert2: loadHaForm completed');
}

//function loadCSS(url) {
//  const link = document.createElement("link");
//  link.type = "text/css";
//  link.rel = "stylesheet";
//  link.href = url;
//  document.head.appendChild(link);
//}
//function loadModule 
//loadCSS('https://ka-f.webawesome.com/webawesome@3.8.0/styles/webawesome.css');
//<link rel="stylesheet" href="https://ka-f.webawesome.com/webawesome@3.8.0/styles/webawesome.css" />
//<script type="module" src="https://ka-f.webawesome.com/webawesome@3.8.0/webawesome.loader.js"></script>
//import('https://ka-f.webawesome.com/webawesome@3.8.0/webawesome.loader.js').then( (module)=> {
//    console.warn('webawesome loaded!!!!');
//});



//let queueMicrotask =  window.queueMicrotask || ((handler) => window.setTimeout(handler, 1));
function jFireEvent(elem, evName, params) {
    const event = new Event(evName, {
        bubbles: true,
        cancelable: Boolean(false),
        composed: true,
    });
    event.detail = params;
    elem.dispatchEvent(event);
}
function showToast(elem, amsg) { jFireEvent(elem, "hass-notification", { message: amsg }); }

let jassertFailCount = 0;
function jassert(abool, ...args) {
    if (!abool) {
        jassertFailCount += 1;
        console.error('assert failed', ...args);
        throw new Error("assert failed");
    }
}
function jasserteq(a, b) {
    if (a !== b) {
        jassertFailCount += 1;
        throw new Error(`assert failed "${a}" != "${b}"`);
    }
}
// unused
function getEvValue(ev) {
    //return ev.detail?.value || ev.target.value;
    // for easier testing, is better to be more precise here:
    if (Object.hasOwn(ev, 'detail') && Object.hasOwn(ev.detail, 'value')) {
        return ev.detail.value;
    }
    return ev.target.value;
}

// Adapted from https://stackoverflow.com/questions/996505/lru-cache-implementation-in-javascript
class LRU {
    constructor(max = 1000) {
        this.max = max;
        this.cache = new Map();
    }
    clear() { this.cache.clear(); }
    get(key) {
        let item = this.cache.get(key);
        if (item !== undefined) {
            // refresh key
            this.cache.delete(key);
            this.cache.set(key, item);
        }
        return item;
    }
    set(key, val) {
        // refresh key
        if (this.cache.has(key)) this.cache.delete(key);
        // evict oldest
        else if (this.cache.size === this.max) this.cache.delete(this.first());
        this.cache.set(key, val);
    }
    first() {
        return this.cache.keys().next().value;
    }
}

class SupersedeMgr {
    constructor() {
        // Map from entityId -> set( entityId )
        this.supersedesMap = new Map();
        this.supersededByMap = new Map();
    }
    addNode(entityId, supersedesList) {
        jasserteq(typeof(entityId), 'string');
        jassert(entityId.length > 0);
        if (this.supersedesMap.has(entityId)) {
            // no dups
            return false;
        }
        jassert(Array.isArray(supersedesList));
        if (supersedesList.length > 0) {
            // cycle check
            let supersedesSet = new Set(supersedesList);
            let supersededBySet = this.supersededBySet(entityId);
            for (const eid of supersedesSet) {
                if (supersededBySet.has(eid)) {
                    return false;
                }
            }
            this.supersedesMap.set(entityId, supersedesSet);
            for (const eid of supersedesSet) {
                if (!this.supersededByMap.has(eid)) {
                    this.supersededByMap.set(eid, new Set());
                }
                this.supersededByMap.get(eid).add(entityId);
            }
        } else {
            this.supersedesMap.set(entityId, new Set());
        }
        return true;
    }
    removeNode(entityId) {
        jassert(this.supersedesMap.has(entityId));
        for (const eid of this.supersedesMap.get(entityId)) {
            this.supersededByMap.get(eid).delete(entityId);
            if (this.supersededByMap.get(eid).size == 0) {
                this.supersededByMap.delete(eid);
            }
        }
        this.supersedesMap.delete(entityId)
    }
    supersededBySet(entityId) {
        let rez = new Set();
        let visitSet = new Set();
        if (this.supersededByMap.has(entityId)) {
            visitSet.add( entityId );
        }
        while (visitSet.size > 0) {
            let eid = visitSet.values().next().value;
            visitSet.delete(eid);
            if (this.supersededByMap.has(eid)) {
                for (const eid2 of this.supersededByMap.get(eid)) {
                    // This may visit a node multiple but finite times if the graph is diamond shaped
                    rez.add(eid2);
                    visitSet.add(eid2);
                }
            }
        }
        return rez;
    }
}

//
// The purpose of DisplayValMonitor is to preserve the display_msg fields of entities shown
// in the Alert2Overview card while that card is re-rendering.  Since display_msg is not stored
// in hass.states, if we don't preserve it, we'd have to refetch it, which results in flashing in
// the UI.
//
class DisplayValMonitor {
    constructor() {
        this.monMap = {}
        this.hass = null;
        // Do a pass removing unused monitors only if we pass a few seconds without removing anything.
        this.removeEmptiesD = debounce(this.removeEmpties.bind(this), 3000);
    }
    updateHass(newHass) {
        this.hass = newHass;
        for (const entity_id in this.monMap) {
            this.monMap[entity_id].updateHass(newHass);
        }
    }
    addChangeCb(entity_id, changeCb) {
        if (!Object.hasOwn(this.monMap, entity_id)) {
            this.monMap[entity_id] = new SingleDisplayValMonitor(entity_id);
            this.monMap[entity_id].updateHass(this.hass);
        }
        this.monMap[entity_id].addChangeCb(changeCb);
    }
    removeChangeCb(entity_id, changeCb) {
        if (this.monMap[entity_id]) {
            this.monMap[entity_id].removeChangeCb(changeCb);
            this.removeEmptiesD();
        } // else I think we already shutdown
    }
    removeEmpties() {
        for (const [entity_id, aValMon] of Object.entries(this.monMap)) {
            if (aValMon.isEmpty()) {
                delete this.monMap[entity_id];
            }
        }
    }
    shutdown() {
        for (const entity_id in this.monMap) {
            this.monMap[entity_id].shutdown();
        }
        this.monMap = {}
    }
}

class SingleDisplayValMonitor {
    constructor(entity_id) {
        this.hass = null;
        this.entity_id = entity_id;
        this.display_msg = null;
        this.has_display_msg = null;
        this._unsubFunc = null;
        this._subscribeInProgress = false;
        this._changeCbs = [];
        this._emptyRemoveTimeout = null; // if empty for a few secs, unsubscribe
        this._readyToUnsubscribe = false;
    }
    isEmpty() { return this._changeCbs.length == 0; }
    addChangeCb(changeCb) {
        if (this._emptyRemoveTimeout) {
            clearTimeout(this._emptyRemoveTimeout);
            this._emptyRemoveTimeout = null;
        }
        this._readyToUnsubscribe = false;
        changeCb(this.display_msg, this.has_display_msg);
        this._changeCbs.push(changeCb);
        this.checkDisplayMsg();
    }
    removeChangeCb(changeCb) {
        let idx = this._changeCbs.indexOf(changeCb);
        if (idx == -1) {
            console.error('DisplayValMonitor for', this.entity_id, 'could not find changeCb');
        } else {
            this._changeCbs.splice(idx, 1);
        }
        if (this.isEmpty()) {
            this._emptyRemoveTimeout = setTimeout(()=> {
                this._readyToUnsubscribe = true;
                this.checkDisplayMsg();
            }, 3000);
        }
    }
    shutdown() {
        if (this._unsubFunc) {
            this._unsubFunc();
        }
        this._unsubFunc = null;
        this._subscribeInProgress = true; // to prevent resubscribing
        this._changeCbs = [];
    }
    updateHass(newHass) {
        let oldHass = this.hass;
        this.hass = newHass;
        const newStateObj = newHass.states[this.entity_id];
        if (!newStateObj || newStateObj.state == 'unavailable') {
            // It could be that the entity was just removed from hass, but Alert2Overview has not yet removed
            // the corresponding rows.
            return;
        }
        const oldStateObj = oldHass ? oldHass.states[this.entity_id] : null;
        if (oldStateObj !== newStateObj) {
            this.has_display_msg = newStateObj.attributes['has_display_msg'];
            this._changeCbs.forEach((acb)=>{ acb(this.display_msg, this.has_display_msg); });
            this.checkDisplayMsg();
        }
    }
    async checkDisplayMsg() {
        //console.log(this.entity_id, 'checkDisplayMsg', this._subscribeInProgress, this.has_display_msg, this._unsubFunc);
        if (this._subscribeInProgress) {
            // checkDisplayMsg will be called again about a second after subscribe finishes.
            return;
        }
        let trySubscribe = false;
        if (this.has_display_msg && !this._readyToUnsubscribe) {
            if (this._unsubFunc) {
                // We want to be subscribed and are.  Good to go.
            } else {
                // Try to subscribe
                trySubscribe = true;
            }
        } else {
            if (this._unsubFunc) {
                // We don't want to be subscribed but are. Unsubscribe
                //console.log('unsubscribing from', this.entity_id);
                this._unsubFunc();
                this._unsubFunc = null;
                this.display_msg = null;
            } else {
                // We don't want to be subscribed and aren't.  Good to go.
            }
        }
        if (trySubscribe) {
            this._subscribeInProgress = true;
            // I think trySubscribe=true implies that this._hass && this._config
            const stateObj = this.hass.states[this.entity_id];
            if (!stateObj || stateObj.state == 'unavailable') {
                console.warn('Entity ', this.entity_id, ' and ', stateObj, ' unavailable or missing in checkDisplayMsg');
            } else {
                //console.log('subscribing to', this.entity_id);
                try {
                    this._unsubFunc = await this.hass.connection.subscribeMessage(
                        (ev) => this.updateDisplayMsg(ev), { // ev is SchedulerEventData
                            type: 'alert2_watch_display_msg',
                            domain: stateObj.attributes['domain'],
                            name: stateObj.attributes['name'],
                        });
                } catch (err) {
                    if (err.code === 'no_display_msg') {
                        // pass - maybe ent doesn't have a display message
                        //} else if (err.code == 'ent_not_found') {
                        // pass - could be ent is a tracked alert and so can't have a display message
                    } else {
                        console.error('subscribeMessage for ', this.entity_id, 'got error', err);
                    }
                }
            }
            this._subscribeInProgress = false;
            // Go around loop one more time, in case we had an error and need to try again.
            // If the subscribe succeeded, then trySubscribe will be false next time and we won't do any work.
            //
            // Also go around loop again in case something happened (eg hass change) that mean we should
            // try subscribing again
            setTimeout(()=>{ this.checkDisplayMsg(); }, 1000);
        }
    }
    updateDisplayMsg(ev) {
        //console.log(this.entity_id, 'updateDisplayMsg to ', ev.rendered, this.has_display_msg);
        this.display_msg = ev.rendered;
        this._changeCbs.forEach((acb)=>{ acb(this.display_msg, this.has_display_msg); });
    }
};

function getPriority(hass, dispInfo) {
    let priority = null;
    if (hass && hass.states[dispInfo.entityName]) {
        // may be null if older server (March 2025)
        priority = hass.states[dispInfo.entityName].attributes.priority;
    }
    return priority ? priority : 'low';
}
//function isTruthy(a) {
//    return !isNaN(parseInt(a)) || ['yes','no','on','off','true','false'].includes(a.toLowerCase());
//}
function isTruthy(aval) {
    if (typeof aval == 'boolean') { return aval; }
    if (typeof aval == 'number') { return aval > 0; }
    if (typeof aval == 'string') {
        return ['yes','on','true', '1'].includes(aval.toLowerCase());
    }
    return false;
}
if (0) {
    // Validate if a value can be processed by isTruthy function
    function isValidBooleanValue(value) {
        const validTypes = ['boolean', 'number', 'string'];
        return validTypes.includes(typeof value);
    }
}

function popupMoreinfo(hass, element, entityName) {
    jFireEvent(element, "hass-more-info", {
        entityId: entityName
    });
    return;
    // let stateObj = hass.states[entityName];
    // let friendlyName = stateObj.attributes.friendly_name;
    // let title = '';
    // if (friendlyName) {
    //     title += `"${friendlyName}" (entity ${entityName})`;
    // } else {
    //     title += entityName;
    // }
    // //let innerHtml = html`<more-info-alert2  dialogInitialFocus .entityId=${entityName} .hass=${this.hass} >
    // //                     </more-info-alert2>`;
    // let innerElem = document.createElement('more-info-alert2');
    // innerElem.stateObj = stateObj;
    // //innerElem.entityId = entityName;
    // innerElem.setAttribute('dialogInitialFocus', '');
    // innerElem.hass = hass;
    // jCreateDialog(element, title, innerElem);
    // if (0) {
    //     jFireEvent(element, "show-dialog", {
    //         dialogTag: "more-info-alert2-container",
    //         dialogImport: () => new Promise((resolve)=> { resolve(); }),
    //         dialogParams: {
    //             entityName: entityName,
    //         },
    //         addHistory: true
    //     });
    // }
}

// A custom card that lists alerts that have fired recently
class Alert2Overview extends LitElement {
    // https://lit.dev/docs/components/properties/
    // has good description of reactive properties
    static properties = {
        _config: {state: true},
        _configError: {state: true},
        _sortedDispInfos: {state: true},
        _cardHelpers: {state: true},
        _ackAllInProgress: {state: true},
        _showVersion: {state: true},
        _showUpgradeAlert: {state: true},
        _sliderVal: {state: true}
    }
    constructor() {
        super();
        this._sortedDispInfos = [];
        this._updateTimer = null;
        this._cardHelpers = null;
        this._ackAllInProgress = false;
        this._showVersion = false;
        this._showUpgradeAlert = '';
        this._configError = null;
        this._sliderValArr = [
            { str: '1 minute', secs: 60 },
            { str: '10 minutes', secs: 10*60 },
            { str: '1 hour', secs: 60*60 },
            { str: '4 hours', secs: 4*60*60 },
            { str: '1 day', secs: 24*60*60 },
            { str: '4 days', secs: 4*24*60*60 },
            { str: '2 weeks', secs: 2*7*24*60*60 }
        ]
        window.loadCardHelpers().then(hs => { this._cardHelpers = hs; });
        this._hass = null;
        // The only indication we get of state changes is hass updating.
        // To prevent scanning through all entitites in hass on each update,
        // we do two optimizations.
        // 1. We throttle scans to at most once per _updateCooldownMs.
        // 2. We keep _alert2StatesMap, a map of the state objects of all alert/alert2
        //    entities. So when we do a scan in jrefresh(), we first do a check to see if any
        //    alert2 entities changed.  If any changed, then we do the heavier
        //    look through entities and check dates/times.
        //
        this._alert2StatesMap = new Map(); // map entity_id -> state object
        this._updateCooldown =  { timer: undefined, rerunIsReload: undefined };
        this._updateCooldownMs = 1000;
        
        this._sliderVal = 3;// 4 hours
        // Check for entities aging out of UI window 6 times each selected interval.
        // e.g., 6 times ever 4 hours
        this._updateIntervalFactor = 6;
        this._displayValMonitor = null;
    }
    // Rate limit how often jrefresh is called.
    // rerunIsReload can be in 3 states:
    //    undefined mean no call to slowedUpdate during timer interval
    //    false means slowedUpdate called during timer interval with isReload false
    //    true means slowedUpdate called during timer interval with isReload true
    slowedUpdate(isReload) {
        if (this._updateCooldown.timer) {
            this._updateCooldown.rerunIsReload = this._updateCooldown.rerunIsReload || isReload;
            //console.log('set hass - deferring');
            return;
        } else {
            //console.log('set hass - doing lightRefresh', this._updateCooldownMs);
            this._updateCooldown.rerunIsReload = undefined;
            this._updateCooldown.timer = window.setTimeout(() => {
                this._updateCooldown.timer = undefined;
                let rerunIsReload = this._updateCooldown.rerunIsReload;
                if (rerunIsReload !== undefined) {
                    setTimeout(()=> { this.jrefresh(rerunIsReload); }, 0);
                }
            }, this._updateCooldownMs);
            setTimeout(()=> { this.jrefresh(isReload); }, 0);
        }
    }
    set hass(newHass) {
        const oldHass = this._hass;
        this._hass = newHass;
        if (this.shadowRoot && this._hass) {
            this.shadowRoot.querySelectorAll("hui-alert2-entity-row").forEach((elem) => {
                elem.hass = this._hass;
            });
        }
        if (this._displayValMonitor) {
            this._displayValMonitor.updateHass(newHass);
        }
        this.slowedUpdate(false);
        if (this._hass && !haformLoadStarted) {
            loadHaForm(this._hass).then( ()=>{ } );
        }
    }
    connectedCallback() {
        super.connectedCallback();
        this._displayValMonitor = new DisplayValMonitor();
        if (this._hass) {
            this._displayValMonitor.updateHass(this._hass);
        }
        this.restartUpdateTimer();
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        clearInterval(this._updateTimer);
        this._updateTimer = null;
        if (this._updateCooldown.timer) {
            window.clearTimeout(this._updateCooldown.timer);
            this._updateCooldown.timer = undefined;
        }
        //this._displayValMonitor.disconnectedCallback();
        if (this._displayValMonitor) {
            this._displayValMonitor.shutdown();
            this._displayValMonitor = null;
        }
    }
    setConfig(config) {
        this._config = config;
        this._configError = null;
        if (this._config) {
            if (Object.hasOwn(this._config, 'filter_entity_id') && typeof this._config.filter_entity_id !== 'string') {
                this._configError = `Config field filter_entity_id must be a string, not of type ${typeof this._config.filter_entity_id}`;
            }
            // Validate color configs
            const colorFields = ['low_priority_color', 'medium_priority_color', 'high_priority_color', 'off_color'];
            for (const colorField of colorFields) {
                if (Object.hasOwn(this._config, colorField)) {
                    const colorValue = this._config[colorField];
                    if (typeof colorValue !== 'string') {
                        this._configError = `Config field ${colorField} must be a string (CSS color value)`;
                        break;
                    }
                }
            }
            if (0) {
                // Validate boolean-like config fields
                const booleanFields = ['snoozed_disabled_use_off_color'];
                for (const boolField of booleanFields) {
                    if (Object.hasOwn(this._config, boolField)) {
                        const value = this._config[boolField];

                        // Check if value is a valid boolean-like type
                        if (!this.isValidBooleanValue(value)) {
                            this._configError = `Config field ${boolField} must be a boolean, number, or string (got ${typeof value}: ${JSON.stringify(value)})`;
                            break;
                        }
                    }
                }
            }
        }
        this.slowedUpdate(true);
    }
    // Slider changed value
    slideCh(ev) {
        let val = this.shadowRoot.querySelector("ha-slider").value;
        if (val >= 0 && val < this._sliderValArr.length) {
            this._sliderVal = val;
        } else {
            console.error('slider value out of bounds:', val);
        }
        this.restartUpdateTimer();
        this.jrefresh(true);
    }
    restartUpdateTimer() {
        if (this._updateTimer) {
            clearInterval(this._updateTimer);
        }
        let intMs = this._sliderValArr[this._sliderVal].secs * 1000 / this._updateIntervalFactor;
        // The purpose of this interval timer is to remove from display old alerts that fall outside
        // the displayed time window.
        this._updateTimer = setInterval(()=> { this.jrefresh(true); }, intMs);
    }
    // Ack all button was pressed
    async _ackAll(ev) {
        this._ackAllInProgress = true;
        let abutton = ev.target;
        let outerThis = this;
        try {
            await this._hass.callWS({
                type: "call_service",
                domain: 'alert2',
                service: 'ack_all'
            });
        } catch (err) {
            this._ackAllInProgress = false;
            abutton.actionError();
            showToast(this, "error: " + err.message);
            return;
        }
        this._ackAllInProgress = false;
        abutton.actionSuccess();
    }
    async _toggleShowVersion(ev) {
        this._showVersion = ! this._showVersion;
    }
    render() {
        if (!this._cardHelpers || !this._hass) {
            return html`<div>Loading.. waiting for hass + card helpers to load</div>`;
        }

        const outerThis = this;
        let entListHtml;
        if (this._sortedDispInfos.length == 0) {
            let filterStr = (this._config && this._config.filter_entity_id) ? " (filter applied)" : "";
            entListHtml = html`<div id="jempt">No alerts active in the past ${this._sliderValArr[this._sliderVal].str}. No alerts snoozed or disabled.${filterStr}</div>`;
        } else {
            const ackedIdx = this._sortedDispInfos.findIndex(el => el.isAcked && !el.isSuperseded);
            entListHtml = [];

            if (0) {
                // For each alert that supersedes other alerts we're going to show,
                // accumulate count of how many superseded alerts will appear below.
                let supersedesCount = new Array(this._sortedDispInfos.length).fill(0);
                let currSCount = 0;
                for (let idx = this._sortedDispInfos.length - 1 ; idx >= 0 ; idx--) {
                    const dispInfo = this._sortedDispInfos[idx];
                    if (dispInfo.isSuperseded) {
                        currSCount += 1;
                    } else {
                        supersedesCount[idx] = currSCount;
                        currSCount = 0;
                    }
                    if (idx == ackedIdx) {
                        jassert(currSCount == 0, currSCount);
                    }
                }
                jassert(currSCount == 0, currSCount);
            }
            
            // Now generate html via entListHtml
            let inDetails = null; // becomes list of superseded alerts
            for (let idx = 0 ; idx < this._sortedDispInfos.length ; idx++) {
                let dispInfo = this._sortedDispInfos[idx];
                let entityConf = { entity: dispInfo.entityName };
                if (dispInfo.entityName.startsWith('alert2.')) {
                    // 'custom:' gets stripped off in src/panels/lovelace/create-element/create-element-base.ts
                    entityConf.type = 'custom:hui-alert2-entity-row';
                    // fire-dom-event causes ll-custom event to fire, if we're using hui-generic-entity-row,
                    // which we're not anymore.
                    // This should have no effect:
                    //     aconf.tap_action = { action: "fire-dom-event" };
                    entityConf.priority = getPriority(this._hass, dispInfo);
                } else {
                    // Must be old Alert1 alert. Let it use the default entity row
                }
                if (inDetails !== null && !dispInfo.isSuperseded) {
                    entListHtml.push(html`<details><summary>${inDetails.length} superseded ${inDetails.length == 1 ? "alert" : "alerts"}</summary>${inDetails}</details>`);
                    inDetails = null;
                }
                if (idx == ackedIdx) {
                    jassert(inDetails === null, inDetails);
                    entListHtml.push(html`<div id="ackbar">---- Acked, snoozed or disabled ---</div>`);
                }
                //console.log('rendering', dispInfo.entityName, ' and ', dispInfo.isSuperseded, dispInfo);
                if (dispInfo.isSuperseded) {
                    if (inDetails === null) {
                        inDetails = [];
                    }
                    inDetails.push(this.renderEntity(entityConf, dispInfo));
                } else {
                    jassert(inDetails === null, inDetails);
                    entListHtml.push(this.renderEntity(entityConf, dispInfo));
                }
            }
            if (inDetails !== null) {
                entListHtml.push(html`<details><summary>${inDetails.length} superseded ${inDetails.length == 1 ? "alert" : "alerts"}</summary>${inDetails}</details>`);
            }
        }
        let manifestVersion = 'unknown';
        let mObj = this._hass.states['binary_sensor.alert2_ha_startup_done'];
        if (Object.hasOwn(mObj.attributes, 'manifest_version')) {
            manifestVersion = mObj.attributes.manifest_version;
        }
        const versionHtml = this._showVersion ? html`<table class="tversions" cellspacing=0>
             <tr><td>Alert2 UI<td>${VERSION_STR}</tr><tr><td>Alert2<td>v${manifestVersion}</tr></table>` : html``;
        const title = (this._config && this._config.title) ? this._config.title : 'Alerts';
        const cfgErrHtml = this._configError ?
            html`<ha-alert alert-type=${"error"} style="display: inline-block;">${this._configError}</ha-alert>` : "";
        let foo = html`<ha-card>
            <h1 class="card-header"><div class="name" @click=${this._toggleShowVersion}>${title}</div>${versionHtml}</h1>
            ${cfgErrHtml}
            ${this._showUpgradeAlert}
            <div class="card-content">
              <div style="display:flex; align-items: center; margin-bottom: 1em;">
                  <ha-slider .min=${0} .max=${this._sliderValArr.length-1} .step=${1} .value=${this._sliderVal} snaps ignore-bar-touch
                     @change=${this.slideCh}
                  ></ha-slider>
                  <span id="slideValue">Last ${this._sliderValArr[this._sliderVal].str}</span>
                <div style="flex-grow: 1;"></div>
                <ha-progress-button
                    .progress=${this._ackAllInProgress}
                    .appearance=${"plain"}
                    @click=${this._ackAll}
                    >Ack all</ha-progress-button>
              </div>
              ${entListHtml}
            </div>
          </ha-card>`;
        return foo;
    }
    renderEntity(entityConf, dispInfo) {
        let entityName = entityConf.entity;
        const element = this._cardHelpers.createRowElement(entityConf);
        element.hass = this._hass;
        element.classList.add('aRowElement');
        if (element instanceof Alert2EntityRow) {
            if (!this._displayValMonitor) {
                // This shouldn't happen - TODO fix this.
                console.warn('setting displayValMonitor to', this._displayValMonitor);
            }
            element.displayValMonitor = this._displayValMonitor;
            element.isSuperseded = dispInfo.isSuperseded;
            element.colorConfig = {
                low_priority_color: this._config?.low_priority_color,
                medium_priority_color: this._config?.medium_priority_color,
                high_priority_color: this._config?.high_priority_color,
                off_color: this._config?.off_color,
                //unacked_off_color: this._config?.unacked_off_color,
            };
            if (dispInfo.isSuperseded) {
                element.classList.add('superseded');
            }
        }
        let outerThis = this;
        // hui-generic-entity-row calls handleAction on events, including clicks.
        // we set the action to take on 'tap' to be 'fire-dom-event', which generates a 'll-custom' event
        // NOTE - the hui- code gobbles up the click event and on chrome-mobile seems to gobble up clicks on an 'ack' button as well :(,
        // and further, the ll-custom event does not include information on which element was originally clicked on. :(
        //
        //element.addEventListener('ll-custom', (ev)=>outerThis._alertClick(ev, entityName));
        if (entityConf.entity.startsWith('alert.')) {
            // it already has a built-in more-info click listener
        } else {
            element.addEventListener('click', (ev)=>outerThis._alertClick(ev, element, entityName));
        }
        //element.addEventListener('click', this.anev2);
        //console.log('foo2', element);
        //console.log('ick', element.shadowRoot.querySelector('hui-generic-entity-row'));
        //return html`<div class="jEvWrapper" @click=${this.anev1} >${element}</div>`;
        //return html`<div class="aRowElement">${element}</div>`;
        return html`${element}`;
    }
    _alertClick(ev, element, entityName) {
        popupMoreinfo(this._hass, element, entityName);
        return true;
    }
    static styles = css`
      .card-header {
        display: flex;
        justify-content: space-between;
      }
      .card-header .name {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
      }
      div#jempt {
        margin: 0px 18px 18px 18px;
      }
      .icon {
        padding: 0px 18px 0px 8px;
      }
      .info {
        overflow: visible;
      }
      .header {
        border-top-left-radius: var(--ha-card-border-radius, 12px);
        border-top-right-radius: var(--ha-card-border-radius, 12px);
        margin-bottom: 16px;
        overflow: hidden;
      }
      .footer {
        border-bottom-left-radius: var(--ha-card-border-radius, 12px);
        border-bottom-right-radius: var(--ha-card-border-radius, 12px);
        margin-top: -16px;
        overflow: hidden;
      }
      .aRowElement {
          display: block;
          margin-top: 1em;
      }
      .aRowElement {
      }
      details {
          /*       hui-alert2-entity-row.superseded { */
          /* margin-top: -0.8em;  to counteract the aRowElement of the row above */
          padding-left: 56px; /* 40px for state badge + 16px padding */
      }
      details[open] summary {
          margin-bottom: -0.5em;
      }
      details > hui-alert2-entity-row {
          margin-left: -56px;
      }
      .tversions {
        font-size: 1rem;
        user-select: text;
        line-height: 1.2em;
        height: 0;  /* necessary, no idea why.  could also be max-content */
      }
      .tversions td {
          padding: 0px;
      }
      .tversions td:first-child {
          padding-right: 0.7em;
      }
      div#ackbar {
          margin-bottom: 1em;
          text-align: center;
          font-size: 0.9em;
      }
    `;

    // Returns true if changed list of entities.
    jrefresh(forceBigRefresh) {
        //console.log('doing jrefresh', forceBigRefresh);
        jassert(forceBigRefresh === true || forceBigRefresh === false);
        if (!this._hass) {
            console.log('  skipping jrefresh cuz no hass');
            return false;
        }
        if (forceBigRefresh) {
            // doing periodic check for aged out entities, gotta take slow path
        } else {
            // called as result of calls to set hass.
            // So just gotta check if states has changed
            let existingCount = 0;
            for (let entityName in this._hass.states) {
                if (entityName.startsWith('alert.') ||
                    entityName.startsWith('alert2.')) {
                    if (this._alert2StatesMap.has(entityName)) {
                        existingCount += 1;
                        if (this._hass.states[entityName] !== this._alert2StatesMap.get(entityName)) {
                            //console.log('  will force cuz', entityName);
                            forceBigRefresh = true;
                        }
                    } else {
                        // New entity appeared
                        forceBigRefresh = true;
                    }
                }
            }
            if (this._alert2StatesMap.size > existingCount) {
                // Some entity has been deleted
                forceBigRefresh = true;
            }
        }

        // Check for upgrade alert
        this._showUpgradeAlert = checkJsUpgradeAlert(this._hass);
        
        if (!forceBigRefresh) {
            return;
        }
        //console.log('doing big refresh');

        // Supersedes processing
        //
        const startMs = Date.now();
        // Create map of domain,name to entity_id
        let dnToKey = (d, n) => { return `d=${d},n=${n}`; }
        let entIdMap = new Map();
        for (let entityName in this._hass.states) {
            if (entityName.startsWith('alert2.')) {
                let stateObj = this._hass.states[entityName];
                entIdMap.set(dnToKey(stateObj.attributes.domain, stateObj.attributes.name), entityName);
            }
        }
        // Add all supersedes info to a new SupersedeMgr
        // TODO - save SupersedeMgr across refreshes
        let supersedeMgr = new SupersedeMgr();
        for (const entityName of entIdMap.values()) {
            let stateObj = this._hass.states[entityName];
            // looks like supersedes is an array
            if (Object.hasOwn(stateObj.attributes, 'supersedes')) {
                let sList = [];
                stateObj.attributes.supersedes.forEach((el) => {
                    jassert(el.domain && el.name, el, entityName);
                    let key = dnToKey(el.domain, el.name);
                    if (entIdMap.has(key)) {
                        let entId = entIdMap.get(key);
                        sList.push(entId);
                    }
                });
                supersedeMgr.addNode(entityName, sList);
                //console.log('supersedes', entityName, stateObj.attributes.supersedes, typeof(stateObj.attributes.supersedes));
            }
        }
        const endMs = Date.now();
        if (!this._logCount) { this._logCount = 0; } this._logCount++;
        if (this._logCount < 10) {
            console.log(`${this._logCount} Recalculating supersedes took ${endMs-startMs} ms`);
        }
        //console.log('refresh', this._hass.states, supersedeMgr.supersedesMap, supersedeMgr.supersededByMap);
        
        this._alert2StatesMap.clear();
        for (let entityName in this._hass.states) {
            if (entityName.startsWith('alert.') ||
                entityName.startsWith('alert2.')) {
                this._alert2StatesMap.set(entityName, this._hass.states[entityName]);
            }
        }
        
        let filterRegex = null;
        if (this._config && this._config.filter_entity_id && typeof this._config.filter_entity_id === "string") {
            let pattern = this._config.filter_entity_id;
            if (!pattern.startsWith("/")) {
                // Convert globs to regex
                pattern = pattern.replace(/\./g, ".").replace(/\*/g, ".*");
                pattern = `/^${pattern}$/`;
            }
            filterRegex = new RegExp(pattern.slice(1, -1));
        }
        
        const intervalSecs = this._sliderValArr[this._sliderVal].secs;
        //console.log('intervalSecs as hours', intervalSecs / 60 / 60);
        const nowMs = Date.now();
        const intervalStartMs = nowMs - (intervalSecs*1000);
        let entDispInfos = [];
        let unsortedEnts = [];
        for (let entityName in this._hass.states) {
            let isAcked = false;
            let isOn = false;
            let testMs = 0; // 1970
            const ent = this._hass.states[entityName];
            if (ent.state === 'unavailable') {
                continue;
            }
            if (entityName.startsWith('alert.')) {
                if (ent.state == 'on') { // on means unacked
                    let lastChangeMs = Date.parse(ent.last_changed);
                    isOn = true;
                    testMs =  lastChangeMs;
                    if (!filterRegex || filterRegex.test(entityName)) {
                        entDispInfos.push({ isOn:isOn, isAcked:isAcked, testMs:testMs, entityName:entityName,
                                            supersededBySet: (new Set()) } );
                    }
                } // else is off, which means acked, or is idle which means is off.
            } else if (entityName.startsWith('alert2.')) {
                //let lastAckMs = 0;
                isAcked = ent.attributes['is_acked'];
                //console.log(entityName, ent.attributes['is_acked'], typeof(ent.attributes['is_acked']));
                //if (ent.attributes['last_ack_time']) {
                //    lastAckMs = Date.parse(ent.attributes['last_ack_time']);
                //}
                if ('last_on_time' in ent.attributes) {
                    // Is a condition alert
                    let lastOnMs = 0;
                    if (ent.attributes['last_on_time']) {
                        lastOnMs = Date.parse(ent.attributes['last_on_time']);
                        //isAcked = lastAckMs > lastOnMs;
                    }
                    if (ent.state == 'on') {
                        isOn = true;
                        testMs = Date.parse(ent.attributes['last_on_time']);
                    } else if (ent.state == 'off') {
                        if (ent.attributes['last_off_time']) {
                            testMs = Date.parse(ent.attributes['last_off_time']);
                        } // else never fired
                    } else {
                        console.error('Entity state is not on/off', ent.state, entityName);
                    }
                } else {
                    // Edge triggered alert
                    if (ent.state && ent.state !== EVENT_ALERT_NEVER_FIRED_STATE) {
                        let lastFireMs = Date.parse(ent.state);
                        //isAcked = lastAckMs > lastFireMs;
                        testMs = lastFireMs;
                    } // else alert has never fired
                }
                if (isNaN(testMs)) {
                    console.error('Entity ', ent.entity_id, ent.state, ent.attributes, 'parse error lastFireMs', testMs);
                    continue;
                }
                const not_enabled = (ent.attributes.notification_control &&
                                     (ent.attributes.notification_control != NOTIFICATIONS_ENABLED));
                if (not_enabled) {
                    isAcked = true;  // treat snoozed or disabled alerts as already acked
                }
                //console.log('considering ', entityName, testMs);
                const includeOldUnacked = (this._config && isTruthy(this._config.include_old_unacked)) ||
                      ent.attributes.ack_required;
                // Check testMs so we ignore alerts that have never fired
                const isOldUnacked = !isAcked && testMs > 0;
                if (isOn || (isOldUnacked && includeOldUnacked) || intervalStartMs < testMs || not_enabled) {
                    if (!filterRegex || filterRegex.test(entityName)) {
                        let supersededBySet = supersedeMgr.supersededBySet(entityName);
                        entDispInfos.push({ isOn:isOn, isAcked:isAcked, testMs:testMs, entityName:entityName,
                                            supersededBySet: supersededBySet } );
                    }
                }
            }
        }
        return this.resort(entDispInfos);
    }
    resort(tentDispInfos) {
        // 2-level deep clone of object, so we can compare e.g. isAcked and isOn between old and new
        let entDispInfos = [];
        tentDispInfos.forEach((el)=> { entDispInfos.push(Object.assign({}, el)); });
        
        let allIds = {}; // entId -> dispInfo
        entDispInfos.forEach((el)=> { allIds[el.entityName] = el; });

        // Want to group together superseded elements
        //
        // 1. Split ents into those that are superseded by another displayed ent and those ready to sort.
        // 
        let toPlace = new Set();
        let readyToSort = new Set();
        let skipped = new Set();
        let readyToSortDispInfos = [];
        
        entDispInfos.forEach((el)=> {
            // If el is superseded by an ent we're displaying and that is on, mark it
            for (const anId of el.supersededBySet) {
                if (Object.hasOwn(allIds, anId) && allIds[anId].isOn) {
                    if (this._config && isTruthy(this._config.hide_superseded)) {
                        skipped.add(el.entityName);
                    } else {
                        toPlace.add(el.entityName);
                        el.isSuperseded = true;
                    }
                    return;
                }
            }
            el.isSuperseded = false;
            readyToSort.add(el.entityName);
            readyToSortDispInfos.push(el);
        });
        //console.log('refreshss', readyToSort, toPlace, skipped);
        
        //
        // 2. Sort the readyToSort entities
        //
        // sort func return negative if a should come before b
        let outerThis = this;
        let sortFunc = function(a, b) {
            if (a.isAcked != b.isAcked) {
                return a.isAcked ? 1 : -1;
            } else if (a.isOn != b.isOn) {
                return a.isOn ? -1 : 1;
            } else {
                let aIdx = ['low', 'medium', 'high'].indexOf(getPriority(outerThis._hass, a));
                let bIdx = ['low', 'medium', 'high'].indexOf(getPriority(outerThis._hass, b));
                if (aIdx != bIdx) {
                    return aIdx > bIdx ? -1 : 1;
                } else {
                    return b.testMs - a.testMs;
                }
            }
        }
        //console.log('about to sort in render', JSON.stringify(readyToSortDispInfos));
        // TODDO - copy of toSorted  here not necessary
        let sortedDispInfos = readyToSortDispInfos.toSorted(sortFunc);

        //
        // 3. Now place the remaining ents under element superseding it.
        //
        while (toPlace.size > 0) {
            for (const candidateId of toPlace) {
                let dispInfo = allIds[candidateId];
                //console.log('considering placing', dispInfo.entityName);
                for (const anId of dispInfo.supersededBySet) {
                    if (toPlace.has(anId)) {
                        // candidate is supserseded by another element in toPlace, so skip it for now.
                        //console.log('   entity is superseded by element yet to be placed: ', anId);
                        break;
                    }
                }
                // candidate is not superseded by anything in toPlace, so can place it.
                let found = false;
                //console.log('    will now place');
                for (let idx = sortedDispInfos.length - 1 ; idx >= 0 ; idx--) {
                    let tinfo = sortedDispInfos[idx];
                    if (dispInfo.supersededBySet.has(tinfo.entityName) && tinfo.isOn) {
                        // insert it
                        found = true;
                        sortedDispInfos.splice(idx+1, 0, dispInfo);
                        toPlace.delete(candidateId);
                        break;
                    }
                }
                jassert(found, 'could not find where to place', candidateId);
                break;
            }
        }
        // make sure we placed everything
        jassert(sortedDispInfos.length >= 0 && Object.keys(allIds).length >= 0, 'type error for', sortedDispInfos, Object.keys(allIds));
        jassert(sortedDispInfos.length + skipped.size == (Object.keys(allIds).length), 'not all supersedes were places', sortedDispInfos, allIds, skipped);
        
        let doUpdate = false;
        if (sortedDispInfos.length !== this._sortedDispInfos.length) {
            doUpdate = true;
        } else {
            for (let idx = 0 ; idx < sortedDispInfos.length; idx ++) {
                let olde = this._sortedDispInfos[idx];
                let newe = sortedDispInfos[idx];
                if (newe.entityName !== olde.entityName) {
                    doUpdate = true;
                    break;
                }
                if (newe.isOn != olde.isOn ||
                    newe.isAcked != olde.isAcked ||
                    newe.testMs != olde.testMs ||
                    newe.isSuperseded != olde.isSuperseded ||
                    newe.configInfo !== olde.configInfo
                   ) {
                    doUpdate = true;
                    break;
                }
            }
        }
        if (doUpdate) {
            // Will trigger rerender
            this._sortedDispInfos = sortedDispInfos;
        }
        return doUpdate;
    }

    
}

// Similar to src/panels/lovelace/entity-rows/hui-climate-entity-row.ts
// implements LovelaceRow
class Alert2EntityRow extends LitElement  {
    static properties = {
        _config: {state: true},
        display_msg: { state: true },
        has_display_msg: { state: true },
    }
    set hass(nh) {
        if (nh && this._config) {
            const newStateObj = nh.states[this._config.entity];
            const oldStateObj = this._hass ? this._hass.states[this._config.entity] : null;
            this._hass = nh;
            if (newStateObj !== oldStateObj) {
                if (this.shadowRoot) {
                    this.shadowRoot.querySelectorAll("ha-alert2-state").forEach((element) => {
                        element.stateObj = newStateObj;
                    });
                }
            }
        }
    }
    set displayValMonitor(ad) {
        this._displayValMonitor = ad;
        // Somehow, connectedCallback can be called while this._displayValMonitor is null.
        // I think it's due to different orderings of calls to parent & child connectedCallback
        // So we don't assume we're connected when displayValMonitor is set.
        if (this._isConnected) {
            let entity_id = this._config.entity;
            this._displayValMonitor.addChangeCb(entity_id, this.display_change_cb);
        }
    }
    set isSuperseded(abool) {
        this._isSuperseded = abool;
    }
    set colorConfig(config) {
        this._colorConfig = config;
        this.requestUpdate();
    }
    constructor() {
        super();
        this._hass = null;
        this._config = null;

        this.display_msg = null;
        this.has_display_msg = false;
        this.display_change_cb = null;
        this._displayValMonitor = null;
        this._isSuperseded = false;
        this._colorConfig = null;
        this._isConnected = false;
    }
    setConfig(config) {
        if (!config || !config.entity) {
            throw new Error("Entity must be specified");
        }
        this._config = config;
    }
    connectedCallback() {
        super.connectedCallback();

        if (this.display_change_cb) {
            console.error(this._config.entity, 'display_change_cb is set but calling connectedCallback');
        }
        this.display_change_cb = (newMsg, newHasMsg)=>{
            this.display_msg = newMsg;
            this.has_display_msg = newHasMsg;
        }
        this._isConnected = true;
        // Somehow, connectedCallback can be called while this._displayValMonitor is null.
        // I don't understand how, unless somehow parent is rendered before connectedCallback or after
        // disconnectedCallback.
        if (this._displayValMonitor) {
            let entity_id = this._config.entity;
            this._displayValMonitor.addChangeCb(entity_id, this.display_change_cb);
        }
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        let entity_id = this._config.entity;
        //console.log(this._config.entity, 'disconnectedCallback so calling removeChangeCb');
        this._isConnected = false;
        if (this._displayValMonitor) {
            this._displayValMonitor.removeChangeCb(entity_id, this.display_change_cb);
            this.display_change_cb = null;
        }
    }
    _rowClick(ev) {
        console.log('_rowClick', ev);
        return true;
    }
    render() {
        if (!this._hass || !this._config) {
            console.warn('foo, not ready to render');
            return nothing;
        }
        const stateObj = this._hass.states[this._config.entity];
        if (!stateObj) {
            console.error('entity not found', this._config.entity);
            return html`
        <hui-warning>
          Entity not found in hass.states: ${this._config.entity}
        </hui-warning>
      `;
        }
        //let entHtml = '';
        //console.log('foo', this._config);
        const friendlyName = this._hass.states[this._config.entity].attributes.friendly_name;
        //console.log('foo3', this._hass.states[this._config.entity]);
        //console.log('foo3b', this._hass.states[this._config.entity].attributes);
        //console.log('foo2b', friendlyName);
        let nameToUse = friendlyName ? friendlyName : stateObj.entity_id;
        const entHtml = nameToUse.split('_').map((x,idx,arr)=>(idx < arr.length-1)? html`${x}_<wbr/>` : html`${x}`);
        
        // This is essentially the guts of hui-generic-entity-row, except it does not swallow click events, like hui-generic-entity-row does (and converts it to ll-custom).  That means we can react to a click on a 'Ack' button in a row entity.
        //       <div class="awrapper">
        //    </div>
        let dispMsgHtml = ``;
        if (this.has_display_msg && this.display_msg !== null) {
            dispMsgHtml = html`<div class="dispMsg">${this.display_msg}</div>`;
        }
        let stateClass = 'pointer';
        if (this._isSuperseded) {  stateClass += ' superseded'; }
        const priority = this._config ? this._config.priority : 'low';
        
        if (priority == 'low') {  stateClass += ' lowpri'; }
        if (priority == 'medium') {  stateClass += ' mediumpri'; }
        if (priority == 'high') {  stateClass += ' highpri'; }
        let badgeStyle = '';
        let customColor = 'grey';
        if (this._colorConfig) {
            const isAcked = stateObj.attributes['is_acked'];
            const isConditionAlert = 'last_on_time' in stateObj.attributes;
            const isOn = stateObj.state === 'on';
            //const notificationControl = stateObj.attributes.notification_control;
            //const isSnoozedOrDisabled = notificationControl && notificationControl !== 'enabled';
            //const shouldUseSnoozedOffColor = this._colorConfig.snoozed_disabled_use_off_color && isTruthy(this._colorConfig.snoozed_disabled_use_off_color);
            
            // Use priority coloring is condition alert is firing or if ack is missing from ack_required alert.
            // For event alerts show priority coloring is not acked. So it's like event alerts force ack_required to be true.
            const isPriorityColored = (isConditionAlert && isOn) || (stateObj.attributes.ack_required && !isAcked) ||
                  (!isConditionAlert && !isAcked);
            if (isPriorityColored) {
                if (priority === 'low') {
                    customColor = this._colorConfig.low_priority_color ? this._colorConfig.low_priority_color : 'blue';
                } else if (priority === 'medium') {
                    customColor = this._colorConfig.medium_priority_color ? this._colorConfig.medium_priority_color : 'orange';
                } else if (priority === 'high') {
                    customColor = this._colorConfig.high_priority_color ? this._colorConfig.high_priority_color : 'red';
                } else {
                    console.error(`Unrecognized priority=${priority} for entity ${stateObj.entity_id}`);
                }
            } else {
                customColor = this._colorConfig.off_color ? this._colorConfig.off_color : 'grey';
            }
        }
        badgeStyle = `color: ${customColor};`;

        return html`
        <div class="mainrow">
            <div class="outhead">
               <state-badge class=${stateClass} style=${badgeStyle} .hass=${this._hass} .stateObj=${stateObj} @click=${this._rowClick} tabindex="0"></state-badge>
               <div class="info pointer text-content" title=${stateObj.entity_id} @click=${this._rowClick}  >${entHtml}</div>
            </div>
            <ha-alert2-state .hass=${this._hass} .stateObj=${stateObj} class="text-content value pointer astate"  @click=${this._rowClick} >
         </div>
         ${dispMsgHtml}
         </ha-alert2-state>
`;
    }

    static styles = css`
      div.mainrow {
        display: flex;
        flex-flow: row wrap;
        align-items: center;
        /*justify-content: space-between;*//* not needed now that we use margin-left: auto */
      }
      .outhead, .astate {
       /* note max-content I think ignores flex basis.
        * so setting flex-basis in children may make things not fit. */
        max-width: max-content; /* flex: once heading has enough room, give rest to state */
      }
      .outhead {
        display: flex;
        align-items: center;
        flex: 1 1 10em;
        min-width: 7em; 
      }
      .astate {
        margin-left: auto; /* so if it wraps it is right justified */
        flex: 0 0 auto;
      }
      .awrapper {
        display: flex;
        align-items: center;
        flex-direction: row;
     }
      .info {
        margin-left: 16px;
        margin-right: 8px;
        line-height: 1.1em;
        flex: 1 1 auto;
      }
      .info,
      .info > * {
        /*white-space: nowrap;*/
        overflow-wrap: anywhere;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      state-badge {
        /* can't use flex basis to set width here, cuz it messes up the max-content directive in parent */
        flex: 0 0 auto; 
        line-height: normal;
        height: auto;
      }
      .pointer {
        cursor: pointer;
      }
      div.dispMsg {
         font-size: 0.9em;
         /*border: 1px solid green;*/
         /*margin-left: 22px;*/
         text-align: right;
      }
      state-badge.superseded {
         visibility: hidden;
      }
      state-badge.lowpri { }
      state-badge.mediumpri { }
      state-badge.highpri { }
    `;
}

function formatLogDate(idate) {
    function z2(num) { return ('0'+num).slice(-2); }
    function z3(num) { return ('00'+num).slice(-3); }
    let adate = new Date(idate);
    // e.g., 2024/12/20 13:05:15.123  (local time)
    return `${adate.getFullYear()}/${z2(adate.getMonth()+1)}/${z2(adate.getDate())} ${z2(adate.getHours())}:${z2(adate.getMinutes())}:${z2(adate.getSeconds())}.${z3(adate.getMilliseconds())}`
}

function agoStr(adate, longnames) {
    const secondsAgo = (new Date() - adate) / 1000.0;
    let astr;
    let intervalSecs;
    if (secondsAgo < 2*60) { astr = `${Math.round(secondsAgo)}${longnames?" seconds":" s"}`; intervalSecs = 1; }
    else if (secondsAgo < 2*60*60) { astr = `${Math.round(secondsAgo/60)}${longnames?" minutes":" min"}`; intervalSecs = 60; }
    else if (secondsAgo < 2*24*60*60) { astr = `${Math.round(secondsAgo/(60*60))}${longnames?" hours":" h"}`; intervalSecs = 60*60; }
    else { astr = `${Math.round(secondsAgo/(24*60*60))}${longnames?" days":" d"}`; intervalSecs = 24*60*60; }
    return { str:`${astr} ago`, secs:intervalSecs };
}

// Similar to ha-relative-time, except adjusts the update interval corresponding to the displayed units.
class RelativeTime extends LitElement {
    static properties = {
        timestamp: {state: true},
        useLongnames: {state: true},
    }
    constructor() {
        super();
        this.timestamp = null;
        this._updateTimer = null;
    }
    connectedCallback() {
        super.connectedCallback();
        this.requestUpdate();
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        if (this._updateTimer) {
            clearTimeout(this._updateTimer);
            this._updateTimer = null;
        }
    }
    render() {
        if (this._updateTimer) {
            clearTimeout(this._updateTimer);
            this._updateTimer = null;
        }
        const info = agoStr(this.timestamp, this.useLongnames);
        this._updateTimer = setTimeout(()=>{this.requestUpdate();}, info.secs*1000);
        return html`<span>${info.str}</span>`;
    }
}

// Element to render the state of an alert
class HaAlert2State extends LitElement {
    static properties = {
        _ackInProgress: {state: true},
    }
    constructor() {
        super();
        this._stateObj = null;
        this._ackInProgress = false;
        this._hass = null;
    }
    set hass(ao) {
        this._hass = ao;
    }
    set stateObj(ao) {
        let old = this._stateObj;
        this._stateObj = ao;
        if (old != ao) {
            this.requestUpdate();
        }
    }
    async _jack(ev) {
        await this.ackInternal(ev, true);
    }
    async _junack(ev) {
        await this.ackInternal(ev, false);
    }
    async ackInternal(ev, isAck) {
        let op = isAck ? 'ack' : 'unack';
        console.log(`${op} clicked`, this._stateObj.entity_id);
        this._ackInProgress = true;
        let abutton = ev.target;
        ev.stopPropagation();
        if (1) {
            try {
                await this._hass.callWS({
                    type: "call_service",
                    domain: 'alert2',
                    service: isAck ? 'ack' : 'unack',
                    target: { entity_id: this._stateObj.entity_id }
                });
            } catch (err) {
                this._ackInProgress = false;
                abutton.actionError();
                showToast(this, "error: " + err.message);
                return;
            }
            this._ackInProgress = false;
            abutton.actionSuccess();
        }
    }
    render() {
        if (!this._stateObj) {
            return html`<div>loading...</div>`;
        }
        const ent = this._stateObj;
        let msg;
        //let last_ack_time = null;
        //if (ent.attributes['last_ack_time']) {
        //    last_ack_time = Date.parse(ent.attributes['last_ack_time']);
        //}
        let last_on_time = null;
        if (ent.attributes['last_on_time']) {
            last_on_time = Date.parse(ent.attributes['last_on_time']);
        }
        let last_fired_time = null;
        if (Object.hasOwn(ent.attributes, 'last_on_time')) {
            last_fired_time = last_on_time;
            if (ent.state == 'on') {
                //msg = 'on';
                const last_on_time = Date.parse(ent.attributes['last_on_time']);
                msg = html`on<j-relative-time .timestamp=${last_on_time} .useLongnames=${false} style="margin-left:0.5em;"></j-relative-time>`;
            } else if (ent.state == 'off') {
                if (ent.attributes['last_off_time']) {
                    const last_off_time = Date.parse(ent.attributes['last_off_time']);
                    msg = html`off<j-relative-time .timestamp=${last_off_time} .useLongnames=${false} style="margin-left:0.5em;"></j-relative-time>`;
                } else {
                    msg = html`off`;
                }
            } // else - should never happen, was checked when populated _shownEntities list.
        } else {
            if (ent.state && ent.state !== EVENT_ALERT_NEVER_FIRED_STATE) {
                last_fired_time = Date.parse(ent.state);
                msg = html`<j-relative-time .timestamp=${last_fired_time} .useLongnames=${false}></j-relative-time>`;
            } else {
                msg = html`${EVENT_ALERT_NEVER_FIRED_STATE}`;
            }
        }
        let ackButton = '';
        const is_acked = ent.attributes['is_acked'];
        if (is_acked) {
            ackButton = html`<ha-progress-button
                  .appearance=${"plain"}
                  .progress=${this._ackInProgress} class="unack"
                  @click=${this._junack}>Unack</ha-progress-button>
                 `;
        } else {
            ackButton = html`<ha-progress-button
                  .appearance=${"plain"}
                  .progress=${this._ackInProgress}
                  @click=${this._jack}>Ack</ha-progress-button>
                 `;
        }
        let snoozeBadge = '';
        if (ent.attributes.notification_control == NOTIFICATIONS_ENABLED) { }
        else if (ent.attributes.notification_control == NOTIFICATIONS_DISABLED) {
            snoozeBadge = html`<div class="badge">Disabled</div>`;
        } else if (ent.attributes.notification_control) {
            // snoozed. val is date snoozed til
            snoozeBadge = html`<div class="badge">Snoozed</div>`;
        }
        let numSince = ent.attributes.fires_since_last_notify;
        if (ent.state == 'on' && numSince > 0) {
            // If alert is on and fires_since_last_notify > 0, then the firing must include
            // the one that turned this on. So subtract it from the count.
            numSince -= 1;
        }
        const extraFiresBadge = (numSince == 0) ? '' : html`<div style="display: flex; align-items:center; margin-left:0.3em;">+${numSince}x</div>`;
        
        return html`<div class="onerow">${snoozeBadge}${ackButton}</div>
                    <div class="onerow"><div class="curr">${msg}</div>${extraFiresBadge}</div>`;
    }
    static styles = css`
      .unack {
          opacity: 0.6;
      }
      .onerow {
          display: flex;
          flex-flow: row;
          align-items: center;
      }
      ha-progress-button {
          display: flex;
          height: 1em;
          align-items: center;
      }
      .badge {
          border-radius: 10%;
          border: 0.2em solid var(--label-badge-text-color, rgb(76, 76, 76));
          color: var(--label-badge-text-color, rgb(76, 76, 76));
          padding: 0.1em 0.3em;
          /* margin-right: 1em; */
          font-size: 0.9em;
          opacity: 0.5;
          height: fit-content;
      }
      .noborder {
          border: none;
      }
      :host {
        display: flex;
        flex-direction: row;
        /* flex-wrap: wrap;*/
        justify-content: right;
        white-space: nowrap;
        align-items: center;
      }
      .curr {
        display: flex;
        align-items: center;
      }
      .target {
        color: var(--primary-text-color);
      }

      .current {
        color: var(--secondary-text-color);
      }

      .state-label {
        font-weight: bold;
        text-transform: capitalize;
      }

      .unit {
        display: inline-block;
        direction: ltr;
      }
    `;
}

class StateCardAlert2 extends LitElement {
    static properties = {
        hass: {attribute: false},
        stateObj: {attribute: false},
        inDialog: { }
    }
    static styles = css`
        :host {
          @apply --paper-font-body1;
          line-height: 1.5;
        }
        .layout.horizontal {
            display: flex;
            flex-direction: row;
            justify-content: space-between;
        }
        ha-alert2-state {
          margin-left: 16px;
          text-align: right;
        }
     `;
  render() {
    return html`
      <style include="iron-flex iron-flex-alignment"></style>
      <div class="horizontal justified layout">
        <state-info
          .hass=${this.hass}
          .stateObj=${this.stateObj}
          ?inDialog=${this.inDialog}
        ></state-info>
        <ha-alert2-state
          .hass=${this.hass}
          .stateObj=${this.stateObj}
        ></ha-alert2-state>
      </div>
    `;
  }
}

function strIsValidNumber(astr) {
    if (typeof(astr) !== 'string') { return false; }
    let bstr = astr.trim();
    let val = Number(bstr);
    if (bstr.length > 0 && !isNaN(val) && val >= 0) {
        return val;
    } else { return false; }
}

// Add this attribute to alert entity attributes:
// 'custom_ui_more_info' : 'more-info-alert2', # name of UI element that must be defined
//
// Similar to ha-more-info-info from src/dialogs/more-info/ha-more-info-info.ts
class MoreInfoAlert2 extends LitElement {
    static properties = {
        hass: { attribute: false },
        stateObj: { attribute: false },
        entry: { attribute: false }, // from ha-more-info-info. unused at present
        editMode: { attribute: false }, // from ha-more-info-info. unused at present
        
        _requestInProgress: {state: true},
        _ackInProgress: {state: true},
        _actionOnCancelInProgress: {state: true},
        _actionOnRunInProgress: {state: true},
        _currSnoozeValue: {state: true},
        _currSelectorValue: {state: true},
        _historyArr: {state: true},
        _snooze_includes_ack: {state: true},
    }
    // I don't think anything sets hass on MoreInfoAlert2 and so this code will never run after init
    shouldUpdate(changedProps) {
        if (this._currSelectorValue === undefined) {
            if (this.stateObj) {
                let nc = this.stateObj.attributes.notification_control;
                this._currSelectorValue = nc;
                if (nc && nc !== NOTIFICATIONS_DISABLED && nc !== NOTIFICATIONS_ENABLED) {
                    this._currSelectorValue = NOTIFICATIONS_SNOOZED;
                }
            }
        }
        if (this.hass && !haformLoadStarted) {
            loadHaForm(this._hass).then( ()=>{ } );
        }
        if (changedProps.size > 1) { return true; }
        if (changedProps.has('hass')) {
            const oldHass = this.hass;
            const newHass = changedProps.get("hass");
            if (!oldHass || !newHass || !this.stateObj) { return true; }
            const entityId = this.stateObj.entity_id;
            const oldState = oldHass.states[entityId];
            const newState = newHass.states[entityId];
            return oldState !== newState;
        }
        return true;
    }
    constructor() {
        super();
        this._requestInProgress = false;
        this._ackInProgress = false;
        this._currSnoozeValue   = undefined;
        this._currSelectorValue = undefined;
        this.textEl = null;
        this._historyArr = null;
        this._historyStartDate = null;
        this._historyEndDate = null;
        this._fetchPrevInProgress = false;
        this._fetchCurrInProgress = false;
        this._actionOnCancelInProgress = false;
        this._actionOnRunInProgress = false;
        this._snooze_includes_ack = true;
        // no shadowRoot yet.
    }
    connectedCallback() {
        super.connectedCallback();
        // no shadowRoot yet.
    }
    firstUpdated() {
        super.firstUpdated();
        // see https://lit.dev/docs/v1/components/lifecycle/#firstupdated
        customElements.whenDefined('state-card-alert2').then(()=>{
            this.requestUpdate();
        });
    }
    showDialog(dialogParams) {
        console.log('MoreInfoAlert2 showDialog called', dialogParams);
    }
    fetchPrev() {
        const msAgo = 24*60*60*1000.0;
        if (!this._historyStartDate) {
            this.fetchCurr();
            return;
        }
        this._historyEndDate = this._historyStartDate;
        this._historyStartDate = new Date(this._historyStartDate.getTime() - msAgo);
        this._fetchPrevInProgress = true;
        this.getHistory();
    }
    fetchCurr() {
        if (!this.hass || !this.stateObj) {
            console.log('skipping fetchCurr since hass or stateObj is null', this.hass, this.stateObj);
            return;
        }
        const msAgo = 24*60*60*1000.0;
        this._historyStartDate = new Date((new Date()).getTime() - msAgo);
        this._historyEndDate = null;
        this._fetchCurrInProgress = true;
        this.getHistory();
    }
    async actionOnCancel(ev) {
        await this.actionOnControl(ev, false);
    }
    async actionOnRun(ev) {
        await this.actionOnControl(ev, true);
    }
    async actionOnControl(ev, isRun) {
        const entId = this.stateObj.entity_id;
        const abutton = ev.target;
        const outerThis = this;
        const setInProgress = function(nval) {
            if (isRun) { outerThis._actionOnRunInProgress = nval; }  else { outerThis._actionOnCancelInProgress = nval; } };
        setInProgress(true);
        try {
            await this.hass.callWS({
                type: "call_service",
                domain: 'alert2',
                service: 'action_control',
                target: { entity_id: entId },
                service_data: { 'operation': (isRun ? 'run' : 'cancel') },
            });
        } catch (err) {
            setInProgress(false);
            abutton.actionError();
            showToast(this, "error: " + err.message);
            return;
        }
        setInProgress(false);
        abutton.actionSuccess();
    }
    getHistory() {
        let stateObj = this.stateObj;
        console.log('will getHistory for', stateObj.entity_id, 'from', this._historyStartDate, 'to', this._historyEndDate);
        let historyUrl = `history/period/${this._historyStartDate.toISOString()}?filter_entity_id=${stateObj.entity_id}`;
        if (this._historyEndDate) {
            historyUrl += `&end_time=${this._historyEndDate.toISOString()}`;
        }
        const outerThis = this;
        const isAlert = 'last_on_time' in stateObj.attributes;
        const maxCount = 20;
        this.hass.callApi('GET', historyUrl).then(function(rez) {
            console.log('got history state', rez);
            outerThis._fetchCurrInProgress = false;
            outerThis._fetchPrevInProgress = false;
            if (Array.isArray(rez) && Array.isArray(rez[0])) {
                let rezArr = rez[0].reverse();
                if (rezArr.length == 0) {
                    outerThis._historyArr = [];
                    return;
                }
                // Iterate from newest to oldest.
                let newArr = [ rezArr[0] ];
                let tstate = rezArr[0].state;
                if (!tstate) {
                    outerThis._historyArr = [];
                    return;
                }
                for (let idx = 1 ; idx < rezArr.length ; idx++) {
                    if (rezArr[idx].state && rezArr[idx].state != tstate) {
                        tstate = rezArr[idx].tstate;
                        newArr.push(rezArr[idx]);
                    }
                }
                if (newArr.length >= maxCount) {
                    let oldestEl = newArr[maxCount-1];
                    let oldestDate = Date.parse(oldestEl.last_updated);
                    if (oldestDate == NaN) {
                        console.error('Alert2: Unable to parse last_updated', oldestEl.last_updated);
                    } else {
                        newArr = newArr.slice(0, maxCount);
                        outerThis._historyStartDate = new Date(oldestDate);
                    }
                }
                outerThis._historyArr = newArr;
            } else if (Array.isArray(rez) && rez.length == 0) {
                outerThis._historyArr = [];
            } else {
                console.error('in fetching history for ', stateObj.entity_id, this._historyStartDate, this._historyEndDate, 'got malformed result', rez);
            }
        }).catch((err)=> { console.error('hass call to get alert history failed: ', err); });
    }
    
    render() {
        if (!this.hass || !this.stateObj) {
            return html`waiting for hass and stateObj to be defined`;
        }
        if (this._historyStartDate == null) {
            // do first fetch of history
            this.fetchCurr();
        }
        let stateObj = this.stateObj;
        let stateValue = stateObj.attributes.notification_control;
        let notification_status;
        if (stateValue == null || stateValue == undefined) {
            notification_status = "unknown";
        } else if (stateValue == NOTIFICATIONS_ENABLED) {
            notification_status = "enabled";
        } else if (stateValue == NOTIFICATIONS_DISABLED) {
            notification_status = "disabled";
        } else {
            let idate = Date.parse(stateValue);
            notification_status = "snoozed until " + formatLogDate(idate);
        }

        let actionOnStatus = stateObj.attributes.actions_on_script_running;
        const hasActionOn = actionOnStatus !== undefined;
        const actionGroup = hasActionOn ? html`
            <div id="actionsOnStatus" style="display: flex; margin-top: 2em; margin-bottom: 1em; align-items: center;">
               <div class="title"><code>actions_on</code> script running: </div>
               <div style="margin-left: 0.8em; margin-right:1em;">${actionOnStatus}</div>
               <ha-progress-button
                 .appearance=${"plain"}
                 .progress=${this._actionOnCancelInProgress}
                 @click=${this.actionOnCancel}
               >Cancel</ha-progress-button>
               <ha-progress-button
                 .appearance=${"plain"}
                 .progress=${this._actionOnRunInProgress}
                 @click=${this.actionOnRun}
               >Run</ha-progress-button>
               </div>` : html``;

        
        let is_snoozed = this._currSelectorValue == NOTIFICATIONS_SNOOZED;
        const entName = stateObj.entity_id;
        const isAlert = 'last_on_time' in stateObj.attributes;
        let isAlertOn = false;
        let onBadge = ''
        if (isAlert) {
            isAlertOn = stateObj.state == 'on';
            onBadge = isAlertOn ? "on" : "off";
        }
        let historyHtml = html`Fetching history...`;
        if (this._historyArr !== null) {
            let histHtmlElems = [];
            let prevEventDate = null;
            for (let idx = this._historyArr.length - 1; idx >= 0; idx--) {
                const elem = this._historyArr[idx];
                let anEventDate = null;
                let stateHtml = '';
                let extraTxt = '';
                if (isAlert) {
                    let stateTxt = elem.state;
                    let lastOnDate = elem.attributes.last_on_time ? Date.parse(elem.attributes.last_on_time) : null;
                    let lastOffDate = elem.attributes.last_off_time ? Date.parse(elem.attributes.last_off_time) : null;
                    if (lastOnDate && (lastOnDate <= prevEventDate ||
                                       (this._historyStartDate && lastOnDate < this._historyStartDate) ||
                                       (this._historyEndDate && lastOnDate >= this._historyEndDate))) {
                        lastOnDate = null;
                    }
                    if (lastOffDate && (lastOffDate <= prevEventDate ||
                                       (this._historyStartDate && lastOffDate < this._historyStartDate) ||
                                       (this._historyEndDate && lastOffDate >= this._historyEndDate))) {
                        lastOffDate = null;
                    }
                    if (lastOffDate && lastOnDate) {
                        console.warn('for entity', entName, 'saw change in both alert on & off time in one db update. Showing only most recent one', elem);
                        if (lastOnDate > lastOffDate) {
                            lastOffDate = null;
                        } else {
                            lastOnDate = null;
                        }
                    }
                    if (lastOnDate) {
                        if (elem.state !== 'on') {
                            console.error(entName, 'looks like alert fired, but state does not match', elem);
                            stateTxt += ' [ turned on (js logic err) ]';
                        }
                        anEventDate = lastOnDate;
                        extraTxt = elem.attributes.last_fired_message;
                    } else if (lastOffDate) {
                        if (elem.state !== 'off') {
                            console.error(entName, 'looks like alert turned off, but state does not match', elem);
                            stateTxt += ' [ turned off (js logic err) ]';
                        }
                        anEventDate = lastOffDate;
                    } else {
                        // do not set anEventDate, so won't add to display list
                    }
                    stateHtml = html`<td>${stateTxt}</td>`;
                } else {
                    let lastEventDate = elem.attributes.last_fired_time ? Date.parse(elem.attributes.last_fired_time) : null;
                    if (lastEventDate && (lastEventDate <= prevEventDate ||
                                       (this._historyStartDate && lastEventDate < this._historyStartDate) ||
                                       (this._historyEndDate && lastEventDate >= this._historyEndDate))) {
                        lastEventDate = null;
                    }
                    if (lastEventDate) {
                        anEventDate = lastEventDate;
                        extraTxt = elem.attributes.last_fired_message;
                    }
                }
                if (anEventDate) {
                    const firedTime = 
                          html`<j-relative-time .timestamp=${anEventDate} .useLongnames=${true}></j-relative-time>`;
                    const absTime =
                          html`<span style="font-size:0.8em;">${formatLogDate(anEventDate)}</span>`;
                    histHtmlElems.push(html`
                       <tr class="eventrow">
                       <td class="eventtime">${firedTime}<br/>${absTime}</td>
                       ${stateHtml}
                       <td>${extraTxt}</td>
                       </tr>
                       `);
                    prevEventDate = anEventDate;
                }
            }
            if (histHtmlElems.length > 0) {
                histHtmlElems.reverse();
                historyHtml = html`<table>
                    <tr>
                      <th>Event time</th>
                      ${ isAlert ? html`<th style="padding-left: 1em;">On/Off</th>` : '' }
                      <th style="padding-left: 1em;">Message</th>
                    </tr>
                    ${histHtmlElems}</table>`;
            } else {
                if (this._historyEndDate) {
                    historyHtml = html`<div style="margin-left:2em;">No state updates found between ${formatLogDate(this._historyStartDate)} and ${formatLogDate(this._historyEndDate)}</div>`;
                } else {
                    historyHtml = html`<div style="margin-left:2em;">No state updates found since ${formatLogDate(this._historyStartDate)}</div>`;
                }
            }
        }
        let snoozeValidFunc = (newValue, nativeValidity) => {
            return { valid: (strIsValidNumber(newValue) != false) };
        }
        let haInput = useHaInput ? html`
                          <ha-input
                              .placeholder=${"1.234"}
                              .min=${0}
                              .disabled=${false}
                              .required=${NOTIFICATIONS_SNOOZED == this._currSelectorValue}
                              .pattern=${"[0-9]+(\.[0-9]+)?"}
                             type="number"
                             inputMode="decimal"
                              auto-validate
                              @input=${this._handleInputChange}
                              ><div slot="end">hours</div></ha-input>
                         ` :  html`
                                  <ha-textfield
                              .placeholder=${"1.234"}
                              .min=${0}
                              .disabled=${false}
                              .required=${NOTIFICATIONS_SNOOZED == this._currSelectorValue}
                              .suffix=${"hours"}
                              .validityTransform=${snoozeValidFunc}
                             type="number"
                             inputMode="decimal"
                              autoValidate
                              ?no-spinner=false
                              @input=${this._handleInputChange}
                              ></ha-textfield>
                           `;
        let radioGroup = useRadioGroup ? html`
            <ha-radio-group label="Notification control options" orientation="vertical"
                            .value=${this._currSelectorValue}
                            @change=${this._selectorValueChanged}>
                  <ha-radio-option
                      .value=${NOTIFICATIONS_ENABLED}
                      >Enable</ha-radio-option>
                 <ha-radio-option
                   .value=${NOTIFICATIONS_DISABLED}
                   >Disable</ha-radio-option>
                  <!-- if change structure of HTML here, update _aclick() -->
                 <ha-radio-option
                      id="rad1"
                      .value=${NOTIFICATIONS_SNOOZED}
                     style="display: flex; flex-direction: row; align-items: center; margin-bottom: 1.3em;"
                      >
                      <div>Snooze for</div>
                      <div style="margin-bottom: -1.3em;">
                          ${haInput}
                          <div style="display:flex;align-items:center;margin-top:0em;margin-left:1em;">
                              <ha-formfield>
                                  <ha-checkbox .checked=${this._snooze_includes_ack}
                                                @change=${this._snooze_ack_toggle} .label=${"happy"}
                                                ></ha-checkbox>
                                  <ha-formfield-label slot="label">Ack once now</ha-formfield-label>
                              </ha-formfield>
                          </div>
                      </div>
                  </div>
                 </ha-radio-option>
                  
              </ha-radio-group>
`:html`
            <div><ha-formfield .label=${"Enable"}>
                  <ha-radio
                      .checked=${NOTIFICATIONS_ENABLED == this._currSelectorValue}
                      .value=${NOTIFICATIONS_ENABLED}
                      .disabled=${false}
                      @change=${this._selectorValueChanged}
                      ></ha-radio></ha-formfield></div>
            <div><ha-formfield .label=${"Disable"}><ha-radio
                  .checked=${NOTIFICATIONS_DISABLED == this._currSelectorValue}
                  .value=${NOTIFICATIONS_DISABLED}
                  .disabled=${false}
                  @change=${this._selectorValueChanged}
                  ></ha-radio></ha-formfield></div>
            <div style="margin-bottom:2em;"><ha-formfield id="for-snooze">
                  <!-- if change structure of HTML here, update _aclick() -->
                  <ha-radio
                      id="rad1"
                      .checked=${NOTIFICATIONS_SNOOZED == this._currSelectorValue}
                      .value=${NOTIFICATIONS_SNOOZED}
                      .disabled=${false}
                      @change=${this._selectorValueChanged}
                      ></ha-radio>
                  <div style="display:flex; flex-direction: row; align-items:center;" id="slabel" @click=${this._aclick}>
                      <div>Snooze for</div>
                      <div style="margin-bottom: -3.3em;">
                          ${haInput}
                          <div style="display:flex;align-items:center;margin-top:-0.5em;">
                              <ha-formfield>
                                  <ha-checkbox .checked=${this._snooze_includes_ack}
                                                @change=${this._snooze_ack_toggle} .label=${"happy"}
                                                ></ha-checkbox>
                                  <ha-formfield-label slot="label">Ack once now</ha-formfield-label>
                              </ha-formfield>
                          </div>
                      </div>
                  </div>

              </ha-formfield>
            </div>
`;

        
        // This is written so that it will stay live and update notification control status,
        // but will not change the notification control settings themselves,
        // so you don't get overrulled why trying to change settings.  This is done by
        // having this._currSelectorValue and _currSnoozeValue only change due to user input, not changes to hass.
        return html`
         <div class="container" >
            <state-card-content
              in-dialog
              .stateObj=${stateObj}
              .hass=${this.hass}
            ></state-card-content>
            <div id="previousFirings" style="margin-top: 1em;">
               <div style="display: flex; margin-top: 2em; margin-bottom: 1em; align-items: center;">
                  <div class="title">Previous Firings (24 hrs)</div>
                  <div style="flex: 1 1 0; max-width: 10em;"></div>
                  <ha-progress-button
                    .appearance=${"plain"}
                    .progress=${this._fetchPrevInProgress}
                    @click=${this.fetchPrev}
                  >Prev</ha-progress-button>
                  <ha-progress-button
                    .appearance=${"plain"}
                    .progress=${this._fetchCurrInProgress}
                    @click=${this.fetchCurr}
                  >Reset</ha-progress-button>
               </div>
               <div class="alist">
                  ${historyHtml}
               </div>
            </div>
            <div class="title" style="margin-top: 1em;">Notifications</div>
            <div style="margin-bottom: 0.3em;">Status: ${notification_status}</div>
            ${radioGroup}
            <ha-progress-button
                  .appearance=${"plain"}
                  .progress=${this._requestInProgress}
                  @click=${this._jupdate}>Update</ha-progress-button>
            <br/><br/>
            ${actionGroup}
            <ha-attributes
                .hass=${this.hass}
                .stateObj=${stateObj}
                ></ha-attributes>
         </div>`;
    }
    //let par = customElements.get("ha-more-info-info").styles;
    static styles = css`
    table {
      /*border-collapse: separate;*/
      /*border-spacing: 0 1em;*/
    }
    td {
      padding: 0 15px 15px 15px;
      vertical-align: top;
    }
    td.eventtime {
       word-break: break-all;
       min-width: 4em;
    }
    div#slabel {
      pointer: default;
    }
    ha-textfield, ha-input {
      margin-left: 1em;
      margin-right: 1em;
    }
    .container {
        /* padding: 24px; */
        margin-bottom: 1em;
     }
        .title {
          font-family: var(--paper-font-title_-_font-family);
          -webkit-font-smoothing: var(
            --paper-font-title_-_-webkit-font-smoothing
          );
          font-size: var(--paper-font-subhead_-_font-size);
          font-weight: var(--paper-font-title_-_font-weight);
          letter-spacing: var(--paper-font-title_-_letter-spacing);
          line-height: var(--paper-font-title_-_line-height);
        }
      `;

    _snooze_ack_toggle(ev) {
        let isChecked = ev.target.checked;
        this._snooze_includes_ack = isChecked;
    }
    _selectorValueChanged(ev) {
        let value = ev.target.value;
        if (!useRadioGroup || ev.target.nodeName == 'HA-RADIO-GROUP') {
            //console.log('radio clicked, val', value);
            this._currSelectorValue = value;
        } else {
            //console.log('ignoring click from I think the ha-input/ha-checkbox', value, ev.target);
        }
    }
    _handleInputChange(ev) {
        //ev.stopPropagation();
        const value = ev.target.value;
        this._currSnoozeValue = value;
    }
    async _jupdate(ev) {
        console.log('submit clicked', this._currSelectorValue, this._currSnoozeValue, this._snooze_includes_ack);
        this._requestInProgress = true;
        let abutton = ev.target;
        let data = { };
        if (this._currSelectorValue === undefined) {
            this._requestInProgress = false;
            abutton.actionError();
            showToast(this, "error: entity state not defiend yet");
            return;
        }
        if (this._currSelectorValue == NOTIFICATIONS_ENABLED) {
            data.enable = 'on';
        } else if (this._currSelectorValue == NOTIFICATIONS_DISABLED) {
            data.enable = 'off';
        } else {
            jasserteq(this._currSelectorValue, NOTIFICATIONS_SNOOZED);
            let val = strIsValidNumber(this._currSnoozeValue);
            if (val == false) {
                this._requestInProgress = false;
                abutton.actionError();
                console.error('bad value', this._currValue);
                showToast(this, "Non-positive numeric value: " + this._currValue);
                return;
            }
            data.enable = 'on';
            let hours = val;
            var newDate = new Date((new Date()).getTime() + hours*60*60*1000);
            data.snooze_until = newDate;
            data.ack_at_snooze_start = this._snooze_includes_ack;
        }
        let stateObj = this.stateObj;
        try {
            await this.hass.callWS({
                type: "call_service",
                domain: 'alert2',
                service: 'notification_control',
                target: { entity_id: stateObj.entity_id },
                service_data: data,
            });
        } catch (err) {
            this._requestInProgress = false;
            abutton.actionError();
            showToast(this, "error: " + err.message);
            return;
        }
        this._requestInProgress = false;
        abutton.actionSuccess();
        this.requestUpdate();
    }
    async _jack(ev) {
        this._ackInProgress = true;
        let abutton = ev.target;
        ev.stopPropagation();
        let stateObj = this.stateObj;
        try {
            await this.hass.callWS({
                type: "call_service",
                domain: 'alert2',
                service: 'ack',
                target: { entity_id: stateObj.entity_id }
            });
        } catch (err) {
            this._ackInProgress = false;
            abutton.actionError();
            showToast(this, "error: " + err.message);
            return;
        }
        this._ackInProgress = false;
        abutton.actionSuccess();
    }
    _aclick(ev) {
        this._currSelectorValue = NOTIFICATIONS_SNOOZED;
    }
}

// innerHtml is something returned by html``
function jCreateDialog(element, titleStr, innerElem) {
    jFireEvent(element, "show-dialog", {
        dialogTag: "more-info-alert2-container",
        dialogImport: () => new Promise((resolve)=> { resolve(); }),
        dialogParams: {
            //entityName: entityName,
            titleStr: titleStr,
            innerElem: innerElem,
            //innerHtml: innerHtml,
        },
        addHistory: true
    });
}

// Similar to ha-more-info-dialog from src/dialogs/more-info/ha-more-info-dialog.ts
class MoreInfoAlert2Container extends LitElement {
    static properties = {
        open: {},
        large: {reflect: true, type: Boolean},
        _hass: { state: true },
        //hass: { attribute: false },
    }
    constructor() {
        super();
        this.config = null;
        this.large = true;
        this._hass = null;
        this.open = false;
        this.waEnabled = true;
    }
    set hass(nhass) {
        this._hass = nhass;
        if (this.config) {
            this.config.innerElem.hass = nhass;
        }
        if (this._hass) {
            const ver = this._hass.config.version.split('.'); // eg '2026.1.3'
            this.waEnabled = true;
            if (ver.length == 3) {
                const yr = +ver[0];
                if (yr < 2026 || (yr == 2026 && +ver[1] < 3)) {
                    this.waEnabled = false;
                }
            } else {
                console.error('Alert2 in render can not tell HA version', ver, this._hass.config.version);
            }
        }
    }
    set stateObj(nobj) {
        if (this.config) { this.config.innerElem.stateObj = stateObj; }
    }
    set entry(nobj) {
        if (this.config) { this.config.innerElem.entry = entry; }
    }
    setConfig(config) {
        this.config = config;
    }
    showDialog(dialogParams) {
        //console.log('MoreInfoAlert2Container showDialog called', dialogParams);
        this.open = true;
        this.setConfig(dialogParams);
    }
    closeDialog() {
        this.open = false;
        jFireEvent(this, "dialog-closed", { dialog: this.localName });
    }
    _dialogClosed() {
        console.log('---------- dialog closed');
        this.open = false;
        //jFireEvent(this, "dialog-closed", { dialog: this.localName });
    }
    _dialogOpened() {
        console.log('---------- dialog opened');
        this.open = true;
    }
    
    connectedCallback() {
        super.connectedCallback();
        //this.getRootNode().querySelector('div.content').style.maxWidth = '60em';
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        let adiv = this.getRootNode().querySelector('div.content');
        if (adiv) { // This may be useless. Seems like sometimes, when element is removed from DOM, the div.content is removed as well.
            adiv.style.maxWidth = null;
        }
    }
    //shouldUpdate(changedProps) {
    //    console.log(' MoreInfoAlert2Container shouldUpdate called ', changedProps);
    //    return true;
    //}
    render() {
        if (!this._hass) {
            return html`<div>waiting for hass</div>`;
        }
        if (!this.config) {
            return html`<div>waiting for config</div>`;
        }
        if (!this.open) {
            return html``;
        }
        //let stateObj = this.hass.states[this.config.entityName];
        let title = this.config.titleStr;
        if (0) {
            let friendlyName = stateObj.attributes.friendly_name;
            let entityName = this.config.entityName;
            if (friendlyName) {
                title += `"${friendlyName}" (entity ${entityName})`;
            } else {
                title += entityName;
            }
        }
        //let innerHtml = this.config.innerHtml;
        let innerElem = this.config.innerElem;
        //<more-info-alert2  dialogInitialFocus .stateObj=${stateObj} .hass=${this.hass} ></more-info-alert2>

        // Request "full" width so we don't also have to set --ha-dialog-width-lg or something like it. Instead we just control dialog width via --ha-dialog-width-full
        if (this.waEnabled) {
            return html`
           <ha-dialog open flexContent width="full" @closed=${this._dialogClosed} @opened=${this._dialogOpened} >
              <span class="main-title" slot="headerTitle"> ${title} </span>
              <ha-icon-button
                slot="headerNavigationIcon"
                @click=${this.closeDialog}
                .label=${this._hass.localize("ui.common.close")}
              ><ha-icon .icon=${"mdi:close"}></ha-icon></ha-icon-button>
              <div class="content" tabindex="-1">
                  ${innerElem}
             </div>
           </ha-dialog>
        `;
        }
        return html`
           <ha-dialog class="old-dialog" open @closed=${this.closeDialog} .heading=${true} hideActions flexContent  >
              <ha-dialog-header slot="heading">
                <mwc-icon-button .label=${"dismiss"} dialogAction="cancel" slot="navigationIcon" ><ha-icon .icon=${"mdi:close"} ></ha-icon>
                  </mwc-icon-button>
                <span class="main-title" slot="title" .title=${title} > ${title} </span>
              </ha-dialog-header>
              <div class="content-old" tabindex="-1" dialogInitialFocus>
                  ${innerElem}
             </div>
           </ha-dialog>
        `;
    }
    static styles = css`
        .content, .content-old {
          display: flex;
          flex-direction: column;
          outline: none;
          flex: 1;
        }
        .main-title {
           white-space: wrap;
           word-break: break-all;
        }
        .content {
           /* width: 100%; */
        }
        ha-dialog {
           --ha-dialog-width-full: min(100%, 106em);
        }
        /********** below is from https://github.com/thomasloven/lovelace-card-tools/blob/master/src/popup.js ***/
          ha-dialog.old-dialog {
            --mdc-dialog-min-width: 400px;
            --mdc-dialog-max-width: 600px;
            --mdc-dialog-heading-ink-color: var(--primary-text-color);
            --mdc-dialog-content-ink-color: var(--primary-text-color);
            --justify-action-buttons: space-between;
          }
          @media all and (max-width: 450px), all and (max-height: 500px) {
            ha-dialog.old-dialog {
              --mdc-dialog-min-width: 100vw;
              --mdc-dialog-max-width: 100vw;
              --mdc-dialog-min-height: 100%;
              --mdc-dialog-max-height: 100%;
              --mdc-shape-medium: 0px;
              --vertial-align-dialog: flex-end;
            }
          }

          ha-dialog-header {
            flex-shrink: 0;
            color: var(--primary-text-color);
            background-color: var(--secondary-background-color);
          }

          @media all and (max-width: 450px), all and (max-height: 500px) {
            ha-dialog-header {
              background-color: var(--app-header-background-color);
              color: var(--app-header-text-color, white);
            }
          }

          @media all and (min-width: 451px) and (min-height: 501px) {
            ha-dialog.old-dialog {
              --mdc-dialog-max-width: 90vw;
            }
            .content-old {
              width: 400px;
            }
            :host([large]) .content-old {
              width: calc(90vw - 48px);
            }
          }
    `;
}

class Alert2Tools {
    static get fireEvent() { return jFireEvent; }
    static get createDialog() { return jCreateDialog; }
    static get html() { return html; }
    static set debounceMs(v) { gDebounceMs = v; }
    static get DisplayValMonitor() { return DisplayValMonitor; }
    static get SupersedeMgr() { return SupersedeMgr; }
};

let gDebounceMs = 750;



//
// --------------------------------------------------------------------------------
// Logic for  Alert Manger
//

    
class Alert2Manager extends LitElement {
    static properties = {
        open: {},
        large: {reflect: true, type: Boolean},
        _hass: { state: true },
        _searchTxt: { state: true },
        _searchStatus: { state: true },
        _showUpgradeAlert: { state: true },
        //hass: { attribute: false },
    }
    constructor() {
        super();
        this._hass = null;
        this._config = null;
        this.fetchD = debounce(this.updateSearch.bind(this), gDebounceMs);
        this._searchTxt = '';
        this._searchStatus = { inProgress: false, rez: null, error: null };
        this._numErrs = 0;
        this._showUpgradeAlert = '';
    }
    set hass(newHass) {
        const oldHass = this._hass;
        this._hass = newHass;
        if (this._hass) {
            this._showUpgradeAlert = checkJsUpgradeAlert(this._hass);
            if (!haformLoadStarted) {
                loadHaForm(this._hass).then( ()=>{ } );
            }
        }
    }
    setConfig(config) {
        this._config = config;
    }
    connectedCallback() {
        super.connectedCallback();
        this.fetchD(); // update starts in 750ms
    }
    async updateSearch() {
        this._searchStatus.inProgress = true;
        this.requestUpdate();
        let retv = null;
        try {
            retv = await this._hass.callApi('POST', 'alert2/manageAlert',
                                            { search: { str: this._searchTxt } });
        } catch (err) {
            this._numErrs += 1;
            if (this._numErrs > 20) {
                console.error('search error', err);
                this._searchStatus = { inProgress: false, error: 'http err: ' + JSON.stringify(err),
                                       rez: null };
                setTimeout(()=>{ this.updateSearch(); }, 10000);
            } else {
                // we're hopefully starting up
                setTimeout(()=>{ this.updateSearch(); }, 2000);
            }
            return;
        }
        this._numErrs = 0;
        retv.results.sort((a,b)=>{ return a.domain == b.domain ? (a.name > b.name ? 1 : -1) : (a.domain > b.domain ? 1 : -1) });
        this._searchStatus = { inProgress: false, error: null, rez: retv };
    }
    _change(ev) {
        let value = ev.detail?.value || ev.target.value;
        this._searchTxt = value;
        this._searchStatus.error = null;
        this.requestUpdate();
        this.fetchD();
    }
    // el has { uiId, id, domain, name }
    entClick(ev, el) {
        let innerElem = document.createElement('alert2-create');
        innerElem.hass = this._hass;
        innerElem.entInfo = el;
        innerElem.didSomethingCb = ()=>{
            //console.log('didSomethingCb in alert2-create', this);
            this.fetchD();
        };
        jCreateDialog(this, 'Edit alert', innerElem);
    }
    getSearchStatus() {    return this._searchStatus;    } // for testing
    render() {
        if (!this._hass) {
            return html`<div>Loading.. waiting for hass to load</div>`;
        }
        //console.log(this._searchStatus);
        let errorHtml = this._searchStatus.error ?
            html`<ha-alert alert-type=${"warning"} style="display: inline-block;">${this._searchStatus.error}</ha-alert>` : "";
        let resultHtml = '';
        if (this._searchStatus.rez) {
            if (this._searchStatus.rez.results.length > 0) {
                let alist = [];
                for (let idx = 0 ; idx < this._searchStatus.rez.results.length ; idx++) {
                    let el = this._searchStatus.rez.results[idx];
                    if (idx == 0 || el.domain != this._searchStatus.rez.results[idx-1].domain) {
                        alist.push(html`<div class="domainheader">${el.domain}</div>`);
                    }
                    let errTxt = html``;
                    if (el.failedToLoad) {
                        errTxt = html`<span class="loadFailure" style="color: red"> -- failed to load. See alert2.alert2_error notification</span>`;
                    }
                    alist.push(html`<div class="anent" @click=${(ev)=>{ this.entClick(ev, el);}}>${el.id}${errTxt}</div>`);
                    if (el.id.startsWith('sensor.alert2generator_')) {
                        let stateObj = this._hass.states[el.id];
                        //console.log(el.id, stateObj);
                        if (stateObj && Object.hasOwn(stateObj.attributes, 'generated_ids')) {
                            let ids = stateObj.attributes['generated_ids'];
                            let entsHtml = [];
                            let outerThis = this;
                            ids.forEach((anId)=> {
                                let aclick = function(ev) {
                                    let elem = ev.target;
                                    popupMoreinfo(outerThis._hass, elem, anId);
                                }
                                entsHtml.push(html`<div class="genEntDiv" @click=${aclick}>${anId}</div>`);
                            });
                            alist.push(html`<details><summary>${ids.length} entities</summary>${entsHtml}</div>`);
                        }
                    }
                }
                resultHtml = html`<div class="results">${alist}</div>`;
            } else {
                resultHtml = html`<div>No results</div>`;
            }
        }
        const haInput = useHaInput ? 
              html`<ha-input type="text" .value=${this._searchTxt} .autofocus=${true} @input=${this._change} ></ha-input>`:
              html`<ha-textfield type="text" .value=${this._searchTxt} autofocus @input=${this._change} ></ha-textfield>`;
        return html`<ha-card>
            <h1 class="card-header"><div class="name">Alert2 Manager</div></h1>
            ${this._showUpgradeAlert}
            <div class="card-content">
              <div style="display:flex; align-items: center; margin-bottom: 0.3em;">
                  <!-- this should really just be ha-button -->
                  <ha-progress-button .progress=${false}
                    .appearance=${"plain"}
                    @click=${this.editDefaults}>Edit defaults</ha-progress-button>
                  <ha-progress-button .progress=${false}
                    .appearance=${"plain"}
                    @click=${this.createNew}>Create new alert</ha-progress-button>
                  <ha-progress-button .progress=${false}
                    .appearance=${"plain"}
                    @click=${this.refresh}>Refresh</ha-progress-button>
              </div>
              <div style="margin-bottom: 1em; display: flex; align-items: center;">
                  <div style="margin-right: 0.6em;">Search:</div>${haInput}
              </div>
              <div>
                  ${this._searchStatus.inProgress ? html`<ha-circular-progress class="render-spinner" indeterminate size="small" style="display: inline-block;"></ha-circular-progress>` : ''}
                  ${errorHtml}
                  ${resultHtml}
              </div>
            </div>
          </ha-card>`;
    }
    async refresh(ev) {
        this.fetchD();
    }
    async createNew(ev) {
        let innerElem = document.createElement('alert2-create');
        innerElem.hass = this._hass;
        innerElem.didSomethingCb = ()=>{
            //console.log('didSomethingCb in createNew', this);
            this.fetchD();
        };
        jCreateDialog(this, 'Create/edit alert', innerElem);
    }
    async editDefaults(ev) {
        let innerElem = document.createElement('alert2-edit-defaults');
        innerElem.hass = this._hass;
        jCreateDialog(this, 'Edit defaults', innerElem);
    }
    static styles = css`
      .card-header {
        display: flex;
        justify-content: space-between;
      }
      .card-header .name {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
      }
      .header {
        border-top-left-radius: var(--ha-card-border-radius, 12px);
        border-top-right-radius: var(--ha-card-border-radius, 12px);
        margin-bottom: 16px;
        overflow: hidden;
      }
      .footer {
        border-bottom-left-radius: var(--ha-card-border-radius, 12px);
        border-bottom-right-radius: var(--ha-card-border-radius, 12px);
        margin-top: -16px;
        overflow: hidden;
      }
      .domainheader {
         font-size: 0.9em;
         font-weight: bold;
         margin-bottom: -0.7em;
      }
      /* putting details padding here just to pick up the same padding-bottom */
      .anent, details {
          padding: 0.7em 0 0.7em 0.7em;
      }
      .anent {
          cursor: pointer;
      }
      .anent:hover {
          background-color: var(--secondary-background-color);
      }
      details {
         padding-left: 1.5em;
         margin-top: -1.5em;
      }
      details > div {
         padding-left: 1em;
         user-select: text;
         cursor: pointer;
      }

    `;
};

function isFloat(a) {
    let v = Number(a);
    return !isNaN(v);
}
function makeEnum(obj) {
    return new Proxy(obj, { get(target, name) { if (obj[name]) { return obj[name] } else { throw new Error(`field ${name} not in obj`); } } });
}
function debounce(callback, wait) {
  let timeoutId = null;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => {
      callback(...args);
    }, wait);
  };
}
function displayStr(tval) {
    return JSON.stringify(tval);
}

//let TopTypes = makeEnum({ COND:  'cond', EVENT:  "event", GENERATOR: "generator" });
const FieldTypes = makeEnum({ TEMPLATE: 'template', FLOAT:  "float", STR: "str", BOOL: 'bool' });
const TemplateTypes = makeEnum({ LIST: 'list', SINGLE:'single' }) //, CONDITION: 'condition', STRING: 'str' });

class Alert2CfgField extends LitElement {
    static properties = {
        hass: { attribute: false },
        name: {  },
        type: {  }, // FieldTypes
        templateType: {  },
        namePrefix: {},
        required: { type: Boolean }, // 'type' is so can specify as attribute rather than prop

        defaultP: { attribute: false },
        savedP: { attribute: false },
        currP: { attribute: false },
        genResult : { attribute: false },
        expanded: { attribute: false },

        renderInfo: { state: true },
        //showRendered: { state: true },
    }
    static shadowRootOptions = {...LitElement.shadowRootOptions, delegatesFocus: true};
    constructor() {
        super();
        this.expanded = false;
        this.required = false; // default
        this.renderD = debounce(this.doRenderTemplate.bind(this), gDebounceMs);
        this.renderInfo = { rendering: false, error: null, result: undefined };
        this.focusOnce = false;
        this.addEventListener('focus', this._handleFocus);
        //this.showRendered = false;
        //this.addEventListener("focusin", (event) => { console.log('focusin'); });
        //this.addEventListener("focusout", (event) => { console.log('focusout'); });
    }
    connectedCallback() {
        super.connectedCallback();
        //console.log('created Alert2CfgField', this.name, gDebounceMs);
        if (!this.currP) {
            throw new Error("this.currP undefined");
        }
    }
    shouldUpdate(changedProps) {
        if (changedProps.has('genResult') || changedProps.has('currP')) {
            this.renderD();
        }
        return true;
    }
    async doRenderTemplate() {
        let value = uToE(this.getValue());
        //console.log('doRenderTemplate', this.name, value);
        if (!value) {
            this.renderInfo = { rendering: false, error: null, result: undefined };
            if (this.name == 'generator') {
                jFireEvent(this, "generator-result", { generatorResult: null });
            }
            return;
        }
        this.renderInfo.rendering = true; // = { rendering: true, error: null, result: null };
        let nameToUse = (this.namePrefix? (this.namePrefix+'.') : '') + this.name;
        let retv;
        let extraVars = this.genResult ? this.genResult.firstElemVars : {};
        this.requestUpdate(); // since changed renderInfo
        try {
            retv = await this.hass.callApi('POST', 'alert2/renderValue',
                                           //{ type: this.templateType, txt: value });
                                           { txt: value, name: nameToUse, extraVars: extraVars });
        } catch (err) {
            this.renderInfo = { rendering: false, error: 'http err: ' + JSON.stringify(err),
                                result: undefined };
            return;
        }
        //console.log('doRenderTemplate RESPONSE ', this.name, retv);
        let resp = { rendering: false, error: null, result: null };
        if (Object.hasOwn(retv, 'error')) {
            resp.error = retv.error;
        }
        if (Object.hasOwn(retv, 'rez')) {
            //console.log(this.name, ' got render result ', retv.rez);
            resp.result = retv.rez;
        }
        if (!Object.hasOwn(retv, 'error') && !Object.hasOwn(retv, 'rez')) {
            this.renderInfo = { rendering: false, error: 'bad result: ' + JSON.stringify(retv),
                                result: undefined };
        } else {
            this.renderInfo = resp; // could be null
            if (this.name == 'generator') {
                jFireEvent(this, "generator-result", { generatorResult: resp.result });
            }
        }
        //console.log('doRenderTemplate FINALY ', this.name, this.renderInfo);
    }
    setConfig(config) {
        this._cardConfig = config;
    }
    _handleFocus(ev) {
        //console.log('_handleFocus', ev.target.nodeName);
        return true;
        //this.expanded = true;
        //this.focusOnce = true;
        //jFireEvent(this, "expand-click", { expanded: this.expanded });
        // TODO - should this call renderD()?
    }
    _click(ev) {
        this.expanded = !this.expanded;
        if (this.expanded) {
            this.focusOnce = true;
        }
        jFireEvent(this, "expand-click", { expanded: this.expanded });
        // this.renderD() just so we update if, e.g. generator was changed and user is checking out this
        // particular field to see what the effect was
        this.renderD(); 
    }
    _change(ev) {
        //this.showRendered = true;
        let value = ev.detail?.value || ev.target.value;
        //console.log(`_change happend to ${this.name} with value=${value}`);
        let parentP = this.currP;
        if (this.namePrefix) {
            parentP = parentP[this.namePrefix];
        }
               
        if (value.trim() === '') {
            if (parentP) {
                delete parentP[this.name];
                if (this.namePrefix && (Object.keys(parentP).length == 0)) {
                    delete this.currP[this.namePrefix];
                }
            } // otherwise no entry to delete
        } else {
            if (parentP === undefined) { // means must be using namePrefix
                this.currP[this.namePrefix] = {};
                parentP = this.currP[this.namePrefix];
            }
            parentP[this.name] = value;
        }
        this.renderD();
        jFireEvent(this, "change", { });
    }
    getValue() {
        if (this.namePrefix) {
            if (this.currP[this.namePrefix]) {
                return this.currP[this.namePrefix][this.name];
            }
            return null;
        }
        return this.currP[this.name];
    }
        
    async firstFocus() {
        await this.updateComplete;
        //console.log(this.shadowRoot.querySelectorAll('ha-textfield'));
        //console.log(this.shadowRoot.querySelectorAll('ha-code-editor'));
        const haInputTag = useHaInput ? 'ha-input' : 'ha-textfield';
        let els = this.shadowRoot.querySelectorAll(`${haInputTag}, ha-code-editor`);
        //console.log(els);
        if (els) {
            console.log('focusing on ', els[0].nodeName);
            if (els[0].nodeName == haInputTag.toUpperCase()) {
                els[0].focus();
            } else {
                let tries = 0;
                let checkInt = setInterval(()=>{
                    tries += 1;
                    let subel = els[0].shadowRoot.querySelector('div.cm-content');
                    if (subel) { // code editor might aready have been closed
                        subel.focus();
                        clearInterval(checkInt);
                    } else {
                        if (tries > 15) {
                            console.warn('ha-code-editor element did not materialize to get focus within ~5s');
                            clearInterval(checkInt);
                        }
                    }
                }, 300);
            }
            //this.addEventListener("focusin", (event) => { console.log('focusin', event); });
            this.focusOnce = false;
        }
    }
    // ha-code-editor uses tab to insert spaces.
    // We want to recapture tab so browser can use it to switch between input elements
    _codeKeydown(ev) {
        if (ev.keyCode === 9) {
            ev.stopPropagation();
        }
        return true;
    }
    render() {
        if (!this.hass) { return "waiting for hass"; }
        let value = uToE(this.getValue());
        let origValue = uToE(this.savedP[this.name]);
        //console.log('render', this.name, value);
        let unsavedChange = html`<span style=${(value == origValue) ? 'visibility: hidden;':''}>*</span>`;
        let hasDefault = this.defaultP && Object.hasOwn(this.defaultP, this.name);
        let defaultValue = hasDefault ? uToE(this.defaultP[this.name]) : '';
        let finalValue = (hasDefault && value == '') ? defaultValue : value;
        
        let editElem;
        if ([FieldTypes.STR, FieldTypes.FLOAT, FieldTypes.BOOL].includes(this.type)) {
            const aType = (this.type == FieldTypes.FLOAT) ? 'number' : 'text';
            editElem = useHaInput ? 
                html`<ha-input .required=${this.required} type=${aType} .value=${value} .autofocus=${true}
                                       @input=${this._change} ></ha-input>`:
                html`<ha-textfield .required=${this.required} type=${aType} .value=${value} autofocus
                                       @input=${this._change} ></ha-textfield>`;
        } else if (this.type == FieldTypes.TEMPLATE) {
            editElem = html`<ha-code-editor mode="jinja2" .hass=${this.hass} .value=${value} .readOnly=${false}
                  autofocus autocomplete-entities autocomplete-icons @value-changed=${this._change} dir="ltr"
                  linewrap style="display: block; min-width: 10em;"
                   @keydown=${{handleEvent: (ev) => this._codeKeydown(ev), capture: true}}
                   ></ha-code-editor>`;
        } else {
            throw new Error(`Unknown cfg field type=${this.type}`);
        }
        if (this.focusOnce) {
            // I wish we had access to Lit's ref() directive.  Sigh.
            this.firstFocus(); // async func
        }
        let renderHtml = '';
        let helpHtml = '';
        if (this.expanded) {
            helpHtml = html`<slot name="help" class="shelp"></slot>`;
        }
        if (true || this.showRendered) {
            let renderedStr = ''+displayStr(this.renderInfo.result);
            let lenStr = '';
            if (this.type == FieldTypes.STR) {
            } else if (this.type == FieldTypes.FLOAT) {
            } else if (this.type == FieldTypes.BOOL) {
            } else if (this.type == FieldTypes.TEMPLATE) {
                if (this.name == 'generator') {
                    if (this.renderInfo.result !== undefined && this.renderInfo.result !== null) {
                        let firstOnly = '';
                        if (this.renderInfo.result.len > this.renderInfo.result.list.length) {
                            firstOnly = `, showing first ${this.renderInfo.result.list.length}`;
                        }
                        lenStr = html` (len=${this.renderInfo.result.len}${firstOnly})`;
                        renderedStr = html`${displayStr(this.renderInfo.result.list)}<br>
                                           First element vars: ${displayStr(this.renderInfo.result.firstElemVars)}`;
                    }
                }
                if (0) {
                    if (this.templateType == TemplateTypes.LIST && this.renderInfo.result !== undefined) {
                        let firstOnly = '';
                        if (this.name == 'generator') {
                            if (this.renderInfo.result.len > this.renderInfo.result.list.length) {
                                firstOnly = `showing first ${this.renderInfo.result.list.length}`;
                            }
                            renderedStr = JSON.stringify(this.renderInfo.result);
                        } else {
                            renderedStr = JSON.stringify(this.renderInfo.result);
                            lenStr = html` (len=${this.renderInfo.result.length}${firstOnly})`;
                            //console.log('list result', this.renderInfo.result);
                        }
                    }
                }
            } else {
                console.error('wrong type for field', this.name, this.type);
            }
            if (!lenStr && Array.isArray(this.renderInfo.result)) {
                //console.log('got array result', this.renderInfo.result);
                lenStr = html` (len=${this.renderInfo.result.length})`;
            }
            renderHtml = (this.renderInfo.result !== undefined) ? html`<div style="display: flex; flex-flow: row; align-items:center;" class="renderResult">Render result${lenStr}:<div class="rendered" style="margin-left: 1em;">${renderedStr}</div></div>`:"";
        }
        // Final value combinbg default as inputted value
        //<code class="avalue">${displayStr(finalValue)}</code>
        //
        // vertical error bar
        //${this.renderInfo.error != null ? html`<div style="background: var(--warning-color); height:1.5em; width: 0.3em; margin-right:0.3em;"></div>`:""}
        //console.log(this.name, 'default', defaultValue, typeof(defaultValue));
        //let helpButton = `<ha-icon-button><ha-icon .icon=${"mdi:help-circle"} ></ha-icon></ha-icon-button>`;
        let helpButton = html`<ha-icon .icon=${"mdi:help-circle"} class="helpi"></ha-icon>`;
        //<mwc-icon-button .label=${"dismiss"} dialogAction="cancel" slot="navigationIcon" ><ha-icon .icon=${"mdi:close"} ></ha-icon>
        //    </mwc-icon-button>
        //let helpButtom = html`<ha-icon-button .path=${helpPath} class="help-icon"></ha-icon-button>`;
        return html`<div class="cfield">
                      <div class=${this.namePrefix?"threshname":"name"} @click=${this._click} >
                           ${unsavedChange}<span>${this.name}${this.required ? "*":""}:</span>
                          ${helpButton}
                      </div>
                      <div class="editfs" style="display: flex; flex-flow: column;">
                         <div class="avalue">${editElem}</div>
                         ${hasDefault ? html`<div class="defaultInfo">Default if empty: <code>${displayStr(defaultValue)}</code></div>`:''}
                         <div class="renderInfo">
                            ${this.renderInfo.rendering ?
                              html`<ha-circular-progress class="render-spinner" indeterminate size="small" style="display: inline-block;" ></ha-circular-progress>` : ''}
                            ${this.renderInfo.error != null ?
                              html`<ha-alert alert-type=${"warning"} style="display: inline-block;">${this.renderInfo.error}</ha-alert>` : ""}
                            ${renderHtml}
                         </div>
                         <div style="margin-left: 0em;">${helpHtml}</div>
                      </div>
                    </div>`;
    }
    static styles = css`
       .renderInfo {
          display: flex;
          flex-direction: row;
        }
       .cfield {
          display: flex;
          flex-flow: row wrap;
          align-items: start;
          margin-bottom: 1em;
       }
       .name, .threshname {
          margin-right: 1em;
          margin-top: 1em;
          cursor: pointer;
          /*min-width: 10em;*/
          flex: 0 0 14em;
          display: flex;
          align-items: center;
       }
       .threshname {
          flex: 0 0 12.5em;
       }
       .editfs {
          flex: 1 1 30em;
          /*max-width: 50em;*/
       }
       pre {
          margin: 0;
       }
       .rendered {
          font-family: ui-monospace, monospace;
       }
       ha-icon.helpi {
        --mdc-icon-size:1.3em;
        margin-left: 0.3em;
       } 
     }
    `;
}

function uToE(val) { return (val == undefined) ? '' : (val); }
// unused
function closeOtherExpanded(elem, ev) {
    // Unexpand other fields when one expands.
    let expanded = ev.detail?.expanded;
    let targetEl = ev.target;
    //console.log('expandClick', expanded, this.nodeName, ev);
    if (expanded) {
        let els = elem.shadowRoot.querySelectorAll('alert2-cfg-field');
        els.forEach((el)=> {
            if (el !== targetEl) {
                el.expanded = false;
            }
        });
    }
}

const helpCommon = {
    notifier: html`Name of notifiers to use for sending notifications. Can be:
                  <div class="extable">
                       <div>Single notifier or name of entity with list:</div>
                           <div class="exval"><code>telegram1</code><div class="bigor">or</div><code>"telegram1"</code><div class="bigor">or</div><code>sensor.my_notifier_list</code></div>
                       <div>List of notifiers (YAML flow):</div><div class="exval"><code>[ telegram1, telegram2 ]</code></div>
                       <div>List of notifiers (YAML):</div><div class="exval"><pre>- telegram1\n- telegram2</code></pre></div>
                       <div>Template producing list of notifiers:</div><div class="exval"><code>{{ [ "tel1", "tel2" ] }}</code></div>
                       <div>null for no notifications:</div><div class="exval"><code>null</code></div>
                  </div>`,
    summary_notifier: html`Name of notifiers to use for sending summary notifications. Can be:
                  <div class="extable">
                       <div>Single notifier or name of entity with list</div>
                           <div class="exval"><code>telegram1</code><div class="bigor">or</div><code>"telegram1"</code><div class="bigor">or</div><code>sensor.my_notifier_list</code></div>
                       <div>List of notifiers (YAML flow):</div><div class="exval"><code>[ telegram1, telegram2 ]</code></div>
                       <div>List of notifiers (YAML):</div><div class="exval"><pre>- telegram1\n- telegram2</code></pre></div>
                      <div>Template producing list of notifiers:</div><div class="exval"><code>{{ [ "tel1", "tel2" ] }}</code></div>
                       <div>Truthy to summary notify using <code>notifier</code>:</div><div class="exval"><code>yes</code></div>
                       <div>Falsey or null for no summary notifications:</div><div class="exval"><code>false</code></div>
                  </div>`,
    done_notifier: html`Name of notifiers to use for sending notifications that a condition alert has stopped firing. Can be:
                  <div class="extable">
                       <div>Single notifier or name of entity with list</div>
                           <div class="exval"><code>telegram1</code><div class="bigor">or</div><code>"telegram1"</code><div class="bigor">or</div><code>sensor.my_notifier_list</code></div>
                       <div>List of notifiers (YAML flow):</div><div class="exval"><code>[ telegram1, telegram2 ]</code></div>
                       <div>List of notifiers (YAML):</div><div class="exval"><pre>- telegram1\n- telegram2</code></pre></div>
                      <div>Template producing list of notifiers:</div><div class="exval"><code>{{ [ "tel1", "tel2" ] }}</code></div>
                       <div>Truthy to notify using <code>notifier</code>:</div><div class="exval"><code>yes</code></div>
                       <div>Falsey or null for no done notifications:</div><div class="exval"><code>false</code></div>
                  </div>`,
    annotate_messages: html`If true, add extra context information to notifications, like number of times alert has fired since last notification. Can be:
                  <div class="extable">
                         <div>Truthy (true/yes/on/1 or opposites)</div><div class="exval"><code>true</code></div>
                  </div>`,
    persistent_notifier_grouping: html`Controls whether multiple notifications for the same alert to the persistent notifier are collapsed into a single persistent notification or not. Can be:
                  <div class="extable">
                         <div>Each notification is distinct</div><div class="exval"><code>separate</code></div>
                         <div>Notifications for the same alert become a single one</div><div class="exval"><code>collapse</code></div>
                         <div>"collapse" and notification is dismissed when alert stops firing (for condition alerts)</div><div class="exval"><code>collapse_and_dismiss</code></div>
                  </div>`,
    reminder_frequency_mins: html`Interval in minutes between reminders that a condition alert continues to fire. Can be:
                  <div class="extable">
                          <div>Single float (>= 0.01)</div><div class="exval"><code>10</code></div>
                         <div>List of floats:</div><div class="exval"><code>[ 10, 15 ]</code></div>
                  </div>`,
    exception_ignore_regexes: html`For alert2.alert2_global_exception and alert2.mycomponent_unhandled_exception.  A list of regexes. If exception + stack trace matches any of the regexes, the exception will be logged but not reported. See the <a href="https://github.com/redstone99/hass-alert2#tracked">Tracked</a> section of the main Alert2 documentation for info and example on how to set this field. Can be:
                  <div class="extable">
                          <div>Single string</div><div class="exval"><code>foo_component</code></div>
                         <div>List of strings:</div><div class="exval"><code>[ "foo", "bar" ]</code></div>
                  </div>`,
    supersede_debounce_secs: html`Seconds to wait after alert activity before notifying, to see if a superseding alert becomes active. Can be:
                  <div class="extable">
                          <div>Single float (>= 0)</div><div class="exval"><code>0.5</code></div>
                  </div>`,
    throttle_fires_per_mins: html`Limit notifications of alert firings based on a list of two numbers [X, Y]. If the alert has fired and notified more than X times in the last Y minutes, then throttling turns on and no further notifications occur until the rate drops below the threshold. Can be:
                  <div class="extable">
                          <div>List of [int, float]</div><div class="exval"><code>[3, 5.2]</code></div>
                          <div>Null to disable throttling</div><div class="exval"><code>null</code></div>
                  </div>`,
    priority: html`A value: low, medium or high. Affects display of alert in Alert2 Overview card. Can be:
                  <div class="extable">
                          <div>Low, medium or high</div><div class="exval"><code>low</code></div>
                  </div>`,
    icon: html`Icon to display next to alert name. Defaults to "mdi:alert". Can be:
                  <div class="extable">
                          <div>prefix:name</div><div class="exval"><code>mdi:alert</code></div>
                  </div>`,
    
    domain: html`Alert entity name is alert2.[domain]_[name]. Can be:
                  <div class="extable">
                       <div>Letters, numbers, underscore</div><div class="exval"><code>test_domain</code></div>
                  </div>`,
    name: html`Alert entity name is alert2.[domain]_[name]. Can be:
                  <div class="extable">
                       <div>Letters, numbers, underscore</div><div class="exval"><code>too_hot</code></div>
                  </div>`,
    friendly_name: html`Name to display instead of the entity name. Can be:
                  <div class="extable">
                       <div>Simple string</div><div class="exval"><code>my test alert</code></div>
                       <div>Template (eg using generator variables)</div><div class="exval"><code>battery {{genElem}}</code></div>
                  </div>`,
    condition: html`If specified, must be true-truthy for alert to fire. Can be:
                  <div class="extable">
                       <div>Truthy value (true/yes/on/1 or opposites)</div><div class="exval"><code>on</code></div>
                       <div>Entity name containing truthy value</div><div class="exval"><code>binary_sensor.trouble</code></div>
                       <div>Template evaluating to truthy</div><div class="exval"><code>{{ states('sensor.foo')|float > 3 }}</code></div>
                  </div>`,
    condition_on: html`Alert starts firing when specified condition becomes true. Can be:
                  <div class="extable">
                       <div>Entity name containing truthy value</div><div class="exval"><code>binary_sensor.trouble</code></div>
                       <div>Template evaluating to truthy</div><div class="exval"><code>{{ states('sensor.foo')|float > 3 }}</code></div>
                  </div>`,
    condition_off: html`Alert stops firing when specified condition becomes true. Can be:
                  <div class="extable">
                       <div>Entity name containing truthy value</div><div class="exval"><code>binary_sensor.trouble</code></div>
                       <div>Template evaluating to truthy</div><div class="exval"><code>{{ states('sensor.foo')|float > 3 }}</code></div>
                  </div>`,
    trigger: html`Alert when the trigger triggers if any condition specified is also true. Can be:
                  <div class="extable">
                       <div>A YAML <a href="https://www.home-assistant.io/docs/automation/trigger/">trigger</a> spec written using YAML flow notation.</div><div class="exval"><pre>[{'platform':'state','entity_id':'sensor.zz'}]\n[{'trigger': 'mqtt', 'topic': 'living_room/switch/ac', 'payload': "on"}]</pre></div>
                  </div>`,
    trigger_on: html`Alert starts firing when trigger triggers if any condition specified is also true. Can be:
                  <div class="extable">
                       <div>A YAML <a href="https://www.home-assistant.io/docs/automation/trigger/">trigger</a> spec written using YAML flow notation.</div><div class="exval"><pre>[{'platform':'state','entity_id':'sensor.zz'}]\n[{'trigger': 'mqtt', 'topic': 'living_room/switch/ac', 'payload': "on"}]</pre></div>
                  </div>`,
    trigger_off: html`Alert stops firing when trigger triggers if any condition specified is also true. Can be:
                  <div class="extable">
                       <div>A YAML <a href="https://www.home-assistant.io/docs/automation/trigger/">trigger</a> spec written using YAML flow notation.</div><div class="exval"><pre>[{'platform':'state','entity_id':'sensor.zz'}]\n[{'trigger': 'mqtt', 'topic': 'living_room/switch/ac', 'payload': "on"}]</pre></div>
                  </div>`,
    value: html`A float or template or entity name evaluating to a float. Can be:
                  <div class="extable">
                       <div>Float</div><div class="exval"><code>3.5</code></div>
                       <div>Entity name</div><div class="exval"><code>sensor.room_temperature</code></div>
                       <div>Template</div><div class="exval"><code>{{ states('sensor.foo') }}</code></div>
                  </div>`,
    hysteresis: html`Compare <code>value</code> to limits using hysteresis. Threshold is considered exceeded if value exceeds min/max, but does not reset until value increases past min+hysteresis or decreases past max-hysteresis. Can be:
                  <div class="extable">
                       <div>Float</div><div class="exval"><code>4.2</code></div>
                       <div>Entity name</div><div class="exval"><code>input_number.temp_leeway</code></div>
                       <div>Template</div><div class="exval"><code>{{ states('sensor.foo') }}</code></div>
                  </div>`,
    maximum: html`Alert fires if <code>value</code> is above maximum. Can be:
                  <div class="extable">
                       <div>Float</div><div class="exval"><code>30</code></div>
                       <div>Entity name</div><div class="exval"><code>input_number.temp_max</code></div>
                       <div>Template</div><div class="exval"><code>{{ states('sensor.foo') }}</code></div>
                  </div>`,
    minimum: html`Alert fires if <code>value</code> is below minimum. Can be:
                  <div class="extable">
                       <div>Float</div><div class="exval"><code>-2</code></div>
                       <div>Entity name</div><div class="exval"><code>input_number.temp_min</code></div>
                       <div>Template</div><div class="exval"><code>{{ states('sensor.foo') }}</code></div>
                  </div>`,
    delay_on_secs: html`Number of seconds that any condition must be true and any threshold specified must be exceeded before the alert starts firing. Can be:
                  <div class="extable">
                       <div>Float</div><div class="exval"><code>5</code></div>
                  </div>`,
    early_start: html`By default, alert monitoring starts only once HA has fully started (i.e., after the HOMEASSISTANT_STARTED event). If early_start is true for an alert, then monitoring of that alert starts earlier, as soon as the alert2 component loads. Can be:
                  <div class="extable">
                       <div>Truthy (eg true/yes/on or opposites)</div><div class="exval"><code>false</code></div>
                  </div>`,
    generator: html`A <a href="https://github.com/redstone99/hass-alert2#generator-patterns">generator pattern</a> for declaring mulitple alerts. Can be:
                  <div class="extable">
                       <div>Single string</div><div class="exval"><code>battery1</code></div>
                       <div>List of strings</div><div class="exval"><code>[ battery1, battery2 ]</code></div>
                       <div>List of entity names</div><div class="exval"><code>[ sensor.battery1, sensor.battery2 ]</code></div>
                       <div>Entity name with list of strings</div><div class="exval"><code>sensor.my_list</code></div>
                       <div>Template producing list of strings</div><div class="exval"><code>{{ [ "a", "b" ] }}</code></div>
                       <div>Template producing list of dicts using entity_regex</div><div class="exval"><code>{{ sensors|entity_regex('sensor.my_battery(\d+)')|list }}</code></div>
                  </div>`,
    generator_name: html`Each generator creates a sensor entity with the name sensor.alert2generator_[generator_name].. Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>all_batteries</code></div>
                  </div>`,
    message: html`Text to send with notifications. Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>Temperature low</code><div class="bigor">or</div><code>"Temperature low"</code></div>
                       <div>Template</div><div class="exval"><code>Temperature is {{ states('sensor.temp') }}</code></div>
                  </div>`,
    done_message: html`Message to send when a condition alert turns off. Replaces the default message. Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>Temperature low</code><div class="bigor">or</div><code>"Temperature low"</code></div>
                       <div>Template</div><div class="exval"><code>Temperature is {{ states('sensor.temp') }}</code></div>
                  </div>`,
    reminder_message: html`Message to send to remind that a condition alert is still on. Variables available are on_secs and on_time_str. Default message is "on for {{ on_time_str }}". Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>is still on</code></div>
                       <div>Template</div><div class="exval"><code>is still on. Temperature is {{ states('sensor.temp') }}</code></div>
                  </div>`,
    ack_reminder_message: html`Message to send to remind that an alert has not yet been acked. Default message is "not acked yet". Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>has not been acked yet</code></div>
                       <div>Template</div><div class="exval"><code>not acked yet. Temperature is {{ states('sensor.temp') }}</code></div>
                  </div>`,
    ack_required: html`If true, reminders will be sent that an alert has not yet been acked. Can be:
                  <div class="extable">
                         <div>Truthy (true/yes/on/1 or opposites)</div><div class="exval"><code>true</code></div>
                  </div>`,
    ack_reminders_only: html`If true, an acked alert will still send a notification when the alert stops firing. If false, an acked alert will not send a notification when the alert stops firing. Can be:
                  <div class="extable">
                         <div>Truthy (true/yes/on/1 or opposites)</div><div class="exval"><code>true</code></div>
                  </div>`,
    display_msg: html`Text to display in Alert2 Overview UI card when alert is displayed there. HTML is accepted. Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>Temperature low</code><div class="bigor">or</div><code>"Temperature low"</code></div>
                       <div>Template</div><div class="exval"><code>Temperature is {{ states('sensor.temp') }}</code></div>
                       <div>To reset inherited value</div><div class="exval"><code>null</code></div>
                  </div>`,
    title: html`Passed as the <code>title</code> parameter to the notify service call. Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>foo bar</code></div>
                       <div>Template</div><div class="exval"><code>{{ states('sensor.foo') }}</code></div>
                  </div>`,
    target: html`Passed as the <code>target</code> parameter to the notify service call. Can be:
                  <div class="extable">
                       <div>String</div><div class="exval"><code>foo bar</code></div>
                       <div>Template</div><div class="exval"><code>{{ states('sensor.foo') }}</code></div>
                  </div>`,
    data: html`Passed as the <code>data</code> parameter to the notify service call. Supports template fields. Can be:
                  <div class="extable">
                       <div>YAML dict (flow notation)</div><div class="exval"><code>{ val1: 3, val2: foo }</code></div>
                       <div>YAML dict:</div><div class="exval"><pre>val1: 3\nval2: foo</code></pre></div>
                       <div>Template</div><div class="exval"><code>{{ { 'val1': 3, 'val2': 'foo' } }}</code></div>
                  </div>`,
    skip_internal_errors: html`If true, an entity for alert2.error will not be created, you will not receive any notifications for problems with your config file or Alert2 internal errors, and such errors won't show up in the Alert2 UI card. Errors will still appear in the log file. Can be:
                  <div class="extable">
                       <div>Truthy (true/on/yes/1 or opposites)</div><div class="exval"><code>false</code></div>
                  </div>`,
    notifier_startup_grace_secs: html`Time to wait after HA starts for a notifier to be defined. Can be:
                  <div class="extable">
                       <div>Float</div><div class="exval"><code>60</code></div>
                  </div>`,
    defer_startup_notifications: html`True means no notifications are sent until notifier_startup_grace_secs passes after startup. False means send notifications as soon as the notifier is defined in HA. Or this parameter can be name of a single notifier or list of notifiers for those to defer during startup. Can be:
                  <div class="extable">
                       <div>Truthy (yes/on/true/1 or opposites)</div><div class="exval"><code>true</code></div>
                       <div>Single notifier:</div>
                           <div class="exval"><code>telegram1</code><div class="bigor">or</div><code>"telegram1"</code></div>
                       <div>List of notifiers (YAML flow):</div><div class="exval"><code>[ telegram1, telegram2 ]</code></div>
                  </div>`,
    supersedes: html`A list of domain+name pairs of alerts that this alert supersedes. Written using YAML flow syntax. Unloess you're quoting, the space after the colon is important. Can be:
                  <div class="extable">
                       <div>Single pair</div><div class="exval"><code>{ domain: test, name: foo }</code></div>
                       <div>List of pairs</div><div class="exval"><code>[{ domain: test, name: foo },{ domain: test, name: foo2 }]</code></div>
                       <div>Pair or list with quotes</div><div class="exval"><code>{domain: 'test', name: 'foo'}</code></div>
                  </div>`,
    actions_on: html`Automation action to perform each time a condition alert starts firing. Can be:
                    <div class="extable">
                       <div>A YAML <a href="https://www.home-assistant.io/docs/automation/action/">automation action</a> spec written using YAML flow notation.</div><div class="exval"><pre>{ actions: [ action: system_log.write, data: { level: info, message: some message } ] }</pre></div>
                  </div>`,
    //: html`. Can be:
    //              <div class="extable">
    //                   <div></div><div><code></code></div>
    //              </div>`,
    
};

//let topCommon = html``;

const extableCss = css`
    div[slot="help"] > ul {
       margin-top: 0.1em;
       margin-bottom: 0;
    }
    div.extable {
       display: grid;
       grid-template-columns: repeat(2,minmax(auto,max-content));
       column-gap: 1.5em;
       margin-left: 1em;
    }
    div.extable div.bigor {
        display: inline-block;
        width: 3.5em;
        text-align: center;
    }
    div.extable pre {
        margin: 0;
        display: inline-block; /* so :before shows up on same line */
    }
    div.extable div.exval:before {
        content: "e.g. ";
        vertical-align: top;
        margin-right: 0.5em;
    }
`;

class Alert2EditDefaults extends LitElement {
    static properties = {
        hass: { attribute: false },
        //_topConfigs: { attribute: false },
        // TEMPORARY for TESTING!!!!!!!
        _topConfigs: { state: true },
        _serverErr: { state: true },
        _saveInProgress: { state: true },
    }
    constructor() {
        super();
        this._saveInProgress = false;
    }
    setConfig(config) {
        this._cardConfig = config;
    }
    connectedCallback() {
        super.connectedCallback();
        this.refresh();
    }
    //shouldUpdate(changedProps) {
    //    if (changedProps.has('hass')) {
    //        console.log('Alert2EditDefaults hass updated');
    //    }
    //    return true;
    //}
    async refresh() {
        //console.log('doing refresh');
        let retv;
        try {
            this._topConfigs = await this.hass.callApi('POST', 'alert2/loadTopConfig', {});
            this._topConfigs.origRawUi = JSON.parse(JSON.stringify(this._topConfigs.rawUi));
        } catch (err) {
            this._serverErr = 'http err: ' + JSON.stringify(err);
            console.error('alert2/loadTopConfig: http err', err);
            return;
        }
        console.log('editDefaults::refresh() got topConfig', this._topConfigs);
    }
    changed(ev, fieldSet) {
        let value = ev.detail?.value || ev.target.value;
        console.log('yay got change: ', value);
        fieldSet(value);
        this._serverErr = null;
    }
    async _save(ev) {
        let abutton = ev.target;
        this._saveInProgress = true;
        let rez;
        //console.log(JSON.stringify(this._topConfigs));
        try {
            rez = await this.hass.callApi('POST', 'alert2/saveTopConfig',
                                          {topConfig: this._topConfigs.rawUi});
        } catch (err) {
            this._saveInProgress = false;
            abutton.actionError();
            if (err.body && err.body.message) {
                this._serverErr = "error: " + err.body.message;
            } else {
                this._serverErr = "error: " + JSON.stringify(err);
            }
            return;
        }
        this._saveInProgress = false;
        if (rez.error) {
            abutton.actionError();
            this._serverErr = "error: " + rez.error;
            return;
        }
        // Update _topConfigs mostly cuz server filters out empty fields,
        // and so we don't drift between browser and server state re configs
        this._topConfigs = rez;
        this._topConfigs.origRawUi = JSON.parse(JSON.stringify(this._topConfigs.rawUi));
        abutton.actionSuccess();
    }
    // Unexpand other fields when one expands.
    expandClick(ev) {
        //closeOtherExpanded(this, ev);
    }
    render() {
        if (!this.hass) { return "waiting for hass"; }
        if (!this._topConfigs) {
            if (this._serverErr) {
                return html`<div>${this._serverErr}</div>`;
            }
            return "waiting for _topConfigs";
        }
        return html`
         <div class="container" >
            <div style="margin-bottom: 1em;">
                Set defaults and parameters affecting all alerts. Click "Save" (at the bottom) when done.
                <ul><li>Values set here override any values set in YAML
               <li>You can go to "Developer tools" -> YAML and click on "Alert2" to reload both YAML and UI Alert2 alerts with the new settings. <code>notifier_startup_grace_secs</code> and <code>defer_startup_notifications</code> require an HA restart.
                <li>Click on any field name for brief help and see <a href="https://github.com/redstone99/hass-alert2">https://github.com/redstone99/hass-alert2</a> for more complete documentation on each field.  Also useful may be <a href="https://github.com/redstone99/hass-alert2/blob/master/Recipes.md">Alert2 Recipes</a>
                <li>Fields are generally interpreted as YAML, with some logic to add quotes if writing a template.
                <li>To adjust settings for Alert2 internal alerts such as alert2_error and alert2_global_exception, create an alert with the appropriate name (eg domain=alert2 and name=global_exception). See info in the <a href="https://github.com/redstone99/hass-alert2#tracked">Tracked</a> section of the main Alert2 documentation.
                </ul>
            </div>
            <h3>Default alert parameters</h3>
            <alert2-cfg-field .hass=${this.hass} name="notifier" type=${FieldTypes.TEMPLATE}
                 templateType=${TemplateTypes.LIST} .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                  .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.notifier}</div></alert2-cfg-field>

            <alert2-cfg-field .hass=${this.hass} name="summary_notifier" type=${FieldTypes.TEMPLATE}
                 templateType=${TemplateTypes.LIST} .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                  .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.summary_notifier}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="done_notifier" type=${FieldTypes.TEMPLATE}
                 templateType=${TemplateTypes.LIST} .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                  .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.done_notifier}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="annotate_messages" type=${FieldTypes.BOOL}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.annotate_messages}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="reminder_frequency_mins" type=${FieldTypes.STR}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.reminder_frequency_mins}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="throttle_fires_per_mins" type=${FieldTypes.STR}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.throttle_fires_per_mins}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="priority" type=${FieldTypes.STR}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.priority}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="icon" type=${FieldTypes.STR}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.icon}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="supersede_debounce_secs" type=${FieldTypes.FLOAT}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.supersede_debounce_secs}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="data" type=${FieldTypes.STR}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.data}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="persistent_notifier_grouping" type=${FieldTypes.BOOL}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.persistent_notifier_grouping}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="reminder_message" type=${FieldTypes.TEMPLATE}
                 .defaultP=${this._topConfigs.rawYaml.defaults}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi.defaults}  .currP=${this._topConfigs.rawUi.defaults} >
               <div slot="help">${helpCommon.reminder_message}</div></alert2-cfg-field>

            <h3>Top-level options</h3>
            <alert2-cfg-field .hass=${this.hass} name="skip_internal_errors" type=${FieldTypes.BOOL}
                 .defaultP=${this._topConfigs.rawYaml}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi}  .currP=${this._topConfigs.rawUi} >
               <div slot="help">${helpCommon.skip_internal_errors}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="notifier_startup_grace_secs" type=${FieldTypes.FLOAT}
                 .defaultP=${this._topConfigs.rawYaml}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi}  .currP=${this._topConfigs.rawUi} >
               <div slot="help">${helpCommon.notifier_startup_grace_secs}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="defer_startup_notifications" type=${FieldTypes.STR}
                 .defaultP=${this._topConfigs.rawYaml}
                  @expand-click=${this.expandClick}
                 .savedP=${this._topConfigs.origRawUi}  .currP=${this._topConfigs.rawUi} >
               <div slot="help">${helpCommon.defer_startup_notifications}</div></alert2-cfg-field>
            
            <div style="margin-top: 0.5em 0 2em 2em; margin-left: 2em;">
                 <ha-progress-button .progress=${this._saveInProgress} .appearance=${"plain"} @click=${this._save}>Save</ha-progress-button></div>
            ${this._serverErr ? html`<ha-alert alert-type=${"error"}>${this._serverErr}</ha-alert>` : ""}
         </div>`;
    }
    static styles = css`
    h3 {
       margin-bottom: 0.3em;
       margin-top: 1.5em;
    }
    h3:first-of-type {
       margin-top: 0em;
    }
    ${extableCss}
      `;
}

function yamlEscape(astr, removeNewline=true) {
    const format = /[{}\[\]&*#?|\-<>=!%@:`,]/;
    astr = astr.trim().replace('\n', ' ');
    if (astr.length > 0 && (astr[0] == '\'' || astr[0] == '"')) {
        // yaml quoted string, so don't need quotes around anything I think.
        // TODO - verify this logic is correct.
        return astr;
    }
    if (format.test(astr)) {
        return '"' + astr.replace('"', '\\"') + '"';
    } else {
        return astr;
    }
}
function hasJinjaTempl(astr) {
    const format = /{{|}}|{%|%}|{#|#}/;
    return format.test(astr);
}
function slugify(str) {
    // Allows [] for convenience below. TODO -fix.
    str = str.trim().toLowerCase();
    str = str.replace(/[^a-z0-9 ._\[\]]/g, '')
              .replace(/\s+/g, '_')
              .replace(/_+/g, '_');
  return str;
}
class Alert2Create extends LitElement {
    static properties = {
        hass: { attribute: false },
        entInfo: { attribute: false },
        // TODO - really only need the CB when create/delete/update, not on validate.
        didSomethingCb: { attribute: false },
        //topType: { state: true },
        _topConfigs: { attribute: false },
        _serverErr: { state: true },
        _opInProgress: { state: true },
        _generatorResult: { state: true },
        alertCfg: { state: true },
    }
    constructor() {
        super();
        //this.topType = TopTypes.COND;
        this.alertCfg = {};
        this._opInProgress = { op: '', inProgress: false };
    }
    setConfig(config) {
        this._cardConfig = config;
    }
    connectedCallback() {
        super.connectedCallback();
        this.init();
    }
    async init() {
        try {
            this._topConfigs = await this.hass.callApi('POST', 'alert2/loadTopConfig', {});
        } catch (err) {
            this._topConfigs = { error: 'http err: ' + JSON.stringify(err) };
        }
        if (this.entInfo) {
            try {
                this.alertCfg = await this.hass.callApi('POST', 'alert2/manageAlert',
                                                        { load: { uiId: this.entInfo.uiId } });
                console.log('initialzing alertCfg to ', this.alertCfg);
            } catch (err) {
                this._serverErr = { error: 'http err: ' + JSON.stringify(err) };
            }
        }
    }
    expandClick(ev) {
        //closeOtherExpanded(this, ev);
    }
    async _validate(ev) { await this.doOp('validate', ev); }
    async _create(ev) { await this.doOp('create', ev); }
    async _update(ev) { await this.doOp('update', ev); }
    async _delete(ev) { await this.doOp('delete', ev); }
    async doOp(opName, ev) {
        this._serverErr = null;
        let abutton = ev.target;
        if (this._opInProgress.inProgress) {
            return;
        }
        if (!this.entInfo && (opName == 'update' || opName == 'delete')) {
            abutton.actionError();
            this._serverErr = "error: no alert uiId to update/delete";
            return;
        }
        
        this._opInProgress = { op: opName, inProgress: true };
        let rez;
        //console.log(opName, 'of', this.alertCfg);
        try {
            let obj = {};
            obj[opName] = {};
            if (opName == 'create' || opName == 'validate') {
                obj[opName] = this.alertCfg;
            } else  {
                obj[opName] = { uiId: this.entInfo.uiId };
                if (opName == 'update') {
                    obj[opName].cfg = this.alertCfg;
                }
            }
            rez = await this.hass.callApi('POST', 'alert2/manageAlert', obj);
        } catch (err) {
            console.log(opName, 'CAUGHT ERR', err);
            this._opInProgress.inProgress = false;
            abutton.actionError();
            if (err.body && err.body.message) {
                this._serverErr = "error: " + err.body.message;
            } else {
                this._serverErr = "error: " + JSON.stringify(err);
            }
            this.requestUpdate();
            return;
        }
        //console.log(opName, ' OP OK? ', rez);
        this._opInProgress.inProgress = false;
        if (rez.error) {
            abutton.actionError();
            this._serverErr = "error: " + rez.error;
            return;
        }
        if (opName == 'create') {
            this.entInfo = { uiId: rez.uiId }; // could also add in domain/name/id, but not necessary
        }
        abutton.actionSuccess();
        this.requestUpdate();
        //console.log('about to call didSomethingCb');
        this.didSomethingCb();
    }
    _change(ev) {
        //console.log('editor _change');
        //if (this.alertCfg.threshold && Object.keys(this.alertCfg.threshold).length == 0) {
        //    delete this.alertCfg.threshold;
        // }
        this._serverErr = null;
        this.requestUpdate();
    }
    _generator_rez(ev) {
        this._generatorResult = ev.detail?.generatorResult;
        //console.log('_generator_rez', ev.detail, this._generatorResult);
    }
    configToYaml() {
        let yaml = 'alert2:';
        yaml += '\n  alerts:';
        let isFirst = true;
        Object.keys(this.alertCfg).forEach((fname)=> {
            yaml += `\n    ${isFirst ? "- " : "  "}`;
            isFirst = false;
            if (fname === 'threshold') {
                yaml += 'threshold:';
                Object.keys(this.alertCfg[fname]).forEach((fname2)=> {
                    yaml += `\n        ${fname2}: ${yamlEscape(this.alertCfg[fname][fname2])}`;
                });
            } else {
                let rawVal = this.alertCfg[fname].trim();
                let val;
                if (['domain','name', 'friendly_name', 'condition', 'condition_on', 'condition_off', 'message',
                     'title', 'target',
                     'annotate_messages', 'persistent_notifier_grouping', 'ack_required', 'ack_reminders_only', 'early_start', 'generator_name', 'manual_on', 'manual_off',
                     'done_message', 'reminder_message', 'ack_reminder_message', 'supersede_debounce_secs', 'display_msg', 'delay_on_secs',
                     'priority','icon'].includes(fname)) {
                    val = yamlEscape(rawVal);
                } else if (['actions_on', 'trigger', 'trigger_on', 'trigger_off', 'data', 'throttle_fires_per_mins',
                            'reminder_frequency_mins', 'exception_ignore_regexes',
                            ].includes(fname)) {
                    val = rawVal;
                } else if (['generator', 'notifier', 'summary_notifier', 'done_notifier', 'supersedes'].includes(fname)) {
                    if (hasJinjaTempl(rawVal)) {
                        val = yamlEscape(rawVal);
                    } else {
                        // TODO - if val is array, then individually yamlEscape the elements.
                        val = rawVal;
                    }
                }
                if (['actions_on', 'trigger', 'trigger_on', 'trigger_off', 'data'].includes(fname)) {
                    val = val.replaceAll('\n', '\n        ');
                    yaml += `${fname}:\n        ${val}`;
                } else {
                    yaml += `${fname}: ${val}`;
                }
            }
        });
        return yaml;
    }
    
    render() {
        //console.log('render with this._generatorResult=', this._generatorResult);
        if (!this.hass) {
            return html`waiting for hass`;
        }
        if (!this._topConfigs) {
            return html`waiting for _topConfigs to load`;
        }
        if (this._topConfigs.error) {
            return html`<ha-alert alert-type="error">Loading _topConfigs: ${this._topConfigs.error}</ha-alert>`;
        }
        let entName = `alert2.${this.alertCfg.domain ? this.alertCfg.domain : "[domain]"}_${this.alertCfg.name ? this.alertCfg.name : "[name]"}`;
        entName = slugify(entName);
        let yaml = this.configToYaml();

        let throttle_defaults = this._topConfigs.raw.defaults;
        if (this.alertCfg.domain == 'alert2' && this.alertCfg.name == 'global_exception' && this._topConfigs.raw.tracked) {
            for (const el of this._topConfigs.raw.tracked) {
                if (el.domain == this.alertCfg.domain && el.name == this.alertCfg.name && Object.hasOwn(el, 'throttle_fires_per_mins')) {
                    throttle_defaults = el;
                    break;
                }
            }
        }
        const localDefaults = {
            ack_required: false,
            ack_reminders_only: false
        };
        let title = '';
        let uiIdStr = '';
        if (this.entInfo) {
            title = html`<h3>Modify alert entry #${this.entInfo.uiId}</h3>`;
            uiIdStr = ` alert entry #${this.entInfo.uiId}`;
        } else {
            title = html`<h3>Create new UI alert</h3>`;
        }
        return html`
         <div class="container">
         <div class="ifields">
            <div style="margin-bottom: 1em;">
                ${title}
                <li>This page can only modify alerts created via the UI. It will not affect any alerts in YAML. Alert2 does not allow any two alerts created via the UI or YAML to have the same domain and name.
                <li>If using a generator, the "Render result" line for all fields will update based on the first element produced by the generator.
                <li>See <a href="https://github.com/redstone99/hass-alert2">https://github.com/redstone99/hass-alert2</a> for more complete documentation on each field.  And see <a href="https://github.com/redstone99/hass-alert2/blob/master/Recipes.md">Alert2 Recipes</a> for examples.
                <li>Fields are generally interpreted as YAML, with some logic to add quotes if writing a template.
                </ul>
            </div>
            <h3>Entity name</h3>
            <alert2-cfg-field .hass=${this.hass} name="domain" type=${FieldTypes.STR} tabindex="0"
                 @expand-click=${this.expandClick} @change=${this._change}
                 .savedP=${{}}  .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.domain}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="name" type=${FieldTypes.STR} tabindex="0"
                 @expand-click=${this.expandClick} @change=${this._change}
                 .savedP=${{}}  .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.name}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="friendly_name" type=${FieldTypes.TEMPLATE} tabindex="0"
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.friendly_name}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="icon" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.icon}</div></alert2-cfg-field>

            <h3>Fire control</h3>
            <alert2-cfg-field .hass=${this.hass} name="condition" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.condition}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="trigger" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.trigger}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="condition_on" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.condition_on}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="condition_off" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.condition_off}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="trigger_on" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.trigger_on}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="trigger_off" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.trigger_off}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="manual_on" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.manual_on}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="manual_off" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.manual_off}</div></alert2-cfg-field>
            <div><span style="visibility:hidden">*</span>Threshold <div style="margin-left: 1.5em;">
               <alert2-cfg-field .hass=${this.hass} name="value" type=${FieldTypes.TEMPLATE}
                    @expand-click=${this.expandClick} @change=${this._change} namePrefix="threshold"
                     templateType=${TemplateTypes.SINGLE}
                     .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
                  <div slot="help">${helpCommon.value}</div></alert2-cfg-field>
               <alert2-cfg-field .hass=${this.hass} name="hysteresis" type=${FieldTypes.TEMPLATE}
                    @expand-click=${this.expandClick} @change=${this._change} namePrefix="threshold"
                     templateType=${TemplateTypes.SINGLE} 
                     .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
                  <div slot="help">${helpCommon.hysteresis}</div></alert2-cfg-field>
               <alert2-cfg-field .hass=${this.hass} name="maximum" type=${FieldTypes.TEMPLATE}
                    @expand-click=${this.expandClick} @change=${this._change} namePrefix="threshold"
                     templateType=${TemplateTypes.SINGLE} 
                     .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
                  <div slot="help">${helpCommon.maximum}</div></alert2-cfg-field>
               <alert2-cfg-field .hass=${this.hass} name="minimum" type=${FieldTypes.TEMPLATE}
                    @expand-click=${this.expandClick} @change=${this._change} namePrefix="threshold"
                     templateType=${TemplateTypes.SINGLE} 
                     .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
                  <div slot="help">${helpCommon.minimum}</div></alert2-cfg-field>
            </div></div>
            <alert2-cfg-field .hass=${this.hass} name="delay_on_secs" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.delay_on_secs}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="early_start" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.early_start}</div></alert2-cfg-field>

            <h3>Notifications</h3>
            <alert2-cfg-field .hass=${this.hass} name="message" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.message}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="done_message" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.done_message}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="reminder_message" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.reminder_message}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="ack_reminder_message" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.ack_reminder_message}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="notifier" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  templateType=${TemplateTypes.LIST} .genResult=${this._generatorResult}
                  .savedP=${{}} .currP=${this.alertCfg} >
               <div slot="help">${helpCommon.notifier}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="summary_notifier" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  templateType=${TemplateTypes.LIST} .genResult=${this._generatorResult}
                  .savedP=${{}} .currP=${this.alertCfg} >
               <div slot="help">${helpCommon.summary_notifier}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="done_notifier" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  templateType=${TemplateTypes.LIST} .genResult=${this._generatorResult}
                  .savedP=${{}} .currP=${this.alertCfg} >
               <div slot="help">${helpCommon.done_notifier}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="reminder_frequency_mins" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.reminder_frequency_mins}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="annotate_messages" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.annotate_messages}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="ack_required" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${localDefaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.ack_required}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="ack_reminders_only" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${localDefaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.ack_reminders_only}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="title" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.title}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="target" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.target}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="data" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.data}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="throttle_fires_per_mins" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${throttle_defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.throttle_fires_per_mins}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="persistent_notifier_grouping" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.persistent_notifier_grouping}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="exception_ignore_regexes" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.exception_ignore_regexes}</div></alert2-cfg-field>

            <h3>Generator</h3>
            <alert2-cfg-field .hass=${this.hass} name="generator" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  templateType=${TemplateTypes.LIST} @generator-result=${this._generator_rez}
                  .savedP=${{}} .currP=${this.alertCfg} >
               <div slot="help">${helpCommon.generator}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="generator_name" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} >
               <div slot="help">${helpCommon.generator_name}</div></alert2-cfg-field>

            <h3>Extra settings</h3>
            <alert2-cfg-field .hass=${this.hass} name="priority" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.priority}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="display_msg" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.display_msg}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="supersedes" type=${FieldTypes.STR}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.supersedes}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="supersede_debounce_secs" type=${FieldTypes.FLOAT}
                 @expand-click=${this.expandClick} @change=${this._change} .defaultP=${this._topConfigs.raw.defaults}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.supersede_debounce_secs}</div></alert2-cfg-field>
            <alert2-cfg-field .hass=${this.hass} name="actions_on" type=${FieldTypes.TEMPLATE}
                 @expand-click=${this.expandClick} @change=${this._change}
                  .savedP=${{}} .currP=${this.alertCfg} .genResult=${this._generatorResult} >
               <div slot="help">${helpCommon.actions_on}</div></alert2-cfg-field>


          </div>
          <div class="doutput">
            <h3>Output</h3>
            <div style="margin-bottom: 1em;">Entity name: <code>${entName}</code></div>
            <div>Equivalent YAML:</div>
            <pre class="output">${yaml}</pre>

            <hr style="width:60%; max-width: 10em; margin-left: 0; margin-top: 2em;">

            <div style="margin-top: 0.5em;"><ha-progress-button class="validateB" @click=${this._validate}
                 .appearance=${"plain"} 
                 .progress=${this._opInProgress.op=='validate'&&this._opInProgress.inProgress}>Validate</ha-progress-button></div>
            <div style="margin-top: 0.5em;"><ha-progress-button class="createB"  @click=${this._create}
                 .appearance=${"plain"} 
                 .progress=${this._opInProgress.op=='create'&&this._opInProgress.inProgress}>Create</ha-progress-button></div>
            <div style="margin-top: 0.5em;"><ha-progress-button  class="updateB" @click=${this._update}
                 .appearance=${"plain"} .disabled=${uiIdStr == ''}
                 .progress=${this._opInProgress.op=='update'&&this._opInProgress.inProgress}>Update${uiIdStr}</ha-progress-button></div>
            <div style="margin-top: 0.5em;"><ha-progress-button  class="deleteB" @click=${this._delete}
                 .appearance=${"plain"} .disabled=${uiIdStr == ''}
                 .progress=${this._opInProgress.op=='delete'&&this._opInProgress.inProgress}>Delete${uiIdStr}</ha-progress-button></div>
            ${this._serverErr ? html`<ha-alert alert-type=${"error"}>${this._serverErr}</ha-alert>` : ""}


         </div>
      </div>
        `;
    }
    
    static styles = css`
    .container {
        margin-bottom: 1em;
        display: flex;
        flex-flow: row wrap;
        gap: 1em;
     }
     .ifields {
        flex: 1 1 45em;
     }
     .doutput {
        flex: 1 1 35em;
     }
     .output {
        background-color: var(--secondary-background-color);
        padding: 8px;
        whitespace: pre-wrap;
        margin-top: 0.2em;
     }
     ${extableCss}
      `;
}

customElements.define('more-info-alert2-container', MoreInfoAlert2Container);
customElements.define('more-info-alert2', MoreInfoAlert2);
customElements.define('alert2-overview', Alert2Overview);
customElements.define('hui-alert2-entity-row', Alert2EntityRow);
customElements.define('ha-alert2-state', HaAlert2State);
customElements.define('j-relative-time', RelativeTime);
customElements.define("state-card-alert2", StateCardAlert2);
customElements.define('alert2-tools', Alert2Tools);
customElements.define('alert2-manager', Alert2Manager);
customElements.define('alert2-create', Alert2Create);
customElements.define('alert2-edit-defaults', Alert2EditDefaults);
customElements.define('alert2-cfg-field', Alert2CfgField);
window.customCards = window.customCards || [];
window.customCards.push({
    type: "alert2-manager",
    name: "Alert2 Manager",
    preview: false, // Optional - defaults to false
    description: "Adjust Alert2 defaults and create and edit alerts",
    documentationURL: "https://github.com/redstone99/hass-alert2-ui",
    getEntitySuggestion: (hass, entityId) => {
        if (entityId.split(".")[0] !== "alert2") {
            return null;
        }
        return { config: { type: "custom:alert2-manager" } };
    },
});
window.customCards.push({
    type: "alert2-overview",
    name: "Alert2 Overview",
    preview: false, // Optional - defaults to false
    description: "View recently active Alert2 alerts",
    documentationURL: "https://github.com/redstone99/hass-alert2-ui",
    getEntitySuggestion: (hass, entityId) => {
        if (entityId.split(".")[0] !== "alert2") {
            return null;
        }
        return { config: { type: "custom:alert2-overview" } };
    },
});
    
}); // end of whenDefined('ha-panel-lovelace')

