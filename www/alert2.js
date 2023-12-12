const LitElement = Object.getPrototypeOf(customElements.get("ha-panel-lovelace"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;
const NOTIFICATIONS_ENABLED  = 'enabled'
const NOTIFICATIONS_DISABLED = 'disabled'
const NOTIFICATION_SNOOZE = 'snooze'
console.log('alert2 v1');

// A custom card that lists alerts that have fired recently
class Alert2Overview extends LitElement {
    // https://lit.dev/docs/components/properties/
    // has good description of reactive properties
    static properties = {
        // TODO - Given we use timeout to refresh entity list, maybe hass doesn't need to be reactive property
       hass: {attribute: false},
        _config: {state: true},
        _shownEntities: {state: true},
        _cardHelpers: {state: true},
        _ackAllInProgress: {state: true},
    }
    constructor() {
        super();
        this._shownEntities = new Map();
        this._updateTimer = null;
        this._cardHelpers = null;
        this._ackAllInProgress = false;
        this._sliderValArr = [
            { str: '1 minute', secs: 60 },
            { str: '10 minutes', secs: 10*60 },
            { str: '1 hour', secs: 60*60 },
            { str: '4 hours', secs: 4*60*60 },
            { str: '1 day', secs: 24*60*60 },
            { str: '4 days', secs: 4*24*60*60 },
            { str: '2 weeks', secs: 2*7*24*60*60 }
        ]
        this._sliderVal = 3;// 4 hours
        window.loadCardHelpers().then(hs => { this._cardHelpers = hs; });
    }
    
    connectedCallback() {
        super.connectedCallback();
        this._updateTimer = setInterval(this.jrefresh, 60*1000, this);
    }
    disconnectedCallback() {
        clearInterval(this._updateTimer);
        super.disconnectedCallback();
    }
    jrefresh(tthis) {
        tthis.jrefreshInt(false).then( result => true );
    }
    setConfig(config) {
        this._config = config;
    }
    shouldUpdate(changedProps) {
        if (changedProps.has('hass')) {
            const oldHass = changedProps.get("hass");
            const newHass = this.hass;
            if (!oldHass) {
                if (newHass) {
                    this.jrefresh(this);
                } else {
                    console.warn('no old or new hass');
                }
            } else {
                // sensor.alert2_change_count is a performance optimization.
                // It increases when any alert changes. The purpose is to limit how often
                // we scan all entities to find which alerts to display. Without it,
                // we'd have to rescan all entities periodically.
                const entityId = 'sensor.alert2_change_count';
                const oldState = oldHass.states[entityId];
                const newState = newHass.states[entityId];
                if (oldState !== newState) {
                    this.jrefreshInt(true).then( result => true );
                }
            }
        }
        if (changedProps.has('_shownEntities') ||
            changedProps.has('_config') ||
            changedProps.has('_cardHelpers') ||
            changedProps.has('_ackAllInProgress')) {
            return true;
        }
        return false;
    }
    // Slider changed value
    slideCh(ev) {
        let val = this.shadowRoot.querySelector("ha-slider").value;
        this._sliderVal = val;
        this.jrefreshInt(true).then( result => true );
    }
    // Ack all button was pressed
    async _ackAll(ev) {
        this._ackAllInProgress = true;
        let abutton = ev.target;
        let outerThis = this;
        try {
            await this.hass.callWS({
                type: "execute_script",
                sequence: [ {
                    service: 'alert2.ack_all',
                    data: {},
                }],
            });
        } catch (err) {
            this._ackAllInProgress = false;
            abutton.actionError();
            this._showToast("error: " + err.message);
            return;
        }
        this._ackAllInProgress = false;
        abutton.actionSuccess();
    }
    render() {
        if (!this._cardHelpers) {
            return html`<div>Loading.. waiting for card helpers to load</div>`;
        }

        const outerThis = this;
        let entListHtml;
        if (this._shownEntities.size == 0) {
            entListHtml = html`<div id="jempt">No alerts active in the past ${this._sliderValArr[this._sliderVal].str}. No alerts snoozed or disabled.</div>`;
        } else {
            // entitiesConf can be just a list of string entity names, or it can be a list of configs. maybe both.
            let sortedEntities = Array.from(this._shownEntities.keys()).sort((a,b)=>
                (this._shownEntities.get(a) == this._shownEntities.get(b)) ? (a < b) :
                    (this._shownEntities.get(a) < this._shownEntities.get(b)));
            let entitiesConf = sortedEntities.map(entName=>({ entity: entName }));
            for (let aconf of entitiesConf) {
                if (aconf.entity.startsWith('alert2.')) {
                    // 'custom:' gets stripped off in src/panels/lovelace/create-element/create-element-base.ts
                    aconf.type = 'custom:hui-alert2-entity-row';
                    aconf.tap_action = { action: "fire-dom-event" };
                }
            }
            entListHtml = html`${entitiesConf.map((entityConf) => this.renderEntity(entityConf)
                                )}`;
        }
        let foo = html`<ha-card>
            <h1 class="card-header"><div class="name">Alerts</div></h1>
            <div class="card-content">
              <div style="display:flex; align-items: center;">
                  <ha-slider .min=${0} .max=${this._sliderValArr.length-1} .step=${1} .value=${this._sliderVal} snaps ignore-bar-touch
                     @change=${this.slideCh}
                  ></ha-slider>
                  <span id="slideValue">Last ${this._sliderValArr[this._sliderVal].str}</span>
                <div style="flex-grow: 1;"></div>
                <ha-progress-button
                    .progress=${this._ackAllInProgress}
                    @click=${this._ackAll}
                    >Ack all</ha-progress-button>
              </div>
              ${entListHtml}
            </div>
          </ha-card>`;
        return foo;
    }
    renderEntity(entityConf) {
        let entityName = entityConf.entity;
        const element = this._cardHelpers.createRowElement(entityConf);
        if (this.hass) {
            element.hass = this.hass;
        }
        let outerThis = this;
        // hui-generic-entity-row calls handleAction on events, including clicks.
        // we set the action to take on 'tap' to be 'fire-dom-event', which generates a 'll-custom' event
        element.addEventListener('ll-custom', (ev)=>outerThis._alertClick(ev, entityName));
        return html`<div class="jEvWrapper">${element}</div>`;
    }
    _alertClick(ev, entityName) {
        let style = '';
        let cardTools = customElements.get('card-tools');
        let x = cardTools.popUp('Alert2 info for ' + entityName, { type: 'custom:more-info-alert2-container', entityName: entityName }, true, style);
        x.then(()=>{
            // dialog has been opened
        });
        return false;
    }
    static styles = css`
      ha-card {
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }
      .card-header {
        display: flex;
        justify-content: space-between;
      }
      .card-header .name {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
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
    `;
    
    async jrefreshInt(forceUpdate) {
        if (!this.hass) {
            console.log('skipping jrefresh cuz no hass');
            return;
        }
        const intervalSecs = this._sliderValArr[this._sliderVal].secs;
        let entities = new Map();
        let nowSecs = Date.now() / 1000.0;
        for (let entityName in this.hass.states) {
            if (entityName.startsWith('alert.')) {
                let ent = this.hass.states[entityName];
                if (ent.state !== 'idle') {
                    entities.set(entityName, nowSecs);
                } else if (ent.attributes.snooze_until == 'notifications-disabled') {
                    entities.set(entityName, nowSecs);
                } else if (ent.attributes.snooze_until != 'notifications-enabled') {
                    entities.set(entityName, nowSecs);
                }
            } else if (entityName.startsWith('alert2.')) {
                let ent = this.hass.states[entityName];
                let lastFireSecs = 0; // 1970
                if (ent.state) {
                    if ('last_on_time' in ent.attributes) {
                        // Is a level-triggered alert
                        if (ent.state == 'on') {
                            lastFireSecs = nowSecs;
                        } else if (ent.state == 'off') {
                            if (ent.attributes['last_off_time']) {
                                lastFireSecs = Date.parse(ent.attributes['last_off_time']) / 1000.0;
                            } // else never fired
                        } else {
                            console.error('Entity state is not on/off', ent.state, entityName);
                        }
                    } else {
                        // Edge triggered alert
                        lastFireSecs = Date.parse(ent.state) / 1000.0;
                    }
                }
                if (isNaN(lastFireSecs)) {
                    console.error('Entity ', ent.entity_id, ent.state, 'parse error lastFireSecs', lastFireSecs);
                } else {
                    const not_enabled = (ent.attributes.notification_control &&
                                         (ent.attributes.notification_control != NOTIFICATIONS_ENABLED));
                    let agoSecs = nowSecs - lastFireSecs;
                    if (agoSecs < intervalSecs) {
                        entities.set(entityName, lastFireSecs);
                    } else if (not_enabled) {
                        entities.set(entityName, lastFireSecs);
                    }
                }
            }
        }
        if (entities.size == this._shownEntities.size) {
            for (const entName of entities.keys()) {
                if (!this._shownEntities.has(entName)) {
                    this._shownEntities = entities;
                    return;
                }
            }
        } else {
            this._shownEntities = entities;
            return;
        }
        // Fall through: entities set hasn't changed so don't trigger an update
        if (forceUpdate) {
            this._shownEntities = entities;
            return;
        }
    }
}

// Similar to src/panels/lovelace/entity-rows/hui-climate-entity-row.ts
// implements LovelaceRow
class Alert2EntityRow extends LitElement  {
    static properties = {
        _config: {state: true},
    }
    set hass(nh) {
        this._hass = nh;
        if (this.shadowRoot && this._hass && this._config) {
            this.shadowRoot.querySelectorAll("ha-alert2-state").forEach((element) => {
                const stateObj = this._hass.states[this._config.entity];
                element.stateObj = stateObj;
            });
        }
    }
    constructor() {
        super();
        this._hass = null;
        this._stateEl = null;
    }
    setConfig(config) {
        if (!config || !config.entity) {
            throw new Error("Entity must be specified");
        }
        this._config = config;
    }
    render() {
        if (!this._hass || !this._config) {
            console.warn('foo, not ready to render');
            return nothing;
        }
        const stateObj = this._hass.states[this._config.entity];
        if (!stateObj) {
            return html`
        <hui-warning>
          ${createEntityNotFoundWarning(this._hass, this._config.entity)}
        </hui-warning>
      `;
        }

        return html`
      <hui-generic-entity-row .hass=${this._hass} .config=${this._config}>
        <ha-alert2-state .hass=${this._hass} .stateObj=${stateObj}>
        </ha-alert2-state>
      </hui-generic-entity-row>
      `;
    }

    static styles = css`
      ha-alert2-state {
        text-align: right;
      }
    `;
}

function agoStr(adate, longnames) {
    const secondsAgo = (new Date() - adate) / 1000.0;
    let astr;
    let intervalSecs;
    if (secondsAgo < 2*60) { astr = `${Math.round(secondsAgo)}${longnames?" seconds":"s"}`; intervalSecs = 1; }
    else if (secondsAgo < 2*60*60) { astr = `${Math.round(secondsAgo/60)}${longnames?" minutes":"m"}`; intervalSecs = 60; }
    else if (secondsAgo < 2*24*60*60) { astr = `${Math.round(secondsAgo/(60*60))}${longnames?" hours":"h"}`; intervalSecs = 60*60; }
    else { astr = `${Math.round(secondsAgo/(24*60*60))}${longnames?" days":"d"}`; intervalSecs = 24*60*60; }
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
    _showToast(amsg) {
        const event = new Event("hass-notification", {
            bubbles: true,
            cancelable: false,
            composed: true,
        });
        event.detail = { message: amsg };
        this.dispatchEvent(event);
    }
    async _jack(ev) {
        this._ackInProgress = true;
        let abutton = ev.target;
        ev.stopPropagation();
        if (1) {
            try {
                await this._hass.callWS({
                    type: "execute_script",
                    sequence: [ {
                        service: 'alert2.ack',
                        data: {},
                        target: { entity_id: this._stateObj.entity_id }
                    }],
                });
            } catch (err) {
                this._ackInProgress = false;
                abutton.actionError();
                this._showToast("error: " + err.message);
                return;
            }
            this._ackInProgress = false;
            abutton.actionSuccess();
        }
    }
    render() {
        if (!this._stateObj) {
            console.warn('foo, not ready to render');
            return html`<div>loading...</div>`;
        }
        const ent = this._stateObj;
        let msg;
        let last_ack_time = null;
        if (ent.attributes['last_ack_time']) {
            last_ack_time = Date.parse(ent.attributes['last_ack_time']);
        }
        let last_on_time = null;
        if (ent.attributes['last_on_time']) {
            last_on_time = Date.parse(ent.attributes['last_on_time']);
        }

        let last_fired_time = null;
        if (last_on_time) {
            last_fired_time = last_on_time;
            if (ent.state == 'on') {
                msg = 'on';
            } else if (ent.state == 'off') {
                const last_off_time = Date.parse(ent.attributes['last_off_time']);
                msg = html`off<j-relative-time .timestamp=${last_off_time} .useLongnames=${false} style="margin-left:0.5em;"></j-relative-time>`;
            } // else - should never happen, was checked when populated _shownEntities list.
        } else {
            last_fired_time = Date.parse(ent.state);
            msg = html`<j-relative-time .timestamp=${last_fired_time} .useLongnames=${false}></j-relative-time>`;
        }
        let ackBadge = '';
        let ackButton = ''
        if (last_ack_time && last_ack_time > last_fired_time) {
            ackBadge = html`<div class="badge noborder">Acked</div>`;
        } else {
            ackButton = html`<ha-progress-button
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
        
        return html`${ackBadge}${snoozeBadge}${ackButton}<div class="curr">${msg}</div>${extraFiresBadge}`;
    }
    static styles = css`
      .badge {
          border-radius: 10%;
          border: 0.2em solid var(--label-badge-text-color, rgb(76, 76, 76));
          color: var(--label-badge-text-color, rgb(76, 76, 76));
          padding: 0.1em 0.3em;
          margin-right: 1em;
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
        justify-content: center;
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
    } else { return null; }
}

// Add this attribute to alert entity attributes:
// 'custom_ui_more_info' : 'more-info-alert2', # name of UI element that must be defined
//
class MoreInfoAlert2 extends LitElement {
    static properties = {
        hass: { attribute: false,
                hasChanged(newVal, oldVal) { return false; }
        },
        stateObj: { },
        _requestInProgress: {state: true},
        _ackInProgress: {state: true},
        _currValue: {state: true},
        _historyArr: {state: true},
    }

    constructor() {
        super();
        this._requestInProgress = false;
        this._ackInProgress = false;
        this._currValue = NOTIFICATIONS_ENABLED;
        this.textEl = null;
        this._historyArr = null;
        this._historyEndDate = null;
        this._fetchPrevInProgress = false;
        this._fetchCurrInProgress = false;
        // no shadowRoot yet.
    }
    connectedCallback() {
        super.connectedCallback();
        // no shadowRoot yet.
    }
    firstUpdated() {
        super.firstUpdated();
        // see https://lit.dev/docs/v1/components/lifecycle/#firstupdated
        // could use connectedCallback to do this earlier
        this._currValue = this.stateObj.attributes.notification_control;
        let s1 = this.shadowRoot.querySelector('ha-formfield#for-snooze ha-textfield');
        this.textEl = s1;
        this.textEl.validityTransform = (newValue, nativeValidity) => {
            let isvalid = strIsValidNumber(newValue) != null;
            return { valid: isvalid };
        }
        this.getHistory();
        customElements.whenDefined('state-card-alert2').then(()=>{
            this.requestUpdate();
        });
    }
    fetchPrev() {
        const msAgo = 24*60*60*1000.0;
        if (this._historyEndDate) {
            this._historyEndDate = new Date(this._historyEndDate.getTime() - msAgo);
        } else {
            this._historyEndDate = new Date((new Date()).getTime() - msAgo);
        }
        this._fetchPrevInProgress = true;
        this.getHistory();
    }
    fetchCurr() {
        this._historyEndDate = null;
        this._fetchCurrInProgress = true;
        this.getHistory();
    }
    getHistory() {
        const msAgo = 24*60*60*1000.0;
        const startDate = new Date((this._historyEndDate ? this._historyEndDate : (new Date())).getTime() - msAgo);
        console.log('will getHistory from', startDate);
        let historyUrl = `history/period/${startDate.toISOString()}?filter_entity_id=${this.stateObj.entity_id}`;
        if (this._historyEndDate) {
            historyUrl += `&end_time=${this._historyEndDate.toISOString()}`;
        }
        const outerThis = this;
        const isAlert = 'last_on_time' in this.stateObj.attributes;
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
                outerThis._historyArr = newArr;
            }
        });
    }
    
    render() {
        if (!this.hass || !this.stateObj) {
            return "";
        }
        let stateValue = this.stateObj.attributes.notification_control;
        let notification_status;
        if (stateValue == null) {
            notification_status = "unknown";
        } else if (stateValue == NOTIFICATIONS_ENABLED) {
            notification_status = "enabled";
        } else if (stateValue == NOTIFICATIONS_DISABLED) {
            notification_status = "disabled";
        } else {
            notification_status = "snoozed until " + stateValue;
        }

        let is_snoozed = false;
        if (this._currValue == NOTIFICATIONS_ENABLED ||
            this._currValue == NOTIFICATIONS_DISABLED) {
        } else {
            is_snoozed = true;
        }
        const entName = this.stateObj.entity_id;
        const isAlert = 'last_on_time' in this.stateObj.attributes;
        let isAlertOn = false;
        let onBadge = ''
        if (isAlert) {
            isAlertOn = this.stateObj.state == 'on';
            onBadge = isAlertOn ? "on" : "off";
        }
        let historyHtml = html`Fetching history...`;
        if (this._historyArr !== null) {
            if (this._historyArr.length == 0) {
                historyHtml = html`No history exists`;
            } else {
                const thass = this.hass;
                function rHist(elem) {
                    const onoff = isAlert ? html`<td>${elem.state}</td>` : '';
                    const extraTxt = (isAlert && elem.state == 'off') ? '' : elem.attributes.last_fired_message;
                    let eventTime = elem.attributes.last_fired_time;
                    if (isAlert) {
                        eventTime = (elem.state == 'on') ? elem.attributes.last_on_time : elem.attributes.last_off_time;
                    }
                    const firedTime = eventTime ?
                          html`<j-relative-time
                                   .timestamp=${Date.parse(eventTime)} .useLongnames=${true}></j-relative-time>` : 'unknown';
                    const absTime = eventTime ?
                          html`<span style="font-size:0.8em;">${eventTime}</span>` : 'unknown';
                    return html`
                <tr class="eventrow">
                <td class="eventtime">${firedTime}<br/>${absTime}</td>
                ${onoff}
                <td>${extraTxt}</td>
                </tr>
                    `;
                }
                historyHtml = html`<table>
                    <tr>
                      <th>Event time</th>
                      ${ isAlert ? html`<th style="padding-left: 1em;">On/Off</th>` : '' }
                      <th style="padding-left: 1em;">Message</th>
                    </tr>
                    ${this._historyArr.map((elem) => rHist(elem) )}</table>`;
            }
        }
        return html`<div style="margin-bottom:2em;">
            <state-card-content
              in-dialog
              .stateObj=${this.stateObj}
              .hass=${this.hass}
            ></state-card-content>
            <div id="previousFirings" style="margin-top: 1em;">
                <div style="display: flex; margin-top: 2em; margin-bottom: 1em; align-items: center;">
                  <div class="title">Previous Firings</div>
                  <div style="flex: 1 1 0; max-width: 10em;"></div>
                  <ha-progress-button
                    .progress=${this._fetchPrevInProgress}
                    @click=${this.fetchPrev}
                  >Prev Day</ha-progress-button>
                  <ha-progress-button
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
              <div><ha-formfield .label=${"Enable"}>
                  <ha-radio
                      .checked=${NOTIFICATIONS_ENABLED == this._currValue}
                      .value=${NOTIFICATIONS_ENABLED}
                      .disabled=${false}
                      @change=${this._valueChanged}
                      ></ha-radio></ha-formfield></div>
              <div><ha-formfield .label=${"Disable"}><ha-radio
                  .checked=${NOTIFICATIONS_DISABLED == this._currValue}
                  .value=${NOTIFICATIONS_DISABLED}
                  .disabled=${false}
                  @change=${this._valueChanged}
                  ></ha-radio></ha-formfield></div>
              <div style="margin-bottom:1em;"><ha-formfield id="for-snooze">
                  <ha-radio
                      id="rad1"
                      .checked=${is_snoozed}
                      .value=${"snooze"}
                      .disabled=${false}
                      @change=${this._valueChanged}
                      ></ha-radio>
                  <div style="display:inline-block;" id="slabel" @click=${this._aclick}>Snooze for 
                      <ha-textfield
                          .placeholder=${"1.234"}
                          .min=${0}
                          .disabled=${false}
                          .required=${is_snoozed}
                          .suffix=${"hours"}
                         type="number"
                         inputMode="decimal"
                          autoValidate
                          ?no-spinner=false
                          @input=${this._handleInputChange}
                          ></ha-textfield>
                  </div>
              </ha-formfield></div>
              <ha-progress-button
                  .progress=${this._requestInProgress}
                  @click=${this._jupdate}>Update</ha-progress-button>
            </div>
            <br/><br/>
            <ha-attributes
                .hass=${this.hass}
                .stateObj=${this.stateObj}
                ></ha-attributes>
        </div>`;
    }
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
    }
    div#slabel {
      pointer: default;
    }
    ha-textfield {
      margin-left: 1em;
      margin-right: 1em;
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

    _valueChanged(ev) {
        let value = ev.detail?.value || ev.target.value;
        if (value == "snooze") {
            value = this.textEl.value;
        }
        this._currValue = value;
    }
    _handleInputChange(ev) {
        ev.stopPropagation();
        const value = ev.target.value;
        this._currValue = value;
    }
    _showToast(amsg) {
        const event = new Event("hass-notification", {
            bubbles: true,
            cancelable: false,
            composed: true,
        });
        event.detail = { message: amsg };
        this.dispatchEvent(event);
    }
    async _jupdate(ev) {
        console.log('submit clicked', this._currValue, this);
        this._requestInProgress = true;
        let abutton = ev.target;
        let data = { };
        if (this._currValue == NOTIFICATIONS_ENABLED) {
            data.enable = 'on';
        } else if (this._currValue == NOTIFICATIONS_DISABLED) {
            data.enable = 'off';
        } else {
            let val = strIsValidNumber(this._currValue);
            if (val == null) {
                this._requestInProgress = false;
                abutton.actionError();
                console.error('bad value', this._currValue);
                this._showToast("Non-positive numeric value: " + this._currValue);
                return;
            }
            data.enable = 'on';
            let hours = val;
            var newDate = new Date((new Date()).getTime() + hours*60*60*1000);
            data.snooze_until = newDate;
        }
        try {
            await this.hass.callWS({
                type: "execute_script",
                sequence: [ {
                    service: 'alert2.notification_control',
                    data: data,
                    target: { entity_id: this.stateObj.entity_id }
                }],
            });
        } catch (err) {
            this._requestInProgress = false;
            abutton.actionError();
            this._showToast("error: " + err.message);
            return;
        }
        this._requestInProgress = false;
        abutton.actionSuccess();
    }
    async _jack(ev) {
        this._ackInProgress = true;
        let abutton = ev.target;
        ev.stopPropagation();
        try {
            await this.hass.callWS({
                type: "execute_script",
                sequence: [ {
                    service: 'alert2.ack',
                    data: {},
                    target: { entity_id: this.stateObj.entity_id }
                }],
            });
        } catch (err) {
            this._ackInProgress = false;
            abutton.actionError();
            this._showToast("error: " + err.message);
            return;
        }
        this._ackInProgress = false;
        abutton.actionSuccess();
    }
    _aclick(ev) {
        let radioEl = ev.target.previousSibling;
        if (ev.target.id == "slabel") {
            // good
        } else if (ev.target.nodeName == "HA-TEXTFIELD") {
            radioEl = ev.target.parentElement.previousSibling;
        }
        if (radioEl.nodeName != "HA-RADIO") {
            log.error("fuck", radioEl.nodeName);
        }
        radioEl.checked = true;
        let textEl = radioEl.parentElement.querySelector('ha-textfield');
        console.log('aclick called, textEl is ', textEl.value);
        this._currValue = textEl.value;
    }
}

