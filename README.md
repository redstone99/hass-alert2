<!-- ~/tmp/general-env/bin/grip -b ~/tmp/hass-alert2/README.md
To spin up a fresh HA for testing:
mkdir -p ha-test/custom_components/hacs
wget https://github.com/hacs/integration/releases/latest/download/hacs.zip
unzip hacs.zip -d ha-test/custom_components/hacs  ; rm hacs.zip
cp .homeassistant/run ha-test/run
chgrp -R homeassistant ha-test ; chmod -R g+w ha-test
cp ha-test.old/configuration.yaml ha-test
# comment out lovelace stuff
# restart home assistant
# install HACS as integration
# test install alert2
-->

[![GitHub Release](https://img.shields.io/github/v/release/redstone99/hass-alert2)](https://github.com/redstone99/hass-alert2/releases)
[![GitHub Release Date](https://img.shields.io/github/release-date/redstone99/hass-alert2)](https://github.com/redstone99/hass-alert2/releases)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/y/redstone99/hass-alert2)](https://github.com/redstone99/hass-alert2/commits/master/)
<!-- ![GitHub commits since latest release](https://img.shields.io/github/commits-since/redstone99/hass-alert2/latest) -->

# Alert2

Alert2 is a [Home Assistant](https://www.home-assistant.io/) component that supports alerting and sending notifications based on conditions and events. It's a retake on the original [Alert](https://www.home-assistant.io/integrations/alert/) integration.


## Table of Contents

- [New features](#new-features)
- [Installation](#installation)
- [Setup](#setup)
- [Description](#description)
- [Configuration](#configuration)
- [Front-end UI](#front-end-ui)
- [Service calls](#service-calls)
- [Python alerting](#python-alerting)


## New features

- **Native event-based alerting**. No need to approximate it with conditions and time windows.
- **Template conditions**.  No need for extra binary sensors. Also means the logic for an alert is in one place in your config file, which makes it easier to manage.
- **Snooze / disable / throttle notifications**. Handy for noisy sensors or while developing your alerts.
- **Persistent notification details**. In your HA dashboard, you can view past alert firings as well as the message text sent in notifications.
- **Custom frontend card**. Makes it easier to view and manage recent alerts.
- **Hysteresis**. Reduce spurious alerts as sensors fluctuate.
- **Template notifiers**. Dynamically specify who gets notified.

Suggestions welcome! Start a [Discussion](https://github.com/redstone99/hass-alert2/discussions) or file an [Issue](https://github.com/redstone99/hass-alert2/issues).

## Installation

### HACS install (recommended)

1. If HACS is not installed, follow HACS installation and configuration instructions at https://hacs.xyz/.

1. Click the button below

    [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=redstone99&repository=hass-alert2&category=integration)

    or visit the HACS pane and add `https://github.com/redstone99/hass-alert2.git` as a custom repository of type  `Integration` by following [these instructions](https://hacs.xyz/docs/faq/custom_repositories/).

1. The UI should now show the Alert2 doc page in HACS. Click "Download" button (bottom right of screen) to download the Alert2 integration.

    If for some reason adding the repository did not take you to the Alert2 doc page, you may need to click again on the HACS pane, search for "Alert2" and click on it to get to the page (and the download button).

1. We strongly recommend also installing the [Alert2 UI](https://github.com/redstone99/hass-alert2-ui) card which is a compact way to view and manage Alert2 alerts.

### Manual install

1. Download the `Source code (zip)` link from the repository [release section](https://github.com/redstone99/hass-alert2/releases) under "Assets" and extract it.

   We do not recommend downloading directly from the `master` branch.

1. Create the directory `custom_components` in your Home Assistant configuration directory if it doesn't already exist.

   Your configuration directory is the directory with `configuration.yaml`. It is commonly `/config`, or may be something like `~/.home-assistant/` for Linux installations.
   
1. Copy the `alert2` folder inside the `custom_components` directory in the `Source code` link you downloaded into the directory `custom_components` in your config.

   Your config directory should look similar to this after copying:
   
        <config dir>/configuration.yaml
        <config dir>/custom_components/alert2/__init__.py
        <config dir>/custom_components/alert2/sensor.py
         ... etc...

1. We strongly recommend also installing the [Alert2 UI](https://github.com/redstone99/hass-alert2-ui) card which is a compact way to view and manage Alert2 alerts.

## Setup

Setup is done through editing your `configuration.yaml` file.


1. Add the following line to `configuration.yaml`:

        alert2:

    The [Configuration](#configuration) section, below, has details on what else to add here.

1. Restart HomeAssistant

## Description

Alert2 supports two kinds of alerts:

- **Condition-based alerts**. The alert watches a specified condition. It is "firing", aka "on", while the condition is true. This is similar to the existing [Alert](https://www.home-assistant.io/integrations/alert/) integration. Example: a temperature sensor that reports a high temperature.

- **Event-based alerts**. The alert waits for a specified trigger to occur and is "firing" for just that moment.  Example: a problematic MQTT message arrives.

Configuration details and examples are in the [Configuration section]((#configuration)). Here is an overview:

### Condition alerts

Condition alerts can specify a `condition` as a template or entity name. The alert is firing when the condition evaluates to true.

An alert can also specify a `threshold` dict that includes min/max limits and optional hysteresis.  If a threshold is specified, the alert is firing if the threshold is exceeded AND any `condition` specified is true.

Hysteresis is also available via the `delay_on_secs` parameter. If specified, the alert starts firing once any `threshold` is exceeded AND any `condition` is true for at least the time interval specified. This is similar in motivation to the `skip_first` option in the old Alert integration.

### Event alerts

Event alerts may be triggered either by an explicit `trigger` option in the config, or by a service call to `alert2.report`.
An event alert can also specify a `condition` as a template or entity name. The alert fires if it is triggered AND the condition evaluates to true.

### Common alert features

Each alert maintains a bit indicating whether it has been ack'd or not.  That bit is reset each time the alert fires. Ack'ing is done by clicking a button in the UI (described below) or calling the `alert2.ack` service. Ack'ing stops reminder notifications (see below) and is indicated visually in the UI.

### Notifications

Notifications are sent when an event alert fires, and also when a condition alert starts firing, stops firing, and periodically as a reminder that the condition alert is still firing.

Each notification by default includes some basic context information (detailed below).  An alert can also specify a template `message` to be sent  each time the alert fires. That message is sent out with notifications and also is viewable in the front-end UI.  Condition alerts can also specify a `done_message` to be sent when the alert stops firing.

There are a few mechanisms available for controlling when and whether notifications are sent.

* `reminder_frequency_mins` - this config parameter specifies how often reminders are sent while an alert continues to fire. May be a list of values (similar to the `repeat` option in the old Alert integration).

* `throttle_fires_per_mins` - this config parameter throttles notifications for an alert that fires frequently. It affects all notifications for the alert.

* Ack'ing an alert prevents further reminders and the stop notification for the current firing of a condition alert. For both condition and event alerts, ack'ing also prevents any throttled notification of previous firings of the alert.

* Snoozing notifications for an alert prevents any notifications from current or future firings of an alert for a specified period of time.

* Disabling notifications for an alert prevents any notifications until it is enabled again.  Snoozing & disabling affect only notifications. Alerts will still fire and be recorded for reviewing in your dashboard.


#### Notification text

The text of each notification by default includes some basic context information that varies based on the type of notification. That information may be augmented with the `message` or `done_message` options.  Notification text looks like:

* Event alert fires: `message` text prepended with name (or `friendly_name`) of alert.

        Alert2 boiler_ignition_error: `message`

* Condition alert fires: `message` text prepended with name (or `friendly_name`) of alert.  Default message is "turned on" if no message specified. Alert name omitted if `annotate_messages` is false

        Alert2 kitchen_door_open: turned on

* Condition alert reminder:

        Alert2 kitchen_door_open: on for 5m

* Condition alert stops firing: `done_message` text prepended with name (or `friendly_name`) of alert.  Default message is "turned off after ..." if no `done_message` specified. Only `done_message` text is sent if `annotate_messages` is false. Setting `annotate_messages` to false may be useful for notification platforms that parse the message (such as the "clear_notification" message of the `mobile_app` platform)

        Alert2 kitchen_door_open: turned off after 10m

* Either event or condition alert fires and exceeds `throttle_fires_per_mins`.  Message is prepended with "[Throttling starts]", which can not be overridden with `annotate_messages`:

        [Throttling starts] Alert2 kitchen_door_open: turned on

* Throttling ends for event or condition alert that specified `throttle_fires_per_mins`.  Message includes information on what happened while the alert was throttled:

        [Throttling ends] Alert2 kitchen_door_open: fired 10x (most recently 15m ago): turned off 19s ago after being on for 3m

### Alert2 internal errors

Alert2 automatically defines an alert, `alert2.error`. It fires and will notify you of problems in your configuration file as well as if Alert2 internally encounters a problem, such as a notifier that does not exist.  If you don't want to be notified of errors like these, an option, `skip_internal_errors`, is available. One reason this alert is important is because if Alert2 itself encounters a problem, you may stop receiving alerts for things you do care about. So in a sense, this alert is at least as important as your most important alert.

`alert2.error` may be configured. See example in the [Tracked](#tracked) section, below.  If you specify a notifier that doesn't exist for `alert2.error` itself, then it falls back to `persistent_notification`.

## Configuration

Alert configuration is done through the `alert2:` section of your `configuration.yaml` file.  There are three subsections: `defaults`, `alerts`, and  `tracked`.

### Defaults

The `defaults:` subsection specifies default values for parameters common to every alert. Each of these parameters may be specified either in this subsection or over-ridden on a per-alert basis.


| Key | Type | Description |
|---|---|---|
| `reminder_frequency_mins` | float or list | Interval in minutes between reminders that a condition alert continues to fire. May be a list of floats in which case the delay between reminders follows successive values in the list. The last list value is used repeatedly when reached (i.e., it does not cycle like the `repeat` option of the old Alert integration).<br>Defaults to 60 minutes if not specified. |
| `notifier` | template | Name of notifiers to use for sending notifications. Notifiers are declared with the [Notify](https://www.home-assistant.io/integrations/notify/) integration. Service called will be `"notify." + notifier`.<br>Defaults to `persistent_notification` (shows up in the UI under "Notifications"). Can be list of notifiers, an entity name whose state is a list of notifiers, or a template that evaluates to either. See [Notifiers](#notifiers) section below for possibilities here.  |
| `annotate_messages` | bool | If true, add extra context information to notifications, like number of times alert has fired since last notification, how long it has been on, etc. You may want to set this to false if you want to set done_message to "clear_notification" for the `mobile_app` notification platform.<br>Defaults to true. |
| `throttle_fires_per_mins` | [int, float] | Limit notifications of alert firings based on a list of two numbers [X, Y]. If the alert has fired and notified more than X times in the last Y minutes, then throttling turns on and no further notifications occur until the rate drops below the threshold. For example, "[10, 60]" means you'll receive no more than 10 notifications of the alert firing every hour.<br>Default is no throttling. |

Example:

     alert2:
       defaults:
         reminder_frequency_mins: 60
         notifier: telegram
         annotate_messages: true
         throttle_fires_per_mins: [ 10, 60 ]

Note `reminder_frequency_mins` or `throttle_fires_per_mins` may be specified as a list using a YAML flow sequence or on separate lines. The following two are identical in YAML:

        reminder_frequency_mins: [ 10, 20, 60 ]
        reminder_frequency_mins:
          - 10
          - 20
          - 60

### Alerts

The `alerts:` subsection contains a list of condition-based and event-based alert specifications. The full list of parameters for each alert are as follows:


| Key | Type | Required | Description |
|---|---|---|---|
|`domain` | string | required | part of the entity name of the alert. The entity name of an alert is `alert2.{domain}_{name}`. `domain` is typically the object causing the alert (e.g., garage door). |
| `name` | string | required | part of the entity name of the alert. The entity name of an alert is `alert2.{domain}_{name}`. `name` is typically the particular fault occurring (e.g., open_too_long)  |
| `friendly_name` | string | optional | Name to display instead of the entity name. Surfaces in the [Alert2 UI](https://github.com/redstone99/hass-alert2-ui) overview card |
| `condition` | string | optional | Template string or entity name. Alert is firing if the template or entity state evaluates to truthy AND any other alert options specified below are also true.  |
| `trigger` | object | optional | A [trigger](https://www.home-assistant.io/docs/automation/trigger/) spec. Indicates an event-based alert. Alert fires when the trigger does, if also any `condition` specified is truthy. |
| `threshold:` | dict | optional | Subsection specifying a threshold criteria with hysteresis. Alert is firing if the threshold value exceeds bounds AND any `condition` specified is truthy. Not available for event-based alerts. |
| --&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`value` | string | required | A template or entity name that evaluates to a float to be compared to threshold limits. |
| --&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`hysteresis` | float | required | Compare `value` to limits using hysteresis. threshold is considered exceeded if value exceeds min/max, but does not reset until value increases past min+hysteresis or decreases past max-hysteresis. (see description below) |
| --&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`maximum` | float | optional | Maximum acceptable value for `value`. At least one of `maximum` and `minimum` must be specified. |
| --&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;`minimum` | float | optional | Minimum acceptable value for `value`. At least one of `maximum` and `minimum` must be specified. |
| `delay_on_secs` | float | optional | Specifies number of seconds that any `condition` must be true and any threshold specified must be exceeded before the alert starts firing. Similar in motivation to the `skip_first` option in the old Alert integration. |
| `message` | template | optional | Template string evaluated when the alert fires. This text is included in notifications. For event-based alerts, the message can reference the `trigger` variable (see example below). Because notifications by default include context information like the alert domain and name, the message can be brief or even omitted all together |
| `done_message` | template | optional | Message to send when a condition alert turns off.  Replaces the default message (e.g., "Alert2 [name] turned off after x minutes") |
| `data` | dict | optional | Optional dictionary passed as the "data" parameter to the notify service call |
| `target` | template | optional | Passed as the "target" parameter to the notify service call |
| `title` | template | optional | Passed as the "title" parameter to the notify service call |
| `annotate_messages` | bool | optional | Override the default value of `annotate_messages`.  |
| `reminder_frequency_mins` | float | optional | Override the default `reminder_frequency_mins`|
| `notifier` | template | optional | Override the default `notifier`. See [Notifiers](#notifiers) section below for examples. |
| `throttle_fires_per_mins` | [int, float] | optional | Override the default value of `throttle_fires_per_mins` |
| `early_start` | bool | optional | By default, alert monitoring starts only once HA has fully started (i.e., after the HOMEASSISTANT_STARTED event). If `early_start` is true for an alert, then monitoring of that alert starts earlier, as soon as the alert2 component loads. Useful for catching problems before HA fully starts.  |

Alert names are split into `domain` and `name`. The reason is partly for semantic clarity and also for future management features, like grouping alerts by domain.

#### Event-based alert

An event-based alert specifies a `trigger`, and fires when the trigger fires, as long as an optional `condition` is also true. Example:

    alert2:
      alerts:
        - domain: boiler
          name: ignition_failed
          trigger:
           - platform: state
             entity_id: sensor.boiler_failed_ignition_count
          condition: "{{ (trigger.from_state is not none) and (trigger.to_state is not none) and (trigger.from_state.state|int(-1) > 0) and (trigger.to_state.state|int(-1) > 0) and (trigger.to_state.state|int > trigger.from_state.state|int) }}"
          #   can be an entity name, e.g.:
          # condition: binary_sensor.boiler_enabled
          message: "{{ trigger.from_state.state }} -> {{ trigger.to_state.state }}"

#### Condition-based alert

There are a few different forms of condition-based alerts.  The simplest is an alert that just specifies a `condition`. It is firing when the condition is true. The condition can be either a template or an entity name. Example of an alert to detect when the temperature is too low:

    alert2:
      alerts:
        - domain: thermostat_fl2
          name: temperature_low
          condition: "{{ states('sensor.nest_therm_fl2_temperature')|float <= 50 }}"
          message: "Temp: {{ states('sensor.nest_therm_fl2_temperature') }}"
          
        - domain: thermostat_fl1
          name: temperature_low
          condition: binary_sensor.nest_therm_fl1_temperature_too_low
          message: ...

Notifications include by default context information, so the resulting text might be:

    Alert2 thermostat_fl2_temperature_low: Temp: 45

An alert can alternatively specify a threshold with hysteresis.  So the previous temperature-low alert could be specified with hysteresis as:

    alert2:
      alerts:
        - domain: thermostat_fl2
          name: temperature_low
          threshold:
            value: sensor.nest_therm_fl2_temperature
            #  can be a template. e.g.
            # value: "{{ states('sensor.nest_therm_fl2_temperature') }}"
            minimum: 50
            hysteresis: 5
          message: "Temp: {{ states('sensor.nest_therm_fl2_temperature') }}"

This alert would start firing if the temperature drops below 50 and won't stop firing until the temperature rises to at least 55.  A corresponding logic applies when a `maximum` is specified. Both `minimum` and `maximum` may be specified together.

A `condition` may be specified along with a `threshold`. In this case, the alert fires when the condition is true AND the threshold value is out of bounds.  `delay_on_secs` is another form of hysteresis that may be specified to reduce false alarms. It requires an alert condition be true or threshold be exceed for at least the specified number of seconds before firing.

#### Common alert features

Alerts may pass additional data to the notifier which is convenient for notification platforms such as [`mobile_app`](https://companion.home-assistant.io/docs/notifications/notifications-basic/). Example:

    alert2:
      alerts:
        - domain: cam_basement
          name: motion_while_away
          condition: "{{ (states('sensor.jdahua_basement_motion') == 'on') and
                         (states('input_select.homeaway') in [ 'Away-local', 'Away-travel' ]) and
                         ((now().timestamp() - states.input_select.homeaway.last_changed.timestamp()) > 5*60) }}"
          notifier: mobile_app_pixel_6
          title: "test title"
          data:
            group: "motion-alarms"

#### Notifiers

The `notifier` parameter can take a variety of different values. The basic usage can specify a single notifier or list of notifiers, or an entity whose state is a list of notifiers:

          # Single notifier
          notifier: telegram_1

          # List of notifiers (native YAML)
          notifier:
          - telegram_1
          - telegram_2

          # List of notifiers (YAML flow sequence, identical to list, above)
          notifier: [ telegram_1, telegram_2 ]

          # List of notifiers as a string.
          # Will be interpreted as python literal, so inner quotes needed.
          notifier: "[ 'telegram_1', 'telegram_2' ]"

          # Entity whose state is a list of notifiers (as a string)
          # for example, if sensor.my_notifier_list has state: "[ 'telegram_1', 'telegram_2' ]"
          # you might say:
          notifier: sensor.my_notifier_list

You can also specify a template that evaluates to either single notifier, a list of notifiers or to a single entity name that contains a list of notifiers

          # The template can resolve to a single notifier
          notifier: "{% if states('binary_sensor.is_away')|bool %} mobile_app_a
                     {% else %} mobile_app_b {% endif %}"
          
          # It can resolve to a list of notifiers
          notifier: "{{ [ 'notifier_a', 'notifier_b' ] + [ 'notifier_c', 'notifier_d' ] }}"

          # It can resolve to the name of an entity that has a notifier or list of notifiers
          # as its state.
          #
          # Suppose you have two entities, one with notifiers to use when away and another
          # to use when home.
          # say sensor.away_notifiers has state "[ 'notifier_a', 'notifier_b' ]"
          # and sensor.home_notifiers has state "notifier_c"
          # you could dynamically switch between them with:
          notifier: "{% if states('binary_sensor.is_away')|bool %} sensor.away_notifiers
                     {% else %} sensor.home_notifiers {% endif %}"

          # Or say you want to conditionally notify a 3rd notifier, "mobile_app_josh":
          notifier: "{{ [ 'telegram_1', 'telegram_2' ] +
                        ( [ 'mobile_app_josh' ] if states('binary_sensor.is_away')|bool else [] ) }}"

A technical note on quoting and lists of notifiers:<br>
Templates evaluate to a string, even if they have a list inside. An entity's state also produces a string.  Alert2 detects lists in such strings by evaluating the string as a python literal and seeing if a list results.  So notifiers in such lists need to be quoted or the eval mechanism will think you're trying to name a variable.

### Tracked

The `tracked` config subsection is for declaring event alerts that have no `trigger` specification and so can only be triggered by a service call to `alert2.report`. Declaring these alerts here avoids an "undeclared alert" alert when reporting, and also enables the system to restore the alert state when HomeAssistant restarts.

Any of the above event alert parameters may be specified here except for `message` (since `alert2.report` specifies the message), `trigger` and `condition`.

The `alert2.error` alert may be configured here.

Example:

    alert2:
      defaults:
        reminder_frequency_mins: 60
        notifier: telegram
      alerts:
        ...
      tracked:
        - domain: alert2
          name: error
          reminder_frequency_mins: 20
          ...
        - domain: dahua
          name: side_porch_fault

### Additional top-level options

`skip_internal_errors` is a optional top-level option. If true, an entity for `alert2.error` will not be created, you will not receive any notifications for problems with your config file or Alert2 internal errors, and such errors won't show up in the Alert2 UI card.  Errors will still appear in the log file.  Example config fragment:

    alert2:
      defaults:
        reminder_frequency_mins: 60
      skip_internal_errors: true


### Alert recommendations

We recommend setting a value for the default notifier so the `alert2.error` alert notifications will go somewhere you wish.  You can also 

As described above in `early_start`, alerts by default don't start being monitored until HA fully starts.  This is to reduce template errors during startup due to entities not being defined yet.  However, the downside is that if some problem prevents HA from fully starting, none of your alerts will be monitored.  To prevent this, we provide a binary_sensor entity, `binary_sensor.alert2_ha_startup_done`, that turns on when HA has fully started. That entity also has an attribute, `start_time`, that is the time the module loaded. Together you can use them to alert if HA startup takes too long as follows:

    alert2:
      alerts:
        - domain: general
          name: ha_startup_delayed
          # test against 'off' so we don't trigger during startup before binary_sensor has initialized
          condition: "{{ states('binary_sensor.alert2_ha_startup_done') == 'off' and
                (now().timestamp() - state_attr('binary_sensor.alert2_ha_startup_done', 'start_time').timestamp()) > 300 }}"
          message: "Starting for last {{ (now().timestamp() - state_attr('binary_sensor.alert2_ha_startup_done', 'start_time').timestamp()) }} seconds"
          early_start: true

Also, alert2 entities are built on `RestoreEntity`, which backs itself up every 15 minutes. This means, alert firing may not be remembered across HA restarts if the alert fired within 15 minutes of HA restarting.

## Front-end UI

We recommend also installing the [Alert2 UI](https://github.com/redstone99/hass-alert2-ui), which includes a card for compactly viewing and managing Alert2 alerts.  It also enhances the information shown in the "more-info" dialog when viewing Alert2 entities.

![Alert2 overview card](resources/overview.png)

Without [Alert2 UI](https://github.com/redstone99/hass-alert2-ui) you can still view and manage Alert2 alerts, but the process is a bit more involved.


## Service calls

Alert2 defines a few new service calls.

`alert2.report` notifies the system that an event-based alert has fired. It takes two parameters, the "domain" and "name" of the alert that fired.  You can also pass an optional `message` argument specifying a template for a message to include with the firing notification. That domain/name should be declared in either the `tracked` or `alerts` section of your config (described above).  `alert2.report` overrides any `condition` and `trigger` specified in the event alert declaration.

An example of using alert2.report in the action section of an automation:

        trigger:
          ...
        condition:
          ...
        action:
          - service: alert2.report
            data:
              domain: "boiler"
              name: "fault_{{trigger.event.data.name}}"
              message: "code is {{ trigger.event.data.dData.Code }}"

A few other service calls are used internally by [Alert2 UI](https://github.com/redstone99/hass-alert2-ui), but are available as well:

`alert2.ack_all` acks all alerts.
<br>`alert2.notification_control` adjust the notification settings.
<br>`alert2.ack` acks a single alert.

More details on these calls are in the [`services.yaml`](https://github.com/redstone99/hass-alert2/blob/master/custom_components/alert2/services.yaml) file in this repo, or in the UI by going to "Developer tools" -> "Actions".

## Python alerting

If you're developing python components, Alert2 is handy for alerting on unexpected conditions. The way to do that is:

1. In the `manifest.json` for your component, put a dependency on alert2. This is to ensure alert2 has initialized before your component.

        {
            "domain": "mydomain",
            "name": "My Component",
            ...
            "dependencies": [ "alert2" ]
        }                    

1. In your component, import `alert2` and in `async_setup` declare whatever event alerts you might want to trigger. E.g.:

        import custom_components.alert2 as alert2

        async def async_setup(hass, config):
            await alert2.declareEventMulti([
                { 'domain': 'mydomain', 'name': 'some err 1' },
                { 'domain': 'mydomain', 'name': 'some err 2' },
                ...
            ])

1. To trigger an alert, call `report()`, which takes an optional message argument. E.g.:

        if unexpected_thing_happens:
            alert2.report(DOMAIN, 'some err 1', 'optional message string')

The alert2 module also offers a `create_task()` and `create_background_task()` method to create tasks. It's similar to `hass.async_create_task` except it also `report()`s uncaught exceptions - so your task doesn't die silently.  Example usage:

```
async def testTask():
    pass
taskHandle = alert2.create_task(hass, 'mydomain', testTask())
#
# Later on, cancel task if you want
taskHandle.cancel()
```
If an unhandled exception occurs, alert2 will fire an alert: `alert2.mydomain_unhandled_exception`.  `declareEventMulti()` automatically declares `mydomain_unhandled_exception` if you haven't already.
