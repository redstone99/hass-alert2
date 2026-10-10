import { MdListItem, MdSlider, textfieldStyles, TextFieldBase, radioStyles, RadioBase,
         formStyles, FormfieldBase, LitElement, html, css } from './lit-material.js';

//import {LitElement, html, css} from './lit-core.min.js';
//import { FormfieldBase }           from "@material/mwc-formfield/mwc-formfield-base";
//import { styles as formStyles }    from "@material/mwc-formfield/mwc-formfield.css";
//import                                  "@material/mwc-button";
//import { RadioBase }               from "@material/mwc-radio/mwc-radio-base";
//import { styles as radioStyles }   from "@material/mwc-radio/mwc-radio.css";
//import { TextFieldBase }           from "@material/mwc-textfield/mwc-textfield-base";
//import {styles as textfieldStyles} from "@material/mwc-textfield/mwc-textfield.css";
//import { MdListItem, MdSlider } from './material.web.all.js';
//import { MdListItem, MdSlider } from '@material/web/all.js';

//import { MdListItem }         from "@material/web/list/list-item";
//import { MdSlider }           from "@material/web/slider/slider";
//import { mdiAlertOctagram, mdiCheckBold } from "@mdi/js";
class HaSlider extends MdSlider {
    static styles = [
        ...super.styles,
        css`
            :host {
              --md-sys-color-primary: var(--primary-color);
              --md-sys-color-on-primary: var(--text-primary-color);
              --md-sys-color-outline: var(--outline-color);
              --md-sys-color-on-surface: var(--primary-text-color);
              --md-slider-handle-width: 14px;
              --md-slider-handle-height: 14px;
              --md-slider-state-layer-size: 24px;
              min-width: 100px;
              min-inline-size: 100px;
              width: 200px;
            }
                 `,
    ];
}
class HaCard extends LitElement {
    static properties = {
        header: {},
        raised: { type: Boolean, reflect: true }
    }
    
    static styles = css`
                :host {
                  background: var(
                    --ha-card-background,
                    var(--card-background-color, white)
                  );
                  -webkit-backdrop-filter: var(--ha-card-backdrop-filter, none);
                  backdrop-filter: var(--ha-card-backdrop-filter, none);
                  box-shadow: var(--ha-card-box-shadow, none);
                  box-sizing: border-box;
                  border-radius: var(--ha-card-border-radius, 12px);
                  border-width: var(--ha-card-border-width, 1px);
                  border-style: solid;
                  border-color: var(
                    --ha-card-border-color,
                    var(--divider-color, #e0e0e0)
                  );
                  color: var(--primary-text-color);
                  display: block;
                  transition: all 0.3s ease-out;
                  position: relative;
                }

                :host([raised]) {
                  border: none;
                  box-shadow: var(
                    --ha-card-box-shadow,
                    0px 2px 1px -1px rgba(0, 0, 0, 0.2),
                    0px 1px 1px 0px rgba(0, 0, 0, 0.14),
                    0px 1px 3px 0px rgba(0, 0, 0, 0.12)
                  );
                }

                .card-header,
                :host ::slotted(.card-header) {
                  color: var(--ha-card-header-color, --primary-text-color);
                  font-family: var(--ha-card-header-font-family, inherit);
                  font-size: var(--ha-card-header-font-size, 24px);
                  letter-spacing: -0.012em;
                  line-height: 48px;
                  padding: 12px 16px 16px;
                  display: block;
                  margin-block-start: 0px;
                  margin-block-end: 0px;
                  font-weight: normal;
                }

                :host ::slotted(.card-content:not(:first-child)),
                slot:not(:first-child)::slotted(.card-content) {
                  padding-top: 0px;
                  margin-top: -8px;
                }

                :host ::slotted(.card-content) {
                  padding: 16px;
                }

                :host ::slotted(.card-actions) {
                  border-top: 1px solid var(--divider-color, #e8e8e8);
                  padding: 5px 16px;
                }
                           `

             render() {
                 return html`
            ${this.header
              ? html`<h1 class="card-header">${this.header}</h1>`
              : ""}
            <slot></slot>
               `;
             }
}

