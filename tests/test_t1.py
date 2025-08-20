#
# For instructions on how to run, see
#    https://github.com/redstone99/hass-alert2#testing
#
#from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import os
import re
import sys
import asyncio
import logging
import pytest
import datetime as rawdt
_LOGGER = logging.getLogger(None) # get root logger
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])
from custom_components.alert2 import (DOMAIN, Alert2Data)
import custom_components.alert2 as alert2
import custom_components.alert2.entities as a2Entities
from custom_components.alert2.util import (     GENERATOR_DOMAIN,
                                                set_shutting_down,
                                                EVENT_ALERT2_CREATE,
                                                EVENT_ALERT2_DELETE,
                                                EVENT_ALERT2_FIRE,
                                                EVENT_ALERT2_ON,
                                                EVENT_ALERT2_OFF,
                                                EVENT_ALERT2_ACK,
                                                EVENT_ALERT2_UNACK,
                                           )
import homeassistant.const
from homeassistant import config as conf_util
import homeassistant.helpers.restore_state as rs
from homeassistant.util.yaml import parse_yaml
#from tests.common import MockConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

alert2.gGcDelaySecs = 0.1

# TODO - move these fixtures into a class that is reused between this t1 and ui tests.
#
# Make sure at end of each test there are no extra notifications we haven't processed
@pytest.fixture(autouse=True)
async def auto_check_empty_calls(hass, service_calls):
    yield
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
    
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
    assert t1.is_acked() == False
    assert t1.extra_state_attributes['is_acked'] == False
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    assert t1.state == 'on'
    service_calls.popNotify('persistent_notification', r'test_t1: turned on')
    assert service_calls.isEmpty()
    assert t1.extra_state_attributes['is_acked'] == False
    # turning it on again should have no effect
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # turn off
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    assert t1.state == 'off'
    assert t1.extra_state_attributes['is_acked'] == False
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
    assert t1.extra_state_attributes['is_acked'] == False
    await t1.async_ack()
    assert t1.is_acked() == True
    assert t1.extra_state_attributes['is_acked'] == True
    await hass.async_block_till_done()
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert t1.extra_state_attributes['is_acked'] == True

    # and let's try ack_all
    hass.states.async_set("sensor.b1", "on")
    await hass.async_block_till_done()
    assert t1.extra_state_attributes['is_acked'] == False
    service_calls.popNotify('persistent_notification', r'test_t1: turned on')
    await hass.services.async_call('alert2', 'ack_all', {})
    assert t1.extra_state_attributes['is_acked'] == True
    hass.states.async_set("sensor.b1", "off")
    await hass.async_block_till_done()
    assert t1.extra_state_attributes['is_acked'] == True
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
    hass.states.async_set("sensor.b3", "off")
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't3a', 'condition': 'sensor.b1', 'reminder_frequency_mins': [0.01, 0.05] },
        { 'domain': 'test', 'name': 't3c', 'condition': 'sensor.b3', 'reminder_frequency_mins': [0.01, 0.05], 'reminder_message': 'on for {{ (now().timestamp() - state_attr("alert2.test_t3d","last_on_time").timestamp())|int }} zsecs' },
        { 'domain': 'test', 'name': 't3d', 'condition': 'sensor.b3', 'reminder_frequency_mins': [0.01, 0.05], 'reminder_message': '{{ nnn  + 3 }}' },
        { 'domain': 'test', 'name': 't3e', 'condition': 'sensor.b3', 'reminder_frequency_mins': [0.01, 0.05], 'reminder_message': 'yay-{{ on_secs }}-{{ on_time_str }}', 'annotate_messages': False },
        { 'domain': 'test', 'name': 't3f', 'condition': 'sensor.b3', 'reminder_frequency_mins': [0.01, 0.05], 'annotate_messages': False },
        { 'domain': 'test', 'name': 't3b', 'condition': 'sensor.b2' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.b1', 'on')
    service_calls.popNotifyEmpty('persistent_notification', r'test_t3a: turned on')
    await setAndWait(hass, 'sensor.b3', 'on')
    service_calls.popNotifySearch('persistent_notification', 't3c', r'test_t3c: turned on')
    service_calls.popNotifySearch('persistent_notification', 't3d', r'test_t3d: turned on')
    service_calls.popNotifySearch('persistent_notification', 'on', r'^turned on') #t3e
    service_calls.popNotifySearch('persistent_notification', 'on', r'^turned on') #t3f
    assert service_calls.isEmpty()
    # reminder interval is 1 + specified interval.  So let's say time is 1.7s
    # we shouldn't see reminders in first say 0.5s
    await asyncio.sleep(0.5)
    assert service_calls.isEmpty()
    # and should see reminder within next 1.2s
    await asyncio.sleep(1.2) 
    service_calls.popNotifySearch('persistent_notification', 't3a', r'test_t3a.*on for [12] s$')
    service_calls.popNotifySearch('persistent_notification', 't3c', r'test_t3c.*on for [12] zsecs$')
    service_calls.popNotifySearch('persistent_notification', 't3d', r'test_t3d.*on for [12] s \[reminder_message template error\]$')
    service_calls.popNotifySearch('persistent_notification', 'yay', r'^yay-[12][.0-9]*-[12] s$') # t3e
    service_calls.popNotifySearch('persistent_notification', 't3f', r'test_t3f.*on for [12] s$')
    service_calls.popNotifySearch('persistent_notification', 'nnn', r'is undefined')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.b3', 'off')
    service_calls.popNotifySearch('persistent_notification', 't3c', r'test_t3c: turned off')
    service_calls.popNotifySearch('persistent_notification', 't3d', r'test_t3d: turned off')
    service_calls.popNotifySearch('persistent_notification', 'off', r'^turned off') #t3e
    service_calls.popNotifyEmpty('persistent_notification', r'^turned off') #t3f
    
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

def mock_service_foo(call):
    return None

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

async def test_notifiers3(hass, service_calls):
    resetModuleLoadTime()
    alert2.kNotifierStartupGraceSecs = 3
    hass.states.async_set("sensor.a", "off")
    # Check if default notifier is bad
    cfg = { 'alert2' : { 'defaults': { 'notifier': 'foo2' }, 'alerts' : [
        { 'domain': 'test', 'name': 't8a', 'condition': 'sensor.a', 'notifier': 'foo' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # notification deferred
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()

    # Wait for end of startup period. Error reported, but since foo2 doesn't exist, it falls
    # back to persistent one
    await asyncio.sleep(alert2.kNotifierStartupGraceSecs + 0.3)
    service_calls.popNotifyEmpty('persistent_notification', r'notifiers are not known.*\'foo\'.*"foo2" is not known')
    
    # And now if new instance:
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifyEmpty('persistent_notification', r't8a.*notifier "foo" is not known.*notifier "foo2" is not known')

async def test_notifiers4(hass, service_calls):
    hass.states.async_set("sensor.a", "off")
    # Check that default notifier is used
    cfg = { 'alert2' : { 'defaults': { 'notifier': 'foo' }, 'alerts' : [
        { 'domain': 'test', 'name': 't9a', 'condition': 'sensor.a' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    hass.services.async_register('notify', 'foo', mock_service_foo)
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('foo', r't9a: turned on')

async def test_notifiers5(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        # notifier can be list.
        # otherwise, jinja2 eval it
        # need to strip()
        # ast.eval_literal
        # if fails, consider a single notifier name (or entity name?)
        #
        # if notifier is single string, it either is name of notifier, or something that evaluates with json.loads
        # First singleton notifiers
        { 'domain': 'test', 'name': 't9a', 'condition': 'sensor.a', 'notifier': 'foo' },
        { 'domain': 'test', 'name': 't9b', 'condition': 'sensor.a', 'notifier': 'sensor.testent' },
        { 'domain': 'test', 'name': 't9b2', 'condition': 'sensor.a', 'notifier': 'sensor.multient' },
        { 'domain': 'test', 'name': 't9c', 'condition': 'sensor.a', 'notifier': '"foo"' },
        { 'domain': 'test', 'name': 't9d', 'condition': 'sensor.a', 'notifier': '\'foo\'' },
        { 'domain': 'test', 'name': 't9e', 'condition': 'sensor.a', 'notifier': '[ "foo" ]' },
        { 'domain': 'test', 'name': 't9f', 'condition': 'sensor.a', 'notifier': '[ \'foo\' ]' },
        
        { 'domain': 'test', 'name': 't9g', 'condition': 'sensor.a', 'notifier': '{{ \'foo\' }}' },
        { 'domain': 'test', 'name': 't9h', 'condition': 'sensor.a', 'notifier': '{{ "foo" }}' },

        { 'domain': 'test', 'name': 't9i', 'condition': 'sensor.a', 'notifier': '{{ ["foo"] }}' },
        { 'domain': 'test', 'name': 't9j', 'condition': 'sensor.a', 'notifier': '{{ [\'foo\'] }}' },

        { 'domain': 'test', 'name': 't9k', 'condition': 'sensor.a', 'notifier': '{{ "a" if false else "foo" }}' },
        { 'domain': 'test', 'name': 't9l', 'condition': 'sensor.a', 'notifier': '{{ "a" if false else "sensor.testent" }}' },

        { 'domain': 'test', 'name': 't9m', 'condition': 'sensor.a', 'notifier': '{% if true %}foo{% endif %}' },
        { 'domain': 'test', 'name': 't9n', 'condition': 'sensor.a', 'notifier': '{% if true %}{{ ["foo"]}}{% endif %}' },

        # And let's test some error cases
        # notifier evals to something other than string
        { 'domain': 'test', 'name': 't9p', 'condition': 'sensor.a', 'notifier': '3' },
        { 'domain': 'test', 'name': 't9q', 'condition': 'sensor.a', 'notifier': '{ "a": 4 }' },
        { 'domain': 'test', 'name': 't9r', 'condition': 'sensor.a', 'notifier': '[ 4 ]' },
        { 'domain': 'test', 'name': 't9s', 'condition': 'sensor.a', 'notifier': '{{ "foo"' },
        { 'domain': 'test', 'name': 't9t', 'condition': 'sensor.a', 'notifier': '{{ ["foo", 5] }}' },
        { 'domain': 'test', 'name': 't9u', 'condition': 'sensor.a', 'notifier': '{% if true %}{% endif %}' },
        { 'domain': 'test', 'name': 't9v', 'condition': 'sensor.a', 'notifier': 'sensor.unavailEnt2' },
        
        { 'domain': 'test', 'name': 't9w', 'condition': 'sensor.w', 'notifier': '{{ ["foo", "bar"] }}' },
        { 'domain': 'test', 'name': 't9x', 'condition': 'sensor.a', 'notifier': 'sensor.unavailEnt' },
        { 'domain': 'test', 'name': 't9x1', 'condition': 'sensor.a', 'notifier': '[ foo ]' },
        { 'domain': 'test', 'name': 't9y', 'condition': 'sensor.a', 'notifier': '[ "foo" ' },

        # we don't support ent in a list
        { 'domain': 'test', 'name': 't9z', 'condition': 'sensor.a', 'notifier': '{{ ["sensor.testent"] }}' },

    ], } }
    resetModuleLoadTime()
    #      # Need more for this slow test to avoid startup ending too early
    alert2.kNotifierStartupGraceSecs = 3
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.w", "off")
    hass.services.async_register('notify', 'foo', mock_service_foo)
    hass.states.async_set("sensor.testent", "foo")
    hass.states.async_set("sensor.multient", '["foo","persistent_notification"]')
    hass.states.async_set("sensor.unavailEnt", 'unavailable')
    hass.states.async_set("sensor.unavailEnt2", None)
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', f'unexpected end of template.*t9s')

    # Turning on alert makes good ones turn on and uncovers errors in the bad ones
    await setAndWait(hass, 'sensor.a', 'on')
    for tname in [ 't9a', 't9b', 't9b2', 't9c', 't9d', 't9e', 't9f', 't9g', 't9h', 't9i', 't9j', 't9k', 't9l', 't9m', 't9n' ]:
        service_calls.popNotifySearch('foo', tname, f'test_{tname}: turned on')
    service_calls.popNotifySearch('persistent_notification', 't9b2', f'test_t9b2: turned on')

    service_calls.popNotifySearch('persistent_notification', 't9p', f'test_t9p.*not a string')
    service_calls.popNotifySearch('persistent_notification', 't9q', f'test_t9q.*not a string')
    service_calls.popNotifySearch('persistent_notification', 't9r', f'test_t9r.*not a string')
    service_calls.popNotifySearch('persistent_notification', 't9t', f'test_t9t.*not a string')
    service_calls.popNotifySearch('foo',                     't9t', f'test_t9t: turned on')
    service_calls.popNotifySearch('persistent_notification', 't9u', f'test_t9u.*empty string')
    service_calls.popNotifySearch('persistent_notification', 't9v', f'test_t9v.*not a string.*NoneType')
    service_calls.popNotifySearch('persistent_notification', 't9x1', f'test_t9x1.*illegal characters')
    service_calls.popNotifySearch('persistent_notification', 't9y', f'test_t9y.*illegal characters')

    #_LOGGER.warning(service_calls.allCalls)
    
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.w', 'on')
    service_calls.popNotifySearch('foo','t9w', f'test_t9w: turned on')
    hass.services.async_register('notify', 'bar', mock_service_foo)
    kStartupWaitPollSecs = alert2.kNotifierStartupGraceSecs / alert2.kStartupWaitPollFactor
    await asyncio.sleep(1.2 * kStartupWaitPollSecs)
    service_calls.popNotifySearch('bar','t9w', f'test_t9w: turned on')
    assert service_calls.isEmpty()

    # Wait rest of startup grace period
    await asyncio.sleep(alert2.kNotifierStartupGraceSecs + 0.3)
    # t9z uses sensor.testent in a list. We don't support detecting that, so sensor.testent is interpreted
    # literally as a notifier name
    service_calls.popNotifyEmpty('persistent_notification', f'Following notifiers are not known.*\'unavailable\'.*\'sensor.testent\'')

async def test_throttle(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
        { 'domain': 'test', 'name': 't10a', 'condition': 'sensor.a', 'throttle_fires_per_mins': [2, 0.05], 'reminder_frequency_mins':0.01 },
        { 'domain': 'test', 'name': 't10b', 'condition': 'sensor.b', 'throttle_fires_per_mins': [2, 0.05], 'reminder_frequency_mins':0.01, 'summary_notifier': True },
    ], } }
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.b", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    for summaryEnabled in [ True, False ]:
        sname = 'sensor.b' if summaryEnabled else 'sensor.a'
        tname = 't10b' if summaryEnabled else 't10a'
        for onAtEnd in [ False, True ]:
            for extraFire in [ False, True ]:
                _LOGGER.info(f'loop: summaryEnabled={summaryEnabled} onAtEnd={onAtEnd} extraFire={extraFire}')
                # 2 fires are fine
                await setAndWait(hass, sname, 'on')
                await setAndWait(hass, sname, 'off')
                await setAndWait(hass, sname, 'on')
                await setAndWait(hass, sname, 'off')
                service_calls.popNotify('persistent_notification', f'test_{tname}: turned on')
                service_calls.popNotify('persistent_notification', f'test_{tname}: turned off')
                service_calls.popNotify('persistent_notification', f'test_{tname}: turned on')
                service_calls.popNotifyEmpty('persistent_notification', f'test_{tname}: turned off')
                
                # 3rd fire should have throttle sign and no turn off or reminders
                await setAndWait(hass, sname, 'on')
                service_calls.popNotifyEmpty('persistent_notification', f'test_{tname}.*turned on.*Throttling started')
                # no reminders
                await asyncio.sleep(2)
                assert service_calls.isEmpty()

                if extraFire:
                    await setAndWait(hass, sname, 'off')
                    await setAndWait(hass, sname, 'on')
                if not onAtEnd:
                    await setAndWait(hass, sname, 'off')
                await asyncio.sleep(0.1)
                assert service_calls.isEmpty()
                
                await asyncio.sleep(2)
                # throttle window done.
                if summaryEnabled:
                    if onAtEnd:
                        if extraFire:
                            service_calls.popNotifyEmpty('persistent_notification', f'Alert2 test_{tname}: on for 2 s .Throttling ending] .fired 1x ')
                        else:
                            service_calls.popNotifyEmpty('persistent_notification', f'Alert2 test_{tname}: on for 4 s .Throttling ending]$')
                    else:
                        service_calls.popNotifyEmpty('persistent_notification', f'Summary.*test_{tname}.*turned off.*after being on .*Throttling ending]')
                else:
                    if onAtEnd:
                        if extraFire:
                            service_calls.popNotifyEmpty('persistent_notification', f'Alert2 test_{tname}: on for 2 s .Throttling ending] .fired 1x ')
                        else:
                            service_calls.popNotifyEmpty('persistent_notification', f'Alert2 test_{tname}: on for 4 s .Throttling ending]$')
                    else:
                        assert service_calls.isEmpty()

                if onAtEnd:
                    await setAndWait(hass, sname, 'off')
                    service_calls.popNotifyEmpty('persistent_notification', f'test_{tname}.*turned off')
                await hass.async_block_till_done()
                assert service_calls.isEmpty()

async def test_annotate(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 },  'alerts' : [
        { 'domain': 'test', 'name': 't11a', 'condition': 'sensor.a' },
        { 'domain': 'test', 'name': 't11b', 'condition': 'sensor.a', 'message': 'ick-t11b' },
        { 'domain': 'test', 'name': 't11c', 'condition': 'sensor.a', 'message': 'ick-t11c', 'done_message': 'ick-t11c done' },
        { 'domain': 'test', 'name': 't11d', 'condition': 'sensor.a', 'message': 'ick-t11d', 'annotate_messages': False, 'reminder_message': 'foo-t11d' },
        { 'domain': 'test', 'name': 't11e', 'condition': 'sensor.a', 'message': 'ick-t11e', 'annotate_messages': False, 'done_message': 'ick-t11e done' },
        { 'domain': 'test', 'name': 't11f', 'condition': 'sensor.a', 'friendly_name': 'friend_t11f' },
        { 'domain': 'test', 'name': 't11g', 'condition': 'sensor.a', 'message': 'ick-t11g', 'annotate_messages': False, 'friendly_name': 'friend_t11g' },
    ], 'tracked': [ { 'domain': 'test', 'name': 't11h' } ] } }
    hass.states.async_set("sensor.a", "off")
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    oldV = (homeassistant.const.MAJOR_VERSION, homeassistant.const.MINOR_VERSION)
    homeassistant.const.MAJOR_VERSION = 2024
    homeassistant.const.MINOR_VERSION = 9

    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifySearch('persistent_notification', 't11a', '{% raw %}Alert2 test_t11a: turned on{% endraw %}', useRegex=False)
    service_calls.popNotifySearch('persistent_notification', 't11b', 'Alert2 test_t11b: ick-t11b')
    service_calls.popNotifySearch('persistent_notification', 't11c', 'Alert2 test_t11c: ick-t11c')
    service_calls.popNotifySearch('persistent_notification', 't11d', 'ick-t11d')
    service_calls.popNotifySearch('persistent_notification', 't11e', 'ick-t11e')
    service_calls.popNotifySearch('persistent_notification', 't11f', 'friend_t11f: turned on')
    service_calls.popNotifySearch('persistent_notification', 't11g', 'ick-t11g')
    assert service_calls.isEmpty()

    # reminders
    await asyncio.sleep(2)
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't11a', 'Alert2 test_t11a: on for')
    service_calls.popNotifySearch('persistent_notification', 't11b', 'Alert2 test_t11b: on for')
    service_calls.popNotifySearch('persistent_notification', 't11c', 'Alert2 test_t11c: on for')
    service_calls.popNotifySearch('persistent_notification', 't11d', 'foo-t11d')
    service_calls.popNotifySearch('persistent_notification', 't11e', 'Alert2 test_t11e: on for')
    service_calls.popNotifySearch('persistent_notification', 't11f', 'friend_t11f: on for')
    service_calls.popNotifySearch('persistent_notification', 't11g', 'friend_t11g: on for')
    assert service_calls.isEmpty()
        
    await setAndWait(hass, 'sensor.a', 'off')
    await asyncio.sleep(1.2)  # Wait for startup delaymgr to expire
    service_calls.popNotifySearch('persistent_notification', 't11a', 'Alert2 test_t11a: turned off after')
    service_calls.popNotifySearch('persistent_notification', 't11b', 'Alert2 test_t11b: turned off after')
    service_calls.popNotifySearch('persistent_notification', 't11c', 'Alert2 test_t11c: ick-t11c done{% endraw')
    service_calls.popNotifySearch('persistent_notification', 't11e', 'ick-t11e done')
    service_calls.popNotifySearch('persistent_notification', 't11f', 'friend_t11f: turned off after')
    # t11d and t11g will have notification messages without any identifying marks
    service_calls.popNotify('persistent_notification', '{% raw %}turned off after 2 s.{% endraw %}')
    service_calls.popNotifyEmpty('persistent_notification', '{% raw %}turned off after 2 s.{% endraw %}')
    assert service_calls.isEmpty()

    # As of 2024.10, HA no longer does template interpretation of message arg to notify
    homeassistant.const.MAJOR_VERSION = 2024
    homeassistant.const.MINOR_VERSION = 9
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t11h', 'message': 'm1'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', '{% raw %}Alert2 test_t11h: m1{% endraw %}')
    homeassistant.const.MAJOR_VERSION = 2023
    homeassistant.const.MINOR_VERSION = 11
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t11h', 'message': 'm2'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', '{% raw %}Alert2 test_t11h: m2{% endraw %}')
    homeassistant.const.MAJOR_VERSION = 2024
    homeassistant.const.MINOR_VERSION = 10
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t11h', 'message': 'm3'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', '^Alert2 test_t11h: m3$')
    homeassistant.const.MAJOR_VERSION = 2025
    homeassistant.const.MINOR_VERSION = 5
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t11h', 'message': 'm4'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', '^Alert2 test_t11h: m4$')

    (homeassistant.const.MAJOR_VERSION, homeassistant.const.MINOR_VERSION) = oldV
    
