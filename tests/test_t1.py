#
# JTESTDIR=/home/redstone/home-monitoring/homeassistant  venv/bin/pytest --show-capture=no
#
#from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import os
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
import homeassistant.const

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
                service_calls.popNotifyEmpty('persistent_notification', f'Throttling started.*test_{tname}.*turned on')
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
                            service_calls.popNotifyEmpty('persistent_notification', f'Throttling ending] Alert2 test_{tname} fired 1x.*: on for 2 s$')
                        else:
                            service_calls.popNotifyEmpty('persistent_notification', f'Throttling ending] Alert2 test_{tname}: on for 4 s$')
                    else:
                        service_calls.popNotifyEmpty('persistent_notification', f'Throttling ending] Summary.*test_{tname}.*turned off.*after being on')
                else:
                    if onAtEnd:
                        if extraFire:
                            service_calls.popNotifyEmpty('persistent_notification', f'Throttling ending] Alert2 test_{tname} fired 1x.*on for 2 s$')
                        else:
                            service_calls.popNotifyEmpty('persistent_notification', f'Throttling ending] Alert2 test_{tname}: on for 4 s$')
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
        { 'domain': 'test', 'name': 't11d', 'condition': 'sensor.a', 'message': 'ick-t11d', 'annotate_messages': False },
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
    service_calls.popNotifySearch('persistent_notification', 't11d', 'Alert2 test_t11d: on for')
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

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t22'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t22')

    await hass.services.async_call('alert2','report', {'domain':'test','name':'t22', 'message': 'foo'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 test_t22: foo')

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
            service_calls.popNotifyEmpty('persistent_notification', f'Throttling started] Alert2 test_{tname}')

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
                    service_calls.popNotifyEmpty('persistent_notification', 'Throttling ending] Summary.*test_t27 fired 2x')
                else:
                    service_calls.popNotifyEmpty('persistent_notification', 'Throttling ending] Summary.*test_t27: Did not fire')
            else:
                assert service_calls.isEmpty()

async def test_event3(hass, service_calls):
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't28',  'trigger':  [{'platform':'state','entity_id':'sensor.t28'}], 'condition': 'sensor.c28' },
        { 'domain': 'test', 'name': 't28a',  'trigger': [{'platform':'state','entity_id':'sensor.t28a'}], 'message': '{{ 3+4 }}' },
        { 'domain': 'test', 'name': 't29',  'trigger': [{'platform':'state','entity_id':'sensor.t29'}], 'condition': 'sensor.t29', 'friendly_name': 'friendly-t29'  },
    ], } }
    hass.states.async_set("sensor.c28", "off")
    hass.states.async_set("sensor.t28", "1")
    hass.states.async_set("sensor.t28a", "1")
    hass.states.async_set("sensor.t29", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

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
    ], } }
    hass.states.async_set("sensor.ick", "3")
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