class HaProgressButton extends LitElement {
             static properties = {
                 disabled: { type: Boolean },
                 progress: { type: Boolean },
                 raised: { type: Boolean },
                 _result: { state: true }
             }
             constructor() {
                 super();
                 this.disabled = false;
                 this.progress = false;
                 this.raised = false;
                 this._result = null;
             }
             render() {
                 const mdiCheckBold = "M9,20.42L2.79,14.21L5.62,11.38L9,14.77L18.88,4.88L21.71,7.71L9,20.42Z";
                 const mdiAlertOctagram = "M2.2,16.06L3.88,12L2.2,7.94L6.26,6.26L7.94,2.2L12,3.88L16.06,2.2L17.74,6.26L21.8,7.94L20.12,12L21.8,16.06L17.74,17.74L16.06,21.8L12,20.12L7.94,21.8L6.26,17.74L2.2,16.06M13,17V15H11V17H13M13,13V7H11V13H13Z";
                 const overlay = this._result || this.progress;
                 return html`
                     <mwc-button
                         ?raised=${this.raised}
                         .disabled=${this.disabled || this.progress}
                         @click=${this._buttonTapped}
                         class=${this._result || ""}
                         >
        <slot></slot>
                     </mwc-button>
                     ${!overlay
                     ? ""
                     : html`
                 <div class="progress">
                 ${this._result === "success"
                 ? html`<ha-svg-icon .path=${mdiCheckBold}></ha-svg-icon>`
                 : this._result === "error"
                 ? html`<ha-svg-icon .path=${mdiAlertOctagram}></ha-svg-icon>`
                 : this.progress
                 ? html`
                     <ha-circular-progress
                        size="small"
                         indeterminate
                         ></ha-circular-progress>
                 `
                 : ""}
                 </div>
                 `}
                 `;
             }

             actionSuccess() {
                 this._setResult("success");
             }
             actionError() {
                 this._setResult("error");
             }
             
             _setResult(result) {
                 this._result = result;
                 setTimeout(() => {
                     this._result = undefined;
                 }, 2000);
             }

             _buttonTapped(ev) {
                 if (this.progress) {
                     ev.stopPropagation();
                 }
             }
             static styles = css`
      :host {
        outline: none;
        display: inline-block;
        position: relative;

             font-family: var(--paper-font-body1_-_font-family);
             -webkit-font-smoothing: var(--paper-font-body1_-_-webkit-font-smoothing);
             font-size: var(--paper-font-body1_-_font-size);
             font-weight: var(--paper-font-body1_-_font-weight);
             line-height: var(--paper-font-body1_-_line-height);


      }

      mwc-button {
        transition: all 1s;
      }

      mwc-button.success {
        --mdc-theme-primary: white;
        background-color: var(--success-color);
        transition: none;
        border-radius: 4px;
        pointer-events: none;
      }

      mwc-button[raised].success {
        --mdc-theme-primary: var(--success-color);
        --mdc-theme-on-primary: white;
      }

      mwc-button.error {
        --mdc-theme-primary: white;
        background-color: var(--error-color);
        transition: none;
        border-radius: 4px;
        pointer-events: none;
      }

      mwc-button[raised].error {
        --mdc-theme-primary: var(--error-color);
        --mdc-theme-on-primary: white;
      }

      .progress {
        bottom: 4px;
        position: absolute;
        text-align: center;
        top: 4px;
        width: 100%;
      }

      ha-svg-icon {
        color: white;
      }

      mwc-button.success slot,
      mwc-button.error slot {
        visibility: hidden;
      }`;
}
class HaFormfield extends FormfieldBase {
             static properties = {
                 disabled: { type: Boolean, reflect: true }
             }
             constructor() {
                 super();
                 this.disabled = false;
             }
             render() {
                 const classes = {
                     "mdc-form-field--align-end": this.alignEnd,
                     "mdc-form-field--space-between": this.spaceBetween,
                     "mdc-form-field--nowrap": this.nowrap,
                 }; // not used.  used to be added as classes if val was truthy
                 
                 return html` <div class="mdc-form-field">
      <slot></slot>
      <label class="mdc-label" @click=${this._labelClick}>
        <slot name="label">${this.label}</slot>
      </label>
    </div>`;
             }