async def test_delay_on(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't12a', 'condition': 'sensor.a', 'delay_on_secs': 1, 'reminder_frequency_mins': 0.01 },
    ], } }
    hass.states.async_set("sensor.a", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.a', 'on')
    # alert should not have fired
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t12a').state == 'off'
    # it should fire after 0.9 secs more of sleeping + 1 sec bufer time
    await asyncio.sleep(2)
    assert hass.states.get('alert2.test_t12a').state == 'on'
    service_calls.popNotifyEmpty('persistent_notification', 'test_t12a: turned on')
    # reminder counts from when turned on, so should be 0.1s into reminder time of 0.6s
    # so sleeping a bit more shouldn't trigger reminder
    await asyncio.sleep(0.2)
    assert service_calls.isEmpty()
    # Sleeping a bit more should now trigger it
    await asyncio.sleep(0.8)
    service_calls.popNotifyEmpty('persistent_notification', 'test_t12a:.*on for')
    await setAndWait(hass, 'sensor.a', 'off')
    assert hass.states.get('alert2.test_t12a').state == 'off'
    service_calls.popNotifyEmpty('persistent_notification', 'test_t12a: turned off')

async def test_threshold(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't13a', 'condition': '{{ "xxx" }}', 'threshold': { 'value': "{{ 'zzz' }}", 'hysteresis': 3, 'minimum': 0 } },
        { 'domain': 'test', 'name': 't13b', 'condition': '{{ true }}', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'maximum': 10 } },
        { 'domain': 'test', 'name': 't13c', 'condition': '{{ true }}', 'threshold': { 'value': "{{ 'zzz' }}", 'hysteresis': 3, 'minimum': 0, 'maximum': 10 } },
        { 'domain': 'test', 'name': 't13d', 'condition': 'sensor.a', 'threshold': { 'value': "sensor.v", 'hysteresis': 3, 'minimum': 0, 'maximum': 10 } },
        { 'domain': 'test', 'name': 't13e', 'condition': '{{ states("sensor.b")|int > 4 }}', 'threshold': { 'value': "sensor.b", 'hysteresis': 3, 'minimum': 0, 'maximum': 10 } },
        { 'domain': 'test', 'name': 't13f', 'condition': 'sensor.min', 'threshold': { 'value': "sensor.v2", 'hysteresis': 3, 'minimum': 0 } },
        { 'domain': 'test', 'name': 't13g', 'condition': 'sensor.max', 'threshold': { 'value': "sensor.v2", 'hysteresis': 3, 'maximum': 10 } },
    ], } }
    hass.states.async_set("sensor.a", "on")
    hass.states.async_set("sensor.min", "off")
    hass.states.async_set("sensor.max", "off")
    hass.states.async_set("sensor.b", "3")
    hass.states.async_set("sensor.v", "3")
    hass.states.async_set("sensor.v2", "3")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()

    service_calls.popNotifySearch('persistent_notification', 't13a', 't13a.*xxx.*truthy')
    service_calls.popNotifySearch('persistent_notification', 't13b', 't13b.*value template.*"" rather than a float')
    service_calls.popNotifySearch('persistent_notification', 't13c', 't13c.*value template.*"zzz" rather than a float')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13a').state == 'off'
    assert hass.states.get('alert2.test_t13b').state == 'off'
    assert hass.states.get('alert2.test_t13c').state == 'off'
    # cond is True, val is ok
    assert hass.states.get('alert2.test_t13d').state == 'off'
    assert hass.states.get('alert2.test_t13e').state == 'off'

    await setAndWait(hass, 'sensor.a', 'off')
    assert service_calls.isEmpty()
    # Illegal val with false condition
    await setAndWait(hass, 'sensor.v', 'zz2')
    service_calls.popNotifySearch('persistent_notification', 't13d', 't13d.*value template.*"zz2" rather than a float')
    # Now try false, false in various combinations
    #
    await setAndWait(hass, 'sensor.v', '1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'
    #
    await setAndWait(hass, 'sensor.a', 'false') # update sensor.a without change it's value (off==false)
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'
    #
    await setAndWait(hass, 'sensor.b', '2') # updates both cond and value at same time.
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13e').state == 'off'

    # Now try cond true, val false
    #
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'
    await setAndWait(hass, 'sensor.v', '5')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'
    await setAndWait(hass, 'sensor.b', '5') # updates both cond and value at same time.
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13e').state == 'off'

    # Now try false, True in various combinations
    #
    await setAndWait(hass, 'sensor.a', 'off')
    await setAndWait(hass, 'sensor.v', '-1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'
    await setAndWait(hass, 'sensor.b', '-1') # updates both cond and value at same time.
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13e').state == 'off'

    # Now try with both true
    #
    # First cond change turns it on
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')
    # and now value change turns it on
    await setAndWait(hass, 'sensor.v', '5')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '-1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')
    # and now both cond & val update turns it on
    await setAndWait(hass, 'sensor.b', '11')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13e: turned on')
    await setAndWait(hass, 'sensor.b', '5')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13e: turned off')

    # Now check hysteresis
    #
    await setAndWait(hass, 'sensor.v', '5')
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '-1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    # going positive, but still less than 3
    await setAndWait(hass, 'sensor.v', '1')
    assert service_calls.isEmpty()
    # 3 counts from 0, not -1
    await setAndWait(hass, 'sensor.v', '2.5')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'on'
    # now turns off
    await setAndWait(hass, 'sensor.v', '3')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')
    assert hass.states.get('alert2.test_t13d').state == 'off'
    
    # We tested above alert turning off due to condition going false

    # Test max hysteresis
    await setAndWait(hass, 'sensor.v', '9')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '10')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '11')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    await setAndWait(hass, 'sensor.v', '10')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'on'
    await setAndWait(hass, 'sensor.v', '9')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'on'
    await setAndWait(hass, 'sensor.v', '8')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'on'
    await setAndWait(hass, 'sensor.v', '7')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')
    assert hass.states.get('alert2.test_t13d').state == 'off'
    
    # Test min-only hysteresis
    await setAndWait(hass, 'sensor.a', 'off')
    await setAndWait(hass, 'sensor.min', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v2', '11')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v2', '-1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13f: turned on')
    await setAndWait(hass, 'sensor.v2', '2')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v2', '3')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13f: turned off')

    # Test max-only hysteresis
    await setAndWait(hass, 'sensor.min', 'off')
    await setAndWait(hass, 'sensor.max', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v2', '-1')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v2', '11')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13g: turned on')
    await setAndWait(hass, 'sensor.v2', '8')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v2', '7')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13g: turned off')

    # Check if turn off by going into hysteresis region of opposite side
    await setAndWait(hass, 'sensor.max', 'off')
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '-1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    await setAndWait(hass, 'sensor.v', '9')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')
    # and in other direction
    await setAndWait(hass, 'sensor.v', '11')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    await setAndWait(hass, 'sensor.v', '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')
    
    # And test if jump from pole to pole
    await setAndWait(hass, 'sensor.v', '-1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned on')
    await setAndWait(hass, 'sensor.v', '11')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '9')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '-1')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '5')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t13d: turned off')

    # No threshold tracking even when condition is false
    await setAndWait(hass, 'sensor.a', 'off')
    await setAndWait(hass, 'sensor.v', '-1')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '1')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'
    # And from max
    await setAndWait(hass, 'sensor.a', 'off')
    await setAndWait(hass, 'sensor.v', '11')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.v', '9')
    assert service_calls.isEmpty()
    # condition true, we don't track hysteresis coming from above max, so no turn on
    await setAndWait(hass, 'sensor.a', 'on')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t13d').state == 'off'

async def test_threshold2(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't14a',  'threshold': { 'value': "sensor.a", 'hysteresis': 3, 'minimum': 0 } },
        { 'domain': 'test', 'name': 't14b', 'threshold': { 'value': "sensor.b", 'hysteresis': 3, 'maximum': 10 }, 'delay_on_secs': 0.5 },
        { 'domain': 'test', 'name': 't14c', 'threshold': { 'value': "sensor.c", 'hysteresis': 3, 'minimum': 0 }, 'delay_on_secs': 0.5 },
        { 'domain': 'test', 'name': 't14d', 'threshold': { 'value': "sensor.d", 'hysteresis': 3, 'minimum':0, 'maximum': 10 }, 'delay_on_secs': 0.5 },
        { 'domain': 'test', 'name': 't14e', 'threshold': { 'value': "sensor.e", 'hysteresis': 3, 'minimum':0 } },
    ], } }
    hass.states.async_set("sensor.a", "2")
    hass.states.async_set("sensor.b", "2.1")
    hass.states.async_set("sensor.c", "2.2")
    hass.states.async_set("sensor.d", "2.3")
    hass.states.async_set("sensor.e", "-1")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()

    service_calls.popNotifyEmpty('persistent_notification', 'test_t14e: turned on')
    await setAndWait(hass, 'sensor.e', '4')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14e: turned off')

    # Test hysteresis without a condition
    await setAndWait(hass, 'sensor.a', '1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14a').state == 'off'
    await setAndWait(hass, 'sensor.a', '-1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14a: turned on')
    await setAndWait(hass, 'sensor.a', '-1.1')
    assert hass.states.get('alert2.test_t14a').state == 'on'
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', '1')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', '3')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14a: turned off')

    # Test thresh with delay_on, so we get multiple updates while it's firing.
    await setAndWait(hass, 'sensor.b', '11')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.b', '12')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14b').state == 'off'
    await asyncio.sleep(1)
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14b: turned on')
    await setAndWait(hass, 'sensor.b', '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14b: turned off')
    
    # Try again, with multiple ticks on past threshold, but turn off before it fully turns on
    await setAndWait(hass, 'sensor.b', '11')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14b').state == 'off'
    await setAndWait(hass, 'sensor.b', '12')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14b').state == 'off'
    await setAndWait(hass, 'sensor.b', '10')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14b').state == 'off'
    await asyncio.sleep(1)
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14b').state == 'off'

    # Same with minimum
    await setAndWait(hass, 'sensor.c', '-1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14c').state == 'off'
    await setAndWait(hass, 'sensor.c', '-2')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14c').state == 'off'
    await setAndWait(hass, 'sensor.c', '0')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14c').state == 'off'
    await asyncio.sleep(1)
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14c').state == 'off'
    
    # Same with max+min
    await setAndWait(hass, 'sensor.d', '-1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14d').state == 'off'
    await setAndWait(hass, 'sensor.d', '-2')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t14d').state == 'off'
    # Switch poles
    await setAndWait(hass, 'sensor.d', '11')
    # We've waqited a bit of time, wait some more to cross the 0.5s delay_on_secs time
    await asyncio.sleep(0.5)
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14d: turned on')
    assert hass.states.get('alert2.test_t14d').state == 'on'
    await setAndWait(hass, 'sensor.d', '5')
    await asyncio.sleep(1)
    service_calls.popNotifyEmpty('persistent_notification', 'test_t14d: turned off')
    assert hass.states.get('alert2.test_t14d').state == 'off'

async def test_event(hass, service_calls):
    cfg = { 'alert2' : { 'tracked' : [
        { 'domain': 'test', 'name': 't22' },
        { 'domain': 'test', 'name': 't23', 'friendly_name': 'friendlyt23' },
        { 'domain': 'test', 'name': 't24', 'title': 'title24' },
        { 'domain': 'test', 'name': 't25', 'target': 'targett25' },
        { 'domain': 'test', 'name': 't25a', 'target': '{{ "ab" + "cd" }}' },
        { 'domain': 'test', 'name': 't26', 'data': { 'd1': 'data-d1' } },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await hass.services.async_call('alert2','report', {})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'alert2_error.*malformed')

    assert hass.states.get('alert2.test_t22').state == 'has never fired'
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t22'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t22')
    # State should now be a timestamp
    assert re.match('[0-9]{4}-[0-9]{2}-', hass.states.get('alert2.test_t22').state)

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t22', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t22: foo')

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t22', 'data':"yuck"})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'alert2_error.*Malformed.*non-dict')

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t22', 'data': { 'a': 7 }})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t22', extraFields={ 'data': { 'a':7}})

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t23', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'friendlyt23: foo')

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t24', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t24.*foo', extraFields={ 'title': 'title24' })

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t25', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t25.*foo', extraFields={ 'target': 'targett25' })

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t25a', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t25a.*foo', extraFields={ 'target': 'abcd' })

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t26', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t26.*foo', extraFields={ 'data': { 'd1': 'data-d1' }})
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t26', 'data': {'d2': 3}})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t26',
                                 extraFields={ 'data': { 'd1': 'data-d1', 'd2': 3 }})

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t26', 'data': {'d1': 3}})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t26',
                                 extraFields={ 'data': { 'd1': 3 }})

async def test_event2(hass, service_calls):
    # Check throttling
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True }, 'tracked' : [
        { 'domain': 'test', 'name': 't27', 'throttle_fires_per_mins': [2, 0.01] },
        { 'domain': 'test', 'name': 't27a', 'throttle_fires_per_mins': [2, 0.01], 'summary_notifier': False },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    isFirst = True
    for summaryEnabled in [ True, False ]:
        tname = 't27' if summaryEnabled else 't27a'
        for extraFire in [ False, True ]:
            _LOGGER.info(f'loop: summaryEnabled={summaryEnabled} extraFire={extraFire}')
            # First two should notify fine
            for i in range(2):
                await hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                await hass.async_block_till_done()
                service_calls.popNotifyEmpty('persistent_notification', f'Alert2 test_{tname}')

            # Start of throttling
            await hass.services.async_call('alert2','report', {'domain':'test','name':tname})
            await hass.async_block_till_done()
            service_calls.popNotifyEmpty('persistent_notification', f'Alert2 test_{tname} .Throttling started]$')

            if extraFire:
                # Two more fires shouldn't notify
                await hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                await hass.async_block_till_done()
                assert service_calls.isEmpty()
                await hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                await hass.async_block_till_done()
                assert service_calls.isEmpty()

            # Wait for throttle to end
            await asyncio.sleep(2)
            if summaryEnabled:
                if extraFire:
                    service_calls.popNotifyEmpty('persistent_notification', 'Summary: Alert2 test_t27 .Throttling ending] .fired 2x ')
                else:
                    service_calls.popNotifyEmpty('persistent_notification', 'Summary: Alert2 test_t27: Did not fire .*Throttling ending]$')
            else:
                assert service_calls.isEmpty()

async def test_event3(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't28',  'trigger':  [{'platform':'state','entity_id':'sensor.t28'}], 'condition': 'sensor.c28' },
        { 'domain': 'test', 'name': 't28a',  'trigger': [{'platform':'state','entity_id':'sensor.t28a'}], 'message': '{{ 3+4 }}' },
        { 'domain': 'test', 'name': 't28b',  'trigger': 'yes', 'message': '{{ 3+4 }}' },
        { 'domain': 'test', 'name': 't29',  'trigger': [{'platform':'state','entity_id':'sensor.t29'}], 'condition': 'sensor.t29', 'friendly_name': 'friendly-t29'  },
    ], } }
    hass.states.async_set("sensor.c28", "off")
    hass.states.async_set("sensor.t28", "1")
    hass.states.async_set("sensor.t28a", "1")
    hass.states.async_set("sensor.t29", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'expected a dictionary.*t28b')
    #assert service_calls.isEmpty()

    # condition is false, so no alert
    await setAndWait(hass, 'sensor.t28', '2')
    assert service_calls.isEmpty()

    # condition is now true
    await setAndWait(hass, 'sensor.c28', 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.t28', '3')
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t28')

    # Both trigger and condition true at same time
    await setAndWait(hass, 'sensor.t29', 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'friendly-t29')

    # and let's try reporting.  Reporting bypasses any conditions
    await setAndWait(hass, 'sensor.c28', 'off')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t28'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t28')

    # and report a non-existent alert
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t28-no'})
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 'test_t28-no', 'Alert2 test_t28-no')
    service_calls.popNotifySearch('persistent_notification', 'undeclared', 'Alert2 alert2_error: undeclared event.*t28-no')
    assert service_calls.isEmpty()

    # try triggering alert without condition
    await setAndWait(hass, 'sensor.t28a', '2')
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t28a: 7')
    
    # Reporting bypasses any message
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t28a'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t28a$')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t28a', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t28a: foo')

