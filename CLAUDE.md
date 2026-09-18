# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Alert2 is a Home Assistant custom integration (`custom_components/alert2`) that replaces the
built-in `alert` integration with richer templating, event-based firing, dynamic generators,
supersede/priority logic, and a companion web UI card (separate repo: `hass-alert2-ui`).

Domain constant: `alert2`. Alert entities live in `alert2.*`; generator entities live in `sensor.*`.
Current version is tracked in `custom_components/alert2/manifest.json`.

## Commands

```bash
# One-time env setup (creates venv, installs deps, ensures a config/ dir for HA)
scripts/setup.sh

# Manual dependency install
pip install -r requirements.txt -r requirements_test.txt

# Run the full test suite
pytest

# Run a single test file
pytest tests/test_t1.py

# Run a single test
pytest tests/test_t1.py::test_name

# Run with debug logging
pytest --log-cli-level=DEBUG

# Load the integration source from a different HA config checkout
JTESTDIR=/path/to/ha/config pytest --show-capture=no tests/test_t1.py

# Lint / type-check (no repo-specific config committed; run with defaults)
ruff check custom_components/alert2
mypy custom_components/alert2
```

There is no build step — this is a Python HA custom component, deployed by copying
`custom_components/alert2/` into a Home Assistant `custom_components` directory (or via HACS).
CI (`.github/workflows/validate.yml`) only runs HACS and hassfest manifest validation, not tests.

To exercise the companion UI card's backend from this repo, run the dummy notify server:
`JTEST_JS_DIR=/path/to/hass-alert2-ui pytest tests/dummy_server.py` (listens on port 50005).

## Architecture

### Central coordinator

`Alert2Data` (`__init__.py`), stored in `hass.data[DOMAIN]`, owns everything:
- `alerts` — `{domain: {name: ConditionAlert}}`
- `tracked` — `{domain: {name: EventAlert}}`
- `generators` — `{name: AlertGenerator}`
- `component` / `sensorComponent` — `EntityComponent`s for the `alert2` and `sensor` domains
- `supersedeMgr`, `supersedeNotifyMgr`, `delayedNotifierMgr`, `uiMgr`

Startup: `async_setup()` (YAML) and `async_setup_entry()` (config entry) both call `init2()`,
which is idempotent (guarded against double-init) and is also called again on `alert2.reload`.
`init2()` applies built-in defaults, then YAML defaults, then merges UI-stored settings, declares
the three built-in internal alerts, starts `DelayedNotifierMgr` (30s startup grace period so
notify platforms finish loading), installs an asyncio exception handler, and registers services.
`processConfig()` then loads YAML alerts/tracked and UI-created alerts, and schedules entity
registry GC after a 10s delay. Alerts with `early_start=false` only start watching after
`EVENT_HOMEASSISTANT_STARTED`.

### Entity model (`entities.py`)

Three alert entity types, all deriving from `AlertCommon(Entity)` → `AlertBase(AlertCommon,
RestoreEntity)`:

- **`EventAlert`** — fires on a HA trigger spec plus optional condition template. State is the
  ISO timestamp of last fire, or `"has never fired"`. An `EventAlert` with no trigger is a
  "tracked" alert, fired only via the `report()` Python API (used for `alert2.error` etc.).
- **`ConditionAlert`** — on/off state driven by `condition`, `threshold` (numeric hysteresis),
  or split `condition_on`/`condition_off`/`trigger_on`/`trigger_off`. Supports `supersedes`,
  `delay_on_secs`, `done_notifier`, `done_message`, `reminder_message`.
- **`AlertGenerator(AlertCommon, SensorEntity)`** — wraps a Jinja2 `generator:` template that
  produces a list; for each element it incrementally creates/destroys child `EventAlert` or
  `ConditionAlert` entities (not recreated wholesale on every list change). Lives in `sensor.*`,
  not `alert2.*`. Injects `genElem`/`genEntityId`/`genIdx`/`genGroups`/`genRaw` into child
  templates, and must use `rawConfig` (not the already-processed config) when building children,
  to avoid double-interpreting template fields.

Supporting classes in `entities.py`: `TriggerCond` (wraps `async_initialize_triggers` plus an
optional condition template), `Tracker` (wraps `async_track_template_result`, handles Bool/Str/
Float/List coercion, blocks template self-reference to avoid feedback loops), `MovingSum`
(10-bucket sliding-window counter backing throttling).

Supersede classes live in `__init__.py`: `SupersedeMgr` is a directed graph (`supersedesMap`/
`supersededByMap`) with transitive traversal and cycle detection — when touching supersede logic,
keep both maps consistent. `SupersedeNotifyMgr` resolves near-simultaneous firings between related
alerts using an `asyncio.Event` + `asyncio.wait_for(timeout=debounce_secs)` so a higher-priority
alert can preempt a lower one's notification.

