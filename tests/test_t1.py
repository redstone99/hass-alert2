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

    