async def test_condition(hass, service_calls):
    # test pssing entity name instead of template for condition or threshold value
    cfg = { 'alert2' : { 'tracked': [
        { 'domain': 'test', 'name': 't30b', 'friendly_name': 'happyt30b' },
        { 'domain': 'test', 'name': 't30b' }, # duplicate
        { 'domain': 'test', 'name': 't30a' }, # duplicate
    ], 'alerts' : [
        { 'domain': 'test', 'name': 't31', 'condition': 'off' },
        { 'domain': 'test', 'name': 't31', 'condition': '{{ false }}' }, # duplicate declaration
        { 'domain': 'test', 'name': 't30a', 'condition':'{{ true }}'  }, # duplicate declaration
        { 'domain': 'test', 'name': 't32', 'condition': 'no', 'trigger': [{'platform':'state','entity_id':'sensor.zz'}] }, 
        { 'domain': 'test', 'name': 't32', 'condition': '{{ true }}', 'trigger': [{'platform':'state','entity_id':'sensor.zz'}] },  # duplicate
        { 'domain': 'test', 'name': 't33', 'condition': 'foo.bar' },
        { 'domain': 'test', 'name': 't34b', 'condition': '{{ ick }}' },
        { 'domain': 'test', 'name': 't34a', 'condition': '{{ 3 }}' },
        { 'domain': 'test', 'name': 't35', 'threshold': 4 },
        { 'domain': 'test', 'name': 't36b', 'threshold': { 'value': 5, 'hysteresis': 6, 'minimum':4 } },
        { 'domain': 'test', 'name': 't36a', 'threshold': { 'value': '3', 'hysteresis': 6, 'minimum':4 } },
        { 'domain': 'test', 'name': 't37b', 'threshold': { 'value': 'foo.bar2', 'hysteresis': 8, 'minimum':9 } },
        { 'domain': 'test', 'name': 't37a', 'threshold': { 'value': 'sensor.ick', 'hysteresis': 8, 'minimum':9 } },
        { 'domain': 'test', 'name': 't38c', 'threshold': { 'value': '{{ ick2 }}', 'hysteresis': 10, 'minimum':11 } },
        { 'domain': 'test', 'name': 't38a', 'condition': 'on' },
        { 'domain': 'test', 'name': 't38b', 'condition': '{{ "on" }}' },
        { 'domain': 'test', 'name': 't38d', 'condition': '{{ states("sensor." + states("sensor.w")) }}' },
    ], } }
    hass.states.async_set("sensor.ick", "3")
    hass.states.async_set("sensor.w", "a")
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.b", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()

    service_calls.popNotifySearch('persistent_notification', 't36a', 't36a.*turned on')
    service_calls.popNotifySearch('persistent_notification', 't37a', 't37a.*turned on')
    service_calls.popNotifySearch('persistent_notification', 't38a', 't38a.*turned on')
    service_calls.popNotifySearch('persistent_notification', 't38b', 't38b.*turned on')
    service_calls.popNotifySearch('persistent_notification', 't30b', 'Duplicate.*t30b')
    service_calls.popNotifySearch('persistent_notification', 't31', 'Duplicate.*t31')
    service_calls.popNotifySearch('persistent_notification', 't30a', 'Duplicate.*t30a')
    service_calls.popNotifySearch('persistent_notification', 't32', 'Duplicate.*t32')
    service_calls.popNotifySearch('persistent_notification', 't35', 'expected dictionary.*t35')
    service_calls.popNotifySearch('persistent_notification', 't33', 't33.*rendered to "unknown", which is not truthy')
    service_calls.popNotifySearch('persistent_notification', 't34b', 't34b.*rendered to "".*not truthy')
    service_calls.popNotifySearch('persistent_notification', 't34a', 't34a.*rendered to "3".*not truthy')
    service_calls.popNotifySearch('persistent_notification', 't37b', 't37b.*value template rendered to "unknown" rather than a float')
    service_calls.popNotifySearch('persistent_notification', 't38c', 't38c.*value template rendered to "".*a float')
    assert service_calls.isEmpty()

    gad = hass.data[DOMAIN]
    assert gad.tracked['test']['t30b']._friendly_name == 'happyt30b'
    assert gad.alerts['test']['t31']._condition_template.template == 'off'
    assert gad.tracked['test']['t32']._condition_template.template == 'no'
    assert gad.alerts['test']['t33']._condition_template.template == '{{ states("foo.bar") }}'
    assert gad.alerts['test']['t34b']._condition_template.template == '{{ ick }}'
    assert '35' not in gad.alerts['test']
    assert gad.alerts['test']['t36b']._threshold_value_template.template ==  '5'
    assert gad.alerts['test']['t36a']._threshold_value_template.template == '3'
    assert gad.alerts['test']['t37b']._threshold_value_template.template == '{{ states("foo.bar2") }}'
    assert gad.alerts['test']['t38c']._threshold_value_template.template ==  '{{ ick2 }}'

    # Test that states() expression can dynamically change which sensor they track in a template
    await setAndWait(hass, 'sensor.b', 'on')
    await setAndWait(hass, 'sensor.b', 'off')
    assert service_calls.isEmpty()
    assert gad.alerts['test']['t38d'].state == 'off'
    # Now track sensor.b
    await setAndWait(hass, 'sensor.w', 'b')
    assert service_calls.isEmpty()
    assert gad.alerts['test']['t38d'].state == 'off'
    await setAndWait(hass, 'sensor.b', 'on')
    assert gad.alerts['test']['t38d'].state == 'on'
    service_calls.popNotifyEmpty('persistent_notification', 't38d.*turned on')
    
    
async def test_err_args(hass, service_calls):
    # alert2_warning is tests in test_ui::test_one_time*
    #
    cfg = { 'alert2' : { 'tracked': [
        { 'domain': 'alert2', 'name': 'error', 'friendly_name': 'happy-terr1' },
        ] } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t39'})
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 'Alert2 test_t39', 'Alert2 test_t39')
    service_calls.popNotifySearch('persistent_notification', 'undeclared', 'happy-terr1: undeclared event.*t39')
    assert service_calls.isEmpty()

    # let's crash a task
    async def gdie():
        raise Exception('boo')
    alert2.create_task(hass, 'alert2', gdie())
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'unhandled_exception.*boo')
    
    gad = hass.data[DOMAIN]
    assert gad.tracked['alert2']['error'].movingSum is None
    assert gad.tracked['alert2']['global_exception'].movingSum is not None

async def test_err_args1a(hass, service_calls):
    hass.services.async_register('notify','foo', mock_service_foo)
    cfg = { 'alert2' : { 'tracked': [
        { 'domain': 'alert2', 'name': 'error', 'throttle_fires_per_mins': [5,6] },
        { 'domain': 'alert2', 'name': 'global_exception', 'throttle_fires_per_mins': [7,8], 'notifier': 'foo' },
        ] } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    assert gad.tracked['alert2']['global_exception'].movingSum.maxCount == 7
    assert gad.tracked['alert2']['error'].movingSum.maxCount == 5

    # let's crash a task
    async def gdie():
        raise Exception('boo')
    alert2.create_task(hass, 'alert2', gdie())
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('foo', 'unhandled_exception.*boo')
    assert service_calls.isEmpty()
    
@pytest.mark.parametrize("cfg, errMsg", [
    ({ 'alert2' : { 'tracked': [ { 'domain': 'alert2', 'nname': 'error', 'friendly_name': 'happy-terr2' }, ] } },
     'extra keys.*nname'),
    ({ 'alert2' : { 'tracked': ['ffstr'] } }, 'expected a dictionary'),
    ({ 'alert2' : { 'tracked': 3 } }, 'expected list'),
    ({ 'alert2' : { 'ttracked': 3 } }, 'extra keys.*ttracked'),
    ({ 'alert2' : 'foo' }, 'expected a dictionary'),
])    
async def test_err_args2(hass, service_calls, cfg, errMsg):
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', errMsg)

async def test_unack(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 }, 'alerts' : [
        { 'domain': 'test', 'name': 't40', 'condition': 'sensor.a' },
        { 'domain': 'test', 'name': 't42', 'condition': 'sensor.a', 'ack_required': True },
        { 'domain': 'test', 'name': 't43', 'condition': 'sensor.a', 'ack_required': True },
        { 'domain': 'test', 'name': 't47', 'condition': 'sensor.a', 'ack_required': True, 'ack_reminders_only': True },
    ],  'tracked' : [
        { 'domain': 'test', 'name': 't41', 'throttle_fires_per_mins': [1, 0.01], 'summary_notifier': True },
        { 'domain': 'test', 'name': 't46', 'throttle_fires_per_mins': [1, 0.01], 'summary_notifier': True, 'ack_required': True },
        { 'domain': 'test', 'name': 't44', 'ack_required': True },
        { 'domain': 'test', 'name': 't45', 'ack_required': True, 'ack_reminder_message': '{{"ack"}}reminder' },
    ] } }
    hass.states.async_set("sensor.a", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    t40 = gad.alerts['test']['t40']
    t41 = gad.tracked['test']['t41']
    
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifySearch('persistent_notification', 't42', 't42.*turned on')
    service_calls.popNotifySearch('persistent_notification', 't43', 't43.*turned on')
    service_calls.popNotifySearch('persistent_notification', 't47', 't47.*turned on')
    service_calls.popNotifyEmpty('persistent_notification', 't40.*turned on')
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    assert t40.extra_state_attributes['is_acked'] == True
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    assert t40.extra_state_attributes['is_acked'] == False
    assert service_calls.isEmpty()

    # reminder should happen after 0.9 secs more of sleeping + 1 sec bufer time
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't42', 't42.*on for')
    service_calls.popNotifySearch('persistent_notification', 't43', 't43.*on for')
    service_calls.popNotifySearch('persistent_notification', 't47', 't47.*on for')
    service_calls.popNotifyEmpty('persistent_notification', 't40.*on for ')
    assert t40.extra_state_attributes['is_acked'] == False

    # Ack and so no notification.
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t40'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t42'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t43'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t47'})
    await hass.async_block_till_done()
    assert t40.extra_state_attributes['is_acked'] == True
    await asyncio.sleep(2)
    assert service_calls.isEmpty()

    # it's been a while since last notify, so unack'ing should result in immediate notify
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t40'})
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t42'})
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t43'})
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t47'})
    await hass.async_block_till_done()
    assert t40.extra_state_attributes['is_acked'] == False
    service_calls.popNotifySearch('persistent_notification', 't42', 't42.*on for')
    service_calls.popNotifySearch('persistent_notification', 't43', 't43.*on for')
    service_calls.popNotifySearch('persistent_notification', 't47', 't47.*on for')
    service_calls.popNotifyEmpty('persistent_notification', 't40.*on for ')

    # and also future reminders
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't42', 't42.*on for')
    service_calls.popNotifySearch('persistent_notification', 't43', 't43.*on for')
    service_calls.popNotifySearch('persistent_notification', 't47', 't47.*on for')
    service_calls.popNotifyEmpty('persistent_notification', 't40.*on for ')
    
    # Now turn off.  ack t40 so no done notification
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t40'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t43'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t47'})
    await hass.async_block_till_done()
    assert t40.extra_state_attributes['is_acked'] == True
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifySearch('persistent_notification', 't47', 't47.*turned off')
    service_calls.popNotifyEmpty('persistent_notification', 't42.*turned off')
    assert service_calls.isEmpty()
    assert t40.extra_state_attributes['is_acked'] == True

    # t42 has not been acked yet
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't42.*not acked yet')
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t42'})
    await hass.async_block_till_done()
    await asyncio.sleep(2)
    assert service_calls.isEmpty()
    # if unack, should get ack reminder again
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t42'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't42.*not acked yet')
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't42.*not acked yet')
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t42'})

    
    # Now try event alert
    #
    # First two should notify fine
    assert t41.extra_state_attributes['is_acked'] == False
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t46'})
    await hass.async_block_till_done()
    assert t41.extra_state_attributes['is_acked'] == False
    service_calls.popNotifySearch('persistent_notification', 't46', '')
    service_calls.popNotifyEmpty('persistent_notification', 't41')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t46'})
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't46', 'Throttling started')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t41 .Throttling started]$')

    # Now should have notification built up
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t46'})
    await hass.async_block_till_done()
    assert t41.extra_state_attributes['is_acked'] == False
    assert service_calls.isEmpty()
    # Ack erases the unotififed firing (fires_since_last_notify).  and unack does not restore it
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t41'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t46'})
    assert t41.extra_state_attributes['is_acked'] == True
    await hass.async_block_till_done()
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t41'})
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t46'})
    assert t41.extra_state_attributes['is_acked'] == False
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't46', 'test_t46: not acked yet.*Throttling ending]$')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t41: Did not fire .*Throttling ending]$')
    assert t41.extra_state_attributes['is_acked'] == False
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t46'})

    # Let try event alert 
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t44'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t45'})
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't45', '')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t44')
    # Reminder should not fire immediately. should wait for 1 + interval, so about 1.7s
    await asyncio.sleep(0.5)
    assert service_calls.isEmpty()
    await asyncio.sleep(1.5)
    service_calls.popNotifySearch('persistent_notification', 't45', 'ackreminder')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t44: not acked yet')
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't45', 'ackreminder')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t44: not acked yet')
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t44'})
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t45'})
    await asyncio.sleep(2)
    assert service_calls.isEmpty()

    
async def test_grace(hass, service_calls):
    # Test some invalid value, no defer, so notify soon
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': None, 'defer_startup_notifications': False } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    #await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'expected float')
async def test_grace2(hass, service_calls):
    # Test some invalid value, with defer, so notify after grace expires
    # ACTUALLY, now we notify immediately.  Because we process top config all at once,
    # so an error in one parameter means we ignore the other parameters.
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': '', 'defer_startup_notifications': True } }
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'expected float')
async def test_grace3(hass, service_calls):
    # Test no grace, notify should be immediate
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': 0, 'defer_startup_notifications': False,
                         'tracked': [ { 'domain': 'test', 'name': 't42', 'notifier': 'persistent_notification' },
                                      { 'domain': 'test', 'name': 't43', 'notifier': 'foo' } ] } }
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t42'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t42')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t43'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't43.*foo.*is not known')

async def test_grace4(hass, service_calls):
    # Test no grace, notify should be immediate, even with defer to True
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': 0, 'defer_startup_notifications': True,
                         'tracked': [ { 'domain': 'test', 'name': 't44', 'notifier': 'persistent_notification' },
                                     ] } }
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t44'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t44')

async def test_grace5(hass, service_calls):
    # Test some grace
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.5, 'defer_startup_notifications': False,
                         'tracked': [ { 'domain': 'test', 'name': 't45', 'notifier': 'persistent_notification' },
                                      { 'domain': 'test', 'name': 't46', 'notifier': 'foo' } ] } }
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t45'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t45')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t46'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    #   unknown notifier waits for grace period
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 'not known to HA.*\'foo\'')

async def test_grace6(hass, service_calls):
    # Test some grace and defer
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.5, 'defer_startup_notifications': True,
                         'tracked': [ { 'domain': 'test', 'name': 't47', 'notifier': 'persistent_notification' },
                                      { 'domain': 'test', 'name': 't48', 'notifier': 'foo' } ] } }
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t47'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t48'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    #   wait for rest of grace period
    await asyncio.sleep(2)
    service_calls.popNotify('persistent_notification', 'Alert2 test_t47')
    service_calls.popNotifyEmpty('persistent_notification', 'not known to HA.*\'foo\'')

async def test_grace7(hass, service_calls):
    # Test defer naming specific list
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.5, 'defer_startup_notifications': ['fooexist','foono'],
                         'tracked': [ { 'domain': 'test', 'name': 't49', 'notifier': 'fooexist' },
                                      { 'domain': 'test', 'name': 't50', 'notifier': 'foono' },
                                      { 'domain': 'test', 'name': 't51', 'notifier': 'persistent_notification' },
                                      { 'domain': 'test', 'name': 't52', 'notifier': 'foono2' } ] } }
    resetModuleLoadTime()
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    hass.services.async_register('notify','fooexist', mock_service_foo)
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t49'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t50'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t51'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t51')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t52'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    #   wait for rest of grace period
    await asyncio.sleep(2)
    service_calls.popNotify('fooexist', 'Alert2 test_t49')
    service_calls.popNotifyEmpty('persistent_notification', 'not known to HA.*\'foono\'.*\'foono2\'')

async def test_snooze(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
        { 'domain': 'test', 'name': 't53c1', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01 },
        { 'domain': 'test', 'name': 't53c2', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01 },
        { 'domain': 'test', 'name': 't53a', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01, 'summary_notifier': False },
        { 'domain': 'test', 'name': 't53b', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01, 'summary_notifier': 'foo' },
        { 'domain': 'test', 'name': 't53d', 'condition': 'sensor.d', 'reminder_frequency_mins': 0.01 },
    ],  'tracked' : [
        { 'domain': 'test', 'name': 't54d' },
        { 'domain': 'test', 'name': 't54a', 'summary_notifier': False },
        { 'domain': 'test', 'name': 't54b', 'summary_notifier': 'foo' },
        { 'domain': 'test', 'name': 't54c', 'summary_notifier': '{{ [ \"foo\" ] }}' },
    ] } }
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.d", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    hass.services.async_register('notify','foo', mock_service_foo)
    gad = hass.data[DOMAIN]

    t53c1 = gad.alerts['test']['t53c1']
    assert t53c1.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t53c1.extra_state_attributes['is_acked'] == False
    t53c2 = gad.alerts['test']['t53c2']
    assert t53c2.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t53c2.extra_state_attributes['is_acked'] == False
    
    # Snoozed so no notification
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c1', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c2', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1),
         'ack_at_snooze_start': False})
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert t53c1.extra_state_attributes['is_acked'] == False
    assert isinstance(t53c1.notification_control, rawdt.datetime)
    await setAndWait(hass, 'sensor.a', 'on')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert t53c1.extra_state_attributes['is_acked'] == False
    
    # snooze expires, get reminder notification summary
    await asyncio.sleep(2)
    assert t53c1.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    service_calls.popNotifySearch('persistent_notification', 't53c1', 't53c1: on for.*fired 1x')
    service_calls.popNotifySearch('persistent_notification', 't53c2', 't53c2: on for.*fired 1x')
    service_calls.popNotifySearch('persistent_notification', 't53a', 't53a.*on for.*fired 1x')
    service_calls.popNotifyEmpty('persistent_notification', 't53b.*on for.*fired 1x')
    # Should still get reminders after snooze expires
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't53c1', 't53c1: on for')
    service_calls.popNotifySearch('persistent_notification', 't53c2', 't53c2: on for')
    service_calls.popNotifySearch('persistent_notification', 't53a', 't53a: on for')
    service_calls.popNotifyEmpty('persistent_notification', 't53b: on for')
    # Set snooze again and turn off. No snooze summary (cuz acked?)
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c1', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c2', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1),
         'ack_at_snooze_start': False })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    # No reminders cuz snooze is implicit ack
    assert t53c1.extra_state_attributes['is_acked'] == True
    assert t53c2.extra_state_attributes['is_acked'] == False
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't53c2: on for')
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'off')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't53c2: turned off')
    assert service_calls.isEmpty()
    assert t53c1.extra_state_attributes['is_acked'] == True
    assert t53c2.extra_state_attributes['is_acked'] == False
    
    # Snoozed so no notification
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c1', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c2', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1),
         'ack_at_snooze_start': False })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert t53c1.extra_state_attributes['is_acked'] == True
    assert t53c2.extra_state_attributes['is_acked'] == False
    await setAndWait(hass, 'sensor.a', 'on')
    await hass.async_block_till_done()
    assert t53c1.extra_state_attributes['is_acked'] == False
    assert t53c2.extra_state_attributes['is_acked'] == False
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # snooze expires, get summary notification
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't53c1', 't53c1: .*fired 1x')
    service_calls.popNotifySearch('persistent_notification', 't53c2', 't53c2: .*fired 1x')
    service_calls.popNotifyEmpty('foo', 't53b: .*fired 1x')

    # Try events
    t54d = gad.tracked['test']['t54d']
    assert t54d.extra_state_attributes['is_acked'] == False
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54d', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54c', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert t54d.extra_state_attributes['is_acked'] == False # since has never fired
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54d'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54a'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54b'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54c'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert t54d.extra_state_attributes['is_acked'] == False
    # snooze expires, get notification summary
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't54d', 't54d.*fired 1x.*ago\\)$')
    service_calls.popNotifySearch('foo', 't54b', 't54b.*fired 1x.*ago\\)$')
    service_calls.popNotifyEmpty('foo', 't54c.*fired 1x.*ago\\)$')

    # Try disabled
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53d', 'enable': False })
    await hass.async_block_till_done()
    await setAndWait(hass, 'sensor.d', 'on')
    assert service_calls.isEmpty()
    # No reminders either
    await asyncio.sleep(2)
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.d', 'off')
    assert service_calls.isEmpty()
    # undo snooze, no summary
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53d', 'enable': True })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.d', 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't53d: turned on')

    # Try disabled event
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54d', 'enable': False })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54d'})
    await hass.async_block_till_done()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54d'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # undo snooze, no summary
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54d', 'enable': True })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

