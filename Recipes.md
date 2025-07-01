# Alert2 recipes

This guide is a companion to the main [Alert2 documentation](README.md). The examples below use YAML syntax. You can equivalently configure alerts via the HomeAssistant UI.

Suggestions welcome! Follow the [development thread](https://community.home-assistant.io/t/alert2-a-new-alerting-component) or file an [Issue](https://github.com/redstone99/hass-alert2/issues).

## Getting started and setting defaults

The first step is to install [Alert2](https://github.com/redstone99/hass-alert2) and [Alert2 UI](https://github.com/redstone99/hass-alert2-ui). If configuring alerts via the UI, you'll be using the Alert2 Manager card.

We recommend setting a few defaults:

```yaml
alert2:
  defaults:
    throttle_fires_per_mins: [ 10, 60 ] # throttle notifications for any alert that fires
                                        # more than 10x in 60 minutes
    notifier: foo # notifier name to use for most alerts
    summary_notifier: foo # notifier to use for summaries (e.g. when throttling ends)
```

Replace "foo" with whatever notifier you want to use. The default is `persistent_notification`, which adds notifications to the "Notifications" tab in HomeAssistant.

## A few simple alerts

A basic condition alert requires just `domain`, `name`, and `condition` to be set.  Everything else is optional. `domain` and `name` can be whatever you want. The purpose is to help you organize your alerts.

If you have an entity `binary_sensor.sidedoor_deadbolt_low_battery`, you could alert when the battery is low with:

```yaml
alert2:
  defaults:
    ...
  alerts:
    - domain: sidedoor
      name: low_battery
      condition: binary_sensor.sidedoor_deadbolt_low_battery
```

If you want to get a feel for what an alert looks like when it's firing, this alert is always firing:

```yaml
    - domain: test
      name: always_firing
      condition: true
```

You can also specify the alert condition using a template:

```yaml
    - domain: sys
      name: memory low
      condition:  "{{ states('sensor.memory_free')|float < 1000 }}"
```

Example alerting if a door is open too long. The alert starts firing only once the door has been open for 10 minutes:

```yaml
    - domain: front_door
      name: open too long
      condition:  binary_sensor.front_door_open
      delay_on_secs: 600
```

Extending above example to notify via HA companion mobile app, with notification that disappears when alert turns off.  In the following, we turn off `annotate_messages` so that the magic "clear_notification" is sent verbatim when the alert turns off.

```yaml
    - domain: front_door
      name: open too long
      condition:  binary_sensor.front_door_open
      delay_on_secs: 600
      annotate_messages: false
      # Since annotate_messages is false, "message" needs to specify what the notification is for
      message: front_door open too long
      done_message: clear_notification
      data:
        tag: "front_door-open-too-long"
```

Or suppose you had multiple doors and you wanted to alert if any of them are open too long.  Using generators:

```yaml
    - domain: "{{ genElem }}"
      name: open too long
      condition:  "{{ states('binary_sensor.' + genElem + '_open') }}"
      delay_on_secs: 600
      generator_name: g1
      generator: [ front_door, side_door, garage_door ]
```
