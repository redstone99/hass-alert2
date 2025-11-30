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

Extending above example to notify via HA companion mobile app, with notification that disappears when alert turns off.  In the following, we turn off `annotate_messages` so that the magic "clear_notification" is sent verbatim when the alert turns off.  Note that the companion app requires setting `tag` when using "clear_notification".

```yaml
    - domain: front_door
      name: open too long
      condition:  binary_sensor.front_door_open
      delay_on_secs: 600
      notifier: mobile_app_pixel_12
      annotate_messages: false
      # Since annotate_messages is false, "message" needs to specify what the notification is for
      message: front_door open too long
      done_message: clear_notification
      data:
        tag: "front_door-open-too-long"
```

Continuing with the door example, suppose you had multiple doors and you wanted to alert if any of them are open too long.  Using generators:

```yaml
    - domain: "{{ genElem }}"
      name: open too long
      condition:  "{{ states('binary_sensor.' + genElem + '_open') }}"
      delay_on_secs: 600
      generator_name: g1
      generator: [ front_door, side_door, garage_door ]
```

### Mobile notification actions

Suppose you want to have mobile notifications include actions such as an option to ack or snooze the alert.  The way to do this is to specify the alert entity id somewhere in the `data` field and then write an automation to handle the notification event.  At the time of writing this, HA doesn't seem to forward any extra data fields to the event, so it seems the only way to pass the alert entity id is encoding it in the action name. The example below adds actions to ack an alert and snooze it for an hour:

````yaml
    - domain: ....
      ...
      data:
        actions:
          - action: "{{ alert_entity_id }} ack"
            title: Ack
          - action: "{{ alert_entity_id }} snooze 01:00:00"
            title: Snooze 1hr
````

Now you need an automation to handle the resulting event. The automation below handles both "ack" and "snooze". Note that "snooze" encodes a duration argument in the action name.

```
- id: React to action events from Alert2 alerts
  alias: Alert2 - React to events from Alert-Notifications
  description: ""
  triggers:
    - trigger: event
      event_type: mobile_app_notification_action
  conditions:
    - condition: template
      value_template: '{{ trigger.event.data.action.startswith("alert2") }}'
  actions:
    - variables:
        alert2id: '{{ (trigger.event.data.action).split(" ")[0] }}'
        type: '{{ (trigger.event.data.action).split(" ")[1] }}'
    - choose:
        - conditions:
            - condition: template
              value_template: '{{ type == "ack" }}'
          sequence:
            - action: alert2.ack
              target:
                entity_id: "{{ alert2id }}"
        - conditions:
            - condition: template
              value_template: '{{ type == "snooze" }}'
          sequence:
            - variables:
                duration: '{{ (trigger.event.data.action).split(" ")[2] }}'
                until:
                  "{% if duration == \"tomorrow\" %}\n  {{ today_at(\"09:00:00\") +
                  timedelta(days=1) }}\n{% else %}\n  {{ now() + as_timedelta(duration)
                  }}\n{% endif %}"
            - action: alert2.notification_control
              data:
                enable: "on"
                ack_at_snooze_start: false
                snooze_until: "{{ until }}"
              target:
                entity_id: "{{ alert2id }}"
  mode: parallel

```

## More advanced alerts

Here's an example using the separate on/off conditions.  Suppose you want to alert when laundry needs to be emptied from the washer or dryer.  You have a power sensor measuring the power used by the washer and dryer, and both the washer and dryer have a door sensor.  You might set up the alert to turn on when the power usage spikes, and then turn off once either of the doors is opened.  That might look like:

```yaml
    - domain: laundry
      name: done
      condition_on:  "{{ states('sensor.laundry_room_power_watts')|float > 200 }}"
      trigger_off:
        - trigger: state
          entity_id:
            - binary_sensor.door_washer_open
            - binary_sensor.door_dryer_open
          to: "on"
```