class MoreInfoAlert2Container extends LitElement {
    static properties = {
        hass: { attribute: false },
    }
    constructor() {
        super();
        this.config = null;
    }
    setConfig(config) {
        this.config = config;
    }
    connectedCallback() {
        super.connectedCallback();
        this.getRootNode().querySelector('div.content').style.maxWidth = '60em';
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        let adiv = this.getRootNode().querySelector('div.content');
        if (adiv) { // This may be useless. Seems like sometimes, when element is removed from DOM, the div.content is removed as well.
            adiv.style.maxWidth = null;
        }
    }
    render() {
        if (!this.hass) {
            return html`<div>waiting for hass</div>`;
        }
        if (!this.config) {
            return html`<div>waiting for config</div>`;
        }
        let stateObj = this.hass.states[this.config.entityName];
        let title = "my title";
        return html`
           <ha-card>
              <div class="card-content">
                   <more-info-alert2
                       .stateObj=${stateObj}
                       .hass=${this.hass} ></more-info-alert2>
             </div>
           </ha-card>
        `;
    }
    static styles = css`
        ha-dialog {
          /* Set the top top of the dialog to a fixed position, so it doesnt jump when the content changes size */
          --vertical-align-dialog: flex-start;
          --dialog-surface-margin-top: 40px;
          /* This is needed for the tooltip of the history charts to be positioned correctly */
          --dialog-surface-position: static;
          --dialog-content-position: static;
          --dialog-content-padding: 0;
          --chart-base-position: static;
        }

        .content {
          display: flex;
          flex-direction: column;
          outline: none;
          flex: 1;
        }
    `;
}

customElements.define('more-info-alert2', MoreInfoAlert2);
customElements.define('more-info-alert2-container', MoreInfoAlert2Container);
customElements.define('alert2-overview', Alert2Overview);
customElements.define('hui-alert2-entity-row', Alert2EntityRow);
customElements.define('ha-alert2-state', HaAlert2State);
customElements.define('j-relative-time', RelativeTime);
customElements.define("state-card-alert2", StateCardAlert2);