async def test_err_args(hass, service_calls):
    # test pssing entity name instead of template for condition or threshold value
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
    cfg = { 'alert2' : { 'alerts' : [
        { 'domain': 'test', 'name': 't40', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01 },
    ],  'tracked' : [
        { 'domain': 'test', 'name': 't41', 'throttle_fires_per_mins': [1, 0.01], 'summary_notifier': True },
    ] } }
    hass.states.async_set("sensor.a", "off")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('persistent_notification', 't40.*turned on')
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # reminder should happen after 0.9 secs more of sleeping + 1 sec bufer time
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't40.*on for ')

    # Ack and so no notification.
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    await asyncio.sleep(2)
    assert service_calls.isEmpty()

    # it's been a while since last notify, so unack'ing should result in immediate notify
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't40.*on for ')

    # and also future reminders
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 't40.*on for ')
    
    # Now turn off
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t40'})
    await hass.async_block_till_done()
    await setAndWait(hass, 'sensor.a', 'off')
    assert service_calls.isEmpty()

    # First two should notify fine
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 't41')
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
    await hass.async_block_till_done()
    service_calls.popNotifyEmpty('persistent_notification', 'Throttling started.*t41')

    # Now should have notification built up
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # Ack erases the unotififed firing (fires_since_last_notify).  and unack does not restore it
    await hass.services.async_call('alert2', 'ack', {'entity_id': 'alert2.test_t41'})
    await hass.async_block_till_done()
    await hass.services.async_call('alert2', 'unack', {'entity_id': 'alert2.test_t41'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await asyncio.sleep(2)
    service_calls.popNotifyEmpty('persistent_notification', 'Throttling ending.*t41.*Did not fire')

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
        { 'domain': 'test', 'name': 't53c', 'condition': 'sensor.a', 'reminder_frequency_mins': 0.01 },
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

    t53c = gad.alerts['test']['t53c']
    assert t53c.notification_control == a2Entities.NOTIFICATIONS_ENABLED

    # Snoozed so no notification
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert isinstance(t53c.notification_control, rawdt.datetime)
    await setAndWait(hass, 'sensor.a', 'on')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    # snooze expires, get reminder notification summary
    await asyncio.sleep(2)
    assert t53c.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    service_calls.popNotifySearch('persistent_notification', 't53c', 't53c.*fired 1x.*on for')
    service_calls.popNotifySearch('persistent_notification', 't53a', 't53a.*fired 1x.*on for')
    service_calls.popNotifyEmpty('persistent_notification', 't53b.*fired 1x.*on for')
    # Should still get reminders after snooze expires
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't53c', 't53c: on for')
    service_calls.popNotifySearch('persistent_notification', 't53a', 't53a: on for')
    service_calls.popNotifyEmpty('persistent_notification', 't53b: on for')
    # Set snooze again and turn off. No snooze summary (cuz acked?)
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    # No reminders cuz snooze is implicit ack
    await asyncio.sleep(2)
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
    # Snoozed so no notification
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53c', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53a', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.test_t53b', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'on')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # snooze expires, get summary notification
    await asyncio.sleep(2)
    service_calls.popNotifySearch('persistent_notification', 't53c', 't53c fired 1x')
    service_calls.popNotifyEmpty('foo', 't53b fired 1x')

    # Try events
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
    assert service_calls.isEmpty()
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54d'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54a'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54b'})
    await hass.services.async_call('alert2','report', {'domain':'test','name':'t54c'})
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
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
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't55a', 'condition': 'sensor.a',  },
        { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': 'sensor.g', 'condition': 'sensor.a',  },
        { 'domain': 'test', 'name': '{{ genElem }}z', 'generator_name': 'g3', 'generator': 'sensor.g3', 'condition': 'sensor.a',  },
    ] } }
    hass.states.async_set("sensor.a", "off")
    hass.states.async_set("sensor.g", "")
    hass.states.async_set("sensor.g3", "")
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    assert len(self.gad.generators) == 3

    # First generation happens
    assert len(gad.alerts['test']) == 1
    assert not 'tracked' in gad.alerts
    t55a = gad.alerts['test']['t55a']
    g1 = gad.generators['g1']
    assert g1.state == 1
    assert g1.entity_id == 'sensor.alert2generator_g1'
    assert hass.states.get(g1.entity_id)
    assert service_calls.isEmpty()

    # And suppose generator is a template and produces an error.  should not change generated alerts.
    #
    # So first generate an alert
    await setAndWait(hass, "sensor.g", "t55b")
    assert len(gad.alerts['test']) == 2
    t55b = gad.alerts['test']['t55b']
    g2 = gad.generators['g2']
    assert g2.state == 1
    assert g2.entity_id == 'sensor.alert2generator_g2'
    assert hass.states.get(g2.entity_id)
    assert service_calls.isEmpty()
    # and now have generator produce a mess
    await setAndWait(hass, "sensor.g", "[ 'a")
    service_calls.popNotifyEmpty('persistent_notification', 'generator_g2 generator template threw error: unexpected end')
    assert gad.alerts['test']['t55b'] == t55b
    assert hass.states.get(t55b.entity_id)
    assert g2.state == 1

    # template producing same string should not recreate alert
    await setAndWait(hass, "sensor.g", "['t55b']")
    assert service_calls.isEmpty()
    assert g2.state == 1
    assert gad.alerts['test']['t55b'] == t55b
    
    # Now suppose template returns nothing, so alert should disappear
    await setAndWait(hass, "sensor.g", "")
    assert service_calls.isEmpty()
    assert not hass.states.get(t55b.entity_id)
    assert g2.state == 0
    assert not 't55b' in gad.alerts['test']
    
    # what if name includes a trailing z in template
    assert not 't56' in gad.alerts['test']
    assert not 't56z' in gad.alerts['test']
    await setAndWait(hass, "sensor.g3", "t56")
    assert service_calls.isEmpty()
    assert not 't56' in gad.alerts['test']
    # let first generation happen
    t56z = gad.alerts['test']['t56z']
    g3 = self.gad.generators['g3']
    assert g3.state == 1
    # Now suppose a second alert appears
    await setAndWait(hass, "sensor.g3", "['t56','t57']")
    assert service_calls.isEmpty()
    assert g3.state == 2
    t57z = self.gad.alerts['test']['t57z']
    assert hass.states.get(t57z.entity_id)
    # And one disappears
    await setAndWait(hass, "sensor.g3", "['t57']")
    assert service_calls.isEmpty()
    assert g3.state == 1
    assert not 't56z' in gad.alerts['test']
    assert 't57z' in gad.alerts['test']
    assert not hass.states.get(t56z.entity_id)
    assert hass.states.get(t57z.entity_id)
    # Now suppose template returns nothing, so alert should disappear
    await setAndWait(hass, "sensor.g3", "[]")
    assert service_calls.isEmpty()
    assert g3.state == 0
    assert not 't56z' in gad.alerts['test']
    assert not 't57z' in gad.alerts['test']
    assert not hass.states.get(t56z.entity_id)
    assert not hass.states.get(t57z.entity_id)