async def test_snooze2(hass, service_calls):
    # Test what happens if snooze ends while alarm is not firing
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
        { 'domain': 'test', 'name': 't54a', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01 },
        { 'domain': 'test', 'name': 't54c', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01 }, # will ack
        { 'domain': 'test', 'name': 't54b', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01, 'summary_notifier': False },
    ] } }
    hass.states.async_set("sensor.a", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    t54a = gad.alerts['test']['t54a']
    t54b = gad.alerts['test']['t54b']
    t54c = gad.alerts['test']['t54c']

    # Alert is on
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifySearch('persistent_notification', 't54a', 't54a: turned on')
    service_calls.popNotifySearch('persistent_notification', 't54b', 't54b: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 't54c: turned on')
    assert t54a.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t54b.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t54c.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    # then we snooze it
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54c', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert isinstance(t54a.notification_control, rawdt.datetime)
    assert isinstance(t54b.notification_control, rawdt.datetime)
    assert isinstance(t54c.notification_control, rawdt.datetime)
    # snooze implicitly acks, but try explicit ack
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t54c'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # then turn alert off
    await setAndWait(hass, 'sensor.a', 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # snooze expires.  Snooze should turn off
    # should not get any notifications since snooze is implicit ack
    await asyncio.sleep(2)
    assert service_calls.isEmpty()
    assert t54a.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t54b.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t54c.notification_control == a2Entities.NOTIFICATIONS_ENABLED

    # Alert is on.
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifySearch('persistent_notification', 't54a', 't54a: turned on')
    service_calls.popNotifySearch('persistent_notification', 't54b', 't54b: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 't54c: turned on')
    assert t54a.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t54b.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert t54c.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    # then we snooze it
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t54c', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert isinstance(t54a.notification_control, rawdt.datetime)
    assert isinstance(t54b.notification_control, rawdt.datetime)
    assert isinstance(t54c.notification_control, rawdt.datetime)
    # unack one of them
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t54c'})
    # Snooze expires
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't54c: on for')
    # and should get reminders
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't54c: on for')

async def test_generator(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't55a', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01, 'reminder_message': 'yay-{{ on_secs }}-{{ on_time_str }}-{{ genElem }}' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': '{{ states("sensor.g") }}', 'condition': 'sensor.a',  },
        { 'domain': 'test', 'name': '{{ genElem }}z', 'generator_name': 'g3', 'generator': '{{ states("sensor.g3") }}', 'condition': 'sensor.a',  },
    ] } }
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.g", "")
    hass.states.async_set("sensor.g3", "")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    assert len(gad.generators) == 3

    # First generation happens
    assert len(gad.alerts['test']) == 1
    assert not 'tracked' in gad.alerts
    t55a = gad.alerts['test']['t55a']
    g1 = gad.generators['g1']
    assert g1.state == 1
    assert g1.entity_id == 'sensor.alert2generator_g1'
    assert g1.extra_state_attributes == { 'generated_ids': [ 'alert2.test_t55a' ] }
    assert hass.states.get(g1.entity_id)
    assert service_calls.isEmpty()

    # interlude, test reminder message for generators with variables
    await setAndWait(hass, "sensor.a", "on")
    service_calls.popNotifyEmpty('persistent_notification', 't55a: turned on')
    await asyncio.sleep(1.7) # reminder interval is 1 + specified interval
    service_calls.popNotifyEmpty('persistent_notification', 't55a: yay-[12][.0-9]*-[12] s-t55a$')
    await setAndWait(hass, "sensor.a", "off")
    service_calls.popNotifyEmpty('persistent_notification', 't55a: turned off')
    
    # And suppose generator is a template and produces an error.  should not change generated alerts.
    #
    # So first generate an alert
    await setAndWait(hass, "sensor.g", "t55b")
    assert len(gad.alerts['test']) == 2
    t55b = gad.alerts['test']['t55b']
    g2 = gad.generators['g2']
    assert g2.state == 1
    assert g2.entity_id == 'sensor.alert2generator_g2'
    assert g2.extra_state_attributes == { 'generated_ids': [ 'alert2.test_t55b' ] }
    assert hass.states.get(g2.entity_id)
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t55b').state == 'off'
    # and now have generator produce a mess
    await setAndWait(hass, "sensor.g", "[ 'a")
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'alert2generator_g2 Name template.*illegal characters')
    assert gad.alerts['test']['t55b'] == t55b
    assert hass.states.get(t55b.entity_id)
    assert g2.state == 1
    assert hass.states.get('alert2.test_t55b').state == 'off'

    # template producing same string should not recreate alert
    await setAndWait(hass, "sensor.g", "['t55b']")
    assert service_calls.isEmpty()
    assert g2.state == 1
    assert gad.alerts['test']['t55b'] == t55b
    assert g2.extra_state_attributes == { 'generated_ids': [ 'alert2.test_t55b' ] }
    
    # Now suppose template returns nothing, so alert should disappear, including from hass states
    await setAndWait(hass, "sensor.g", "")
    assert service_calls.isEmpty()
    assert not hass.states.get(t55b.entity_id)
    assert hass.states.get('alert2.test_t55b') is None
    assert g2.state == 0
    assert not 't55b' in gad.alerts['test']
    assert g2.extra_state_attributes == { 'generated_ids': [ ] }
    # And if alert reappears, should be fine, no entity registry issues
    await setAndWait(hass, "sensor.g", "['t55b']")
    assert service_calls.isEmpty()
    assert g2.state == 1
    assert hass.states.get('alert2.test_t55b').state == 'off'
    
    # what if name includes a trailing z in template
    assert not 't56' in gad.alerts['test']
    assert not 't56z' in gad.alerts['test']
    await setAndWait(hass, "sensor.g3", "t56")
    assert service_calls.isEmpty()
    assert not 't56' in gad.alerts['test']
    # let first generation happen
    t56z = gad.alerts['test']['t56z']
    g3 = gad.generators['g3']
    assert g3.state == 1
    assert g3.extra_state_attributes == { 'generated_ids': [ 'alert2.test_t56z' ] }
    # Now suppose a second alert appears
    await setAndWait(hass, "sensor.g3", "['t56','t57']")
    assert service_calls.isEmpty()
    assert g3.state == 2
    assert g3.extra_state_attributes == { 'generated_ids': [ 'alert2.test_t56z', 'alert2.test_t57z' ] }
    t57z = gad.alerts['test']['t57z']
    assert hass.states.get(t57z.entity_id)
    # And one disappears
    await setAndWait(hass, "sensor.g3", "['t57']")
    assert service_calls.isEmpty()
    assert g3.state == 1
    assert g3.extra_state_attributes == { 'generated_ids': [ 'alert2.test_t57z' ] }
    assert not 't56z' in gad.alerts['test']
    assert 't57z' in gad.alerts['test']
    assert not hass.states.get(t56z.entity_id)
    assert hass.states.get(t57z.entity_id)
    # Now suppose template returns nothing, so alert should disappear
    await setAndWait(hass, "sensor.g3", "[]")
    assert service_calls.isEmpty()
    assert g3.state == 0
    assert g3.extra_state_attributes == { 'generated_ids': [ ] }
    assert not 't56z' in gad.alerts['test']
    assert not 't57z' in gad.alerts['test']
    assert not hass.states.get(t56z.entity_id)
    assert not hass.states.get(t57z.entity_id)

async def test_generator2(hass, service_calls):
    # Try templating of genElem variable
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't57',
          'condition': 'sensor.a',
          # If genElem doesn't resolve to 't57', then we'll pick the wrong notifier
          'notifier': '{% if genElem == "t57" %}persistent_notification{% else %}foo{% endif %}',
          'title': '{{ genElem }}tt', 'target': '{{ genElem }}tar',
          'message': '{{ genElem }}msg{{ genEntityId}}z', # genEntityId should be empty
          'done_message': '{{ genElem }}dmsg',
          'reminder_frequency_mins': [0.01, 0.05],
          'reminder_message': '{{ genElem }}rmsg',
         },
        # duplicate g1
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't57zz',
          'condition': '{{ zzz }}',
         },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': 't58',
          'condition': '{{ true }}',
          'threshold': {
              'value': '{% if genElem == "zzz" %}10{% else %}5{% endif %}',
              'hysteresis': 2,
              'maximum': 9
          },
         },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g3', 'generator': 't59a',
          'condition': '{{ genElem == "t59a" }}',
         },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g4', 'generator': 't59b',
          'condition': '{{ genElem == states("sensor.v2") }}',
         },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g5', 'generator': 't59c',
          'condition': '{{ true }}',
          'threshold': {
              'value': '{% if genElem == states("sensor.v") %}10{% else %}5{% endif %}',
              'hysteresis': 2,
              'maximum': 9
          },
         },
        { 'domain': 'test', 'name': '{{ genElem[0] }}', 'generator_name': 'g6', 'generator': '[ ["t59d",4] ]',
          'delay_on_secs': '{{ genElem[1] }}', 'condition': 'off',
         },
        { 'domain': 'test', 'name': '{{ genElem[0] }}', 'generator_name': 'g7', 'generator': '{{ [ ["t59e",5] ] }}',
          'delay_on_secs': '{{ genElem[1] }}', 'condition': 'off',
         },
        { 'domain': 'test', 'name': '{{ elem }}', 'generator_name': 'g8', 'generator': '{{ [ {"elem":"t59f","num":6} ] }}',
          'delay_on_secs': '{{ num }}', 'condition': 'off',
         },
        { 'domain': 'test', 'name': '{{ elem }}', 'generator_name': 'g9', 'generator': '[ {"elem":"t59g","num":7} ]',
          'delay_on_secs': '{{ num }}', 'condition': 'off',
         },
        { 'domain': 'test', 'name': '{{ elem }}', 'generator_name': 'g10', 'generator': [ {"elem":"t59h","num":8} ],
          'delay_on_secs': '{{ num }}', 'condition': 'off',
         },
    ] } }
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.v", "1")
    hass.states.async_set("sensor.v2", "1")
    hass.services.async_register('notify','foo', mock_service_foo)
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    gad = hass.data[DOMAIN]
    service_calls.popNotifySearch('persistent_notification', 't59a', 'Alert2 test_t59a: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 'Duplicate generator name=g1')

    # first generations happenned
    assert len(gad.alerts['test']) == 10
    assert not 'tracked' in gad.alerts
    t57 = gad.alerts['test']['t57']
    t58 = gad.alerts['test']['t58']
    t59a = gad.alerts['test']['t59a']
    t59b = gad.alerts['test']['t59b']
    t59c = gad.alerts['test']['t59c']
    t59d = gad.alerts['test']['t59d']
    assert t59d.delay_on_secs == 4
    t59e = gad.alerts['test']['t59e']
    assert t59e.delay_on_secs == 5
    t59f = gad.alerts['test']['t59f']
    assert t59f.delay_on_secs == 6
    t59g = gad.alerts['test']['t59g']
    assert t59g.delay_on_secs == 7
    t59h = gad.alerts['test']['t59h']
    assert t59h.delay_on_secs == 8
    assert len(gad.generators) == 10
    g1 = gad.generators['g1']
    g2 = gad.generators['g2']
    g3 = gad.generators['g3']
    g4 = gad.generators['g4']
    g5 = gad.generators['g5']
    assert g1.state == 1
    assert g2.state == 1
    assert g3.state == 1
    assert g4.state == 1
    assert g5.state == 1
    assert service_calls.isEmpty()

    await setAndWait(hass, "sensor.a", "on")
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t57: t57msgz',
                                 extraFields={ 'title': 't57tt', 'target': 't57tar' })
    # Check reminder_message
    await asyncio.sleep(1.7) # reminder interval is 1 + specified interval
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t57: t57rmsg',
                                 extraFields={ 'title': 't57tt', 'target': 't57tar' })

    # Check done_message
    await setAndWait(hass, "sensor.a", "off")
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t57: t57dmsg',
                                 extraFields={ 'title': 't57tt', 'target': 't57tar' })
    # So we've tested genElem in name, title, target, message, done_message, notifier.

    await setAndWait(hass, "sensor.v", "t59c")
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t59c: turned on')
    await setAndWait(hass, "sensor.v", "t59cz")
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t59c: turned off')

    await setAndWait(hass, "sensor.v2", "t59b")
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t59b: turned on')
    await setAndWait(hass, "sensor.v2", "t59bb")
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t59b: turned off')
    # And now checked genElem in condition and value.

async def test_generator3(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't61',
          'condition': '{{ False }}' },
        { 'domain': 'test', 'name': '{{ genRaw }}', 'generator_name': 'g1a', 'generator': 't61a',
          'condition': '{{ False }}' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': [ "t62", "t63" ],
          'condition': 'sensor.b' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g3', 'generator': '{{ states("sensor.a") }}',
          'condition': '{{ False }}' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g4', 'generator': '{{ [ "t66", "t67" ] }}',
          'condition': '{{ False }}' },
        { 'domain': 'test', 'name': 'happy_{{ genElem }}', 'generator_name': 'g5', 'generator': '{{ [ 10, 11 ] }}',
          'condition': 'off' },
        { 'domain': 'test', 'name': 'happy2_{{ genElem }}', 'generator_name': 'g6', 'generator': [ 7, 9 ],
          'condition': 'off' },
    ] } }
    hass.states.async_set("sensor.a", '[ "t64", "t65" ]')
    hass.states.async_set("sensor.b", 'off')
    hass.services.async_register('notify','foo', mock_service_foo)
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]

    assert len(gad.alerts['test']) == 12
    assert not 'tracked' in gad.alerts
    for id in [ 't61', 't61a', 't62', 't63', 't64', 't65', 't66', 't67',
                'happy_10', 'happy_11', 'happy2_7', 'happy2_9' ]:
        assert gad.alerts['test'][id]
    assert len(gad.generators) ==  7
    for id in [ 'g1', 'g1a', 'g2', 'g3', 'g4' ]:
        assert gad.generators[id]

    # Pick one and try adding another alert
    g3 = gad.generators['g3']
    await setAndWait(hass, "sensor.a", '[ "t64", "t65", "t65a" ]')
    assert len(gad.alerts['test']) == 13
    assert gad.alerts['test']['t65a']
    assert service_calls.isEmpty()

    await setAndWait(hass, "sensor.b", 'on')
    service_calls.popNotifySearch('persistent_notification', 't62', 'Alert2 test_t62: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t63: turned on')


async def test_generator3a(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': '{{ states("sensor.a") }}',
          'condition': '{{ False }}' },
        { 'domain': 'test', 'name': 't64aa', 'condition': '{{ False }}' },
        { 'domain': GENERATOR_DOMAIN, 'name': 't64ab', 'condition': '{{ False }}' },
        { 'domain': '{{ genElem }}', 'name': 't64ac', 'generator_name': 'g2', 'generator': '{{ states("sensor.b") }}',
          'condition': '{{ False }}' },
    ] } }
    hass.states.async_set("sensor.a", '')
    hass.states.async_set("sensor.b", '')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'required key not provided.*generator.*t64ab')

    # Generator can't create a duplicate alert
    await setAndWait(hass, "sensor.a", 't64ad')
    gad = hass.data[DOMAIN]
    assert list(gad.alerts['test'].keys()) == [ 't64aa', 't64ad' ]
    await setAndWait(hass, "sensor.a", 't64aa')
    service_calls.popNotifyEmpty('persistent_notification', 'Duplicate declaration.*t64aa')
    assert list(gad.alerts['test'].keys()) == [ 't64aa', 't64ad' ]

    # can't create alert in generator domain
    await setAndWait(hass, "sensor.b", 'test')
    assert list(gad.alerts['test'].keys()) == [ 't64aa', 't64ad', 't64ac' ]
    await setAndWait(hass, "sensor.b", GENERATOR_DOMAIN)
    service_calls.popNotifyEmpty('persistent_notification', 'required key not provided.*generator.*t64ac')
    
    