### Notification pipeline

```
report() / trigger fires
  → AlertBase._notify_pre_debounce()      builds message, updates last_fired_time
  → SupersedeNotifyMgr.processNotify()    waits debounce_secs if a superseding alert may fire
  → AlertBase._notify_post_debounce()     can_notify_now() checks snooze/throttle/reminder timing,
                                           resolves notifier list via notifierTemplateToList()
  → hass.services.async_call('notify', ...)
```

`_notify_pre_debounce()` does not itself call `async_write_ha_state()` or `reminder_check()` —
callers must do both. Both new entity-platform notifiers (`notify.send_message`, matched via
entity registry) and legacy service-based notifiers are supported; `notifierExists()` checks both.
`NotificationReason` enum: `Fire`, `ReminderOn`, `StopFiring`, `Summary`, `SnoozeEnded`,
`ReminderToAck`. Reminder scheduling (`reminder_frequency_mins`, escalating intervals) is
centralized in `AlertBase.reminder_check()`, which cancels/reschedules on every state change,
ack, snooze, or throttle transition.

### Config schemas (`config.py`)

Voluptuous schemas: `DEFAULTS_SCHEMA`, `SINGLE_TRACKED_SCHEMA`, `SINGLE_ALERT_SCHEMA_EVENT_{NO_GEN,GEN}`,
`SINGLE_ALERT_SCHEMA_CONDITION_{NO_GEN,GEN}`, `TOP_LEVEL_SCHEMA`. `check_off()` enforces that
`condition`/`threshold` are mutually exclusive with `condition_on`/`condition_off`. Custom
validators: `boolTemplate`, `floatTemplate`, `jtemplate`, `jstringList`, `jProtectedTrigger`,
`jProtectedGeneratorTrigger`. `JTemplate` extends `template_helper.Template` to move `domains` →
`domains_lifecycle` (avoids expensive state tracking for generator templates) and adds the
`entity_regex` Jinja2 filter — use `JTemplate` for generator templates, `cv.template` for regular
alert templates.

### UI layer (`ui.py`)

`UiMgr` persists UI-created alerts and global settings via HA's `Store` (key `alert2.ui`), serves
`POST /api/alert2/manageAlert` (load/create/update/delete/validate/search), and WebSocket commands
for alert listing, top-config, and entity navigation. Config layering is YAML overridden by UI
settings, merged in `Alert2Data.noteUiUpdate()` — never mutate `rawYamlBaseTopConfig` directly.
`loadAlertBlock` in `__init__.py` processes alerts in two passes (supersedes registration, then
entity declaration) to support forward references between alerts.

### Internal error reporting

`util.report(domain, name, message)` fires the `alert2_report` HA bus event, handled by
`Alert2Data.handle_event_report`. Three internal alerts are auto-declared unless
`skip_internal_errors: true`: `alert2.error`, `alert2.warning`, `alert2.global_exception`
(throttled 20/60min by default). Use `reportIfSafe()` inside `alert2.error` handling itself to
avoid infinite recursion.

### Entity IDs and keys

Entity IDs are always `alert2.<slugify(domain + "_" + name)>`, generated by
`getPreferredEntityId(domain, name)`. `domain` + `name` (not `entity_id`) is the logical key for
every alert everywhere in the codebase.

### Task helpers

`create_task()` vs `create_background_task()` (in `util.py`) both wrap HA task creation with
exception reporting and tracking in `global_tasks`. Prefer `create_background_task` for
long-running loops, `create_task` for one-shot work.

## Testing notes

- Tests use `pytest-homeassistant-custom-component`; `conftest.py` provides the `service_calls`
  fixture (a `CallCollector` that monkeypatches `ServiceRegistry.async_call` to intercept `notify.*`
  calls) and an autouse `global_setup_teardown` fixture.
- The `auto_check_empty_calls` fixture (used across tests) asserts no unprocessed notify calls
  remain at test end — pop every expected notification via `service_calls.popNotify*`.
- `alert2.gGcDelaySecs` is set to `0.1` in tests to speed up entity registry GC.
- `test_t1.py` covers core alert types, generators, supersede, throttle, snooze, reload;
  `test_ui.py` covers the REST/WebSocket UI layer.

## External developer API

Other integrations can fire Alert2 event alerts programmatically:

```python
from custom_components.alert2 import declareEventMulti
await declareEventMulti([{'domain': 'my_integration', 'name': 'connection_lost'}])

from custom_components.alert2.util import report
report('my_integration', 'connection_lost', 'Lost connection to device XYZ')
```

`report()` is synchronous and thread-safe (uses `loop.call_soon_threadsafe()`), so it can be
called from worker threads.