             _labelClick() {
                 const input = this.input;
                 if (!input) return;

                 input.focus();
                 if (input.disabled) {
                     return;
                 }
                 switch (input.tagName) {
                     case "HA-CHECKBOX":
                         input.checked = !input.checked;
                         fireEvent(input, "change");
                         break;
                     case "HA-RADIO":
                         input.checked = true;
                         fireEvent(input, "change");
                         break;
                     default:
                         input.click();
                         break;
                 }
             }

             static styles = [
                 formStyles,
                 css`
            :host(:not([alignEnd])) ::slotted(ha-switch) {
              margin-right: 10px;
              margin-inline-end: 10px;
              margin-inline-start: inline;
            }
            .mdc-form-field {
              align-items: var(--ha-formfield-align-items, center);
              gap: 4px;
            }
            .mdc-form-field > label {
              direction: var(--direction);
              margin-inline-start: 0;
              margin-inline-end: auto;
              padding: 0;
            }
            :host([disabled]) label {
              color: var(--disabled-text-color);
            }`];
}
class HaRadio extends RadioBase {
             static styles = [
                 radioStyles,
                 css`
            :host {
              --mdc-theme-secondary: var(--primary-color);
            }
                 `,
             ];
}
class HaInput extends LitElement {
             static properties = {
                 type: { reflect: true },
                 invalid: { type: Boolean },
                 value: { state: true },
                 required: { state: true },
             }
             constructor() {
                 super();
                 this.invalid = null;
                 this.value = 'happy';
                 this.required = false;
             }
    render() {
        //console.log('render ha-input', this.type, this.value, this.required, this.pattern);
                 return html`
                    <wa-input 
                      .type=${this.type}
                      .value=${this.value ?? null}
                      .required=${this.required}
                      .pattern=${this.pattern}
                      .min=${this.min}
                      .autofocus=${this.autofocus}
                    >
                        <slot name="end" slot="end"></slot>
                    </wa-input>
                 `;
    }
}

class HaPanelLovelace extends LitElement {
        constructor() { super(); }
};
class StateBadge extends LitElement {
        render() {
            return html`<div style="width: 40px; height: 20px; border: 1px solid green; box-sizing: border-box;">!</div>`;
        }
};
class HaMdListItem extends MdListItem {
      static styles = [
          super.styles,
        css`
          :host {
            --ha-icon-display: block;
            --md-sys-color-primary: var(--primary-text-color);
            --md-sys-color-secondary: var(--secondary-text-color);
            --md-sys-color-surface: var(--card-background-color);
            --md-sys-color-on-surface: var(--primary-text-color);
            --md-sys-color-on-surface-variant: var(--secondary-text-color);
          }
          md-item {
            overflow: var(--md-item-overflow, hidden);
          }
        `,
      ];
    }
    class HaCodeEditor extends LitElement {
        static properties = {
            hass: { attribute: false },
            value: { attribute: false }
        }
        constructor() {
            super();
            this.value = null;
        }
        render() {
            return html`<ha-input label="some code" .required=${true} type="text" helperpersistent=""  .helper=${"fake code helper"} .value=${this.value} @input=${this._vChange}></ha-input>`;
        }
        _vChange(ev) {
            let value = ev.detail?.value || ev.target.value;
            this.value = value;
            fireEvent(this, "value-changed", { value: this.value });
        }
    }
    customElements.define('state-badge', StateBadge);
    customElements.define('ha-panel-lovelace', HaPanelLovelace);
    customElements.define('ha-md-list-item', HaMdListItem);
    customElements.define('ha-code-editor', HaCodeEditor);

         customElements.define('ha-slider', HaSlider);
         customElements.define('ha-card', HaCard);
         customElements.define('ha-progress-button', HaProgressButton);
         customElements.define('ha-formfield', HaFormfield);
         customElements.define('ha-radio', HaRadio);
    customElements.define('ha-input', HaInput); // hack
    window.LitElement = LitElement;
    window.LitElement.prototype.html = html;
    window.LitElement.prototype.css = css;

function fireEvent(node, type, detail=null, options={}) {
  options = options || {};
    detail = detail === null || detail === undefined ? {} : detail;
    const event = new Event(type, {
        bubbles: options.bubbles === undefined ? true : options.bubbles,
        cancelable: Boolean(options.cancelable),
        composed: options.composed === undefined ? true : options.composed,
    });
    event.detail = detail;
    node.dispatchEvent(event);
    return event;
}