async def test_generator4(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g5', 'generator': '{{ foo ',
          'condition': 'off' } ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'invalid template.*g5')

async def test_generator4a(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem ', 'generator_name': 'g6', 'generator': 'foo',
          'condition': 'off' },
        { 'domain': 'test', 'name': '{{ zz() }}', 'generator_name': 'g7', 'generator': 'foo',
          'condition': 'off' },
        { 'domain': '{{ genElem', 'name': 'yay', 'generator_name': 'g8', 'generator': 'foo',
          'condition': 'off' },
        { 'domain': '{{ zz() }}', 'name': 'yay', 'generator_name': 'g9', 'generator': 'foo',
          'condition': 'off' },
        { 'domain': '{{ genElem }}dd', 'name': '{{genElem}}nn', 'generator_name': 'g10', 'generator': 'foo',
          'condition': 'off' } ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    
    service_calls.popNotifySearch('persistent_notification', 'g6', 'invalid template.*\'name\'.*g6')
    service_calls.popNotifySearch('persistent_notification', 'g7', 'g7 Name template returned err.*zz.*undefined')
    service_calls.popNotifySearch('persistent_notification', 'g8', 'invalid template.*\'domain\'.*g8')
    service_calls.popNotifyEmpty('persistent_notification', 'g9 Domain template returned err.*zz.*undefined')
    gad = hass.data[DOMAIN]
    assert len(gad.generators) == 3
    #assert gad.generators['g6'].state == 0
    assert gad.generators['g7'].state == 0
    #assert gad.generators['g8'].state == 0
    assert gad.generators['g9'].state == 0
    assert gad.generators['g10'].state == 1
    assert gad.alerts['foodd']['foonn'].state == 'off'

async def test_generator5(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genGroups[0] }}', 'generator_name': 'g11',
          'generator': "{{ states|entity_regex('sensor.(.*)_bar')|list }}",
          'condition': 'off' },
        { 'domain': 'test', 'name': '{{ genGroups[0] }}a', 'generator_name': 'g12',
          'generator': "{{ states|entity_regex('sensor.(.*)_bar')|list }}",
          'message': 'aa={{genGroups[0]}} and bb={{genEntityId}} and cc={{genRaw}}',
          'condition': '{{ states("sensor.z_"+genGroups[0]) }}' },  # e.g. sensor.z_foo1
        # No group
        { 'domain': 'test', 'name': '{{ genGroups[0] }}b', 'generator_name': 'g13',
          # the "1" in the regex is so we only gen one element to avoid duplicate alert name error
          'generator': "{{ states|entity_regex('sensor..*1_bar')|list }}",
          'condition': 'off' },
        { 'domain': 'test', 'name': '{{ genGroups[0] }}c', 'generator_name': 'g14',
          'generator': "{{ states|entity_regex('sensor.(.*)_bar')|list }}",
          'condition': '{{ states(genEntityId) }}' },
        # Check genEntityId auto-populates
        { 'domain': 'test', 'name': '{{ genEntityId|replace("sensor.foo1_bar","foo1") }}d', 'generator_name': 'g15',
          'generator': "{{ states|selectattr('entity_id','equalto','sensor.foo1_bar')|map(attribute='entity_id')|list }}",
          'message': 'ee={{genRaw}} rr={{genEntityId}}',
          'condition': '{{ states(genEntityId) }}' }
    ]}}
    hass.states.async_set("sensor.ickbar", 'foo')
    hass.states.async_set("sensor.foo1_bar", 'on')
    hass.states.async_set("sensor.foo2_bar", 'off')
    hass.states.async_set("sensor.z_foo1", 'off')
    hass.states.async_set("sensor.z_foo2", 'off')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()

    service_calls.popNotifySearch('persistent_notification', 'test_foo1c', 'test_foo1c: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 'test.foo1d: ee=sensor.foo1_bar rr=sensor.foo1_bar') # turned on
    gad = hass.data[DOMAIN]
    assert len(gad.generators) == 5
    g11 = gad.generators['g11']
    assert g11.state == 2
    assert gad.alerts['test']['foo1'].state == 'off'
    assert gad.alerts['test']['foo2'].state == 'off'
    g12 = gad.generators['g12']
    assert g12.state == 2
    assert gad.alerts['test']['foo1a'].state == 'off'
    assert gad.alerts['test']['foo2a'].state == 'off'
    tfoo1a = gad.alerts['test']['foo1a']
    
    g13 = gad.generators['g13']
    assert g13.state == 1
    assert gad.alerts['test']['b'].state == 'off'
    g14 = gad.generators['g14']
    assert g14.state == 2
    assert gad.alerts['test']['foo1c'].state ==  'on'
    assert gad.alerts['test']['foo2c'].state == 'off'

    await setAndWait(hass, "sensor.z_foo1", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'aa=foo1.*bb=sensor.foo1_bar.*cc={\'genEntityId')

    g15 = gad.generators['g15']
    assert g15.state == 1
    assert gad.alerts['test']['foo1d'].state == 'on'

    _LOGGER.warning('\n\n')
    # Let's add a new sensor and see what happens
    hass.states.async_set("sensor.foo3_bar", 'off')
    await hass.async_block_till_done()
    # g11 adds a new alert
    assert gad.alerts['test']['foo3'].state == 'off'
    # g12 adds a new alert with bad condition
    assert gad.alerts['test']['foo3a'].state == 'off'  # no truthy val in condition
    service_calls.popNotifySearch('persistent_notification', 'test_foo3a', 'unknown.*not truthy')
    # g13 has no groups so tried to readd sensor.test_b again
    assert g13.state == 1
    # g14 adds new alert with condition sensor.foo3_bar, which is off
    assert gad.alerts['test']['foo3c'].state == 'off'
    # g15 does not add a new alert
    assert g15.state == 1

async def test_generator6(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g15',
          'generator': [ 'foo1' ],
          'friendly_name': '{{ genElem }}zz', 'condition': 'sensor.a' },
        # Test if one alert has a render error in domain/name, we don't delete the rest
        { 'domain': 'test',
          'name': '{% if states("sensor.ick") == "on" and genElem == "foo2" %}{{blowup()}}{% else %}{{ genElem }}{% endif %}',
          'generator_name': 'g16', 'generator': '{{ states("sensor.g") }}',
          'condition': 'off' },
        # Test that generator throw error if generates duplicate domain/name pairs
        { 'domain': 'test', 'name': 'dupname', 'condition': 'off',
          'generator': [ 'a1', 'a2' ], 'generator_name': 'g16a' }
        ]}}
    hass.states.async_set("sensor.a", 'off')
    hass.states.async_set("sensor.g", '[ "foo2", "foo3" ]')
    hass.states.async_set("sensor.ick", 'off')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'duplicate entity id test_dupname')
    #assert service_calls.isEmpty()
    
    gad = hass.data[DOMAIN]
    assert len(gad.generators) == 3
    g15 = gad.generators['g15']
    assert g15.state == 1
    foo1 = gad.alerts['test']['foo1']
    assert foo1.state == 'off'

    await setAndWait(hass, "sensor.a", 'on')
    service_calls.popNotifyEmpty('persistent_notification', '^foo1zz: turned on')

    g16 = gad.generators['g16']
    assert g16.state == 2
    foo2 = gad.alerts['test']['foo2']
    foo3 = gad.alerts['test']['foo3']
    assert 'foo3' in gad.alerts['test']

    await setAndWait(hass, "sensor.ick", 'on')
    assert service_calls.isEmpty()

    #_LOGGER.warning('\n\n')
    await setAndWait(hass, "sensor.g", '[ "foo2", "foo3", "foo4" ]')
    service_calls.popNotifyEmpty('persistent_notification', 'blowup\' is undefined')
    # Here's the crux of the test.  generator had a render error while processing "foo2"
    # so neither foo2 nor foo3 should be deleted.
    assert 'foo2' in gad.alerts['test']
    assert 'foo3' in gad.alerts['test']

async def test_generator7(hass, service_calls):
    # Test that generators don't start generating until HA has fully started
    cfg = { 'alert2' : { 'alerts' : [
        # test config err where generator missing condition
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g16',
          'generator': [ 'foo1' ] },
        # test generator doesn't gen till HA started
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g17',
          'generator': [ 'foo1' ], 'condition': 'off' },
        # test conditions don't start firing till HA started if early_start is False
        { 'domain': 'test', 'name': 't68', 'condition': True, 'early_start': False },
        { 'domain': 'test', 'name': 't69', 'condition': True, 'early_start': True },
        ], 'tracked': [
            # Our test harness isn't fancy enough to be able to test early_start
            # for event alerts
        ]}}
    hass.states.async_set("sensor.a", 'off')
    hass.states.async_set("sensor.g", '[ "foo2", "foo3" ]')
    hass.states.async_set("sensor.ick", 'off')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()

    service_calls.popNotifySearch('persistent_notification', 't69', 't69.* turned on')
    service_calls.popNotifyEmpty('persistent_notification', 'Must specify either.*g16')

    gad = hass.data[DOMAIN]
    assert len(gad.generators) == 1
    g17 = gad.generators['g17']
    assert g17.state == 0
    assert 'foo1' not in gad.alerts['test']
    assert gad.alerts['test']['t68'].state == 'off'
    assert gad.alerts['test']['t69'].state == 'on'

    await hass.async_start()
    await hass.async_block_till_done()
    assert g17.state == 1
    foo1 = gad.alerts['test']['foo1']
    assert foo1.state == 'off'
    assert gad.alerts['test']['t68'].state == 'on'
    assert gad.alerts['test']['t69'].state == 'on'
    service_calls.popNotifyEmpty('persistent_notification', 't68.* turned on')


async def test_generator8(hass, service_calls):
    # Test genIdx and genPrevDomainName
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': '{{ genElem }}', 'friendly_name': 'idx={{genIdx}}',
          'supersedes': "{{ genPrevDomainName }}", 'generator_name': 'g1',
          'generator': 't1','condition': '{{ False }}' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'friendly_name': 'idx={{genIdx}}',
          'supersedes': "{{ genPrevDomainName }}", 'generator_name': 'g2', 'generator': '{{ [ "t2", "t3" ] }}',
          'condition': '{{ False }}' },
        # For now we don't support [None] as a supersedes argument
        #{ 'domain': 'test', 'name': '{{ genElem }}', 'friendly_name': 'idx={{genIdx}}',
        #  'supersedes': "{{ [genPrevDomainName] }}", 'generator_name': 'g3', 'generator': '{{ [ "t4", "t5" ] }}',
        #  'condition': '{{ False }}' },
    ] } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]

    assert len(gad.alerts['test']) == 3
    assert not 'tracked' in gad.alerts
    assert hass.states.get('alert2.test_t1').attributes['friendly_name'] == 'idx=0'
    assert hass.states.get('alert2.test_t2').attributes['friendly_name'] == 'idx=0'
    assert hass.states.get('alert2.test_t3').attributes['friendly_name'] == 'idx=1'

    assert gad.supersedeMgr.supersedesMap == {
        ('test','t1'): set(),
        ('test','t2'): set(),
        ('test','t3'): set( [ ('test','t2') ] ),
        #('test','t4'): set(),
        #('test','t5'): set( [ ('test','t4') ] ),
    }

    
    
async def test_late_state(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        # Check that template condition still becomes states("sensor.ick") even if sensor.ick doesn't yet exist
        # when the alert is created.
        { 'domain': 'test', 'name': 't70', 'condition': 'sensor.ick' },
        ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't70.*condition template rendered to "unknown", which is not truthy')
    gad = hass.data[DOMAIN]
    t70 = gad.alerts['test']['t70']
    assert re.search('states."sensor.ick"', t70._condition_template.template)
    
async def test_friendlyname(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't71', 'friendly_name': '{{ states("sensor.ick") }}', 'condition': 'off' },
        ]}}
    hass.states.async_set("sensor.ick", 't71yy')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]

    t71 = gad.alerts['test']['t71']
    assert hass.states.get('alert2.test_t71').attributes['friendly_name'] == 't71yy'
    await setAndWait(hass, "sensor.ick", 'foo71')
    assert hass.states.get('alert2.test_t71').attributes['friendly_name'] == 'foo71'
    
async def test_reload(hass, service_calls, monkeypatch):
    cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.0,
                         'defaults': { 'summary_notifier': True, 'reminder_frequency_mins': 0.01}, 'alerts' : [
        { 'domain': 'test', 'name': 't72', 'condition': 'off' },
        { 'domain': 'test', 'name': 't73', 'condition': 'off' },
        { 'domain': 'test', 'name': 't74', 'condition': 'off' }, # will snooze
        { 'domain': 'test', 'name': 't75', 'condition': 'on' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g18', 'generator': [ 't76' ], 'condition':'off' },
        ], 'tracked': [
            { 'domain': 'test', 'name': 't77' },
            { 'domain': 'test', 'name': 't78' },
        ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't75: turned on')
    gad = hass.data[DOMAIN]

    now = rawdt.datetime.now(rawdt.timezone.utc)
    t74 = gad.alerts['test']['t74']
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t74', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=30) })
    await hass.async_block_till_done()
    entids = hass.states.async_entity_ids()
    _LOGGER.warning(entids)
    assert len(entids) == 12 # 1 is alert2_error, alert2_warning, alert2_global_exception 1 is binary_sensor.alert2_ha_startup_done
    assert t74.future_notification_info is not None
    
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True, 'reminder_frequency_mins': 0.01}, 'alerts' : [
        { 'domain': 'test', 'name': 't72', 'condition': 'off' },
        { 'domain': 'test', 'name': 't80', 'condition': 'off' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g18', 'generator': [ 't81' ], 'condition':'off' },
        ], 'tracked': [
            { 'domain': 'test', 'name': 't77' },
            { 'domain': 'test', 'name': 't82' },
        ]}}
    #gad.component.newCfg = cfg
    async def fake_cfg(thass):
        return cfg
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    await asyncio.sleep(alert2.gGcDelaySecs + 0.1)
    
    entids = hass.states.async_entity_ids()
    assert len(entids) == 10 # 1 is alert2_error, alert2_warning, alert2_global_exception, 1 is binary_sensor.alert2_ha_startup_done
    for anid in entids:
        if anid in ['alert2.alert2_error', 'alert2.alert2_warning', 'alert2.alert2_global_exception', 'binary_sensor.alert2_ha_startup_done', 'alert2.test_t77',
                  'alert2.test_t82', 'alert2.test_t72',
                  'alert2.test_t80', 'sensor.alert2generator_g18', 'alert2.test_t81']:
            assert hass.states.get(anid).state != 'unavailable'
        else:
            assert False
            #assert hass.states.get(anid).state == 'unavailable'
    # The snooze task should have been canceled
    assert t74.future_notification_info is None
    
    cfg = { 'alert2' : {}}
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    await asyncio.sleep(alert2.gGcDelaySecs + 0.1)
    entids = hass.states.async_entity_ids()
    assert len(entids) == 4 # 1 is alert2_error alert2_warning, alert2_global_exception
    for anid in entids:
        if anid in ['alert2.alert2_error', 'alert2.alert2_warning', 'alert2.alert2_global_exception', 'binary_sensor.alert2_ha_startup_done']:
            assert hass.states.get(anid).state != 'unavailable'
        else:
            assert False
            #assert hass.states.get(anid).state == 'unavailable'

    # Reload and ent reappears
    cfg = { 'alert2' : { 'alerts': [
        { 'domain': 'test', 'name': 't72', 'condition': 'off' },
        ]}}
    assert hass.states.get('alert2.test_t72') == None
    #assert hass.states.get('alert2.test_t72').state == 'unavailable'
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    await asyncio.sleep(alert2.gGcDelaySecs + 0.1)
    assert hass.states.get('alert2.test_t72').state == 'off'

            
async def test_shutdown(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True, 'reminder_frequency_mins': 0.01}, 'alerts' : [
        { 'domain': 'test', 'name': 't83', 'condition': 'off' },
        { 'domain': 'test', 'name': 't84', 'condition': 'on' },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g19', 'generator': [ 't85' ], 'condition':'off' },
        ], 'tracked': [
            { 'domain': 'test', 'name': 't86' },
        ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't84: turned on')
    gad = hass.data[DOMAIN]
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t83', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=30) })
    await hass.async_block_till_done()
    t83 = gad.alerts['test']['t83']
    t84 = gad.alerts['test']['t84']
    entids = hass.states.async_entity_ids()
    assert len(entids) == 9 # 1 is alert2_error, alert2_warning, 1 for binary_sensor.alert2_ha_startup_done
    for id in ['alert2.alert2_error', 'alert2.alert2_warning', 'alert2.alert2_global_exception', 'binary_sensor.alert2_ha_startup_done',
               'alert2.test_t83', 'alert2.test_t84', 'alert2.test_t85',
               'alert2.test_t86', 'sensor.alert2generator_g19']:
        assert id in entids

    # Shutdown should stop all tasks, reminders and whatnot
    assert t83.future_notification_info is not None
    assert t84.future_notification_info is not None
    await hass.async_stop()
    await hass.async_block_till_done()
    assert t83.future_notification_info is None
    assert t84.future_notification_info is None

async def test_declare_event(hass, service_calls, monkeypatch):
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True} } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await alert2.declareEventMulti([
        { 'domain': 'test', 'name': 't87' },
        { 'domain': 'test', 'name': 't88' },
    ])
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t87'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t87')
    alert2.report('test', 't88', 'foo')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t88: foo')
    
    alert2.report('test', 't88', 'foo', data={'d': 8})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t88: foo', extraFields={'data': {'d': 8}})

    # Try a reload, should preserve the declareEventMulti
    gad = hass.data[DOMAIN]
    assert gad.tracked['test']['t88']
    async def fake_cfg(thass):
        return cfg
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    await asyncio.sleep(alert2.gGcDelaySecs + 0.1)
    assert gad.tracked['test']['t88']
    alert2.report('test', 't88', 'foo')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t88: foo')

async def test_bad2(hass, service_calls):
    # Try to get template validation code to crash
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 't01', 'name': 3, 'condition': 'off' },  # 3 becomes '3'
        { 'domain': 't02', 'name': True, 'condition': 'off' }, # True becomes something
        { 'domain': 't02a', 'name': '', 'condition': 'off' },
        { 'domain': 't02b', 'name': None, 'condition': 'off' },
        { 'domain': 't03', 'name': ['x'], 'condition': 'off' },
        { 'domain': 't04', 'name': { 'y': 3 }, 'condition': 'off' },
        { 'domain': 't05', 'name': 'x', 'condition': ['x'] },
        { 'domain': 't05a', 'name': 'x', 'condition': '' },
        { 'domain': 't05b', 'name': 'x', 'condition': None },
        { 'domain': 't06', 'name': 'x', 'condition': { 'y': 4} },
        { 'domain': 't07', 'name': 'x', 'condition': 'off', 'annotate_messages': 3 },
        { 'domain': 't08', 'name': 'x', 'condition': 'off', 'annotate_messages': None },
        { 'domain': 't09', 'name': 'x', 'condition': 'off', 'annotate_messages': '' },
        { 'domain': 't10', 'name': 'x', 'condition': 'off', 'annotate_messages': [2] },
        { 'domain': 't11', 'name': 'x', 'condition': 'off', 'annotate_messages': { 'x':2} },
        { 'domain': 't11a', 'name': 'x', 'condition': 'off', 'annotate_messages': False },
        { 'domain': 't12', 'name': 'x', 'condition': 'off', 'generator_name':'g1',
          'generator': None },
        { 'domain': 't13', 'name': 'x', 'condition': 'off', 'generator_name':'g2',
          'generator': '' },  # I guess this is ok?
        { 'domain': 't14', 'name': 'x', 'condition': 'off', 'generator_name':'g3',
          'generator': False },
        { 'domain': 't15', 'name': 'x', 'condition': 'off', 'generator_name':'g4',
          'generator': [None] },
        { 'domain': 't16', 'name': 'y{{xx}}', 'condition': 'off', 'generator_name':'g5',
          'generator': { 'xx':3 } },
        { 'domain': 't16a', 'name': 'x', 'condition': 'off', 'generator_name':'g6',
          'generator': [ [4] ] },

        { 'domain': 't17', 'name': 'x', 'condition': 'on', 'notifier': None }, # ok, no notifier specified
        { 'domain': 't18', 'name': 'x', 'condition': 'on', 'notifier': 3 },
        { 'domain': 't19', 'name': 'x', 'condition': 'off', 'notifier': [ {'a':2} ] },
        { 'domain': 't20', 'name': 'x', 'condition': 'off', 'notifier': [ None ] },
        
        { 'domain': 't21', 'name': 'x', 'condition': 'on', 'message': False }, # ok
        { 'domain': 't22', 'name': 'x', 'condition': 'on', 'message': 3 },  # ok
        { 'domain': 't23', 'name': 'x', 'condition': 'on', 'message': [ 3 ] },

        { 'domain': 't24', 'name': 'x', 'threshold': { 'value': None, 'hysteresis': 10, 'minimum':11 } },
        { 'domain': 't25', 'name': 'x', 'threshold': { 'value': False, 'hysteresis': 10, 'minimum':11 } },
        { 'domain': 't26', 'name': 'x', 'threshold': { 'value': [2], 'hysteresis': 10, 'minimum':11 } },
        { 'domain': 't27', 'name': 'x', 'threshold': { 'value': {'a':3}, 'hysteresis': 10, 'minimum':11 } },

        { 'domain': 't28', 'name': 'x', 'trigger': None }, # ok - I guess this just never triggers
        { 'domain': 't29', 'name': 'x', 'trigger': 3 }, 
        { 'domain': 't30', 'name': 'x', 'trigger': 'foo' }, 
        { 'domain': 't31', 'name': 'x', 'trigger': False },
        { 'domain': 't32', 'name': 'x', 'trigger': {'a': 3} }, 
        { 'domain': 't33', 'name': 'x', 'trigger': [ None ] }, 
        { 'domain': 't34', 'name': 'x', 'trigger': [ 3 ] }, 
        { 'domain': 't35', 'name': 'x', 'trigger': [ 'foo' ] }, 
        { 'domain': 't36', 'name': 'x', 'trigger': [ False ] }, 
        { 'domain': 't37', 'name': 'x', 'trigger': [ { 'a' : 4} ] }, 
        
        # others where template becomes false or something weird?
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()

    service_calls.popNotifySearch('persistent_notification', 't02a', 'required key not provided')
    service_calls.popNotifySearch('persistent_notification', 't02b', 'None for dictionary value')
    service_calls.popNotifySearch('persistent_notification', 't03', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't04', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't05', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't05b', 'template value is None')
    service_calls.popNotifySearch('persistent_notification', 't06', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't05a', 'which is not truthy')
    service_calls.popNotifySearch('persistent_notification', 't08', 'invalid boolean value None')
    service_calls.popNotifySearch('persistent_notification', 't09', 'invalid boolean value')
    service_calls.popNotifySearch('persistent_notification', 't10', 'invalid boolean value')
    service_calls.popNotifySearch('persistent_notification', 't11', 'invalid boolean value')
    service_calls.popNotifySearch('persistent_notification', 't12', 'template is None')
    #service_calls.popNotifySearch('persistent_notification', 'g3', 'generator produced non-string or dict')
    #service_calls.popNotifySearch('persistent_notification', 't15', 'None.*rather than string')
    #service_calls.popNotifySearch('persistent_notification', 't16', 'should be a string')
    #service_calls.popNotifySearch('persistent_notification', 't16a', 'Notifier.*rather than string')
    # service_calls.popNotifySearch('persistent_notification', 't17', 'no notifier specified')
    service_calls.popNotifySearch('persistent_notification', 't18', 'not a string')
    service_calls.popNotifySearch('persistent_notification', 't19', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't20', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't21', 't21_x: False')
    service_calls.popNotifySearch('persistent_notification', 't22', 't22_x: 3')
    service_calls.popNotifySearch('persistent_notification', 't23', 'should be a string')
    service_calls.popNotifySearch('persistent_notification', 't24', 'template value is None')
    service_calls.popNotifySearch('persistent_notification', 't25', 'rather than a float')
    service_calls.popNotifySearch('persistent_notification', 't26', 'template value should be a string')
    service_calls.popNotifySearch('persistent_notification', 't27', 'template value should be a string')
    service_calls.popNotifySearch('persistent_notification', 't29', 'is not iterable')
    service_calls.popNotifySearch('persistent_notification', 't30', 'expected a dictionary')
    service_calls.popNotifySearch('persistent_notification', 't31', 'is not iterable')
    service_calls.popNotifySearch('persistent_notification', 't32', 'required key not provided')
    service_calls.popNotifySearch('persistent_notification', 't33', 'is not iterable')
    service_calls.popNotifySearch('persistent_notification', 't34', 'is not iterable')
    service_calls.popNotifySearch('persistent_notification', 't35', 'expected a dictionary')
    service_calls.popNotifySearch('persistent_notification', 't36', 'is not iterable')
    service_calls.popNotifySearch('persistent_notification', 't37', 'required key not provided')
    #_LOGGER.warning(service_calls.allCalls)
    gad = hass.data[DOMAIN]
    assert service_calls.isEmpty()

    assert 't11a' in gad.alerts
    assert not 't12' in gad.alerts
    assert not 't13' in gad.alerts
    assert 't14' in gad.alerts
    assert 't15' in gad.alerts
    assert 't16' in gad.alerts
    assert gad.alerts['t16']['y3']
    assert 't16a' in gad.alerts
    _LOGGER.warning(gad.generators)
    assert not 'g1' in gad.generators
    assert gad.generators['g2'].state == 0
    assert gad.generators['g3'].state == 1
    assert gad.generators['g4'].state == 1
    assert gad.generators['g5'].state == 1
    assert gad.generators['g6'].state == 1

