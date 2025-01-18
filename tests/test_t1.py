#
# JTESTDIR=/home/redstone/home-monitoring/homeassistant  venv/bin/pytest --show-capture=no
#
#from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import os
import sys
import asyncio
import logging
import datetime as rawdt
_LOGGER = logging.getLogger(None) # get root logger
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])
from custom_components.alert2 import (DOMAIN, Alert2Data)
import custom_components.alert2 as alert2

async def test_cfg1(hass):
    assert await async_setup_component(hass, DOMAIN, { 'alert2': {} })
    await hass.async_block_till_done()
    assert isinstance(hass.data[DOMAIN], Alert2Data)

async def test_badarg1(hass, service_calls):
    cfg = { 'alert2' : {
        'defaults' : {
            'notifierz' : 'foobar'
        },
    } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    service_calls.popNotify('persistent_notification', r'extra keys not allowed')
    assert service_calls.isEmpty()

async def test_ack(hass, service_calls):
    hass.states.async_set("sensor.b1", "off")
    #cfg = { 'input_boolean': { 'b1': { 'name': 'b1' } } }
    #assert await async_setup_component(hass, 'input_boolean', cfg)

    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'sensor.b1' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]

    t1 = gad.alerts['test']['t1']

    # First let's try condition on then off
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    assert t1.state == 'on'
    service_calls.popNotify('persistent_notification', r'test_t1: turned on')
    assert service_calls.isEmpty()
    # turning it on again should have no effect
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # turn off
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    assert t1.state == 'off'
    service_calls.popNotify('persistent_notification', r'test_t1: turned off')
    assert service_calls.isEmpty()
    # turn off again shouldn't change anything
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    # Now let's try condition on, ack, off
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    service_calls.popNotify('persistent_notification', r'test_t1: turned on')
    await t1.async_ack()
    await hass.async_block_till_done()
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # and let's try ack_all
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    service_calls.popNotify('persistent_notification', r'test_t1: turned on')
    await hass.services.async_call('alert2', 'ack_all', {})
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    # auto_check_empty_calls makes sure no calls left in stack

async def setAndWait(hass, eid, state): 
    hass.states.async_set(eid, state)
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    
async def test_badtemplate(hass, service_calls):
    hass.states.async_set("sensor.b1", "off")
    hass.states.async_set("sensor.e1", "1")
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't2a', 'condition': '{{ foo' },
        { 'domain': 'test', 'name': 't2b', 'condition': 'happy' },
        { 'domain': 'test', 'name': 't2c', 'condition': 'sensor.b1' },
        { 'domain': 'test', 'name': 't2d', 'condition': '' },
        { 'domain': 'test', 'name': 't2e', 'condition': '{{}}' },
        { 'domain': 'test', 'name': 't2f', 'condition': '{{none}}' },

        { 'domain': 'test', 'name': 't2at', 'trigger': [{'platform':'state','entity_id':'sensor.e1'}], 'condition': '{{ foo' },
        { 'domain': 'test', 'name': 't2bt', 'trigger': [{'platform':'state','entity_id':'sensor.e1'}], 'condition': 'happy' },
        { 'domain': 'test', 'name': 't2ct', 'trigger': [{'platform':'state','entity_id':'sensor.e1'}], 'condition': 'sensor.b1' },
        { 'domain': 'test', 'name': 't2dt', 'trigger': [{'platform':'state','entity_id':'sensor.e1'}], 'condition': '' },
        { 'domain': 'test', 'name': 't2et', 'trigger': [{'platform':'state','entity_id':'sensor.e1'}], 'condition': '{{}}' },
        { 'domain': 'test', 'name': 't2ft', 'trigger': [{'platform':'state','entity_id':'sensor.e1'}], 'condition': '{{none}}' },
    ], 'tracked': [
    ] } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't2a', r'unexpected end of template.*\'t2a\'')
    service_calls.popNotifySearch('persistent_notification', 't2b', r'test_t2b.*not truthy.*happy')
    service_calls.popNotifySearch('persistent_notification', 't2d', r'test_t2d.*not truthy.*states\(""')
    service_calls.popNotifySearch('persistent_notification', 't2e', r'invalid template.*\'t2e\'.*{{}}')
    service_calls.popNotifySearch('persistent_notification', 't2f', r'test_t2f.*returned None')

    service_calls.popNotifySearch('persistent_notification', 't2at', r'unexpected end of template.*\'t2at\'')
    service_calls.popNotifySearch('persistent_notification', 't2et', r'invalid template.*\'t2et\'.*{{}}')
    
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.b1", "sad")
    service_calls.popNotify('persistent_notification', r'test_t2c.*sad.*not truthy.*sensor.b1')
    assert service_calls.isEmpty()

    # Now try bad conditions with triggers
    await setAndWait(hass, "sensor.e1", "2")
    
    service_calls.popNotifySearch('persistent_notification', 't2bt', r'test_t2bt.*not truthy.*happy')
    service_calls.popNotifySearch('persistent_notification', 't2ct', r'test_t2ct.*sad.*not truthy.*sensor.b1')
    service_calls.popNotifySearch('persistent_notification', 't2dt', r'test_t2dt.*not truthy.*states\(""')
    service_calls.popNotifySearch('persistent_notification', 't2ft', r'test_t2ft.*not truthy.*none')
    assert service_calls.isEmpty()

