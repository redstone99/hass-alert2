#!/usr/bin/python3
#
# run from repository root directory
#
# JTESTDIR=/home/redstone/home-monitoring/homeassistant  ~/tmp/general-env/bin/python3 tests/t1.py Foo.test_ack
# 

import inspect
import sys
import os.path
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
if os.environ.get('JTESTDIR'):
    sys.path.append(os.environ['JTESTDIR']) # parent dir of custom_components
else:
    sys.path.insert(0, parentdir)
#sys.path.append(currentdir)

from testlib import *
from testlib import _LOGGER


class Foo(unittest.IsolatedAsyncioTestCase, TestHelper):
    
    def tearDown(self):
        #self.gad.shutdown()
        pass
    async def test_badarg1(self):
        cfg = { 'alert2' : {
            'defaults' : {
                'notifierz' : 'foobar'
            },
        } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        nn.assert_awaited_once()
        self.assertIsNotNone(re.search('defaults section.*extra keys', nn.await_args_list[0].args[0].data['message']))

        
    async def test_ack(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't1', 'condition': '{{ false }}' },
        ], } }
        await self.initCase(cfg)
        t1 = self.gad.alerts['test']['t1']
        nn = self.hass.servHandlers['notify.persistent_notification']

        self.assertEqual(t1.async_write_ha_state.call_count, 0)
        
        # First let's try condition on then off
        doConditionUpdate(t1, True)
        self.assertEqual(t1.state, 'on')
        self.assertEqual(t1.async_write_ha_state.call_count, 1)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t1.*turned on')
        # turning it on again should have no effect
        doConditionUpdate(t1, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertEqual(t1.async_write_ha_state.call_count, 1)
        # turn off
        doConditionUpdate(t1, False)
        self.assertEqual(t1.state, 'off')
        self.assertEqual(t1.async_write_ha_state.call_count, 2)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t1.*turned off')
        await asyncio.sleep(0.05)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)  # should be nothing left waiting
        # turn off again shouldn't change anything
        doConditionUpdate(t1, False)
        await asyncio.sleep(0.05)
        self.assertEqual(t1.async_write_ha_state.call_count, 2)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)  # should be nothing left waiting
        self.assertEqual(len(nn.await_args_list), 2)

        
        # Now let's try condition on, ack, off
        doConditionUpdate(t1, True)
        self.assertEqual(t1.async_write_ha_state.call_count, 3)
        await t1.async_ack()
        self.assertEqual(t1.async_write_ha_state.call_count, 4)
        doConditionUpdate(t1, False)
        self.assertEqual(t1.async_write_ha_state.call_count, 5)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t1.*turned on')

        # and let's try ack_all
        doConditionUpdate(t1, True)
        self.assertEqual(t1.async_write_ha_state.call_count, 6)
        await self.hass.services.async_call('alert2','ack_all', {})
        self.assertEqual(t1.async_write_ha_state.call_count, 7)
        doConditionUpdate(t1, False)
        self.assertEqual(t1.async_write_ha_state.call_count, 8)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'test_t1.*turned on')
        
    async def test_badtemplate(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't2a', 'condition': '{{ false }}' },
            { 'domain': 'test', 'name': 't2b', 'condition': '{{ false }}', 'trigger': 'zzz' },
        ], 'tracked': [ { 'domain': 'test', 'name': 't2c' } ] } }
        await self.initCase(cfg)
        nn = self.hass.servHandlers['notify.persistent_notification']
        t2a = self.gad.alerts['test']['t2a']
        t2b = self.gad.tracked['test']['t2b']
        perCount = 0
        self.assertEqual(len(nn.await_args_list), perCount)

        await asyncio.sleep(0.1)  # so startWatching is called
        self.assertEqual(len(nn.await_args_list), perCount)
        
        doConditionUpdate(t2a, '{{ foo')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2a.*unexpected end of template')
        doConditionUpdate(t2a, 'happy')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2a.*happy.*not truthy')
        doConditionUpdate(t2a, '{{ none }}')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2a.*None.*not truthy')

        setCondition(t2b, '{{ foo')
        await t2b.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2b.*unexpected end of template')
        setCondition(t2b, 'happy')
        await t2b.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2b.*happy.*not truthy')
        setCondition(t2b, '{{ none }}')
        await t2b.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2b.*None.*not truthy')

        
        
    async def test_reminder(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't2', 'condition': '{{ true }}', 'reminder_frequency_mins': [0.01, 0.05] },
            { 'domain': 'test', 'name': 't5', 'condition': '{{ false }}' },
        ], } }
        await self.initCase(cfg)

        # And how about a reminder, checking successive values. so should only see two reminders, not more
        t2 = self.gad.alerts['test']['t2']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        #doConditionUpdate(t2, True). Since condition is true at startup, startWatching will trigger it
        await asyncio.sleep(0.1)
        self.assertEqual(t2.async_write_ha_state.call_count, 1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2.*turned on')
        await asyncio.sleep(1.7) # reminder interval is 1 + specified interval
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2.*on for')
        await asyncio.sleep(2)  # not enough
        self.assertEqual(len(nn.await_args_list), perCount)
        await asyncio.sleep(2)  # enough for 2nd reminder
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2.*on for')
        self.assertEqual(t2.async_write_ha_state.call_count, 3) # even though no notify, still record last fire time
        doConditionUpdate(t2, False)
        self.assertEqual(t2.async_write_ha_state.call_count, 4)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2.*turned off')

        # And what about if ack'd before reminder time.  Should only see turn-on notification
        self.assertEqual(t2.async_write_ha_state.call_count, 4)
        doConditionUpdate(t2, True)
        self.assertEqual(t2.async_write_ha_state.call_count, 5)
        await t2.async_ack()
        self.assertEqual(t2.async_write_ha_state.call_count, 6)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        self.assertEqual(t2.async_write_ha_state.call_count, 6)
        doConditionUpdate(t2, False)
        self.assertEqual(t2.async_write_ha_state.call_count, 7)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(t2.async_write_ha_state.call_count, 7)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t2.*turned on')

        # and default remimder time is long, so no reminders
        t5 = self.gad.alerts['test']['t5']
        doConditionUpdate(t5, True)
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t5.*turned on')
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        self.assertEqual(len(nn.await_args_list), perCount)
        doConditionUpdate(t5, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'test_t5.*turned off')

        
    async def test_reminder2(self):
        # Check that default value of reminder is overridden and is used
        cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 10 },
                             'alerts' : [
            { 'domain': 'test', 'name': 't3', 'condition': '{{ false }}', 'reminder_frequency_mins': [0.01, 0.05] },
            { 'domain': 'test', 'name': 't4', 'condition': '{{ false }}' },
        ], } }
        await self.initCase(cfg)
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0

        t3 = self.gad.alerts['test']['t3']
        doConditionUpdate(t3, True)
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t3.*turned on')
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t3.*on for')
        doConditionUpdate(t3, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t3.*turned off')

        t4 = self.gad.alerts['test']['t4']
        doConditionUpdate(t4, True)
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t4.*turned on')
        doConditionUpdate(t4, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t4.*turned off')

    async def test_reminder3(self):
        # Check that default value of reminder is used
        cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 },
                             'alerts' : [
            { 'domain': 'test', 'name': 't6', 'condition': '{{ false }}' },
        ], } }
        await self.initCase(cfg)
        t6 = self.gad.alerts['test']['t6']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0

        doConditionUpdate(t6, True)
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t6.*turned on')
        await asyncio.sleep(2) # reminder interval is 1 + specified interval
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t6.*on for')
        doConditionUpdate(t6, False)
        await asyncio.sleep(1.2) # Wait for remainder 
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t6.*turned off')

    async def test_notifiers1(self):
        cfg = { 'alert2' : { 'alerts' : [
            # notifier available immediately
            { 'domain': 'test', 'name': 't7', 'condition': '{{ false }}', 'notifier': 'persistent_notification' },
            # notifier available in grace period
            { 'domain': 'test', 'name': 't7a', 'condition': '{{ false }}', 'notifier': 'foo' },
            # notifier available after grace period
            { 'domain': 'test', 'name': 't7b', 'condition': '{{ false }}', 'notifier': 'foo2' },
        ], } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        t7 = self.gad.alerts['test']['t7']
        t7a = self.gad.alerts['test']['t7a']
        t7b = self.gad.alerts['test']['t7b']
        #self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
        
        #####
        # initial startup
        doConditionUpdate(t7, True)
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t7: turned on')
        doConditionUpdate(t7a, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        doConditionUpdate(t7a, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        doConditionUpdate(t7b, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)

        ####
        # Now notifier foo becomes available, so we get the notification
        self.hass.servHandlers['notify.foo'] = AsyncMock(name='foo', spec_set=[])
        nfoo = self.hass.servHandlers['notify.foo']
        fooCount = 0
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        kStartupWaitPollSecs = alert2.kNotifierStartupGraceSecs / alert2.kStartupWaitPollFactor
        await asyncio.sleep(1.2 * kStartupWaitPollSecs)
        fooCount += 2
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(nfoo.await_args_list[fooCount-2].args[0].data['message'], 'Alert2 test_t7a: turned on')
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], 'Alert2 test_t7a: turned off')
        
        ###
        # Now let the rest of the grace period interval elapse. Should get errors finally
        # ( we already waited some, so waiting the full kNotifierInitGraceSecs should be adequate )
        await asyncio.sleep(alert2.kNotifierStartupGraceSecs)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'notifiers are not known.*\'foo2\'')
        self.assertNotRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'malformed list')
        
        # TODO - what about the los test_t7b notification?

        #and test now new notifications now that we are out of the grace period
        doConditionUpdate(t7, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t7: turned off')
        doConditionUpdate(t7a, True)
        await asyncio.sleep(0.05)
        fooCount += 1
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], 'Alert2 test_t7a: turned on')
        doConditionUpdate(t7b, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t7b.*notifier "foo2" is not known.*with message=.*turned off')
        self.assertNotRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'malformed list')

        # And now register foo2
        self.hass.servHandlers['notify.foo2'] = AsyncMock(name='foo2', spec_set=[])
        nfoo2 = self.hass.servHandlers['notify.foo2']
        self.assertEqual(len(nfoo2.await_args_list), 0)
        doConditionUpdate(t7b, True)
        await asyncio.sleep(0.05)
        self.assertEqual(nfoo2.await_args_list[0].args[0].data['message'], 'Alert2 test_t7b: turned on')
        doConditionUpdate(t7a, False)
        doConditionUpdate(t7b, False)
        await asyncio.sleep(0.05)

        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)

        
    async def test_notifiers2(self):
        cfg = { 'alert2' : { 'alerts' : [
            # some combos
            # foo available soon after startup.  Foo2 not available till later
            { 'domain': 'test', 'name': 't7c', 'condition': '{{ false }}', 'notifier': ['persistent_notification', 'foo'] },
            { 'domain': 'test', 'name': 't7d', 'condition': '{{ false }}', 'notifier': ['foo', 'persistent_notification'] },
            { 'domain': 'test', 'name': 't7e', 'condition': '{{ false }}', 'notifier': ['foo', 'foo2'] },
            { 'domain': 'test', 'name': 't7f', 'condition': '{{ false }}', 'notifier': ['foo2', 'persistent_notification'] },
        ], } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        t7c = self.gad.alerts['test']['t7c']
        t7d = self.gad.alerts['test']['t7d']
        t7e = self.gad.alerts['test']['t7e']
        t7f = self.gad.alerts['test']['t7f']
        nn = self.hass.servHandlers['notify.persistent_notification']

        # only persistent one exists.
        doConditionUpdate(t7c, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertEqual(nn.await_args_list[0].args[0].data['message'], 'Alert2 test_t7c: turned on')
        doConditionUpdate(t7d, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertEqual(nn.await_args_list[1].args[0].data['message'], 'Alert2 test_t7d: turned on')
        doConditionUpdate(t7e, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 2)
        doConditionUpdate(t7f, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t7f: turned on')

        # Now foo comes around
        self.hass.servHandlers['notify.foo'] = AsyncMock(name='foo', spec_set=[])
        nfoo = self.hass.servHandlers['notify.foo']
        self.assertEqual(len(nfoo.await_args_list), 0)
        kStartupWaitPollSecs = alert2.kNotifierStartupGraceSecs / alert2.kStartupWaitPollFactor
        await asyncio.sleep(1.2 * kStartupWaitPollSecs)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertEqual(len(nfoo.await_args_list), 3)
        self.assertEqual(nfoo.await_args_list[0].args[0].data['message'], 'Alert2 test_t7c: turned on')
        self.assertRegex(nfoo.await_args_list[1].args[0].data['message'], 'Alert2 test_t7d: turned on')
        self.assertRegex(nfoo.await_args_list[2].args[0].data['message'], 'Alert2 test_t7e: turned on')

        # Now let rest of startup grace period elapse.
        await asyncio.sleep(alert2.kNotifierStartupGraceSecs)
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertEqual(len(nfoo.await_args_list), 3)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'notifiers are not known.*\'foo2\'')

        doConditionUpdate(t7c, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertEqual(len(nfoo.await_args_list), 4)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'Alert2 test_t7c: turned off')
        self.assertRegex(nfoo.await_args_list[3].args[0].data['message'], 'Alert2 test_t7c: turned off')
        doConditionUpdate(t7d, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 6)
        self.assertEqual(len(nfoo.await_args_list), 5)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'Alert2 test_t7d: turned off')
        self.assertRegex(nfoo.await_args_list[4].args[0].data['message'], 'Alert2 test_t7d: turned off')
        doConditionUpdate(t7e, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertEqual(len(nfoo.await_args_list), 6)
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], '"foo2".*is not known.*message=.*t7e.*turned off')
        self.assertRegex(nfoo.await_args_list[5].args[0].data['message'], 'Alert2 test_t7e: turned off')
        doConditionUpdate(t7f, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 9)
        self.assertEqual(len(nfoo.await_args_list), 6)
        self.assertRegex(nn.await_args_list[7].args[0].data['message'], 'Alert2 test_t7f: turned off')
        self.assertRegex(nn.await_args_list[8].args[0].data['message'], '"foo2".*is not known.*message=.*turned off')
        
        # Now register foo2
        self.hass.servHandlers['notify.foo2'] = AsyncMock(name='foo2', spec_set=[])
        nfoo2 = self.hass.servHandlers['notify.foo2']
        self.assertEqual(len(nfoo2.await_args_list), 0)
        doConditionUpdate(t7e, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nfoo.await_args_list), 7)
        self.assertEqual(len(nfoo2.await_args_list), 1)
        self.assertRegex(nfoo.await_args_list[6].args[0].data['message'], 'Alert2 test_t7e: turned on')
        self.assertRegex(nfoo2.await_args_list[0].args[0].data['message'], 'Alert2 test_t7e: turned on')
        
        doConditionUpdate(t7e, False)
        await asyncio.sleep(0.05)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)

    async def test_notifiers3(self):
        # Check if default notifier is bad
        cfg = { 'alert2' : { 'defaults': { 'notifier': 'foo2' }, 'alerts' : [
            { 'domain': 'test', 'name': 't8a', 'condition': '{{ false }}', 'notifier': 'foo' },
        ], } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        t8a = self.gad.alerts['test']['t8a']
        nn = self.hass.servHandlers['notify.persistent_notification']

        # notification deferred
        doConditionUpdate(t8a, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 0)

        # Wait for end of startup period. Error reported, but since foo2 doesn't exist, it falls
        # back to persistent one
        await asyncio.sleep(alert2.kNotifierStartupGraceSecs + 0.3)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'notifiers are not known.*\'foo\'.*"foo2" is not known')

        # And now if new instance:
        doConditionUpdate(t8a, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], '\"foo\" is not known.*turned off.*"foo2" is not known')
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
        
    async def test_notifiers4(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'defaults': { 'notifier': 'foo' }, 'alerts' : [
            { 'domain': 'test', 'name': 't8', 'condition': '{{ false }}' },
        ], } }
        await self.initCase(cfg)
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        tal = self.gad.alerts['test']['t8']
        
        doConditionUpdate(tal, True)
        doConditionUpdate(tal, False)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 0)
        nn2 = self.hass.servHandlers['notify.foo']
        self.assertEqual(len(nn2.await_args_list), 2) # start + stop
        self.assertRegex(nn2.await_args_list[0].args[0].data['message'], 'test_t8.*turned on')
        self.assertRegex(nn2.await_args_list[1].args[0].data['message'], 'test_t8.*turned off')

    async def test_notifiers5(self):
        # Check template notifier formats
        cfg = { 'alert2' : { 'alerts' : [
            # notifier can be list.
            # otherwise, jinja2 eval it
            # need to strip()
            # ast.eval_literal
            # if fails, consider a single notifier name (or entity name?)
            #
            # if notifier is single string, it either is name of notifier, or something that evaluates with json.loads
            # First singleton notifiers
            { 'domain': 'test', 'name': 't9a', 'condition': '{{ false }}', 'notifier': 'foo' },
            { 'domain': 'test', 'name': 't9b', 'condition': '{{ false }}', 'notifier': 'sensor.testent' },
            { 'domain': 'test', 'name': 't9b2', 'condition': '{{ false }}', 'notifier': 'sensor.multient' },
            { 'domain': 'test', 'name': 't9c', 'condition': '{{ false }}', 'notifier': '"foo"' },
            { 'domain': 'test', 'name': 't9d', 'condition': '{{ false }}', 'notifier': '\'foo\'' },
            { 'domain': 'test', 'name': 't9e', 'condition': '{{ false }}', 'notifier': '[ "foo" ]' },
            { 'domain': 'test', 'name': 't9f', 'condition': '{{ false }}', 'notifier': '[ \'foo\' ]' },
            
            { 'domain': 'test', 'name': 't9g', 'condition': '{{ false }}', 'notifier': '{{ \'foo\' }}' },
            { 'domain': 'test', 'name': 't9h', 'condition': '{{ false }}', 'notifier': '{{ "foo" }}' },

            { 'domain': 'test', 'name': 't9i', 'condition': '{{ false }}', 'notifier': '{{ ["foo"] }}' },
            { 'domain': 'test', 'name': 't9j', 'condition': '{{ false }}', 'notifier': '{{ [\'foo\'] }}' },

            { 'domain': 'test', 'name': 't9k', 'condition': '{{ false }}', 'notifier': '{{ "a" if false else "foo" }}' },
            { 'domain': 'test', 'name': 't9l', 'condition': '{{ false }}', 'notifier': '{{ "a" if false else "sensor.testent" }}' },

            { 'domain': 'test', 'name': 't9m', 'condition': '{{ false }}', 'notifier': '{% if true %}foo{% endif %}' },
            { 'domain': 'test', 'name': 't9n', 'condition': '{{ false }}', 'notifier': '{% if true %}{{ ["foo"]}}{% endif %}' },

            # And let's test some error cases
            # notifier evals to something other than string
            { 'domain': 'test', 'name': 't9p', 'condition': '{{ false }}', 'notifier': '3' },
            { 'domain': 'test', 'name': 't9q', 'condition': '{{ false }}', 'notifier': '{ "a": 4 }' },
            { 'domain': 'test', 'name': 't9r', 'condition': '{{ false }}', 'notifier': '[ 4 ]' },
            { 'domain': 'test', 'name': 't9s', 'condition': '{{ false }}', 'notifier': '{{ "foo"' },
            { 'domain': 'test', 'name': 't9t', 'condition': '{{ false }}', 'notifier': '{{ ["foo", 5] }}' },
            { 'domain': 'test', 'name': 't9u', 'condition': '{{ false }}', 'notifier': '{% if true %}{% endif %}' },
            { 'domain': 'test', 'name': 't9v', 'condition': '{{ false }}', 'notifier': 'sensor.unavailEnt2' },
            
            { 'domain': 'test', 'name': 't9w', 'condition': '{{ false }}', 'notifier': '{{ ["foo", "bar"] }}' },
            { 'domain': 'test', 'name': 't9x', 'condition': '{{ false }}', 'notifier': 'sensor.unavailEnt' },
            { 'domain': 'test', 'name': 't9x1', 'condition': '{{ false }}', 'notifier': '[ foo ]' },
            { 'domain': 'test', 'name': 't9y', 'condition': '{{ false }}', 'notifier': '[ "foo" ' },

            # we don't support ent in a list
            { 'domain': 'test', 'name': 't9z', 'condition': '{{ false }}', 'notifier': '{{ ["sensor.testent"] }}' },

        ], } }
        oldStSecs = alert2.kNotifierStartupGraceSecs
        alert2.kNotifierStartupGraceSecs += 2  # Need more for this slow test to avoid startup ending too early
        resetModuleLoadTime()
        await self.initCase(cfg)
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        self.hass.states.set('sensor.testent', SimpleNamespace(state='foo'))
        #self.hass.states['sensor.multient'] = SimpleNamespace(state='[ foo, persistent_notification ]')
        self.hass.states.set('sensor.multient', SimpleNamespace(state='[ "foo", "persistent_notification" ]'))
        self.hass.states.set('sensor.unavailEnt', SimpleNamespace(state='unavailable'))
        self.hass.states.set('sensor.unavailEnt2', SimpleNamespace(state=None))
        nn = self.hass.servHandlers['notify.persistent_notification']
        nfoo = self.hass.servHandlers['notify.foo']
        self.assertEqual(len(nn.await_args_list), 0)
        self.assertEqual(len(nfoo.await_args_list), 0)

        perCount = 0
        fooCount = 0
        async def doTst(tname, perBump, fooBump, onVal=True):
            alertEnt = self.gad.alerts['test'][tname]
            doConditionUpdate(alertEnt, onVal)
            await asyncio.sleep(0.05)
            nonlocal perCount
            nonlocal fooCount
            perCount += perBump
            fooCount += fooBump
            _LOGGER.warning(f'testing tname={tname} perCount={perCount}')
            self.assertEqual(len(nn.await_args_list), perCount)
            self.assertEqual(len(nfoo.await_args_list), fooCount)
        
        for tname in [ 't9a', 't9b', 't9c', 't9d', 't9e', 't9f', 't9g', 't9h', 't9i', 't9j', 't9k', 't9l', 't9m', 't9n' ]:
            #print(f'tname = {tname}')
            await doTst(tname, 0, 1)
            self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_{tname}.*turned on')
            await doTst(tname, 0, 1, onVal = False)
            self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_{tname}.*turned off')

        await doTst('t9b2', 1, 1)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_t9b2.*turned on')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9b2.*turned on')
        await doTst('t9b2', 1, 1, onVal = False)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_t9b2.*turned off')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9b2.*turned off')

        for tname in ['t9p', 't9q', 't9r' ]:
            await doTst(tname, 1, 0)
            self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_{tname}.*not a string')
        await doTst('t9s', 1, 0)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9s.*unexpected end of template')
        await doTst('t9t', 1, 1)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9t.*not a string')
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_t9t.*turned on')
        await doTst('t9u', 1, 0)
        # TODO - would be nice if the error message included the template for context
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9u.*cannot be the empty string')
        await doTst('t9v', 1, 0)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9v.*notifier is not a string.*NoneType')

        # Next set of tests use the startup grace period
        await doTst('t9w', 0, 1)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_t9w.*turned on')
        for tname in ['t9x', 't9y', 't9z', 't9x1' ]:
            await doTst(tname, 0, 0)

        t9v = self.gad.alerts['test']['t9v']
        t9w = self.gad.alerts['test']['t9w']
        t9x = self.gad.alerts['test']['t9x']
        t9y = self.gad.alerts['test']['t9y']
        t9z = self.gad.alerts['test']['t9z']
        
        self.hass.services.async_register('notify','bar', AsyncMock(name='bar', spec_set=[]))
        nbar = self.hass.servHandlers['notify.bar']
        kStartupWaitPollSecs = alert2.kNotifierStartupGraceSecs / alert2.kStartupWaitPollFactor
        await asyncio.sleep(1.2 * kStartupWaitPollSecs)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        await doTst('t9w', 0, 1, onVal=False)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], f'test_t9w.*turned off')
        self.assertEqual(len(nbar.await_args_list), 2)
        self.assertRegex(nbar.await_args_list[1].args[0].data['message'], f'test_t9w.*turned off')
        
        # Wait rest of startup grace period
        await asyncio.sleep(alert2.kNotifierStartupGraceSecs + 0.3)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertEqual(len(nbar.await_args_list), 2)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'not known to HA.*\'unavailable\'.*\'\\[ "foo"\', \'sensor.testent\'.*\\[ foo \\].*malformed list')

        await doTst('t9x', 1, 0, False)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9x.*unavailable" is not known.*sensor.unavailEnt')
        await doTst('t9x1', 1, 0, False)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_t9x1.*is not known.*malformed list')

        # We leave lots of alerts on, so kill them
        #self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
        alert2.kNotifierStartupGraceSecs = oldStSecs
        
    async def test_throttle(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'defaults': { }, 'alerts' : [
            { 'domain': 'test', 'name': 't9', 'condition': '{{ false }}', 'throttle_fires_per_mins': [2, 0.05], 'reminder_frequency_mins':0.01 },
            { 'domain': 'test', 'name': 't9a', 'condition': '{{ false }}', 'throttle_fires_per_mins': [2, 0.05], 'reminder_frequency_mins':0.01, 'summary_notifier': True },
        ], } }
        await self.initCase(cfg)
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        t9 = self.gad.alerts['test']['t9']
        t9a = self.gad.alerts['test']['t9a']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        #await self.waitForAllBut(self.oldTasks) # wait for delayed notifier thingy to expire

        for summaryEnabled in [ True, False ]:
            tal   =  t9a  if summaryEnabled else  t9
            tname = 't9a' if summaryEnabled else 't9'
            for onAtEnd in [ False, True ]:
                for extraFire in [ False, True ]:
                    _LOGGER.info(f'loop: summaryEnabled={summaryEnabled} onAtEnd={onAtEnd} extraFire={extraFire}')
                    # 2 fires are fine
                    doConditionUpdate(tal, True)
                    doConditionUpdate(tal, False)
                    doConditionUpdate(tal, True)
                    doConditionUpdate(tal, False)
                    await asyncio.sleep(0.1)
                    perCount += 4
                    self.assertEqual(len(nn.await_args_list), perCount)
                    self.assertRegex(nn.await_args_list[perCount-4].args[0].data['message'], f'test_{tname}.*turned on')
                    self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], f'test_{tname}.*turned off')
                    self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], f'test_{tname}.*turned on')
                    self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_{tname}.*turned off')

                    # 3rd fire should have throttle sign and no turn off or reminders
                    doConditionUpdate(tal, True)
                    await asyncio.sleep(0.05)
                    perCount += 1
                    self.assertEqual(len(nn.await_args_list), perCount)
                    self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling started.*test_{tname}.*turned on')
                    # no reminders
                    await asyncio.sleep(2)
                    self.assertEqual(len(nn.await_args_list), perCount)

                    if extraFire:
                        doConditionUpdate(tal, False)
                        doConditionUpdate(tal, True)
                    if not onAtEnd:
                        doConditionUpdate(tal, False)
                    await asyncio.sleep(0.1)
                    self.assertEqual(len(nn.await_args_list), perCount)
                    
                    await asyncio.sleep(2)
                    # throttle window done.
                    if summaryEnabled:
                        perCount += 1
                        self.assertEqual(len(nn.await_args_list), perCount)
                        if onAtEnd:
                            if extraFire:
                                self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling ending] Alert2 test_{tname} fired 1x.*: on for 2 s$')
                            else:
                                self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling ending] Alert2 test_{tname}: on for 4 s$')
                        else:
                            self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling ending] Summary.*test_{tname}.*turned off.*after being on')
                    else:
                        if onAtEnd:
                            perCount += 1
                            self.assertEqual(len(nn.await_args_list), perCount)
                            if extraFire:
                                self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling ending] Alert2 test_{tname} fired 1x.*on for 2 s$')
                            else:
                                self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling ending] Alert2 test_{tname}: on for 4 s$')
                        else:
                            self.assertEqual(len(nn.await_args_list), perCount)

                    if onAtEnd:
                        doConditionUpdate(tal, False)
                        await asyncio.sleep(0.05)
                        perCount += 1
                        self.assertEqual(len(nn.await_args_list), perCount)
                        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'test_{tname}.*turned off')
                    self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
        
    async def test_annotate(self):
        cfg = { 'alert2' : { 'defaults': { 'reminder_frequency_mins': 0.01 },  'alerts' : [
            { 'domain': 'test', 'name': 't10', 'condition': '{{ false }}' },
            { 'domain': 'test', 'name': 't11', 'condition': '{{ false }}', 'message': 'ick-t11' },
            { 'domain': 'test', 'name': 't12', 'condition': '{{ false }}', 'message': 'ick-t12', 'done_message': 'ick-t12 done' },
            { 'domain': 'test', 'name': 't13', 'condition': '{{ false }}', 'message': 'ick-t13', 'annotate_messages': False },
            { 'domain': 'test', 'name': 't14', 'condition': '{{ false }}', 'message': 'ick-t14', 'annotate_messages': False, 'done_message': 'ick-t14 done' },
            { 'domain': 'test', 'name': 't15', 'condition': '{{ false }}', 'friendly_name': 'friend_t15' },
            { 'domain': 'test', 'name': 't16', 'condition': '{{ false }}', 'message': 'ick-t16', 'annotate_messages': False, 'friendly_name': 'friend_t16' },
        ], 'tracked': [ { 'domain': 'test', 'name': 't16a' } ] } }
        await self.initCase(cfg)
        t10 = self.gad.alerts['test']['t10']
        t11 = self.gad.alerts['test']['t11']
        t12 = self.gad.alerts['test']['t12']
        t13 = self.gad.alerts['test']['t13']
        t14 = self.gad.alerts['test']['t14']
        t15 = self.gad.alerts['test']['t15']
        t16 = self.gad.alerts['test']['t16']
        t16a = self.gad.tracked['test']['t16a']
        allt = [ t10, t11, t12, t13, t14, t15, t16 ]
        FakeConst.MAJOR_VERSION = 2024
        FakeConst.MINOR_VERSION = 9
        for at in allt:
            doConditionUpdate(at, True)
            await asyncio.sleep(0.05) # so reminders are ordered
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertEqual(nn.await_args_list[0].args[0].data['message'], '{% raw %}Alert2 test_t10: turned on{% endraw %}')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Alert2 test_t11: ick-t11')
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t12: ick-t12')
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'ick-t13')
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'ick-t14')
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'friend_t15: turned on')
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'ick-t16')

        # reminders
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), 14)
        self.assertRegex(nn.await_args_list[7].args[0].data['message'], 'Alert2 test_t10: on for')
        self.assertRegex(nn.await_args_list[8].args[0].data['message'], 'Alert2 test_t11: on for')
        self.assertRegex(nn.await_args_list[9].args[0].data['message'], 'Alert2 test_t12: on for')
        self.assertRegex(nn.await_args_list[10].args[0].data['message'], 'Alert2 test_t13: on for')
        self.assertRegex(nn.await_args_list[11].args[0].data['message'], 'Alert2 test_t14: on for')
        self.assertRegex(nn.await_args_list[12].args[0].data['message'], 'friend_t15: on for')
        self.assertRegex(nn.await_args_list[13].args[0].data['message'], 'friend_t16: on for')
        
        for at in allt:
            doConditionUpdate(at, False)
            await asyncio.sleep(0.05) # so offs are ordered
        await asyncio.sleep(1.2)  # Wait for startup delaymgr to expire
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
        self.assertEqual(len(nn.await_args_list), 21)

        self.assertRegex(nn.await_args_list[14].args[0].data['message'], 'Alert2 test_t10: turned off after')
        self.assertRegex(nn.await_args_list[15].args[0].data['message'], 'Alert2 test_t11: turned off after')
        self.assertRegex(nn.await_args_list[16].args[0].data['message'], 'Alert2 test_t12: ick-t12 done{% endraw')
        self.assertRegex(nn.await_args_list[17].args[0].data['message'], 'turned off after')
        self.assertRegex(nn.await_args_list[18].args[0].data['message'], 'ick-t14 done')
        self.assertRegex(nn.await_args_list[19].args[0].data['message'], 'friend_t15: turned off after')
        self.assertRegex(nn.await_args_list[20].args[0].data['message'], 'turned off after')

        # As of 2024.10, HA no longer does template interpretation of message arg to notify
        FakeConst.MAJOR_VERSION = 2024
        FakeConst.MINOR_VERSION = 9
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm1'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 22)
        self.assertEqual(nn.await_args_list[21].args[0].data['message'], '{% raw %}Alert2 test_t16a: m1{% endraw %}')
        FakeConst.MAJOR_VERSION = 2023
        FakeConst.MINOR_VERSION = 11
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm2'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 23)
        self.assertEqual(nn.await_args_list[22].args[0].data['message'], '{% raw %}Alert2 test_t16a: m2{% endraw %}')
        FakeConst.MAJOR_VERSION = 2024
        FakeConst.MINOR_VERSION = 10
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm3'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 24)
        self.assertEqual(nn.await_args_list[23].args[0].data['message'], 'Alert2 test_t16a: m3')
        FakeConst.MAJOR_VERSION = 2025
        FakeConst.MINOR_VERSION = 5
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t16a', 'message': 'm4'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 25)
        self.assertEqual(nn.await_args_list[24].args[0].data['message'], 'Alert2 test_t16a: m4')
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)

        
    async def test_delay_on(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't17', 'condition': '{{ false }}', 'delay_on_secs': 1, 'reminder_frequency_mins': 0.01 },
        ], } }
        await self.initCase(cfg)
        t17 = self.gad.alerts['test']['t17']
        t17a = self.gad.alerts['test']['t17']
        nn = self.hass.servHandlers['notify.persistent_notification']
        
        doConditionUpdate(t17, True)
        await asyncio.sleep(0.1)
        # alert should not have fired
        self.assertEqual(len(nn.await_args_list), 0)
        self.assertEqual(t17.state, 'off')

        # it should fire after 0.9 secs more of sleeping + 1 sec bufer time
        await asyncio.sleep(2)
        self.assertEqual(t17.state, 'on')
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'test_t17.*turned on')

        # reminder counts from when turned on, so should be 0.1s into reminder time of 0.6s
        # so sleeping a bit more shouldn't trigger reminder
        await asyncio.sleep(0.2)
        self.assertEqual(len(nn.await_args_list), 1)

        # Sleeping a bit more should now trigger it
        await asyncio.sleep(0.8)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'test_t17.*on for')
        
        doConditionUpdate(t17, False)
        self.assertEqual(t17.state, 'off')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'test_t17.*turned off')
        
    async def test_threshold(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't18', 'condition': '{{ "xxx" }}', 'threshold': { 'value': "{{ 'zzz' }}", 'hysteresis': 3, 'minimum': 0 } },
            { 'domain': 'test', 'name': 't19', 'condition': '{{ true }}', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'maximum': 10 } },
            { 'domain': 'test', 'name': 't20', 'condition': '{{ true }}', 'threshold': { 'value': "{{ zzz }}", 'hysteresis': 3, 'minimum': 0, 'maximum': 10 } },
        ], } }
        await self.initCase(cfg)
        t18 = self.gad.alerts['test']['t18']
        t19 = self.gad.alerts['test']['t19']
        t20 = self.gad.alerts['test']['t20']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        self.assertEqual(t18.state, 'off')
        self.assertEqual(t19.state, 'off')
        self.assertEqual(t20.state, 'off')

        await asyncio.sleep(0.1)
        await self.waitForAllBut(self.oldTasks)
        perCount += 3
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], 't18.*xxx.*truthy')
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 't19.*value template.*"" rather than a float')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't20.*value template.*"" rather than a float')
        self.assertEqual(t18.state, 'off')
        
        doConditionUpdate(t18, True)  # cond updating causes value to be evaluated, which returns zzz:
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'value template.*zzz.*rather than a float')
        self.assertEqual(t18.state, 'off')

        doConditionUpdate(t18, True)  # cond updating causes value to be evaluated, which returns zzz:
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'value template.*zzz.*rather than a float')
        self.assertEqual(t18.state, 'off')

        # condition updates can never fail - i.e., helpers.result_as_boolean never fails
        setValue(t18, '3')
        doConditionUpdate(t18, True)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')

        # Now try value update with false condition
        setCondition(t18, False)
        doValueUpdate(t18, 'zz2')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'template.*zz2.*rather than a float')
        self.assertEqual(t18.state, 'off')
        
        # Now try false, false in various combinations
        #
        setCondition(t18, False)
        doValueUpdate(t18, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '3')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, False, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')

        # Now try cond true, val false
        #
        setCondition(t18, True)
        doValueUpdate(t18, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '3')
        doConditionUpdate(t18, True)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, True, '3')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')

        # Now try false, True in various combinations
        #
        setCondition(t18, False)
        doValueUpdate(t18, '-1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '-1')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, False, '-1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'off')

        # Now try with both true
        setCondition(t18, True)
        doValueUpdate(t18, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        #
        setValue(t18, '-1')
        doConditionUpdate(t18, True)
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        #
        doCondValueUpdate(t18, True, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        
        # Now check hysteresis
        doCondValueUpdate(t18, True, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        # going positive but still less than 3
        doValueUpdate(t18, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'on')
        # 3 counts from 0, not -1
        doValueUpdate(t18, '2.5')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t18.state, 'on')
        # now turns off
        doValueUpdate(t18, '3')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')

        # Check turning off due to condition going false
        setValue(t18, '-2')
        doCondValueUpdate(t18, True, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned on')
        self.assertEqual(t18.state, 'on')
        doConditionUpdate(t18, False)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t18: turned off')
        self.assertEqual(t18.state, 'off')
        
        # Check max hysteresis
        doCondValueUpdate(t19, True, '9')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t19.state, 'off')
        doCondValueUpdate(t19, True, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t19.state, 'off')
        # turn on
        doCondValueUpdate(t19, True, '11')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t19: turned on')
        self.assertEqual(t19.state, 'on')
        doValueUpdate(t19, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t19.state, 'on')
        doValueUpdate(t19, '8')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t19.state, 'on')
        doValueUpdate(t19, '7')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t19: turned off')
        self.assertEqual(t19.state, 'off')
        
        # Check min,max hysteresis
        doCondValueUpdate(t20, True, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '11')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '8')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '7')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '0')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '2')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '3')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        # Check if turn off by going into hysteresis region of opposite side
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '9')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')
        # and in other direction
        doValueUpdate(t20, '11')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '1')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        # And test if jump from pole to pole
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned on')
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '9')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'on')
        doValueUpdate(t20, '5')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t20: turned off')
        self.assertEqual(t20.state, 'off')

        # No threshold tracking even when condition is false
        setCondition(t20, False)
        doValueUpdate(t20, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')
        doValueUpdate(t20, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')
        doConditionUpdate(t20, True)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')

        doCondValueUpdate(t20, False, '11')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')

        doCondValueUpdate(t20, False, '9')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')

        # condition true, we don't track hysteresis coming from above max, so no turn on
        doConditionUpdate(t20, True)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')

        # Lastly a temlate error
        doConditionUpdate(t20, '{{ zz')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'err')
        self.assertEqual(t20.state, 'off')

        doConditionUpdate(t20, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t20.state, 'off')
        
    async def test_threshold2(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't21',  'threshold': { 'value': "{{ 2 }}", 'hysteresis': 3, 'minimum': 0 } },
            { 'domain': 'test', 'name': 't21a', 'threshold': { 'value': "{{ 2.1 }}", 'hysteresis': 3, 'maximum': 10 }, 'delay_on_secs': 0.5 },
            { 'domain': 'test', 'name': 't21b', 'threshold': { 'value': "{{ 2.2 }}", 'hysteresis': 3, 'minimum': 0 }, 'delay_on_secs': 0.5 },
            { 'domain': 'test', 'name': 't21c', 'threshold': { 'value': "{{ 2.3 }}", 'hysteresis': 3, 'minimum':0, 'maximum': 10 }, 'delay_on_secs': 0.5 },
            { 'domain': 'test', 'name': 't21d', 'threshold': { 'value': "{{ -1 }}", 'hysteresis': 3, 'minimum':0 } },
        ], } }
        await self.initCase(cfg)
        t21 = self.gad.alerts['test']['t21']
        t21a = self.gad.alerts['test']['t21a']
        t21b = self.gad.alerts['test']['t21b']
        t21c = self.gad.alerts['test']['t21c']
        t21d = self.gad.alerts['test']['t21d']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        self.assertEqual(t21.state, 'off')
        self.assertEqual(t21a.state, 'off')

        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21d: turned on')
        doValueUpdate(t21d, '4')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21d: turned off')

        
        # Test hysteresis without a condition
        doValueUpdate(t21, '1')
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21.state, 'off')

        doValueUpdate(t21, '-1')
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21: turned on')
        self.assertEqual(t21.state, 'on')

        doValueUpdate(t21, '-1.1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21.state, 'on')
        
        doValueUpdate(t21, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21.state, 'on')

        doValueUpdate(t21, '3')
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21: turned off')
        self.assertEqual(t21.state, 'off')
        await self.waitForAllBut(self.oldTasks)

        # Test thresh with delay_on, so we get multiple updates while it's firing.
        doValueUpdate(t21a, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21a.state, 'off')
        doValueUpdate(t21a, '12')
        await asyncio.sleep(0.1)
        self.assertEqual(t21a.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        await asyncio.sleep(1)
        self.assertEqual(t21a.state, 'on')
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21a: turned on')
        doValueUpdate(t21a, '1')
        await asyncio.sleep(0.1)
        self.assertEqual(t21a.state, 'off')
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21a: turned off')
        await self.waitForAllBut(self.oldTasks)

        # Try again, with multiple ticks on past threshold, but turn off before it fully turns on
        doValueUpdate(t21a, '11')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21a.state, 'off')
        doValueUpdate(t21a, '12')
        await asyncio.sleep(0.1)
        self.assertEqual(t21a.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        doValueUpdate(t21a, '10')
        await asyncio.sleep(0.1)
        self.assertEqual(t21a.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        await asyncio.sleep(1)
        self.assertEqual(t21a.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.waitForAllBut(self.oldTasks)

        # Same with minimum
        doValueUpdate(t21b, '-1')
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21b.state, 'off')
        doValueUpdate(t21b, '-2')
        await asyncio.sleep(0.1)
        self.assertEqual(t21b.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        doValueUpdate(t21b, '0')
        await asyncio.sleep(0.1)
        self.assertEqual(t21b.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        await asyncio.sleep(1)
        self.assertEqual(t21b.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.waitForAllBut(self.oldTasks)

        # Same with max+min
        doValueUpdate(t21c, '-1')
        await asyncio.sleep(0.2)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t21c.state, 'off')
        doValueUpdate(t21c, '-2')
        await asyncio.sleep(0.2)
        self.assertEqual(t21c.state, 'off')
        self.assertEqual(len(nn.await_args_list), perCount)
        # we're close to 0.5 secs to turn on.  Now switch poles.
        # so 0.3 should be enough to turn it on
        doValueUpdate(t21c, '11')
        await asyncio.sleep(0.3)
        self.assertEqual(t21c.state, 'on')
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21c: turned on')
        doValueUpdate(t21c, '5')
        await asyncio.sleep(1)
        self.assertEqual(t21c.state, 'off')
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test_t21c: turned off')
        await self.waitForAllBut(self.oldTasks)

        
    async def test_event(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'tracked' : [
            { 'domain': 'test', 'name': 't22' },
            { 'domain': 'test', 'name': 't23', 'friendly_name': 'friendlyt23' },
            { 'domain': 'test', 'name': 't24', 'title': 'title24' },
            { 'domain': 'test', 'name': 't25', 'target': 'targett25' },
            { 'domain': 'test', 'name': 't25a', 'target': '{{ "ab" + "cd" }}' },
            { 'domain': 'test', 'name': 't26', 'data': { 'd1': 'data-d1' } },
        ], } }
        await self.initCase(cfg)
        t22 = self.gad.tracked['test']['t22']
        t23 = self.gad.tracked['test']['t23']
        t24 = self.gad.tracked['test']['t24']
        t25 = self.gad.tracked['test']['t25']
        t26 = self.gad.tracked['test']['t26']
        nn = self.hass.servHandlers['notify.persistent_notification']

        await self.hass.services.async_call('alert2','report', {})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'alert2_error.*malformed')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t22'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'Alert2 test_t22')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t22', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t22: foo')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t23', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 4)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'friendlyt23: foo')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t24', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'test_t24.*foo')
        self.assertRegex(nn.await_args_list[4].args[0].data['title'],   'title24')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t25', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 6)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'test_t25.*foo')
        self.assertEqual(nn.await_args_list[5].args[0].data['target'],   'targett25')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t25a', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertRegex(nn.await_args_list[6].args[0].data['message'], 'test_t25a.*foo')
        self.assertEqual(nn.await_args_list[6].args[0].data['target'],   'abcd')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t26', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 8)
        self.assertRegex(nn.await_args_list[7].args[0].data['message'], 'test_t26.*foo')
        self.assertDictEqual(nn.await_args_list[7].args[0].data['data'], { 'd1': 'data-d1' })

    async def test_event2(self):
        # Check throttling
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True }, 'tracked' : [
            { 'domain': 'test', 'name': 't27', 'throttle_fires_per_mins': [2, 0.01] },
            { 'domain': 'test', 'name': 't27a', 'throttle_fires_per_mins': [2, 0.01], 'summary_notifier': False },
        ], } }
        await self.initCase(cfg)
        t27 = self.gad.tracked['test']['t27']
        t27a = self.gad.tracked['test']['t27a']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0

        isFirst = True
        for summaryEnabled in [ True, False ]:
            tal   =  t27  if summaryEnabled else  t27a
            tname = 't27' if summaryEnabled else 't27a'
            for extraFire in [ False, True ]:
                _LOGGER.info(f'loop: summaryEnabled={summaryEnabled} extraFire={extraFire}')
                # First two should notify fine
                for i in range(2):
                    await self.hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                    await asyncio.sleep(0.05)
                    perCount += 1
                    self.assertEqual(len(nn.await_args_list), perCount)
                    self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Alert2 test_{tname}')

                # Start of throttling
                await self.hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                await asyncio.sleep(0.1)
                perCount += 1
                self.assertEqual(len(nn.await_args_list), perCount)
                self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], f'Throttling started] Alert2 test_{tname}')

                if extraFire:
                    # Two more fires shouldn't notify
                    await self.hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                    await asyncio.sleep(0.1)
                    self.assertEqual(len(nn.await_args_list), perCount)
                    await self.hass.services.async_call('alert2','report', {'domain':'test','name':tname})
                    await asyncio.sleep(0.1)
                    self.assertEqual(len(nn.await_args_list), perCount)

                # Wait for throttle to end
                await asyncio.sleep(2)
                if summaryEnabled:
                    perCount += 1
                    self.assertEqual(len(nn.await_args_list), perCount)
                    if extraFire:
                        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Throttling ending] Summary.*test_t27 fired 2x')
                    else:
                        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Throttling ending] Summary.*test_t27: Did not fire')
                else:
                    self.assertEqual(len(nn.await_args_list), perCount)

                if isFirst:
                    isFirst = False
                    await self.waitForAllBut(self.oldTasks)  # wait for delayed notifier mgr
                else:
                    self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
        
    async def test_event3(self):
        # Check throttling
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't28a',  'trigger': 'foo', 'message': '{{ 3+4 }}' },
            { 'domain': 'test', 'name': 't28',  'trigger': 'foo', 'condition': '{{ zzz }}' },
            { 'domain': 'test', 'name': 't29',  'trigger': 'foo', 'condition': '{{ zzz }}', 'friendly_name': 'friendly-t29'  },
        ], } }
        await self.initCase(cfg)
        t28 = self.gad.tracked['test']['t28']
        t28a = self.gad.tracked['test']['t28a']
        t29 = self.gad.tracked['test']['t29']
        nn = self.hass.servHandlers['notify.persistent_notification']

        # condition is false, so no alert
        setCondition(t28, False)
        await t28.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 0)

        # condition is now true
        setCondition(t28, True)
        await t28.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'Alert2 test_t28')

        setCondition(t29, True)
        await t29.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], 'friendly-t29')

        # and let's try reporting.  Reporting bypasses any conditions
        setCondition(t28, False)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t28'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 3)
        self.assertRegex(nn.await_args_list[2].args[0].data['message'], 'Alert2 test_t28')

        # and report a non-existent alert
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t28-no'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 5)
        self.assertRegex(nn.await_args_list[3].args[0].data['message'], 'Alert2 test_t28-no')
        self.assertRegex(nn.await_args_list[4].args[0].data['message'], 'Alert2 alert2_error: undeclared event.*t28-no')

        # try triggering alert without condition
        await t28a.async_trigger({'trigger': {}}, None, skip_condition=False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 6)
        self.assertRegex(nn.await_args_list[5].args[0].data['message'], 'Alert2 test_t28a: 7')
        
        # Reporting bypasses any message
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t28a'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 7)
        self.assertEqual(nn.await_args_list[6].args[0].data['message'], 'Alert2 test_t28a')
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t28a', 'message': 'foo'})
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 8)
        self.assertEqual(nn.await_args_list[7].args[0].data['message'], 'Alert2 test_t28a: foo')


        
    async def test_condition(self):
        # test pssing entity name instead of template for condition or threshold value
        cfg = { 'alert2' : { 'tracked': [
            { 'domain': 'test', 'name': 't30', 'friendly_name': 'happyt30' },
            { 'domain': 'test', 'name': 't30' }, # duplicate
            { 'domain': 'test', 'name': 't30a' }, # duplicate
        ], 'alerts' : [
            { 'domain': 'test', 'name': 't31', 'condition': 'off' },
            { 'domain': 'test', 'name': 't31', 'condition': '{{ false }}' }, # duplicate declaration
            { 'domain': 'test', 'name': 't30a', 'condition':'{{ true }}'  }, # duplicate declaration
            { 'domain': 'test', 'name': 't32', 'condition': 'no', 'trigger': 'fff' }, 
            { 'domain': 'test', 'name': 't32', 'condition': '{{ true }}', 'trigger': 'fff2' },  # duplicate
            { 'domain': 'test', 'name': 't33', 'condition': 'foo.bar' },
            { 'domain': 'test', 'name': 't34', 'condition': '{{ ick }}' },
            { 'domain': 'test', 'name': 't34a', 'condition': '{{ 3 }}' },
            { 'domain': 'test', 'name': 't35', 'threshold': 4 },
            { 'domain': 'test', 'name': 't36', 'threshold': { 'value': 5, 'hysteresis': 6, 'minimum':4 } },
            { 'domain': 'test', 'name': 't36a', 'threshold': { 'value': '3', 'hysteresis': 6, 'minimum':4 } },
            { 'domain': 'test', 'name': 't37', 'threshold': { 'value': 'foo.bar2', 'hysteresis': 8, 'minimum':9 } },
            { 'domain': 'test', 'name': 't37a', 'threshold': { 'value': 'sensor.ick', 'hysteresis': 8, 'minimum':9 } },
            { 'domain': 'test', 'name': 't38', 'threshold': { 'value': '{{ ick2 }}', 'hysteresis': 10, 'minimum':11 } },
            { 'domain': 'test', 'name': 't38a', 'condition': 'on' },
            { 'domain': 'test', 'name': 't38b', 'condition': '{{ "on" }}' },
        ], } }
        ahass = FakeHass()
        ahass.states.set('sensor.ick', SimpleNamespace(entity_id='sensor.ick', state='3'))
        await self.initCase(cfg, ahass)
        await asyncio.sleep(0.1)
        #await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't36a.*turned on')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't37a.*turned on')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't38a.*turned on')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't38b.*turned on')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Duplicate.*t30')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Duplicate.*t31')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Duplicate.*t30a')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Duplicate.*t32')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'expected dictionary.*t35')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't33.*rendered to "", which is not truthy')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't34.*rendered to "".*not truthy')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't34a.*rendered to "3".*not truthy')
        # t37 test here is a hack cuz we don't implement AllStates when looking up states that don't exist.
        # Real HA would return unknown.
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't37.*value template rendered to "" rather than a float')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't38.*value template rendered to "".*a float')
        self.assertEqual(len(nn.await_args_list), perCount)

        self.assertEqual(self.gad.tracked['test']['t30']._friendly_name, 'happyt30')
        self.assertEqual(self.gad.alerts['test']['t31']._condition_template.template, 'off')
        self.assertEqual(self.gad.tracked['test']['t32']._condition_template.template, 'no')
        self.assertEqual(self.gad.alerts['test']['t33']._condition_template.template, '{{ states("foo.bar") }}')
        self.assertEqual(self.gad.alerts['test']['t34']._condition_template.template, '{{ ick }}')
        self.assertNotIn('35', self.gad.alerts['test'])
        self.assertEqual(self.gad.alerts['test']['t36']._threshold_value_template.template, '5')
        self.assertEqual(self.gad.alerts['test']['t36a']._threshold_value_template.template, '3')
        self.assertEqual(self.gad.alerts['test']['t37']._threshold_value_template.template, '{{ states("foo.bar2") }}')
        self.assertEqual(self.gad.alerts['test']['t38']._threshold_value_template.template, '{{ ick2 }}')

    async def test_err_args(self):
        # test pssing entity name instead of template for condition or threshold value
        cfg = { 'alert2' : { 'tracked': [
            { 'domain': 'alert2', 'name': 'error', 'friendly_name': 'happy-terr' },
            ] } }
        await self.initCase(cfg)
        terr = self.gad.tracked['alert2']['error']
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.1)
        #await self.waitForAllBut(self.oldTasks)
        
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t39'})
        #await asyncio.sleep(0.1)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), 2)
        self.assertEqual(nn.await_args_list[0].args[0].data['message'], 'Alert2 test_t39')
        self.assertRegex(nn.await_args_list[1].args[0].data['message'], '^happy-terr: undeclared event.*t39')

        cfg = { 'alert2' : { 'tracked': [
            { 'domain': 'alert2', 'nname': 'error', 'friendly_name': 'happy-terr' },
            ] } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'extra keys.*nname')
        
        cfg = { 'alert2' : { 'tracked': [
            'ffstr'
            ] } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'expected a dictionary')

        cfg = { 'alert2' : { 'tracked': 3 } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'expected list')
        
        cfg = { 'alert2' : { 'ttracked': 3 } }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'extra keys.*ttracked')

        cfg = { 'alert2' : 'foo' }
        await self.initCase(cfg)
        await self.waitForAllBut(self.oldTasks)
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), 1)
        self.assertRegex(nn.await_args_list[0].args[0].data['message'], 'expected a dictionary')
        
    async def test_unack(self):
        # Check that default notifier is used
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't40', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01 },
        ],  'tracked' : [
            { 'domain': 'test', 'name': 't41', 'throttle_fires_per_mins': [1, 0.01], 'summary_notifier': True },
        ] } }
        await self.initCase(cfg)
        t40 = self.gad.alerts['test']['t40']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0
        
        doConditionUpdate(t40, True)
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't40.*turned on')
        await t40.async_ack()
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        await t40.async_unack()
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)

        # it should fire after 0.9 secs more of sleeping + 1 sec bufer time
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't40.*on for ')

        # Ack and so no notification.
        await t40.async_ack()
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), perCount)

        # it's been a while since last notify, so unack'ing should result in immediate notify
        await t40.async_unack()
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't40.*on for ')

        # and also future reminders
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't40.*on for ')
        
        # Now turn off
        await t40.async_ack()
        await asyncio.sleep(0.1)
        doConditionUpdate(t40, False)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)

        t41 = self.gad.tracked['test']['t41']
        # First two should notify fine
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't41')

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Throttling started.*t41')

        # Now should have notification built up
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t41'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        # Ack erases the unotififed firing (fires_since_last_notify).  and unack does not restore it
        await t41.async_ack()
        await asyncio.sleep(0.1)
        await t41.async_unack()
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.waitForAllBut(self.oldTasks)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Throttling ending.*t41.*Did not fire')

    async def test_grace(self):
        # Test some invalid value, no defer, so notify soon
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': None, 'defer_startup_notifications': False } }
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'expected float')
        await self.waitForAllBut(self.oldTasks)  # will wait a default 3 secs

        # Test some invalid value, with defer, so notify after grace expires
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': '', 'defer_startup_notifications': True } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.waitForAllBut(self.oldTasks)  # will wait a default 3 secs
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'expected float')

        # Test no grace, notify should be immediate
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': 0, 'defer_startup_notifications': False,
                             'tracked': [ { 'domain': 'test', 'name': 't42', 'notifier': 'persistent_notification' },
                                          { 'domain': 'test', 'name': 't43', 'notifier': 'foo' } ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t42'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t42')
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t43'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't43.*foo.*is not known')
        await self.waitForAllBut(self.oldTasks)

        # Test no grace, notify should be immediate, even with defer to True
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': 0, 'defer_startup_notifications': True,
                             'tracked': [ { 'domain': 'test', 'name': 't44', 'notifier': 'persistent_notification' },
                                         ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t44'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t44')
        await self.waitForAllBut(self.oldTasks)

        # Test some grace
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.5, 'defer_startup_notifications': False,
                             'tracked': [ { 'domain': 'test', 'name': 't45', 'notifier': 'persistent_notification' },
                                          { 'domain': 'test', 'name': 't46', 'notifier': 'foo' } ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t45'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t45')
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t46'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        #   unknown notifier waits for grace period
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'not known to HA.*\'foo\'')
        await self.waitForAllBut(self.oldTasks)

        # Test some grace and defer
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.5, 'defer_startup_notifications': True,
                             'tracked': [ { 'domain': 'test', 'name': 't47', 'notifier': 'persistent_notification' },
                                          { 'domain': 'test', 'name': 't48', 'notifier': 'foo' } ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t47'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t48'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        #   wait for rest of grace period
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), perCount + 2)
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t47')
        perCount += 1
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'not known to HA.*\'foo\'')
        await self.waitForAllBut(self.oldTasks)

        # Test defer naming specific list
        cfg = { 'alert2' : { 'notifier_startup_grace_secs': 1.5, 'defer_startup_notifications': ['fooexist','foono'],
                             'tracked': [ { 'domain': 'test', 'name': 't49', 'notifier': 'fooexist' },
                                          { 'domain': 'test', 'name': 't50', 'notifier': 'foono' },
                                          { 'domain': 'test', 'name': 't51', 'notifier': 'persistent_notification' },
                                          { 'domain': 'test', 'name': 't52', 'notifier': 'foono2' } ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        self.hass.services.async_register('notify','fooexist', AsyncMock(name='fooexist', spec_set=[]))
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        nfoo = self.hass.servHandlers['notify.fooexist']
        
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t49'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t50'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t51'})
        await asyncio.sleep(0.1)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t51')
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t52'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        fooCount = 0
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        #   wait for rest of grace period
        await asyncio.sleep(2)
        fooCount += 1
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], 'Alert2 test_t49')
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'not known to HA.*\'foono\'.*\'foono2\'')
        await self.waitForAllBut(self.oldTasks)

    async def test_snooze(self):
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
            { 'domain': 'test', 'name': 't53', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01 },
            { 'domain': 'test', 'name': 't53a', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01, 'summary_notifier': False },
            { 'domain': 'test', 'name': 't53b', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01, 'summary_notifier': 'foo' },
        ],  'tracked' : [
            { 'domain': 'test', 'name': 't54' },
            { 'domain': 'test', 'name': 't54a', 'summary_notifier': False },
            { 'domain': 'test', 'name': 't54b', 'summary_notifier': 'foo' },
            { 'domain': 'test', 'name': 't54c', 'summary_notifier': '{{ [ \"foo\" ] }}' },
        ] } }
        await self.initCase(cfg)
        t53 = self.gad.alerts['test']['t53']
        t53a = self.gad.alerts['test']['t53a']
        t53b = self.gad.alerts['test']['t53b']
        t54 = self.gad.tracked['test']['t54']
        t54a = self.gad.tracked['test']['t54a']
        t54b = self.gad.tracked['test']['t54b']
        t54c = self.gad.tracked['test']['t54c']
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        nfoo = self.hass.servHandlers['notify.foo']
        perCount = 0
        fooCount = 0
        await asyncio.sleep(0.05)
        self.assertEqual(t53.notification_control, a2Entities.NOTIFICATIONS_ENABLED)

        # Snoozed so no notification
        now = rawdt.datetime.now(rawdt.timezone.utc)
        await t53.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t53a.async_notification_control(True, now + rawdt.timedelta(seconds=1.1))
        await t53b.async_notification_control(True, now + rawdt.timedelta(seconds=1.2))
        await asyncio.sleep(0.05)
        self.assertTrue(isinstance(t53.notification_control, rawdt.datetime))
        doConditionUpdate(t53, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53a, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53b, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        # snooze expires, get reminder notification summary
        await asyncio.sleep(2)
        perCount += 3
        self.assertEqual(t53.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], 't53.*fired 1x.*on for')
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 't53a.*fired 1x.*on for')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't53b.*fired 1x.*on for')
        # Should still get reminders after snooze expires
        await asyncio.sleep(2)
        perCount += 3
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], 't53: on for')
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 't53a: on for')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't53b: on for')
        # Set snooze again and turn off. No snooze summary (cuz acked?)
        now = rawdt.datetime.now(rawdt.timezone.utc)
        await t53.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t53a.async_notification_control(True, now + rawdt.timedelta(seconds=1.1))
        await t53b.async_notification_control(True, now + rawdt.timedelta(seconds=1.2))
        # No reminders cuz snooze is implicit ack
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        doConditionUpdate(t53, False)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53a, False)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53b, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        
        # Snoozed so no notification
        now = rawdt.datetime.now(rawdt.timezone.utc)
        await t53.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t53a.async_notification_control(True, now + rawdt.timedelta(seconds=1.1))
        await t53b.async_notification_control(True, now + rawdt.timedelta(seconds=1.2))
        await asyncio.sleep(0.05)
        doConditionUpdate(t53, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53a, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53b, True)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        doConditionUpdate(t53, False)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53a, False)
        await asyncio.sleep(0.05)
        doConditionUpdate(t53b, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        # snooze expires, get summary notification
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't53 fired 1x')
        fooCount += 1
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], 't53b fired 1x')

        # Try events
        now = rawdt.datetime.now(rawdt.timezone.utc)
        await t54.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t54a.async_notification_control(True, now + rawdt.timedelta(seconds=1.05))
        await t54b.async_notification_control(True, now + rawdt.timedelta(seconds=1.1))
        await t54c.async_notification_control(True, now + rawdt.timedelta(seconds=1.15))
        await asyncio.sleep(0.05)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t54'})
        await asyncio.sleep(0.05)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t54a'})
        await asyncio.sleep(0.05)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t54b'})
        await asyncio.sleep(0.05)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t54c'})
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        # snooze expires, get notification summary
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't54.*fired 1x.*ago\\)$')
        fooCount += 2
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertRegex(nfoo.await_args_list[fooCount-2].args[0].data['message'], 't54b.*fired 1x.*ago\\)$')
        self.assertRegex(nfoo.await_args_list[fooCount-1].args[0].data['message'], 't54c.*fired 1x.*ago\\)$')

        # Try disabled
        await t53.async_notification_control(False, None)
        doConditionUpdate(t53, True)
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        # No reminders either
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), perCount)
        doConditionUpdate(t53, False)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        # undo snooze, no summary
        await t53.async_notification_control(False, None)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)

        # Try disabled event
        await t54.async_notification_control(False, None)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t54'})
        await asyncio.sleep(0.1)
        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t54'})
        await asyncio.sleep(0.1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        # undo snooze, no summary
        await t54.async_notification_control(False, None)
        await self.waitForAllBut(self.oldTasks)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)

    async def test_snooze2(self):
        # Test what happens if snooze ends while alarm is not firing
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
            { 'domain': 'test', 'name': 't54a', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01 },
            { 'domain': 'test', 'name': 't54c', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01 }, # will ack
            { 'domain': 'test', 'name': 't54b', 'condition': '{{ false }}', 'reminder_frequency_mins': 0.01, 'summary_notifier': False },
        ] } }
        await self.initCase(cfg)
        t54a = self.gad.alerts['test']['t54a']
        t54b = self.gad.alerts['test']['t54b']
        t54c = self.gad.alerts['test']['t54c']
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount = 0

        # Alert is on
        doConditionUpdate(t54a, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t54b, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t54c, True)
        await asyncio.sleep(0.05)
        perCount += 3
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], 't54a: turned on')
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 't54b: turned on')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't54c: turned on')
        self.assertEqual(t54a.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(t54b.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(t54c.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        # then we snooze it
        now = rawdt.datetime.now(rawdt.timezone.utc)
        await t54a.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t54b.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t54c.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await asyncio.sleep(0.05)
        self.assertTrue(isinstance(t54a.notification_control, rawdt.datetime))
        self.assertTrue(isinstance(t54b.notification_control, rawdt.datetime))
        self.assertTrue(isinstance(t54c.notification_control, rawdt.datetime))
        self.assertEqual(len(nn.await_args_list), perCount)
        await t54c.async_ack()  # snooze implicitly acks, but try explicit ack
        await asyncio.sleep(0.05)
        # then turn alert off
        doConditionUpdate(t54a, False)
        doConditionUpdate(t54b, False)
        doConditionUpdate(t54c, False)
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        # snooze expires.  Snooze should turn off
        # should not get any notifications since snooze is implicit ack
        await asyncio.sleep(2)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(t54a.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(t54b.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(t54c.notification_control, a2Entities.NOTIFICATIONS_ENABLED)

        # Alert is on.
        doConditionUpdate(t54a, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t54b, True)
        await asyncio.sleep(0.05)
        doConditionUpdate(t54c, True)
        await asyncio.sleep(0.05)
        perCount += 3
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], 't54a: turned on')
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 't54b: turned on')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't54c: turned on')
        self.assertEqual(t54a.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(t54b.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        self.assertEqual(t54c.notification_control, a2Entities.NOTIFICATIONS_ENABLED)
        # then we snooze it
        now = rawdt.datetime.now(rawdt.timezone.utc)
        await t54a.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t54b.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await t54c.async_notification_control(True, now + rawdt.timedelta(seconds=1))
        await asyncio.sleep(0.05)
        self.assertTrue(isinstance(t54a.notification_control, rawdt.datetime))
        self.assertTrue(isinstance(t54b.notification_control, rawdt.datetime))
        self.assertTrue(isinstance(t54c.notification_control, rawdt.datetime))
        self.assertEqual(len(nn.await_args_list), perCount)
        await t54c.async_unack()  # unack one of them
        # Snooze expires
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't54c: on for')
        # and should get reminders
        await asyncio.sleep(2)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't54c: on for')


        
    async def test_generator(self):
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't55', 'condition': '{{ False }}',  },
        ] } }
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), perCount)
        # let first generation happen
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.gad.alerts['test']), 1)
        self.assertTrue(not 'tracked' in self.gad.alerts)
        t55 = self.gad.alerts['test']['t55']
        self.assertEqual(len(self.gad.generators), 1)
        g1 = self.gad.generators['g1']
        self.assertEqual(g1.state, 1)
        self.assertEqual(g1.entity_id, 'sensor.alert2generator_g1')
        self.assertTrue(self.hass.states.get(g1.entity_id))
        self.assertEqual(len(nn.await_args_list), perCount)

        
        # And suppose generator is a template and produces an error.  should not change generated alerts.
        doGeneratorUpdate(g1, '{{ foo')
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'generator_g1 generator template threw error: unexpected end')
        self.assertEqual(self.gad.alerts['test']['t55'], t55)

        # suppose template is missing - it's an error
        g1.tracker._result_cb(SimpleNamespace(context=3, data={ 'entity_id': 'eid' }),
                                [ SimpleNamespace(template=None, result='fff') ] )
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'generator_g1 template not found: None')
        self.assertEqual(self.gad.alerts['test']['t55'], t55)
        
        # template producing same string should not recreate alert
        doGeneratorUpdate(g1, 't55')
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(self.gad.generators), 1)
        self.assertEqual(self.gad.alerts['test']['t55'], t55)
        
        # Now suppose template returns nothing, so alert should disappear
        doGeneratorUpdate(g1, '')
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(self.gad.alerts['test']), 0)

        # what if name includes a trailing z in template
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True}, 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}z', 'generator_name': 'g1', 'generator': 't56', 'condition': '{{ False }}',  },
        ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), perCount)
        # let first generation happen
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.gad.alerts['test']), 1)
        self.assertTrue(not 'tracked' in self.gad.alerts)
        t56z = self.gad.alerts['test']['t56z']
        self.assertEqual(len(self.gad.generators), 1)
        g1 = self.gad.generators['g1']
        self.assertEqual(g1.state, 1)
        self.assertEqual(len(nn.await_args_list), perCount)
        # Now suppose a second alert appears
        doGeneratorUpdate(g1, '[ "t56", "t57" ]' )
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(self.gad.alerts['test']), 2)
        t57z = self.gad.alerts['test']['t57z']
        self.assertEqual(g1.state, 2)
                
        # Now suppose template returns nothing, so alert should disappear
        doGeneratorUpdate(g1, '')
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(self.gad.alerts['test']), 0)

    async def test_generator2(self):
        # Try templating of genElem variable
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't57',
              'condition': '{{ False }}',
              # If genElem doesn't resolve to 't57', then we'll pick the wrong notifier
              'notifier': '{% if genElem == "t57" %}persistent_notification{% else %}foo{% endif %}',
              'title': '{{ genElem }}tt', 'target': '{{ genElem }}tar',
              'message': '{{ genElem }}msg{{ genEntityId}}z', # genEntityId should be empty
              'done_message': '{{ genElem }}dmsg',
             },
            # duplicate g1
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't57zz',
              'condition': '{{ zzz }}',
             },
            # In the real world, this would immediately alert, but our test harness
            # isn't smart enough???
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': 't58',
              'condition': '{{ true }}',
              'threshold': {
                  'value': '{% if genElem == "zzz" %}10{% else %}5{% endif %}',
                  'hysteresis': 2,
                  'maximum': 9
              },
             },
        ] } }
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        nfoo = self.hass.servHandlers['notify.foo']
        fooCount = 0
        # let first generation happen
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Duplicate generator name=g1')
        self.assertEqual(len(self.gad.alerts['test']), 2)
        self.assertTrue(not 'tracked' in self.gad.alerts)
        t57 = self.gad.alerts['test']['t57']
        t58 = self.gad.alerts['test']['t58']
        self.assertEqual(len(self.gad.generators), 2)
        g1 = self.gad.generators['g1']
        g2 = self.gad.generators['g2']
        self.assertEqual(g1.state, 1)
        self.assertEqual(g2.state, 1)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(nfoo.await_args_list), fooCount)

        doConditionUpdate(t57, True)
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertEqual(len(nn.await_args_list), perCount)
        #print(nn.await_args_list[perCount-1].args[0].data)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t57: t57msgz')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['title'], 't57tt')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['target'], 't57tar')
        # Check done_message
        doConditionUpdate(t57, False)
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nfoo.await_args_list), fooCount)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t57: t57dmsg')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['title'], 't57tt')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['target'], 't57tar')
        # So we've tested genElem in name, title, target, message, done_message, notifier.

        # Testing 'condition' is tricker cuz our test harness only evaluates that variables
        # are passed during alert creation.  TODO - spiffy this testing up
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't59',
              'condition': '{{ genElem == "t59" }}',
             },
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': 't60',
              'condition': '{{ true }}',
              'threshold': {
                  'value': '{% if genElem == "t60" %}10{% else %}5{% endif %}',
                  'hysteresis': 2,
                  'maximum': 9
              },
             },
        ] } }
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.hass.services.async_register('notify','foo', AsyncMock(name='foo', spec_set=[]))
        nfoo = self.hass.servHandlers['notify.foo']
        fooCount = 0
        await asyncio.sleep(0.05)
        perCount += 2
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 'Alert2 test_t59: turned on')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t60: turned on')
        # And now checked genElem in condition and value.
        
    async def test_generator3(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g1', 'generator': 't61',
              'condition': '{{ False }}' },
            { 'domain': 'test', 'name': '{{ genRaw }}', 'generator_name': 'g1a', 'generator': 't61a',
              'condition': '{{ False }}' },
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g2', 'generator': [ "t62", "t63" ],
              'condition': '{{ False }}' },
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g3', 'generator': '[ "t64", "t65" ]',
              'condition': '{{ False }}' },
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g4', 'generator': '{{ [ "t66", "t67" ] }}',
              'condition': '{{ False }}' },
        ] } }
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(self.gad.alerts['test']), 8)
        self.assertTrue(not 'tracked' in self.gad.alerts)
        for id in [ 't61', 't61a', 't62', 't63', 't64', 't65', 't66', 't67' ]:
            self.assertTrue(self.gad.alerts['test'][id])
        self.assertEqual(len(self.gad.generators), 5)
        for id in [ 'g1', 'g1a', 'g2', 'g3', 'g4' ]:
            self.assertTrue(self.gad.generators[id])

        # Pick one and try adding another alert
        g3 = self.gad.generators['g3']
        doGeneratorUpdate(g3, '[ "t64", "t65", "t65a" ]')
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.gad.alerts['test']), 9)
        self.assertTrue(self.gad.alerts['test']['t65a'])
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)

        t63 = self.gad.alerts['test']['t63']
        doConditionUpdate(t63, True)
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t63: turned on')

    async def test_generator4(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g5', 'generator': '{{ foo ',
              'condition': 'off' } ]}}
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'invalid template.*g5')
        self.assertEqual(len(self.gad.generators), 0)
        #g5 = self.gad.generators['test']['g5']
        #self.assertEqual(g5.state, 0)
        self.assertEqual(len(self.gad.alerts), 0)

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
        resetModuleLoadTime()
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.05)
        perCount += 4
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-4].args[0].data['message'], 'g6 Name template returned err.*unexpected')
        self.assertRegex(nn.await_args_list[perCount-3].args[0].data['message'], 'g7 Name template returned err.*zz.*undefined')
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 'g8 Domain template returned err.*unexpected')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'g9 Domain template returned err.*zz.*undefined')
        self.assertEqual(len(self.gad.generators), 5)
        self.assertEqual(len(self.gad.alerts), 1)
        self.assertEqual(self.gad.generators['g6'].state, 0)
        self.assertEqual(self.gad.generators['g7'].state, 0)
        self.assertEqual(self.gad.generators['g8'].state, 0)
        self.assertEqual(self.gad.generators['g9'].state, 0)
        self.assertEqual(self.gad.generators['g10'].state, 1)
        self.assertEqual(self.gad.alerts['foodd']['foonn'].state, 'off')
        _LOGGER.warning(self.hass.states.get('alert2.foodd_foonn'))

    async def test_generator5(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': '{{ genGroups[0] }}', 'generator_name': 'g11',
              'generator': "{{ states|entity_regex('sensor.(.*)_bar')|list }}",
              'condition': 'off' },
            { 'domain': 'test', 'name': '{{ genGroups[0] }}a', 'generator_name': 'g12',
              'generator': "{{ states|entity_regex('sensor.(.*)_bar')|list }}",
              'message': 'aa={{genGroups[0]}} and bb={{genEntityId}} and cc={{genRaw}}',
              'condition': 'off' },
            # No group
            { 'domain': 'test', 'name': '{{ genGroups[0] }}b', 'generator_name': 'g13',
              'generator': "{{ states|entity_regex('sensor..*_bar')|list }}",
              'condition': 'off' },
            { 'domain': 'test', 'name': '{{ genGroups[0] }}c', 'generator_name': 'g14',
              'generator': "{{ states|entity_regex('sensor.(.*)_bar')|list }}",
              'condition': '{{ states(genEntityId) }}' },
            # Check genEntityId auto-populates
            { 'domain': 'test', 'name': '{{ genEntityId|replace("sensor.foo1_bar","foo1") }}d', 'generator_name': 'g15',
              'generator': "{{ states|selectattr('entity_id','equalto','sensor.foo1_bar')|map(attribute='entity_id')|list }}",
              'message': 'ee={{genRaw}}',
              'condition': '{{ states(genEntityId) }}' }
        ]}}
        ahass = FakeHass()
        ahass.states.set('sensor.ickbar', SimpleNamespace(entity_id='sensor.ickbar', state='foo'))
        ahass.states.set('sensor.foo1_bar', SimpleNamespace(entity_id='sensor.foo1_bar', state='on'))
        ahass.states.set('sensor.foo2_bar', SimpleNamespace(entity_id='sensor.foo2_bar', state='off'))
        await self.initCase(cfg, ahass)
        perCount = 2
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 'test_foo1c: turned on')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'test.foo1d: ee=sensor.foo1_bar')
        self.assertEqual(len(self.gad.generators), 5)
        g11 = self.gad.generators['g11']
        self.assertEqual(g11.state, 2)
        self.assertEqual(self.gad.alerts['test']['foo1'].state, 'off')
        self.assertEqual(self.gad.alerts['test']['foo2'].state, 'off')
        g12 = self.gad.generators['g12']
        self.assertEqual(g12.state, 2)
        self.assertEqual(self.gad.alerts['test']['foo1a'].state, 'off')
        self.assertEqual(self.gad.alerts['test']['foo2a'].state, 'off')
        tfoo1a = self.gad.alerts['test']['foo1a']
        
        g13 = self.gad.generators['g13']
        self.assertEqual(g13.state, 1)
        self.assertEqual(self.gad.alerts['test']['b'].state, 'off')
        g14 = self.gad.generators['g14']
        self.assertEqual(g14.state, 2)
        self.assertEqual(self.gad.alerts['test']['foo1c'].state, 'on')
        self.assertEqual(self.gad.alerts['test']['foo2c'].state, 'off')
        doConditionUpdate(tfoo1a, True)
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'aa=foo1.*bb=sensor.foo1_bar.*cc={\'genEntityId')

        g15 = self.gad.generators['g15']
        self.assertEqual(g15.state, 1)
        self.assertEqual(self.gad.alerts['test']['foo1d'].state, 'on')
    async def test_generator6(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g15',
              'generator': [ 'foo1' ],
              'friendly_name': '{{ genElem }}zz', 'condition': 'off' },
            # Test if one alert has a render error in domain/name, we don't delete the rest
            { 'domain': 'test',
              'name': '{% if states("sensor.ick") == "on" and genElem == "foo2" %}{{blowup()}}{% else %}{{ genElem }}{% endif %}',
              'generator_name': 'g16', 'generator': '[ "foo2", "foo3" ]',
              'condition': 'off' },
            ]}}
        ahass = FakeHass()
        ahass.states.set('sensor.ick', SimpleNamespace(entity_id='sensor.ick', state='foo'))
        await self.initCase(cfg, ahass)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertEqual(len(self.gad.generators), 2)
        g15 = self.gad.generators['g15']
        self.assertEqual(g15.state, 1)
        foo1 = self.gad.alerts['test']['foo1']
        self.assertEqual(foo1.state, 'off')

        doConditionUpdate(foo1, True)
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], '^foo1zz: turned on')

        g16 = self.gad.generators['g16']
        self.assertEqual(g16.state, 2)
        foo2 = self.gad.alerts['test']['foo2']
        foo3 = self.gad.alerts['test']['foo3']
        self.assertTrue('foo3' in self.gad.alerts['test'])
        ahass.states.get('sensor.ick').state = 'on'

        doGeneratorUpdate(g16, '["foo2","foo3"]')
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'blowup\' is undefined')
        # Here's the crux of the test.  generator had a render error while processing "foo2"
        # so neither foo2 nor foo3 should be deleted.
        self.assertTrue('foo2' in self.gad.alerts['test'])
        self.assertTrue('foo3' in self.gad.alerts['test'])
        
    async def test_generator7(self):
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
        await self.initCase(cfg, startWatching=False)
        nn = self.hass.servHandlers['notify.persistent_notification']
        await asyncio.sleep(0.05)
        perCount = 2
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-2].args[0].data['message'], 't69.* turned on')
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'must contain at least one of')
        self.assertEqual(len(self.gad.generators), 1)
        g17 = self.gad.generators['g17']
        self.assertEqual(g17.state, 0)
        self.assertTrue('foo1' not in self.gad.alerts['test'])
        self.assertEqual(self.gad.alerts['test']['t68'].state, 'off')
        self.assertEqual(self.gad.alerts['test']['t69'].state, 'on')

        await self.startWatching()
        self.assertEqual(g17.state, 1)
        foo1 = self.gad.alerts['test']['foo1']
        self.assertEqual(foo1.state, 'off')
        self.assertEqual(self.gad.alerts['test']['t68'].state, 'on')
        self.assertEqual(self.gad.alerts['test']['t69'].state, 'on')
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't68.* turned on')

    async def test_late_state(self):
        cfg = { 'alert2' : { 'alerts' : [
            # Check that template condition still becomes states("sensor.ick") even if sensor.ick doesn't yet exist
            # when the alert is created.
            { 'domain': 'test', 'name': 't70', 'condition': 'sensor.ick' },
            ]}}
        await self.initCase(cfg)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't70 condition template rendered to "", which is not truthy')
        t70 = self.gad.alerts['test']['t70']
        self.assertRegex(t70._condition_template.template, 'states."sensor.ick"')
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)
        
        #self.hass.states.set('sensor.ick', SimpleNamespace(entity_id='sensor.ick', state='on'))
        
    async def test_friendlyname(self):
        cfg = { 'alert2' : { 'alerts' : [
            { 'domain': 'test', 'name': 't71', 'friendly_name': '{{ states("sensor.ick") }}', 'condition': 'off' },
            ]}}
        ahass = FakeHass()
        ahass.states.set('sensor.ick', SimpleNamespace(entity_id='sensor.ick', state='t71yy'))
        await self.initCase(cfg, ahass)
        await asyncio.sleep(0.05)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), perCount)
        t71 = self.gad.alerts['test']['t71']
        self.assertEqual(t71.extra_state_attributes['friendly_name2'], 't71yy')
        doFriendlyNameUpdate(t71, 'foo71')
        await asyncio.sleep(0.05)
        self.assertEqual(t71.extra_state_attributes['friendly_name2'], 'foo71')
        
    async def test_reload(self):
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
        await self.initCase(cfg)
        await asyncio.sleep(0.05)
        perCount = 1
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't75: turned on')
        now = rawdt.datetime.now(rawdt.timezone.utc)
        t74 = self.gad.alerts['test']['t74']
        await t74.async_notification_control(True, now + rawdt.timedelta(seconds=30))
        entids = self.hass.states.data.keys()
        self.assertEqual(len(entids), 9) # 1 is alert2.error

        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True, 'reminder_frequency_mins': 0.01}, 'alerts' : [
            { 'domain': 'test', 'name': 't72', 'condition': 'off' },
            { 'domain': 'test', 'name': 't80', 'condition': 'off' },
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g18', 'generator': [ 't81' ], 'condition':'off' },
            ], 'tracked': [
                { 'domain': 'test', 'name': 't77' },
                { 'domain': 'test', 'name': 't82' },
            ]}}
        self.gad.component.newCfg = cfg
        await self.gad.reload_service_handler(None)
        await asyncio.sleep(0.05)
        entids = list(self.hass.states.data.keys())
        self.assertEqual(len(entids), 7) # 1 is alert2.error
        for id in ['alert2.alert2_error', 'alert2.test_t77', 'alert2.test_t82', 'alert2.test_t72',
                   'alert2.test_t80', 'sensor.alert2generator_g18', 'alert2.test_t81']:
            self.assertTrue(id in entids)
        # The snooze task should have been canceled
        await asyncio.sleep(2)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)
            
        cfg = { 'alert2' : {}}
        self.gad.component.newCfg = cfg
        await self.gad.reload_service_handler(None)
        await asyncio.sleep(0.05)
        entids = list(self.hass.states.data.keys())
        self.assertEqual(len(entids), 1) # 1 is alert2.error
        for id in ['alert2.alert2_error']:
            self.assertTrue(id in entids)

    async def test_shutdown(self):
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True, 'reminder_frequency_mins': 0.01}, 'alerts' : [
            { 'domain': 'test', 'name': 't83', 'condition': 'off' },
            { 'domain': 'test', 'name': 't84', 'condition': 'on' },
            { 'domain': 'test', 'name': '{{ genElem }}', 'generator_name': 'g19', 'generator': [ 't85' ], 'condition':'off' },
            ], 'tracked': [
                { 'domain': 'test', 'name': 't86' },
            ]}}
        await self.initCase(cfg)
        await asyncio.sleep(0.05)
        perCount = 1
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 't84: turned on')
        now = rawdt.datetime.now(rawdt.timezone.utc)
        t74 = self.gad.alerts['test']['t83']
        await t74.async_notification_control(True, now + rawdt.timedelta(seconds=30))
        entids = self.hass.states.data.keys()
        entids = list(self.hass.states.data.keys())
        self.assertEqual(len(entids), 6) # 1 is alert2.error
        for id in ['alert2.alert2_error', 'alert2.test_t83', 'alert2.test_t84', 'alert2.test_t85',
                   'alert2.test_t86', 'sensor.alert2generator_g19']:
            self.assertTrue(id in entids)

        # Shutdown should stop all tasks, reminders and whatnot
        self.hass.bus.async_fire(FakeConst.EVENT_HOMEASSISTANT_STOP, 'happy2')
        await asyncio.sleep(0.2)
        self.assertEqual(await self.waitForAllBut(self.oldTasks), 0)

    async def test_declare_event(self):
        cfg = { 'alert2' : { 'defaults': { 'summary_notifier': True} } }
        await self.initCase(cfg)
        await asyncio.sleep(0.05)
        perCount = 0
        nn = self.hass.servHandlers['notify.persistent_notification']
        self.assertEqual(len(nn.await_args_list), perCount)

        await alert2.declareEventMulti([
            { 'domain': 'test', 'name': 't87' },
            { 'domain': 'test', 'name': 't88' },
        ])
        await asyncio.sleep(0.05)
        self.assertEqual(len(nn.await_args_list), perCount)

        await self.hass.services.async_call('alert2','report', {'domain':'test','name':'t87'})
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t87')
        alert2.report('test', 't88', 'foo')
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t88: foo')
        
        # Try a reload, should preserve the declareEventMulti
        await self.gad.reload_service_handler(None)
        await asyncio.sleep(0.05)
        alert2.report('test', 't88', 'foo')
        await asyncio.sleep(0.05)
        perCount += 1
        self.assertEqual(len(nn.await_args_list), perCount)
        self.assertRegex(nn.await_args_list[perCount-1].args[0].data['message'], 'Alert2 test_t88: foo')

        
        
if __name__ == '__main__':
    unittest.main()