async def test_ha_event(hass, service_calls):
    cfg = { 'alert2' : {  'alerts' : [
        { 'domain': 'test', 'name': 't9', 'condition': 'sensor.a' },
        { 'domain': 'test', 'name': 't10', 'trigger': [{'platform':'state','entity_id':'sensor.b'}] }, 
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off', 'generator_name':'g1', 'generator':"{{ states('sensor.c')}}" }, 
        ], 'tracked': [
            { 'domain': 'test', 'name': 't11' },
        ]}}
    hass.states.async_set("sensor.a", 'off')
    hass.states.async_set("sensor.b", '3')
    hass.states.async_set("sensor.c", '[]')
    calls = []
    hass.bus.async_listen(EVENT_ALERT2_CREATE, lambda ev: calls.append({EVENT_ALERT2_CREATE: ev }))
    hass.bus.async_listen(EVENT_ALERT2_DELETE, lambda ev: calls.append({EVENT_ALERT2_DELETE: ev }))
    hass.bus.async_listen(EVENT_ALERT2_FIRE, lambda ev: calls.append({EVENT_ALERT2_FIRE: ev }))
    hass.bus.async_listen(EVENT_ALERT2_ON, lambda ev: calls.append({EVENT_ALERT2_ON: ev }))
    hass.bus.async_listen(EVENT_ALERT2_OFF, lambda ev: calls.append({EVENT_ALERT2_OFF: ev }))
    hass.bus.async_listen(EVENT_ALERT2_ACK, lambda ev: calls.append({EVENT_ALERT2_ACK: ev }))
    hass.bus.async_listen(EVENT_ALERT2_UNACK, lambda ev: calls.append({EVENT_ALERT2_UNACK: ev }))
    def callHas(an, eid):
        idx = next((i for i, x in enumerate(calls) if an in x and x[an].data['entity_id'] == eid), -1)
        assert idx >= 0
        robj = calls[idx][an].data
        del calls[idx]
        return robj
    assert len(calls) == 0
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()

    # Check creation and deletion
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.test_t9') == { 'entity_id': 'alert2.test_t9', 'domain': 'test', 'name': 't9' }
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.test_t10') == { 'entity_id': 'alert2.test_t10', 'domain': 'test', 'name': 't10' }
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.test_t11') == { 'entity_id': 'alert2.test_t11', 'domain': 'test', 'name': 't11' }
    assert callHas(EVENT_ALERT2_CREATE, 'sensor.alert2generator_g1') == { 'entity_id': 'sensor.alert2generator_g1', 'domain': 'alert2generator', 'name': 'g1' }
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.alert2_error') == { 'entity_id': 'alert2.alert2_error', 'domain': 'alert2', 'name': 'error' }
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.alert2_warning') == { 'entity_id': 'alert2.alert2_warning', 'domain': 'alert2', 'name': 'warning' }
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.alert2_global_exception') == { 'entity_id': 'alert2.alert2_global_exception', 'domain': 'alert2', 'name': 'global_exception' }
    assert not calls

    await setAndWait(hass, "sensor.c", '[ "x1" ]')
    assert callHas(EVENT_ALERT2_CREATE, 'alert2.test_x1') == { 'entity_id': 'alert2.test_x1', 'domain': 'test', 'name': 'x1' }
    assert not calls
    await setAndWait(hass, "sensor.c", '[]')
    assert callHas(EVENT_ALERT2_DELETE, 'alert2.test_x1') == { 'entity_id': 'alert2.test_x1', 'domain': 'test', 'name': 'x1' }
    assert not calls

    # Check condition turning on and off
    await setAndWait(hass, "sensor.a", 'on')
    assert callHas(EVENT_ALERT2_ON, 'alert2.test_t9') == { 'entity_id': 'alert2.test_t9', 'domain': 'test', 'name': 't9' }
    assert not calls
    service_calls.popNotifyEmpty('persistent_notification', 'test_t9: turned on')
    await setAndWait(hass, "sensor.a", 'off')
    assert callHas(EVENT_ALERT2_OFF, 'alert2.test_t9') == { 'entity_id': 'alert2.test_t9', 'domain': 'test', 'name': 't9' }
    assert not calls
    service_calls.popNotifyEmpty('persistent_notification', 'test_t9: turned off')
    
    # Check event triggering
    await setAndWait(hass, "sensor.b", '4')
    assert callHas(EVENT_ALERT2_FIRE, 'alert2.test_t10') == { 'entity_id': 'alert2.test_t10', 'domain': 'test', 'name': 't10' }
    service_calls.popNotifyEmpty('persistent_notification', 'test_t10')
    assert not calls

    # check event reported
    alert2.report('test', 't11', 'foo')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t11: foo')
    assert callHas(EVENT_ALERT2_FIRE, 'alert2.test_t11') == { 'entity_id': 'alert2.test_t11', 'domain': 'test', 'name': 't11' }
    assert not calls

    # check ack / unack on condition
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t9'})
    assert callHas(EVENT_ALERT2_ACK, 'alert2.test_t9') == { 'entity_id': 'alert2.test_t9', 'domain': 'test', 'name': 't9' }
    assert not calls
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t9'})
    assert callHas(EVENT_ALERT2_UNACK, 'alert2.test_t9') == { 'entity_id': 'alert2.test_t9', 'domain': 'test', 'name': 't9' }
    assert not calls
    assert service_calls.isEmpty()
    # check ack / unack on event
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t11'})
    assert callHas(EVENT_ALERT2_ACK, 'alert2.test_t11') == { 'entity_id': 'alert2.test_t11', 'domain': 'test', 'name': 't11' }
    assert not calls
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t11'})
    assert callHas(EVENT_ALERT2_UNACK, 'alert2.test_t11') == { 'entity_id': 'alert2.test_t11', 'domain': 'test', 'name': 't11' }
    assert not calls
    assert service_calls.isEmpty()
    

    
async def test_restore_on(hass, service_calls, hass_storage):
    # test that alert sends reminders if was on when HA restarts
    now = rawdt.datetime.now(rawdt.timezone.utc)
    def hrsAgoStr(anum):
        return str(now - rawdt.timedelta(hours=anum))
    # Create an alert that's fired 7 times since the last notification
    hass_storage['core.restore_state'] = { 'version': 1, 'minor_version': 1, 'key': 'core.restore_state',
        'data': [
            {
                "state": {"entity_id":"alert2.test_t1","state":"off",
                          "attributes":{"icon":"mdi:alert","custom_ui_more_info":"more-info-alert2",
                                        "custom_ui_state_card":"state-card-alert2",
                                        "last_notified_time":hrsAgoStr(7),
                                        "last_fired_time":hrsAgoStr(5),
                                        "last_fired_message":"",
                                        "last_ack_time":None,
                                        "fires_since_last_notify":7, ######
                                        "notified_max_on":0,
                                        "notification_control":"enabled",
                                        "last_on_time":hrsAgoStr(5),
                                        "last_off_time":hrsAgoStr(4),
                                        "reminders_since_fire":0,"cond_true_time":None,
                                        "device_class":"problem","friendly_name":"test_t1"},
                          "last_changed":hrsAgoStr(1),
                          "last_reported":hrsAgoStr(1),
                          "last_updated":hrsAgoStr(1),
                          "context":{"id":"01JJVFG73JJNRX1A4B2E92D98G","parent_id":None,"user_id":None}},
                "extra_data": None,
                "last_seen": hrsAgoStr(1)
            },
        ] }
    cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True }, 'alerts' : [
                             { 'domain': 'test', 'name': 't1', 'condition': 'off' },
                         ] } }
    await rs.async_load(hass)
    assert await async_setup_component(hass, DOMAIN, cfg)
    await asyncio.sleep(0.1)
    gad = hass.data[DOMAIN]
    t1 = gad.alerts['test']['t1']
    assert t1.fires_since_last_notify > 0
    await hass.async_start()
    await hass.async_block_till_done()
    await asyncio.sleep(0.3)
    service_calls.popNotifyEmpty('persistent_notification', 'test_t1: .*fired 7x')