async def test_reminder(hass, service_calls):
    hass.states.async_set("sensor.b1", "off")
    hass.states.async_set("sensor.b2", "off")
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't3a', 'condition': 'sensor.b1', 'reminder_frequency_mins': [0.01, 0.05] },
        { 'domain': 'test', 'name': 't3b', 'condition': 'sensor.b2' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.b1', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3a: turned on')
    await asyncio.sleep(1.7) # reminder interval is 1 + specified interval
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3a.*on for')
    await asyncio.sleep(2)  # not enough
    assert service_calls.isEmpty()
    await asyncio.sleep(2)  # enough for 2nd reminder
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3a.*on for')
    await setAndWait(hass, 'sensor.b1', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3a: turned off')

    # And what about if ack'd before reminder time.  Should only see turn-on notification
    await setAndWait(hass, 'sensor.b1', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3a: turned on')
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t3a'})
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    await asyncio.sleep(2) # reminder interval is 1 + specified interval
    await setAndWait(hass, 'sensor.b1', 'off')
    assert service_calls.isEmpty()
    
    # and default remimder time is long, so no reminders
    await setAndWait(hass, 'sensor.b2', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3b: turned on')
    await asyncio.sleep(2) # reminder interval is 1 + specified interval
    await setAndWait(hass, 'sensor.b2', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3b: turned off')
    assert service_calls.isEmpty()

async def test_reminder2(hass, service_calls):
    hass.states.async_set("sensor.b1", "off")
    hass.states.async_set("sensor.b2", "off")
    # Check that default value of reminder is overridden and is used
    cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 10 },
                         'alerts' : [
                             { 'domain': 'test', 'name': 't4a', 'condition': 'sensor.b1', 'reminder_frequency_mins': [0.01, 0.05] },
                             { 'domain': 'test', 'name': 't4b', 'condition': 'sensor.b2' },
                         ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.b1', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t4a: turned on')
    await asyncio.sleep(2) # reminder interval is 1 + specified interval
    service_calls.popNotifyEmpty('persistent_notification', r'test_t4a.*on for')
    await setAndWait(hass, 'sensor.b1', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t4a: turned off')

    # and default remimder time is long, so no reminders
    await setAndWait(hass, 'sensor.b2', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t4b: turned on')
    await asyncio.sleep(2) # reminder interval is 1 + specified interval
    await setAndWait(hass, 'sensor.b2', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t4b: turned off')
    assert service_calls.isEmpty()

    
async def test_reminder3(hass, service_calls):
    hass.states.async_set("sensor.b1", "off")
    # Check that default value of reminder is used
    cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 },
                         'alerts' : [
                             { 'domain': 'test', 'name': 't5a', 'condition': 'sensor.b1' },
                         ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.b1', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t5a: turned on')
    await asyncio.sleep(2) # reminder interval is 1 + specified interval
    service_calls.popNotifyEmpty('persistent_notification', r'test_t5a.*on for')
    await setAndWait(hass, 'sensor.b1', 'off')
    await asyncio.sleep(1.2) # Wait for remainder 
    service_calls.popNotifyEmpty('persistent_notification', r'test_t5a: turned off')

def resetModuleLoadTime():
    alert2.moduleLoadTime = rawdt.datetime.now(rawdt.UTC)

    
async def test_notifiers1(hass, service_calls):
    resetModuleLoadTime()
    alert2.kNotifierStartupGraceSecs = 3
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.b", "off")
    hass.states.async_set("sensor.c", "off")
    cfg = { 'alert2' : { 'alerts' : [
        # notifier available immediately
        { 'domain': 'test', 'name': 't6a', 'condition': 'sensor.a', 'notifier': 'persistent_notification' },
        # notifier available in grace period
        { 'domain': 'test', 'name': 't6b', 'condition': 'sensor.b', 'notifier': 'foo' },
        # notifier available after grace period
        { 'domain': 'test', 'name': 't6c', 'condition': 'sensor.c', 'notifier': 'foo2' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    #####
    # initial startup
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t6a: turned on')
    await setAndWait(hass, 'sensor.b', 'on')
    await setAndWait(hass, 'sensor.b', 'off')
    await setAndWait(hass, 'sensor.c', 'on')
    assert service_calls.isEmpty()
    
    ####
    # Now notifier foo becomes available, so we get the notification
    def mock_service_foo(call):
        return None
    hass.services.async_register('notify', 'foo', mock_service_foo)
    kStartupWaitPollSecs = alert2.kNotifierStartupGraceSecs / alert2.kStartupWaitPollFactor
    await asyncio.sleep(1.2 * kStartupWaitPollSecs)
    service_calls.popNotify('foo', r'test_t6b: turned on')
    service_calls.popNotifyEmpty('foo', r'test_t6b: turned off')

    ###
    # Now let the rest of the grace period interval elapse. Should get errors finally
    # ( we already waited some, so waiting the full kNotifierInitGraceSecs should be adequate )
    await asyncio.sleep(alert2.kNotifierStartupGraceSecs)
    service_calls.popNotifyEmpty('persistent_notification', r'notifiers are not known.*\'foo2\'')

    # TODO - what about the los test_t6c notification?

    # and test now new notifications now that we are out of the grace period
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t6a: turned off')
    await setAndWait(hass, 'sensor.b', 'on')
    service_calls.popNotifyEmpty('foo', r'test_t6b: turned on')
    await setAndWait(hass, 'sensor.c', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t6c.*notifier "foo2" is not known.*with message=.*turned off')

    # And now register foo2
    hass.services.async_register('notify', 'foo2', mock_service_foo)
    await setAndWait(hass, 'sensor.c', 'on')
    service_calls.popNotifyEmpty('foo2', r'test_t6c: turned on')

async def test_notifiers2(hass, service_calls):
    resetModuleLoadTime()
    alert2.kNotifierStartupGraceSecs = 3
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.b", "off")
    hass.states.async_set("sensor.c", "off")
    hass.states.async_set("sensor.d", "off")
    cfg = { 'alert2' : { 'alerts' : [
        # some combos
        # foo available soon after startup.  Foo2 not available till later
        { 'domain': 'test', 'name': 't7a', 'condition': 'sensor.a', 'notifier': ['persistent_notification', 'foo'] },
        { 'domain': 'test', 'name': 't7b', 'condition': 'sensor.b', 'notifier': ['foo', 'persistent_notification'] },
        { 'domain': 'test', 'name': 't7c', 'condition': 'sensor.c', 'notifier': ['foo', 'foo2'] },
        { 'domain': 'test', 'name': 't7d', 'condition': 'sensor.d', 'notifier': ['foo2', 'persistent_notification'] },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # only persistent one exists.
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t7a: turned on')
    await setAndWait(hass, 'sensor.b', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t7b: turned on')
    await setAndWait(hass, 'sensor.c', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.d', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t7d: turned on')

    # Now foo comes around
    def mock_service_foo(call):
        return None
    hass.services.async_register('notify', 'foo', mock_service_foo)
    kStartupWaitPollSecs = alert2.kNotifierStartupGraceSecs / alert2.kStartupWaitPollFactor
    await asyncio.sleep(1.2 * kStartupWaitPollSecs)
    service_calls.popNotify('foo', r'test_t7a: turned on')
    service_calls.popNotify('foo', r'test_t7b: turned on')
    service_calls.popNotifyEmpty('foo', r'test_t7c: turned on')

    # Now let rest of startup grace period elapse.
    await asyncio.sleep(alert2.kNotifierStartupGraceSecs)
    service_calls.popNotifyEmpty('persistent_notification', r'notifiers are not known.*\'foo2\'')
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifySearch('persistent_notification', 't7a', r'test_t7a: turned off')
    service_calls.popNotifySearch('foo', 't7a', r'test_t7a: turned off')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.b', 'off')
    service_calls.popNotifySearch('persistent_notification', 't7b', r'test_t7b: turned off')
    service_calls.popNotifySearch('foo', 't7b', r'test_t7b: turned off')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.c', 'off')
    service_calls.popNotifySearch('foo', 't7c', r'test_t7c: turned off')
    service_calls.popNotifySearch('persistent_notification', 't7c', r'"foo2".*is not known.*message=.*t7c.*turned off')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.d', 'off')
    service_calls.popNotifySearch('persistent_notification', 't7d', r'test_t7d: turned off')
    service_calls.popNotifySearch('persistent_notification', 't7d', r'"foo2".*is not known.*message=.*t7d.*turned off')
    assert service_calls.isEmpty()

    # And now register foo2
    hass.services.async_register('notify', 'foo2', mock_service_foo)
    await setAndWait(hass, 'sensor.c', 'on')
    service_calls.popNotifySearch('foo2', 't7c', r'test_t7c: turned on')
    service_calls.popNotifySearch('foo', 't7c', r'test_t7c: turned on')
    assert service_calls.isEmpty()