async def test_onoff_cond(hass, service_calls, caplog):
    cfg = { 'alert2' : {  'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'off', 'condition_off': 'off', 'condition_on':'off' }, # bad
        { 'domain': 'test', 'name': 't5', 'condition_off': 'off' }, # bad
        { 'domain': 'test', 'name': 't2', 'trigger': [{'platform':'state','entity_id':'sensor.nope'}],
          'condition': 'off', 'condition_off': 'off' }, # bad
        
        { 'domain': 'test', 'name': 't3', 'condition_on': 'sensor.3on', 'condition_off': 'sensor.3off' },
        { 'domain': 'test', 'name': 't4', 'condition_on': 'sensor.4on', 'trigger_on': [{'platform':'state','entity_id':'sensor.4ton'}], 'condition_off': 'sensor.4off' }, 
        { 'domain': 'test', 'name': 't6', 'trigger_on': [{'platform':'state','entity_id':'sensor.6ton'}], 'condition_on': 'sensor.6on', 'trigger_off': [{'platform':'state','entity_id':'sensor.6toff'}], 'condition_off': 'sensor.6off' },
        { 'domain': 'test', 'name': 't7', 'trigger_on': [{'platform':'state','entity_id':'sensor.7ton'}], 'trigger_off': [{'platform':'state','entity_id':'sensor.7toff'}] },
        { 'domain': 'test', 'name': 't8', 'trigger_on': [{'platform':'state','entity_id':'sensor.8ton'}], 'manual_on': True, 'trigger_off': [{'platform':'state','entity_id':'sensor.8toff'}] },
        { 'domain': 'test', 'name': 't9', 'trigger_on': [{'platform':'state','entity_id':'sensor.9ton'}], 'manual_off': True },
        { 'domain': 'test', 'name': 't10', 'trigger_on': [{'trigger':'state','entity_id':'sensor.10ton','to':'on'}], 'condition_off': 'sensor.10toff' },
        # triggers don't allow templates in state platform, so doesn't work easily with generators
        #{ 'domain': 'test', 'name': '{{genElem}}', 'trigger_on': [{'platform':'state','entity_id':'sensor.foo_{{genElem}}'}], 'manual_off': True, 'generator_name':'g1', 'generator': 't11' },
        { 'domain': 'test', 'name': '{{genElem}}', 'trigger_on': [{'trigger':'template','value_template': '{{ states("sensor.foo_"+genElem) }}'}], 'manual_off': True, 'generator_name':'g2', 'generator': 't12' },
        # test delay_on_secs
    ]}}
    hass.states.async_set("sensor.3on", 'off')
    hass.states.async_set("sensor.3off", 'off')
    hass.states.async_set("sensor.4on", 'off')
    hass.states.async_set("sensor.4off", 'off')
    hass.states.async_set("sensor.6on", 'off')
    hass.states.async_set("sensor.6off", 'off')
    hass.states.async_set("sensor.10ton", 'on')
    hass.states.async_set("sensor.10toff", 'off')
    hass.states.async_set("sensor.foo_t11", 'off')
    hass.states.async_set("sensor.foo_t12", 'off')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    
    service_calls.popNotifySearch('persistent_notification', 't1', 'Can not mix condition')
    service_calls.popNotifySearch('persistent_notification', 't5', 'off. criteria must also include an .on')
    service_calls.popNotifySearch('persistent_notification', 't2', 'extra keys not allowed')
    assert service_calls.isEmpty()
    # Invalid call, so nothing turns on
    await hass.services.async_call('alert2', 'manual_on', {'entity_id':'alert2.test_t3'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert 'manual_on called but alert alert2.test_t3 does not have manual_on enabled' in caplog.text
    # Invalid call, so nothing turns on
    await hass.services.async_call('alert2', 'manual_off', {'entity_id':'alert2.test_t3'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert 'manual_off called but alert alert2.test_t3 does not have manual_off enabled' in caplog.text

    # t3 tests
    await setAndWait(hass, "sensor.3on", 'false')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.3on", 'no')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.3on", 'on')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t3: turned on')
    # cond on/of is edge triggered, so turning off sensor shouldn't affect alert.
    await setAndWait(hass, "sensor.3on", 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t3').state == 'on'
    await setAndWait(hass, "sensor.3on", 'on')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t3').state == 'on'
    await setAndWait(hass, "sensor.3off", 'false')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t3').state == 'on'
    # sensor.3on is still on, alert is on.  Since cond on/off is edge triggered, now
    # switching edges of 3off to on should turn off alert.
    await setAndWait(hass, "sensor.3off", 'on')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t3: turned off')
    assert hass.states.get('alert2.test_t3').state == 'off'
    # and with edge trigger, changing form of yes for 3on should turn it back on
    await setAndWait(hass, "sensor.3on", 'yes')
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t3: turned on')
    assert hass.states.get('alert2.test_t3').state == 'on'
    # But edge trigger of moving off should change state
    await setAndWait(hass, "sensor.3off", 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t3').state == 'on'
    await setAndWait(hass, "sensor.3on", 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t3').state == 'on'

    # t4 tests
    #
    # Cond is false, so triggering shouldn't turn on
    await setAndWait(hass, "sensor.4on", 'off')
    await setAndWait(hass, "sensor.4ton", '1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t4').state == 'off'
    # turning on condition doesn't trigger anything
    await setAndWait(hass, "sensor.4on", 'on')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t4').state == 'off'
    # now triggering will turn on
    await setAndWait(hass, "sensor.4ton", '2')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t4: turned on')
    assert hass.states.get('alert2.test_t4').state == 'on'
    # change to cond off that's off doesn't change anything
    await setAndWait(hass, "sensor.4off", 'false')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t4').state == 'on'
    # change of off one to on does
    await setAndWait(hass, "sensor.4off", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t4: turned off')
    assert hass.states.get('alert2.test_t4').state == 'off'

    # t6 tests
    await setAndWait(hass, "sensor.6ton", '1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t6').state == 'off'
    await setAndWait(hass, "sensor.6toff", '1')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t6').state == 'off'
    await setAndWait(hass, "sensor.6on", 'yes')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t6').state == 'off'
    await setAndWait(hass, "sensor.6off", 'yes')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t6').state == 'off'
    # now trigger should work
    await setAndWait(hass, "sensor.6toff", '2')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t6').state == 'off'
    await setAndWait(hass, "sensor.6ton", '2')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t6: turned on')
    assert hass.states.get('alert2.test_t6').state == 'on'
    await setAndWait(hass, "sensor.6toff", '3')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t6: turned off')
    assert hass.states.get('alert2.test_t6').state == 'off'
    
    # t7 tests
    await setAndWait(hass, "sensor.7ton", '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t7: turned on')
    assert hass.states.get('alert2.test_t7').state == 'on'
    await setAndWait(hass, "sensor.7ton", '2')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t7').state == 'on'
    await setAndWait(hass, "sensor.7toff", '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t7: turned off')
    assert hass.states.get('alert2.test_t7').state == 'off'

    # t8 tests
    await hass.services.async_call('alert2', 'manual_on', {'entity_id':'alert2.test_t8'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t8: turned on')
    assert hass.states.get('alert2.test_t8').state == 'on'
    # manual off is not enabled
    await hass.services.async_call('alert2', 'manual_off', {'entity_id':'alert2.test_t8'})
    await hass.async_block_till_done()
    assert 'manual_off called but alert alert2.test_t8 does not have manual_off enabled' in caplog.text
    assert hass.states.get('alert2.test_t8').state == 'on'
    await setAndWait(hass, "sensor.8toff", '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t8: turned off')
    assert hass.states.get('alert2.test_t8').state == 'off'
    await setAndWait(hass, "sensor.8ton", '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t8: turned on')
    assert hass.states.get('alert2.test_t8').state == 'on'

    # t9 tests
    await setAndWait(hass, "sensor.9ton", '1')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t9: turned on')
    assert hass.states.get('alert2.test_t9').state == 'on'
    await hass.services.async_call('alert2', 'manual_off', {'entity_id':'alert2.test_t9'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t9: turned off')
    assert hass.states.get('alert2.test_t9').state == 'off'

    # t10 tests
    await setAndWait(hass, "sensor.10ton", 'off')
    assert service_calls.isEmpty()
    assert hass.states.get('alert2.test_t10').state == 'off'
    await setAndWait(hass, "sensor.10toff", 'on')
    await setAndWait(hass, "sensor.10toff", 'off')
    await asyncio.sleep(0.05)
    assert hass.states.get('alert2.test_t10').state == 'off'
    assert service_calls.isEmpty()

    if False:
        # t11 tests
        await setAndWait(hass, "sensor.foo_t11", 'on')
        service_calls.popNotifyEmpty('persistent_notification', 'test_t11: turned on')
        assert hass.states.get('alert2.test_t11').state == 'on'
        await setAndWait(hass, "sensor.foo_t11", 'off')
        await asyncio.sleep(0.05)
        assert hass.states.get('alert2.test_t10').state == 'on'
        assert service_calls.isEmpty()
        await hass.services.async_call('alert2', 'manual_off', {'entity_id':'alert2.test_t11'})
        await hass.async_block_till_done()
        service_calls.popNotifyEmpty('persistent_notification', 'test_t11: turned off')
        assert hass.states.get('alert2.test_t11').state == 'off'
    
    # t12 tests
    assert hass.states.get('alert2.test_t12').state == 'off'
    await setAndWait(hass, "sensor.foo_t12", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'test_t12: turned on')
    assert hass.states.get('alert2.test_t12').state == 'on'
    await setAndWait(hass, "sensor.foo_t12", 'off')
    await asyncio.sleep(0.05)
    assert hass.states.get('alert2.test_t12').state == 'on'
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2', 'manual_off', {'entity_id':'alert2.test_t12'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t12: turned off')
    assert hass.states.get('alert2.test_t12').state == 'off'
    
async def test_empty(hass, service_calls):
    cfg = { 'alert2' : {  'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'sensor.a', 'message': ''  },
        { 'domain': 'test', 'name': 't2', 'condition': 'sensor.a', 'message': '{{ states("sensor.b") }}'  },
        { 'domain': 'test', 'name': 't3', 'condition': 'sensor.a', 'message': 'yay', 'notifier': None  },
    ]}}
    hass.states.async_set("sensor.a", 'off')
    hass.states.async_set("sensor.b", '')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    await setAndWait(hass, "sensor.a", 'on')
    service_calls.popNotifySearch('persistent_notification', 't1', 'test_t1')
    service_calls.popNotifySearch('persistent_notification', 't2', 'test_t2')
    assert service_calls.isEmpty()

    await hass.async_stop()
    await hass.async_block_till_done()

async def test_start(hass, service_calls):
    # Check early_start for each kind of timing - friendly_name, generators, and cond_on/cond_ff fields
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't10', 'friendly_name': '{{ states("sensor.a") }}', 'condition': 'off' },
        { 'domain': 'test', 'name': 't11', 'friendly_name': '{{ states("sensor.a") }}', 'condition': 'off', 'early_start': True },
        { 'domain': 'test', 'name': 't12{{genElem}}', 'condition': 'off', 'generator_name': 'g1', 'generator':'{{ states("sensor.g") }}' },
        { 'domain': 'test', 'name': 't13{{genElem}}', 'condition': 'off', 'generator_name': 'g2', 'generator':'{{ states("sensor.g") }}', 'early_start': True },
        { 'domain': 'test', 'name': 't14', 'condition_on': '{{ states("sensor.c") }}', 'manual_off': True },
        { 'domain': 'test', 'name': 't15', 'condition_on': '{{ states("sensor.c") }}', 'manual_off': True, 'early_start': True },
        { 'domain': 'test', 'name': 't16', 'manual_on': True, 'condition_off': '{{ states("sensor.d") }}' },
        { 'domain': 'test', 'name': 't17', 'manual_on': True, 'condition_off': '{{ states("sensor.d") }}', 'early_start': True },
        ]}}
    hass.states.async_set("sensor.a", '3')
    hass.states.async_set("sensor.g", '[ "x" ]')
    hass.states.async_set("sensor.c", 'on')
    hass.states.async_set("sensor.d", 'off')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    gad = hass.data[DOMAIN]

    t10 = gad.alerts['test']['t10']
    t11 = gad.alerts['test']['t11']
    assert hass.states.get('alert2.test_t10').attributes['friendly_name'] == 'test_t10'
    assert hass.states.get('alert2.test_t11').attributes['friendly_name'] == '3'
    #assert t10.extra_state_attributes['friendly_name2'] == None
    #assert t11.extra_state_attributes['friendly_name2'] == '3'
    assert not 't12x' in gad.alerts['test']
    assert 't13x' in gad.alerts['test']
    service_calls.popNotifyEmpty('persistent_notification', 't15: turned on')
    assert service_calls.isEmpty()

    await hass.services.async_call('alert2', 'manual_on', {'entity_id':'alert2.test_t16'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't16: turned on')
    await hass.services.async_call('alert2', 'manual_on', {'entity_id':'alert2.test_t17'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't17: turned on')

    # should trigger one of the condition_off alerts turning off
    await setAndWait(hass, "sensor.d", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't17: turned off')

    await hass.async_start()
    await hass.async_block_till_done()

    assert hass.states.get('alert2.test_t10').attributes['friendly_name'] == '3'
    assert hass.states.get('alert2.test_t11').attributes['friendly_name'] == '3'
    assert 't12x' in gad.alerts['test']
    assert 't13x' in gad.alerts['test']
    service_calls.popNotifySearch('persistent_notification', 't14', 't14: turned on')
    service_calls.popNotifySearch('persistent_notification', 't16', 't16: turned off')
    assert service_calls.isEmpty()

async def test_supersede_mgr(hass, service_calls):
    cfg = { 'alert2' : { } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    s = alert2.SupersedeMgr()
    assert s.supersededBySet('d', 'n1') == set()
    assert s.addNode('d', 'n1', []) is True
    assert s.supersededBySet('d', 'n1') == set()
    assert service_calls.isEmpty()
    # n2 supersedes n1
    assert s.addNode('d', 'n2', [ { 'domain':'d', 'name': 'n1' }]) is True
    assert s.supersededBySet('d', 'n1') == set([('d', 'n2')])
    assert service_calls.isEmpty()
    # Trying to add dup throws error, but doesn't mess up results
    assert s.addNode('d', 'n2', [ { 'domain':'d', 'name': 'n1' }]) is True
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'should not be adding duplicate')
    assert s.supersededBySet('d', 'n1') == set([ ('d', 'n2') ])
    assert s.supersededBySet('d', 'n2') == set()

    # Trying to add n1 supersedes n2 should fail
    s.removeNode('d', 'n1')
    assert s.addNode('d', 'n1', [ { 'domain':'d', 'name': 'n2' }]) is False
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    #service_calls.popNotifyEmpty('persistent_notification', 'should not be adding duplicate')
    assert s.supersededBySet('d', 'n1') == set([ ('d', 'n2') ])
    assert s.supersededBySet('d', 'n2') == set()

    # n3 supersedes n2
    assert s.addNode('d', 'n3', [ { 'domain':'d', 'name': 'n2' }]) is True
    assert s.supersededBySet('d', 'n1') == set([ ('d', 'n2'), ('d', 'n3') ])
    assert s.supersededBySet('d', 'n2') == set([ ('d', 'n3') ])
    assert s.supersededBySet('d', 'n3') == set([ ])
    
    # Trying to add n1 supersedes n3 should fail
    assert s.addNode('d', 'n1', [ { 'domain':'d', 'name': 'n3' }]) is False
    assert s.supersededBySet('d', 'n1') == set([ ('d', 'n2'), ('d', 'n3') ])
    assert s.supersededBySet('d', 'n2') == set([ ('d', 'n3') ])
    assert s.supersededBySet('d', 'n3') == set([ ])

    # should be able to supersede an alert that doesn't yet exist
    assert s.addNode('d', 'n5', [ { 'domain':'d', 'name': 'n4' }, { 'domain': 'd', 'name': 'n3' },
                                  { 'domain':'d', 'name': 'n2' }]) is True
    assert s.supersededBySet('d', 'n1') == set([ ('d', 'n2'), ('d', 'n3'), ('d', 'n5') ])
    assert s.supersededBySet('d', 'n2') == set([ ('d', 'n3'), ('d', 'n5') ])
    assert s.supersededBySet('d', 'n3') == set([ ('d', 'n5') ])
    assert s.supersededBySet('d', 'n4') == set([ ('d', 'n5') ])
    assert s.supersededBySet('d', 'n5') == set([ ])

    # supersedes graph is
    #
    # n5 -> (n4, n3, n2)
    # n3 -> n2 -> n1
    
    assert s.addNode('d', 'n4', [ { 'domain':'d', 'name': 'n5' }]) is False
    # Now try n4 supersedes n2
    assert s.addNode('d', 'n4', [ { 'domain':'d', 'name': 'n2' }]) is True
    assert s.supersededBySet('d', 'n1') == set([ ('d', 'n2'), ('d', 'n3'), ('d', 'n5'), ('d', 'n4') ])
    assert s.supersededBySet('d', 'n2') == set([ ('d', 'n3'), ('d', 'n5'), ('d', 'n4') ])
    assert s.supersededBySet('d', 'n3') == set([ ('d', 'n5') ])
    assert s.supersededBySet('d', 'n4') == set([ ('d', 'n5') ])
    assert s.supersededBySet('d', 'n5') == set([ ])

    s.removeNode('d', 'n2')
    assert s.supersededBySet('d', 'n1') == set()
    assert s.supersededBySet('d', 'n2') == set([ ('d', 'n3'), ('d', 'n5'), ('d', 'n4') ])
    assert s.supersededBySet('d', 'n3') == set([ ('d', 'n5') ])
    assert s.supersededBySet('d', 'n4') == set([ ('d', 'n5') ])
    assert s.supersededBySet('d', 'n5') == set([ ])
    
    # try two roots
    s = alert2.SupersedeMgr()
    assert s.addNode('d', 'n1', [ { 'domain':'d', 'name': 'n3' }]) is True
    assert s.addNode('d', 'n2', [ { 'domain':'d', 'name': 'n3' }]) is True
    assert s.addNode('d', 'n3', [ ]) is True
    assert s.supersededBySet('d', 'n1') == set()
    assert s.supersededBySet('d', 'n2') == set()
    assert s.supersededBySet('d', 'n3') == set([ ('d', 'n1'),('d', 'n2') ])
    
    # Try cycle separated by a node
    s = alert2.SupersedeMgr()
    assert s.addNode('d', 'n6', [ { 'domain':'d', 'name': 'n7' }, { 'domain':'d', 'name': 'n8' }]) is True
    assert s.addNode('d', 'n7', [ { 'domain':'d', 'name': 'n8' }]) is True
    assert s.addNode('d', 'n8', [ { 'domain':'d', 'name': 'n6' }]) is False
    assert s.supersededBySet('d', 'n8') == set([ ('d', 'n7'), ('d', 'n6') ])
    assert s.supersededBySet('d', 'n7') == set([ ('d', 'n6') ])
    assert s.supersededBySet('d', 'n6') == set()

    # Try diamond shape
    s = alert2.SupersedeMgr()
    assert s.addNode('d', 'n9', [ { 'domain':'d', 'name': 'n10' }, { 'domain':'d', 'name': 'n11' }]) is True
    assert s.addNode('d', 'n10', [ { 'domain':'d', 'name': 'n12' }]) is True
    assert s.supersededBySet('d', 'n9') == set()
    assert s.supersededBySet('d', 'n10') == set([ ('d', 'n9') ])
    assert s.supersededBySet('d', 'n11') == set([ ('d', 'n9') ])
    assert s.supersededBySet('d', 'n12') == set([ ('d', 'n9'), ('d', 'n10') ])
    assert s.addNode('d', 'n11', [ { 'domain':'d', 'name': 'n12' }]) is True
    assert s.supersededBySet('d', 'n9') == set()
    assert s.supersededBySet('d', 'n10') == set([ ('d', 'n9') ])
    assert s.supersededBySet('d', 'n11') == set([ ('d', 'n9') ])
    assert s.supersededBySet('d', 'n12') == set([ ('d', 'n9'), ('d', 'n10'), ('d', 'n11') ])
    assert s.addNode('d', 'n12', [ ]) is True

    # Try removing node that collapses parent
    s = alert2.SupersedeMgr()
    assert s.addNode('d', 'n1', [ { 'domain':'d', 'name': 'n2' } ]) is True
    assert s.supersededBySet('d', 'n1') == set()
    assert s.supersededBySet('d', 'n2') == set([ ('d', 'n1') ])
    s.removeNode('d', 'n1')
    assert s.supersededBySet('d', 'n1') == set()
    assert s.supersededBySet('d', 'n2') == set()
    
    # NOTE
    #
    # If you add any tests here, also add tests to t2.html::doTestSupersedeMgr
    #

    
async def test_supersede_mgr2(hass, service_calls, monkeypatch):
    await setAndWait(hass, "sensor.t1", 'off')
    await setAndWait(hass, "sensor.t2", 'off')
    await setAndWait(hass, "sensor.t3", 'off')
    cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01, 'supersede_debounce_secs': 0 }, 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'sensor.t1' },
        { 'domain': 'test', 'name': 't2', 'condition': 'sensor.t2', 'supersedes': [ {'domain':'test','name':'t1'} ] },
        # t3 added later
        # Test that supersedes is flexible with expressions of empty set
        #{ 'domain': 'test', 'name': 't4', 'condition': 'off', 'supersedes': '' },
        #{ 'domain': 'test', 'name': 't6', 'condition': 'off', 'supersedes': [None] },
        { 'domain': 'test', 'name': 't6', 'condition': 'off', 'supersedes': [] },
        { 'domain': 'test', 'name': 't7', 'condition': 'off', 'supersedes': None },
    ] } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    gad = hass.data[DOMAIN]
    assert gad.supersedeMgr.supersedesMap == {
        ('test','t1'): set(),
        ('test','t2'): set( [ ('test','t1') ] ),
        ('test','t6'): set(),
        ('test','t7'): set(),
    }
    
    await setAndWait(hass, "sensor.t1", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't1: turned on')
    await setAndWait(hass, "sensor.t2", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned on')
    # Wait for reminders, only t2 should have it
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't2: on for')
    await setAndWait(hass, "sensor.t1", 'off')
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.t1", 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.t2", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned off')
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't1.*: on for')

    # t2 on, miss t1 reminder, so test to see if future reminders happen
    await setAndWait(hass, "sensor.t2", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned on')
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't2: on for')
    await setAndWait(hass, "sensor.t2", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned off')
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't1: on for')

    # Try a reload introducing a new alert superseding t1
    cfg['alert2']['alerts'].append(
        { 'domain': 'test', 'name': 't3', 'condition': 'sensor.t3', 'supersedes': [ {'domain':'test','name':'t1'} ] }
    )
    async def fake_cfg(thass):
        return cfg
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    await asyncio.sleep(alert2.gGcDelaySecs + 0.1)
    _LOGGER.info('reload done')
    # We will get a reminder because reminder freq is set for 0.6s, but when schedule reminders, we add a second.
    # So there was a reminder that was due but in that 1-second window.  When we reload, we see the reminder is
    # due and send it.
    service_calls.popNotifyEmpty('persistent_notification', 't1: on for')
    assert service_calls.isEmpty()

    # should still get reminders
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't1: on for')
    # And once t3 turns on, no more reminders or notification when t1 turns off
    await setAndWait(hass, "sensor.t3", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't3: turned on')
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't3: on for')
    await setAndWait(hass, "sensor.t1", 'off')
    assert service_calls.isEmpty()

async def test_supersede3(hass, service_calls, monkeypatch):
    # Check when supersedes template has a literal eval error
    cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 }, 'alerts' : [
        { 'domain': 'test', 'name': 't8', 'condition': 'off', 'supersedes': '[ 3', 'generator': 'gg','generator_name':'g1' },
        { 'domain': 'test', 'name': 't9', 'condition': 'off', 'supersedes': '{{ "[ 3" }}', 'generator': 'gg','generator_name':'g2' },
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': '{ "domain": "test", "name": "{{genElem}}_is_low" }', 'generator': 'tg1','generator_name':'g3' },
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': '{{ { "domain": "test", "name": genElem+"_is_low" } }}', 'generator': 'tg2','generator_name':'g4' },
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': { "domain": "dd{{ genElem }}", "name": "nn{{ genElem }}" }, 'generator': 'tg3','generator_name':'g5' },
        # Template produces dict with wrong keys
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': '{{ { "domainzz": "dd", "name": "nn" } }}', 'generator': 'tg3a','generator_name':'g5a' },
        # Template produces single dict rather than array
        # This works because it is proessed into yaml, then cv.ensure_list
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': '{{ { "domain": "dd", "name": "nntg3b" } }}', 'generator': 'tg3b','generator_name':'g5b' },
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': { "domain": "dd", "name": "nn{{ genElem }}" }, 'generator': 'tg4','generator_name':'g6' },
        # Bad template
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': { "domain": "dd", "name": "nn{{ genElem" }, 'generator': 'tg5','generator_name':'g7' },
        # Template ok but renders to bad name
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': { "domain": "dd", "name": "{{ 'x[' }}" }, 'generator': 'tg6','generator_name':'g8' },
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': [ { "domain": "dd{{genElem}}", "name": "nn{{ genElem }}" },
                          { "domain": "dd{{genElem}}", "name": "nn2{{ genElem }}" } ],
          'generator': 'tg7','generator_name':'g9' },
        # Second element in supersedes renders to bad value
        { 'domain': 'test', 'name': '{{genElem}}', 'condition': 'off',
          'supersedes': [ { "domain": "dd{{genElem}}", "name": "nn{{ genElem }}" },
                          { "domain": "dd{{genElem}}", "name": "nn2{{ '[' }}" } ],
          'generator': 'tg8','generator_name':'g10' },
        # Template not allowed if not a generator
        { 'domain': 'test', 'name': 't10', 'condition': 'off', 'supersedes': { 'domain': 'test', 'name': '{{ "foo" }}' } },
    ] } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    service_calls.popNotifySearch('persistent_notification', 't8', 'expected a dictionary')
    service_calls.popNotifySearch('persistent_notification', 'g2', 'trying to parse.*was never closed')
    service_calls.popNotifySearch('persistent_notification', 'tg6', 'Illegal characters')
    service_calls.popNotifySearch('persistent_notification', 'tg8', 'Illegal characters')
    service_calls.popNotifySearch('persistent_notification', 't10', 'Illegal characters')
    service_calls.popNotifySearch('persistent_notification', 'tg3a', 'extra keys not allowed.*domainzz')
    service_calls.popNotifyEmpty('persistent_notification', 'unexpected end of template.*g7')
    gad = hass.data[DOMAIN]
    assert list(gad.alerts['test'].keys()) == [ 'tg1', 'tg2', 'tg3', 'tg3b', 'tg4', 'tg7' ]
    _LOGGER.warning(gad.supersedeMgr.supersedesMap)
    assert gad.supersedeMgr.supersedesMap == {
        ('test','tg1'): set( [ ('test','tg1_is_low') ] ),
        ('test','tg2'): set( [ ('test','tg2_is_low') ] ),
        ('test','tg3'): set( [ ('ddtg3','nntg3') ] ),
        ('test','tg3b'): set( [ ('dd','nntg3b') ] ),
        ('test','tg4'): set( [ ('dd','nntg4') ] ),
        ('test','tg7'): set( [ ('ddtg7','nntg7'),('ddtg7','nn2tg7') ] ),
    }

async def test_supersede4(hass, service_calls):
    # Test ok supersedes.
    cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
        # Yaml interpretation happens only in UI
        #{ 'domain': 'd', 'name': 'n2','supersedes': '{ "domain": "d" , "name": "n1" }', 'condition': 'off' },
        { 'domain': 'd', 'name': 'n3','supersedes': '{ "domain": "d" , "name": "{{ genElem }}" }', 'condition': 'off', 'generator_name':'g3','generator': ['n1'] },
        { 'domain': 'd', 'name': 'n4','supersedes': '{{ [{ "domain": "d", "name": genElem }] }}', 'condition': 'off', 'generator_name':'g2','generator': ['n1'] },
        { 'domain': 'd', 'name': 'n5','supersedes': [{ 'domain': 'd', 'name': '{{ genElem }}' }], 'generator_name':'g5a','generator': ['n1'], 'condition': 'off' },
        { 'domain': 'd', 'name': 'n1', 'condition': 'off'},
        ] }}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    #service_calls.popNotifyEmpty('persistent_notification', 'extra keys.*\'x\'')
    gad = hass.data[DOMAIN]
    assert gad.supersedeMgr.supersedesMap == {
        ('d','n5'): set( [ ('d','n1') ] ),
        ('d','n4'): set( [ ('d','n1') ] ),
        ('d','n3'): set( [ ('d','n1') ] ),
        #('d','n2'): set( [ ('d','n1') ] ),
        ('d','n1'): set( ),
    }

    
async def test_no_yaml(hass, service_calls):
    # First, let's say YAML setup happens before config entry
    #
    cfg = { } # no alert2 section
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        entry_id="01JAZ5DPWAAA2D620DGYNG2R8H",
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

async def test_display_msg(hass, service_calls):
    cfg = { } # no alert2 section
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # Make sure doc is correct saying "null" works
    assert parse_yaml("x: null") == { 'x': None }
    
async def test_priority(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'off' },
        { 'domain': 'test', 'name': 't2', 'condition': 'off', 'priority': 'medium' },
        # bad name
        { 'domain': 'test', 'name': 't3', 'condition': 'off', 'priority': 'foo' },
        # Template only allowed in generator
        { 'domain': 'test', 'name': 't4', 'condition': 'off', 'priority': '{{ "low" }}' },
        { 'domain': 'test', 'name': 't5', 'condition': 'off', 'priority': '{{ "high" }}', 'generator': 'gg1', 'generator_name': 'g1' },
        { 'domain': 'test', 'name': 't6', 'condition': 'off', 'priority': 'medium', 'generator': 'gg2', 'generator_name': 'g2' },
        { 'domain': 'test', 'name': 't7', 'condition': 'off', 'priority': '{{ ["high"][genIdx] }}', 'generator': 'gg3', 'generator_name': 'g3' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't3', 'required key not provided')
    service_calls.popNotifySearch('persistent_notification', 't4', 'required key not provided')
    assert service_calls.isEmpty()

    gad = hass.data[DOMAIN]
    assert list(gad.alerts['test'].keys()) == [ 't1', 't2', 't5', 't6', 't7' ]
    assert gad.alerts['test']['t1']._priority == 'low'
    assert gad.alerts['test']['t2']._priority == 'medium'
    assert gad.alerts['test']['t5']._priority == 'high'
    assert gad.alerts['test']['t6']._priority == 'medium'
    assert gad.alerts['test']['t7']._priority == 'high'

async def test_icon(hass, service_calls, monkeypatch):
    cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'off' },
        { 'domain': 'test', 'name': 't2', 'condition': 'off', 'icon': 'a:b' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    gad = hass.data[DOMAIN]
    assert list(gad.alerts['test'].keys()) == [ 't1', 't2' ]
    assert gad.alerts['test']['t1']._icon == 'mdi:alert'
    assert gad.alerts['test']['t2']._icon == 'a:b'

    cfg = { 'alert2' : { 'defaults': { 'icon': 'c:d' }, 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'off' },
        { 'domain': 'test', 'name': 't2', 'condition': 'off', 'icon': 'a:b' },
    ], } }
    async def fake_cfg(thass):
        return cfg
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    await asyncio.sleep(alert2.gGcDelaySecs + 0.1)
    assert service_calls.isEmpty()
    assert list(gad.alerts['test'].keys()) == [ 't1', 't2' ]
    assert gad.alerts['test']['t1']._icon == 'c:d'
    assert gad.alerts['test']['t2']._icon == 'a:b'

    

async def test_delay_on_secs(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'off' },
        { 'domain': 'test', 'name': 't2', 'condition': 'off', 'delay_on_secs': 3 },
        { 'domain': 'test', 'name': 't2a', 'condition': 'off', 'delay_on_secs': 0 },
        { 'domain': 'test', 'name': 't3', 'condition': 'off', 'delay_on_secs': '4' },
        { 'domain': 'test', 'name': 't4', 'condition': 'off', 'delay_on_secs': 'foo' },
        { 'domain': 'test', 'name': 't5', 'condition': 'off', 'delay_on_secs': -2 },
        # Template only allowed in generator
        { 'domain': 'test', 'name': 't6', 'condition': 'off', 'delay_on_secs': '{{ 5 }}' },
        { 'domain': 'test', 'name': 't7', 'condition': 'off', 'delay_on_secs': '{{ "6" }}', 'generator': 'gg1', 'generator_name': 'g1' },
        { 'domain': 'test', 'name': 't8', 'condition': 'off', 'delay_on_secs': '{{ -7 }}', 'generator': 'gg2', 'generator_name': 'g2' },
        { 'domain': 'test', 'name': 't9', 'condition': 'off', 'delay_on_secs': '{{ [8][genIdx] }}', 'generator': 'gg3', 'generator_name': 'g3' },
        { 'domain': 'test', 'name': 't10', 'condition': 'off', 'delay_on_secs': '{{ (foo|float)*60 }}',
          'generator': [ { 'ent':'abc', 'foo': 0 } ], 'generator_name': 'g4' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't4', 'required key not provided')
    service_calls.popNotifySearch('persistent_notification', 't5', 'required key not provided')
    service_calls.popNotifySearch('persistent_notification', 't6', 'required key not provided')
    service_calls.popNotifySearch('persistent_notification', 't8', 'required key not provided')
    assert service_calls.isEmpty()

    gad = hass.data[DOMAIN]
    assert list(gad.alerts['test'].keys()) == [ 't1', 't2', 't2a', 't3', 't7', 't9', 't10' ]
    assert gad.alerts['test']['t1'].delay_on_secs == 0
    assert gad.alerts['test']['t2'].delay_on_secs == 3
    assert gad.alerts['test']['t2a'].delay_on_secs == 0
    assert gad.alerts['test']['t3'].delay_on_secs == 4
    assert gad.alerts['test']['t7'].delay_on_secs == 6
    assert gad.alerts['test']['t9'].delay_on_secs == 8
    assert gad.alerts['test']['t10'].delay_on_secs == 0

    
async def test_native_friendly(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
        { 'domain': 'test', 'name': 't1', 'condition': 'off' },
        { 'domain': 'test', 'name': 't2', 'condition': 'off', 'friendly_name': 'happy' },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    assert hass.states.get('alert2.test_t1').attributes['friendly_name'] == 'test_t1'
    assert hass.states.get('alert2.test_t2').attributes['friendly_name'] == 'happy'

async def test_supersedes_debounce(hass, service_calls, caplog):
    # Test when alert A & B both turn on or off at the same time and A supersedes B
    # Test bug where fires_since_last_notify was being set for superseded alert, resulting in skipped summary
    await setAndWait(hass, "sensor.a", 'off')
    await setAndWait(hass, "sensor.b", 'off')
    await setAndWait(hass, "sensor.c", 'off')
    await setAndWait(hass, "sensor.s7", 'off')
    await setAndWait(hass, "sensor.s8", 'off')
    debounce_secs = 0.3
    cfg = { 'alert2' : { 'defaults': { 'supersede_debounce_secs': debounce_secs }, 'alerts' : [
        { 'domain': 't', 'name': 't3', 'condition': 'sensor.a', 'supersedes': [{'domain':'t','name':'t1'},{'domain':'t','name':'t2'}] },
        { 'domain': 't', 'name': 't1', 'condition': 'sensor.a' },
        { 'domain': 't', 'name': 't4', 'condition': 'sensor.a', 'supersedes': {'domain':'t','name':'t1'} },

        { 'domain': 't', 'name': 't5', 'condition': 'sensor.b' },
        { 'domain': 't', 'name': 't6', 'condition': 'sensor.c', 'supersedes': {'domain':'t','name':'t5'} },

        { 'domain': 't', 'name': 't7', 'condition': 'sensor.s7', 'reminder_frequency_mins': 0.01, 'supersede_debounce_secs':2 },
        { 'domain': 't', 'name': 't8', 'condition': 'sensor.s8', 'supersedes': {'domain':'t','name':'t7'}, 'supersede_debounce_secs': 2 },
    ], } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # t1 superseded. on at same time
    await setAndWait(hass, "sensor.a", 'on')
    service_calls.popNotifySearch('persistent_notification', 't3', 'turned on')
    service_calls.popNotifySearch('persistent_notification', 't4', 'turned on')
    assert service_calls.isEmpty()
    
    # t1 superseded. off at same time
    await setAndWait(hass, "sensor.a", 'off')
    service_calls.popNotifySearch('persistent_notification', 't3', 'turned off')
    service_calls.popNotifySearch('persistent_notification', 't4', 'turned off')
    assert service_calls.isEmpty()
    assert not 'skipping summaries' in caplog.text
    await asyncio.sleep(debounce_secs + 0.05)

    # t6 supersedews t5

    # t5 on shortly before t6
    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.b", 'on')
    await asyncio.sleep(0.05)
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.c", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned on')
    # t6 off shortly before t5
    await setAndWait(hass, "sensor.c", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned off')
    await asyncio.sleep(0.05)
    await setAndWait(hass, "sensor.b", 'off')
    assert service_calls.isEmpty()

    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.b", 'on')
    await setAndWait(hass, "sensor.c", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned on')
    # t6 off long before t5
    await setAndWait(hass, "sensor.c", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned off')
    await asyncio.sleep(debounce_secs + 0.05)
    await setAndWait(hass, "sensor.b", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't5: turned off')

    # t5 on long before t6
    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.b", 'on')
    await asyncio.sleep(debounce_secs + 0.05)
    service_calls.popNotifyEmpty('persistent_notification', 't5: turned on')
    await setAndWait(hass, "sensor.c", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned on')
    # t5 off shortly before t6
    await setAndWait(hass, "sensor.b", 'off')
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.c", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned off')

    # t6 on shortly before t5
    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.c", 'on')
    await setAndWait(hass, "sensor.b", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned on')
    await setAndWait(hass, "sensor.c", 'off')
    await setAndWait(hass, "sensor.b", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned off')

    # t5 goes on/off before t6 turns on
    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.b", 'on')
    await setAndWait(hass, "sensor.b", 'off')
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.c", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned on')
    await setAndWait(hass, "sensor.c", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned off')

    # t5 goes on/off/on before t6 turns on
    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.b", 'on')
    await setAndWait(hass, "sensor.b", 'off')
    await setAndWait(hass, "sensor.b", 'on')
    assert service_calls.isEmpty()
    await setAndWait(hass, "sensor.c", 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned on')
    await setAndWait(hass, "sensor.c", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't6: turned off')
    await setAndWait(hass, "sensor.b", 'off')
    assert service_calls.isEmpty()
    
    await asyncio.sleep(debounce_secs + 0.05)  # reset for next test
    await setAndWait(hass, "sensor.b", 'on')
    await setAndWait(hass, "sensor.b", 'off')
    await setAndWait(hass, "sensor.b", 'on')
    await setAndWait(hass, "sensor.b", 'off')
    await asyncio.sleep(debounce_secs + 0.05)
    service_calls.popNotifySearch('persistent_notification', 't5', 't5: turned on')
    service_calls.popNotifySearch('persistent_notification', 't5', 't5: turned off')
    service_calls.popNotifySearch('persistent_notification', 't5', 't5: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 't5: turned off')

    _LOGGER.info('testing............')
    await setAndWait(hass, "sensor.s7", 'on')
    await asyncio.sleep(1.5) # should get reminder that is delayed
    assert service_calls.isEmpty()
    await asyncio.sleep(1) # now wait expires
    gad = hass.data[DOMAIN]
    t7 = gad.alerts['t']['t7']
    assert gad.supersedeNotifyMgr.isWaiting(t7) is False
    # no reminder notification cuz reminder timer starts from first call to _notify_post_debounce
    service_calls.popNotifyEmpty('persistent_notification', 't7: turned on')
    await setAndWait(hass, "sensor.s7", 'off')
    service_calls.popNotifyEmpty('persistent_notification', 't7: turned off')


    _LOGGER.info('testing2............')
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.t_t7', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=0.5) })
    await setAndWait(hass, "sensor.s7", 'on')
    await setAndWait(hass, "sensor.s7", 'off')
    await setAndWait(hass, "sensor.s7", 'on')
    await setAndWait(hass, "sensor.s7", 'off')
    await asyncio.sleep(2) # snooze expires and wait expires
    assert gad.supersedeNotifyMgr.isWaiting(t7) is False
    # snoozing check is done in _notify_post_debounce, so they all go through since snooze expired
    service_calls.popNotifySearch('persistent_notification', 't7', 't7: turned on')
    service_calls.popNotifySearch('persistent_notification', 't7', 't7: turned off')
    service_calls.popNotifySearch('persistent_notification', 't7', 't7: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 't7: turned off')

async def test_shutdown2(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': { },
                         'tracked': [{ 'domain':'t', 'name': 't1' }],
                        } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await asyncio.sleep(0.3)

    ev = asyncio.Event()
    async def sd(event):
        await asyncio.sleep(0.1)
        ev.set()
        # Wish we could raise exception and let report() do its thing naturally.
        # pytest can't handle that though :(
        # raise Exception('darn')
        #
        # Instead we report manually
        alert2.report('t', 't1', 'some error')
    hass.bus.async_listen_once(homeassistant.const.EVENT_HOMEASSISTANT_STOP, sd)

    await hass.async_stop()
    await hass.async_block_till_done()
    await ev.wait()
    await asyncio.sleep(0.3)

    # This is the main test - that no undeclared alert errors occurred
    assert service_calls.isEmpty()

    # Restore shutting down for next test
    set_shutting_down(False)
    
async def test_done_notifier(hass, service_calls):
    def mock_service_foo(call):
        return None
    hass.services.async_register('notify', 'foo', mock_service_foo)
    await setAndWait(hass, "sensor.a", 'off')
    cfg = { 'alert2' : { 'defaults': { },
                         'alerts': [
                             { 'domain':'t', 'name': 't1', 'condition': 'sensor.a', 'done_notifier': False  },
                             { 'domain':'t', 'name': 't2', 'condition': 'sensor.a', 'done_notifier': 'foo'  },
                             { 'domain':'t', 'name': 't3', 'condition': 'off', 'done_notifier': 'no'  },
                         ],
                        } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    assert gad.alerts['t']['t1']._done_notifier == False
    assert gad.alerts['t']['t2']._done_notifier.template == 'foo'
    assert gad.alerts['t']['t3']._done_notifier == False


    await setAndWait(hass, "sensor.a", 'on')
    service_calls.popNotifySearch('persistent_notification', 't1', 't1: turned on')
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned on')

    await setAndWait(hass, "sensor.a", 'off')
    service_calls.popNotifyEmpty('foo', 't2: turned off')

async def test_data(hass, service_calls):
    await setAndWait(hass, "sensor.a", 'off')
    await setAndWait(hass, "sensor.b", 'off')
    cfg = { 'alert2' : { 'alerts': [
        { 'domain': 'test', 'name': 't1', 'condition': 'sensor.a',
          'data': { 'd1': 7, 'd2': '{% if notify_reason=="Fire" %}99{%else%}30{%endif%}',
                    'd3': '"{% if notify_reason=="Fire" %}abc{%else%}def{%endif%}"', 'd4': 'foo-bar',
                    'd5': '{% if notify_reason=="Fire" %}True{%else%}False{%endif%}',
                    'd6': '{% if notify_reason=="Fire" %}[ { "action": "foo", "title": "bar" } ]{%else%}[]{%endif%}',
                    'd7': '"{{ alert_entity_id }}"',
                   } },
        { 'domain': 'test', 'name': '{{ genElem }}', 'condition': 'sensor.a', 'data': { 'd1': 6, 'd2': '"{{ genElem+notify_reason }}"' }, 'generator': 't2', 'generator_name': 'g1' },
        { 'domain': 'test', 'name': 't4', 'condition': 'sensor.b', 'data':{ 'd1': ' "{{ "foo" }}"   ' }}, # ok
        # Some bad literals
        { 'domain': 'test', 'name': 't5', 'condition': 'sensor.b', 'data':{ 'd1': '{{ "foo" }}' }}, # missing both quotes
        { 'domain': 'test', 'name': 't6', 'condition': 'sensor.b', 'data':{ 'd1': '"{{ "foo" }}' }}, # missing one quote
        ], 'tracked' : [
            { 'domain': 'test', 'name': 't3', 'data': { 'd1': '"{{ notify_reason }}xy"', 'd2': 99 } },
        ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, "sensor.a", 'on')
    service_calls.popNotifySearch('persistent_notification', 't1', 'turned on',
                                  extraFields={ 'data': { 'd1': 7, 'd2': 99, 'd3':'abc', 'd4':'foo-bar',
                                                          'd5': True, 'd6': [ { 'action': 'foo', 'title': 'bar'} ],
                                                          'd7': 'alert2.test_t1' }})
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned on', extraFields={ 'data': { 'd1': 6, 'd2': 't2Fire'}})
    
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t3', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'test_t3.*foo', extraFields={ 'data': { 'd1': 'Firexy', 'd2':99 }})

    await setAndWait(hass, "sensor.a", 'off')
    service_calls.popNotifySearch('persistent_notification', 't1', 'turned off',
                                  extraFields={ 'data': { 'd1': 7, 'd2': 30, 'd3':'def', 'd4':'foo-bar',
                                                          'd5': False, 'd6': [], 'd7': 'alert2.test_t1' }})
    service_calls.popNotifyEmpty('persistent_notification', 't2: turned off', extraFields={ 'data': { 'd1': 6, 'd2': 't2StopFiring'}})

    await setAndWait(hass, "sensor.b", 'on')
    service_calls.popNotifySearch('persistent_notification', 't4', 'turned on', extraFields={ 'data': { 'd1': 'foo'  }})
    service_calls.popNotifySearch('persistent_notification', 't5 data template Error', 'extra quotes')
    service_calls.popNotifySearch('persistent_notification', 't6 data template Error', 'extra quotes')
    service_calls.popNotifySearch('persistent_notification', 't5', 'turned on')
    service_calls.popNotifySearch('persistent_notification', 't6', 'turned on')
    assert service_calls.isEmpty()

async def test_data2(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': {
        'data': {
            'actions': "[{ action: '{{ 3+4 }}' }]"
        }}, 'tracked': [ { 'domain': 'd', 'name': 't1' } ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await hass.services.async_call('alert2','report', {'domain':'d','name':'t1', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifySearch('persistent_notification', 't1: foo', '')
    service_calls.popNotifyEmpty('persistent_notification', 'd_t1 data template Error rendering data field "actions".*alert2_error itself had issue: alert2_error data template')

async def test_data3(hass, service_calls):
    cfg = { 'alert2' : { 'defaults': {
        'data': {
            'actions': "[{ 'action': 'foo_{{ 3+4 }}' }]"
        }}, 'tracked': [ { 'domain': 'd', 'name': 't1' } ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await hass.services.async_call('alert2','report', {'domain':'d','name':'t1', 'message': 'ick'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'd_t1: ick', extraFields={ 'data': { 'actions': [{ 'action': 'foo_7' }] } })

    
    
async def test_nested_generator(hass, service_calls):
    cfg = { 'alert2' : { 'alerts': [
        { 'domain': 'test', 'name': '{{ genA }}__{{ genB }}', 'condition': 'off','generator_name': 'g1',
          'generator': ' [{% for a in [ 3, 4 ] %}{% for b in [7, 8 ] %}{"genA":{{a}},"genB":{{b}}},{% endfor %}{% endfor %}]',  },
        ]}}
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    assert list(gad.alerts['test'].keys()) == [ '3__7','3__8','4__7','4__8' ]

    # Hrm, writing the supersedes so it only applies to genA or genB would be messy
    # eg. want to alert on printer ink being low, across different ink colors

