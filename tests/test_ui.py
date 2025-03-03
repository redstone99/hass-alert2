#
# JTESTDIR=/home/redstone/home-monitoring/homeassistant  venv/bin/pytest --show-capture=no
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
import custom_components.alert2.ui as a2Ui
from custom_components.alert2.util import (     GENERATOR_DOMAIN )
from homeassistant.util import json as json_util
from homeassistant.helpers import json as json_helper
from   homeassistant.helpers import template as template_helper
from homeassistant import config as conf_util
import homeassistant.components.websocket_api as wsapi

a2Ui.SAVE_DELAY = 0

async def setAndWait(hass, eid, state): 
    hass.states.async_set(eid, state)
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()

async def startAndTpost(hass, service_calls, hass_client, cfg):
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    client = await hass_client()
    async def tpost(url, adict):
        resp = await client.post(url, json=adict)
        assert resp.status == 200
        rez = await resp.json()
        await hass.async_block_till_done()
        return rez
    gad = hass.data[DOMAIN]
    return (tpost, client, gad)
    
async def test_defaults(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2' : {
        'defaults' : {
            'notifier' : 'n',
            'summary_notifier' : 'sn',
            'reminder_frequency_mins': [3],
            'throttle_fires_per_mins': [1,2],
            'priority': 'medium',
        },
        'alerts': [
            { 'domain': 'test', 'name': 't1', 'condition': 'off' }
        ],
        'skip_internal_errors': True,
        'notifier_startup_grace_secs': 4,
        'defer_startup_notifications': True,
    } }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)
    # Test top-level flags were set
    assert hass.states.get('alert2.error') == None # skip_internal_errors
    cfga = cfg['alert2']
    assert gad.delayedNotifierMgr.notifier_startup_grace_secs == cfga['notifier_startup_grace_secs']
    assert gad.delayedNotifierMgr.defer_startup_notifications == cfga['defer_startup_notifications']
    t1 = gad.alerts['test']['t1']
    # and check all the defaults
    assert t1._notifier_list_template.template == cfga['defaults']['notifier']
    assert t1._summary_notifier.template == cfga['defaults']['summary_notifier']
    assert t1.reminder_frequency_mins == cfga['defaults']['reminder_frequency_mins']
    assert t1.movingSum.maxCount == cfga['defaults']['throttle_fires_per_mins'][0]
    assert t1.movingSum.intervalSecs == cfga['defaults']['throttle_fires_per_mins'][1]*60

    # Get defaults.   No UI changes so far
    resp = await client.post("/api/alert2/loadTopConfig", json={})
    assert resp.status == 200
    rez = await resp.json()
    _LOGGER.warning(rez)
    topParams = [ 'skip_internal_errors', 'notifier_startup_grace_secs', 'defer_startup_notifications' ]
    for p in topParams:
        assert rez['rawYaml'][p] == cfga[p]
    for p in cfga['defaults'].keys():
        assert rez['rawYaml']['defaults'][p] == cfga['defaults'][p]
    assert rez['rawUi'] == {'defaults': {}}
    assert rez['raw'] == rez['rawYaml']

    # Try some bad requests
    resp = await client.post("/api/alert2/saveTopConfig", json={})
    assert resp.status == 400
    assert re.search('required key not provided', await resp.text())
    resp = await client.post("/api/alert2/saveTopConfig", json={'topConfig': { 'bad': 'dd' }})
    assert resp.status == 200
    rez = await resp.json()
    assert re.search('extra keys not allowed', rez['error'])

    # Check bad values for all parameters
    #
    # First skip_internal_errors
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'skip_internal_errors': 'gg' }})
    assert re.search('invalid boolean value gg', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'skip_internal_errors': [ 3 ] }})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'skip_internal_errors': True }})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'skip_internal_errors': 'on   ' }})
    assert not 'error' in rez
    assert rez['rawUi']['skip_internal_errors'] == 'on'
    assert hass_storage['alert2.storage']['data']['config']['skip_internal_errors'] == 'on'
    assert gad.topConfig['skip_internal_errors'] == True
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'skip_internal_errors': 'off' }})
    assert gad.topConfig['skip_internal_errors'] == False
    # all values must be strings. for cv.boolean, that's fine, true/false work as expected
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'skip_internal_errors': 'true' }})
    assert rez['rawUi']['skip_internal_errors'] == 'true'
    assert hass_storage['alert2.storage']['data']['config']['skip_internal_errors'] == 'true'
    assert gad.topConfig['skip_internal_errors'] == True
    # empty things out
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { }})
    assert 'skip_internal_errors' not in hass_storage['alert2.storage']['data']['config']
    
    # notifier_startup_grace_secs
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'notifier_startup_grace_secs': 'gg' }})
    assert re.search('expected float', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'notifier_startup_grace_secs': 3 }})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'notifier_startup_grace_secs': '3' }})
    assert rez['rawUi']['notifier_startup_grace_secs'] == '3'
    assert hass_storage['alert2.storage']['data']['config']['notifier_startup_grace_secs'] == '3'
    assert gad.topConfig['notifier_startup_grace_secs'] == 3
 
    # defer_startup_notifications
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defer_startup_notifications': False }})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defer_startup_notifications': 'false' }})
    assert rez['rawUi']['defer_startup_notifications'] == 'false'
    assert hass_storage['alert2.storage']['data']['config']['defer_startup_notifications'] == 'false'
    assert gad.topConfig['defer_startup_notifications'] == False
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defer_startup_notifications': 'foo' }})
    assert rez['rawUi']['defer_startup_notifications'] == 'foo'
    assert rez['raw']['defer_startup_notifications'] == 'foo'
    assert hass_storage['alert2.storage']['data']['config']['defer_startup_notifications'] == 'foo'
    assert gad.topConfig['defer_startup_notifications'] == ['foo']
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defer_startup_notifications': '[  "foo"]' }})
    assert rez['rawUi']['defer_startup_notifications'] == '[  "foo"]'
    assert hass_storage['alert2.storage']['data']['config']['defer_startup_notifications'] == '[  "foo"]'
    assert gad.topConfig['defer_startup_notifications'] == ['foo']
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defer_startup_notifications': 'foo,bar' }})
    assert re.search('invalid boolean value', rez['error'])
    
    # Now try the default fields
    #
    # notifier
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': { 'notifier': '' }}})
    assert not 'notifier' in rez['rawUi']['defaults']
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': { 'notifier': 3 }}})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': { 'notifier': 'foo2' }}})
    assert rez['rawUi']['defaults']['notifier'] == 'foo2'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['notifier'] == 'foo2'
    assert isinstance(gad.topConfig['defaults']['notifier'], template_helper.Template)
    # foo2,foo3 ends up being interpreted as a single "notifier" with a funny name here.
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': { 'notifier': 'foo2,foo3' }}})
    assert isinstance(gad.topConfig['defaults']['notifier'], template_helper.Template)
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': { 'notifier': '[foo4,foo5 ]' }}})
    assert rez['rawUi']['defaults']['notifier'] == '[foo4,foo5 ]'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['notifier'] == '[foo4,foo5 ]'
    assert gad.topConfig['defaults']['notifier'] == ['foo4', 'foo5']
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert rez['raw']['defaults']['notifier'] == ['foo4','foo5']
    assert rez['rawUi']['defaults']['notifier'] == '[foo4,foo5 ]'
    #    Clearing notifier should remove it from the rawUi cfg
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': { 'notifier': '' }}})
    assert not 'notifier' in rez['rawUi']['defaults']
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert not 'notifier' in rez['rawUi']['defaults']

    # summary_notifier
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'summary_notifier': False} }})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'summary_notifier': 'false'} }})
    assert rez['rawUi']['defaults']['summary_notifier'] == 'false'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['summary_notifier'] == 'false'
    assert gad.topConfig['defaults']['summary_notifier'] == False
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'summary_notifier': 'ick'} }})
    assert rez['rawUi']['defaults']['summary_notifier'] == 'ick'
    assert isinstance(gad.topConfig['defaults']['summary_notifier'], template_helper.Template)
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'summary_notifier': '[foo,bar ]'} }})
    assert rez['rawUi']['defaults']['summary_notifier'] == '[foo,bar ]'
    assert gad.topConfig['defaults']['summary_notifier'] == ['foo','bar']
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'summary_notifier': '["foo","bar" ]'} }})
    assert rez['rawUi']['defaults']['summary_notifier'] == '["foo","bar" ]'
    assert gad.topConfig['defaults']['summary_notifier'] == ['foo','bar']

    # annotate_messages
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'annotate_messages': 'FAlse'} }})
    assert rez['rawUi']['defaults']['annotate_messages'] == 'FAlse'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['annotate_messages'] == 'FAlse'
    assert gad.topConfig['defaults']['annotate_messages'] == False

    # reminder_frequency_mins
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'reminder_frequency_mins': 3} }})
    assert re.search('non-string value', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'reminder_frequency_mins': '4'} }})
    assert rez['rawUi']['defaults']['reminder_frequency_mins'] == '4'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['reminder_frequency_mins'] == '4'
    assert gad.topConfig['defaults']['reminder_frequency_mins'] == [4]
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert rez['raw']['defaults']['reminder_frequency_mins'] == 4
    assert rez['rawUi']['defaults']['reminder_frequency_mins'] == '4'
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'reminder_frequency_mins': '-4'} }})
    assert re.search('be at least 0.01', rez['error'])
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'reminder_frequency_mins': '[5,6]'} }})
    assert rez['rawUi']['defaults']['reminder_frequency_mins'] == '[5,6]'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['reminder_frequency_mins'] == '[5,6]'
    assert gad.topConfig['defaults']['reminder_frequency_mins'] == [5,6]
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'reminder_frequency_mins': '["5","7"]'} }})
    assert rez['rawUi']['defaults']['reminder_frequency_mins'] == '["5","7"]'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['reminder_frequency_mins'] == '["5","7"]'
    assert gad.topConfig['defaults']['reminder_frequency_mins'] == [5,7]

    # throttle_fires_per_mins
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'throttle_fires_per_mins': ''} }})
    #   pick up the default val
    assert rez['raw']['defaults']['throttle_fires_per_mins'] == [1,2]
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'throttle_fires_per_mins': 'null'} }})
    assert rez['rawUi']['defaults']['throttle_fires_per_mins'] == 'null'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['throttle_fires_per_mins'] == 'null'
    assert rez['raw']['defaults']['throttle_fires_per_mins'] == None
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'throttle_fires_per_mins': '[3,5.2]'} }})
    assert rez['rawUi']['defaults']['throttle_fires_per_mins'] == '[3,5.2]'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['throttle_fires_per_mins'] == '[3,5.2]'
    assert rez['raw']['defaults']['throttle_fires_per_mins'] == [3, 5.2]

    # priority
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'priority': ''} }})
    #   pick up the default val
    assert rez['raw']['defaults']['priority'] == 'medium'
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'priority': 'high'} }})
    assert rez['rawUi']['defaults']['priority'] == 'high'
    assert hass_storage['alert2.storage']['data']['config']['defaults']['priority'] == 'high'
    assert rez['raw']['defaults']['priority'] == 'high'
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': { 'defaults': {'priority': 'foo'} }})
    assert re.search('must be one of', rez['error'])


    
    ########################
    # Now try full save
    uiCfg = { 'defaults' : {
        'notifier' : 'n2',
        'summary_notifier' : 'sn2',
        'reminder_frequency_mins': '[4]',
        'throttle_fires_per_mins': '[1,3]',
        'priority': 'high',
    },
              'skip_internal_errors': 'true',
              'notifier_startup_grace_secs': '5',
              'defer_startup_notifications': 'True',
             }
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': uiCfg })
    assert rez['rawUi'] == uiCfg
    assert hass_storage['alert2.storage']['data']['config'] == uiCfg
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert rez['rawUi'] == uiCfg
    # And remove all fields and make sure config shrinks down
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': {} })
    assert rez['rawUi'] == { 'defaults': {} }
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert rez['rawUi'] == { 'defaults': {} }
    
    
async def test_defaults2(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2' : {
        'defaults' : {
            'notifier' : 'n',                 # yaml comes through
            #'summary_notifier' : 'sn',   underderlying default comes through
            #'reminder_frequency_mins': [3], UI overrides base
            'throttle_fires_per_mins': [1,2]  # UI overrides yaml
            # 'priority' - underlying default comes through
        },
        'alerts': [
            { 'domain': 'test', 'name': 't1', 'condition': 'off' }
        ],
        #'skip_internal_errors': True,   UI overrides base
        'notifier_startup_grace_secs': 4, # UI overrides yaml
        'defer_startup_notifications': True, # yaml comes through
    } }
    cfga = cfg['alert2']
    uiCfg = { 'defaults' : { 'reminder_frequency_mins': '[4]',
                              'throttle_fires_per_mins': '[5,6]',
                             },
               'skip_internal_errors': 'true',
               'notifier_startup_grace_secs': '7',
              }
    hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                       'data': { 'config': uiCfg } }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)
    
    # Test top-level flags were set
    assert hass.states.get('alert2.alert2_error') is None # skip_internal_errors
    cfga = cfg['alert2']
    assert gad.delayedNotifierMgr.notifier_startup_grace_secs == float(uiCfg['notifier_startup_grace_secs'])
    assert gad.delayedNotifierMgr.defer_startup_notifications == cfga['defer_startup_notifications']
    t1 = gad.alerts['test']['t1']
    # and check all the defaults
    assert t1._notifier_list_template.template == cfga['defaults']['notifier']
    assert t1._summary_notifier == False
    assert t1.reminder_frequency_mins == [4] # uiCfg['defaults']['reminder_frequency_mins']
    assert t1.movingSum.maxCount == 5 # uiCfg['defaults']['throttle_fires_per_mins'][0]
    assert t1.movingSum.intervalSecs == 60*6 # uiCfg['defaults']['throttle_fires_per_mins'][1]*60
    assert t1._priority == 'low'
    
    # Check how defaults are sent to UI
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert rez == {'rawYaml': {'defaults': {'reminder_frequency_mins': [60], 'notifier': 'n',
                                            'summary_notifier': False, 'annotate_messages': True,
                                            'throttle_fires_per_mins': [1, 2], 'priority': 'low' },
                               'skip_internal_errors': False, 'notifier_startup_grace_secs': 4,
                               'defer_startup_notifications': True},
                   'raw': {'defaults': {'reminder_frequency_mins': [4], 'notifier': 'n',
                                        'summary_notifier': False, 'annotate_messages': True,
                                        'throttle_fires_per_mins': [5, 6], 'priority': 'low' },
                           'skip_internal_errors': True, 'notifier_startup_grace_secs': 7,
                           'defer_startup_notifications': True},
                   'rawUi': {'defaults': {'reminder_frequency_mins': '[4]',
                                          'throttle_fires_per_mins': '[5,6]'},
                             'skip_internal_errors': 'true', 'notifier_startup_grace_secs': '7'}}

    
async def test_render_v(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2': {} }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)

    # notifier
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '' })
    assert rez == { 'rez': [] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': 'foo' })
    assert rez == { 'rez': ['foo'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '"foo"' })
    assert rez == { 'rez': ['foo'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '{{ "a"+"b"}}' })
    assert rez == { 'rez': ['ab'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '{{ ["a"+"b", "c"] }}' })
    assert rez == { 'rez': ['ab', 'c'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '\'{{ "a"+"b"}}\'' })
    assert rez == { 'rez': ['ab'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '[aa,bb]' })
    assert rez == { 'rez': ['aa','bb'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'notifier', 'txt': '["aa",bb]' })
    assert rez == { 'rez': ['aa','bb'] }

    # summary_notifier
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': 'foo' })
    assert rez == { 'rez': ['foo'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': '"foo"' })
    assert rez == { 'rez': ['foo'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': '{{ "a"+"b"}}' })
    assert rez == { 'rez': ['ab'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': '{{ ["a"+"b", "c"] }}' })
    assert rez == { 'rez': ['ab', 'c'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': '\'{{ "a"+"b"}}\'' })
    assert rez == { 'rez': ['ab'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': '[aa,bb]' })
    assert rez == { 'rez': ['aa','bb'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': '["aa",bb]' })
    assert rez == { 'rez': ['aa','bb'] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': 'false' })
    assert rez == { 'rez': False }
    rez = await tpost("/api/alert2/renderValue", {'name': 'summary_notifier', 'txt': 'on' })
    assert rez == { 'rez': True }

    # annotate_messages
    rez = await tpost("/api/alert2/renderValue", {'name': 'annotate_messages', 'txt': 'yes' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'annotate_messages', 'txt': '{{ true }}' })
    assert re.search('invalid boolean value', rez['error'])

    # manual_off
    rez = await tpost("/api/alert2/renderValue", {'name': 'manual_off', 'txt': 'yes' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'manual_off', 'txt': '{{ true }}' })
    assert re.search('invalid boolean value', rez['error'])

    # manual_on
    rez = await tpost("/api/alert2/renderValue", {'name': 'manual_on', 'txt': 'yes' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'manual_on', 'txt': '{{ true }}' })
    assert re.search('invalid boolean value', rez['error'])

    # reminder_frequency_mins
    rez = await tpost("/api/alert2/renderValue", {'name': 'reminder_frequency_mins', 'txt': '3' })
    assert rez == { 'rez': [3] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'reminder_frequency_mins', 'txt': '[3,4]' })
    assert rez == { 'rez': [3,4] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'reminder_frequency_mins', 'txt': '"[3,5]"' })
    assert re.search('expected float', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'reminder_frequency_mins', 'txt': '-3' })
    assert re.search('must be at least', rez['error'])

    # supersedes
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '' })
    assert rez == { 'rez': [] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '[]' })
    assert rez == { 'rez': [] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '{{ {"domain":"x","name":"y"} }}' })
    assert rez == { 'rez': [ { 'domain': 'x', 'name': 'y'} ] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '{{ [ {"domain":"x","name":"y"} ] }}' })
    assert rez == { 'rez': [ { 'domain': 'x', 'name': 'y'} ] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '[ { "foo":3 } ]' })
    assert re.search('extra keys not allowed', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '[ { "domain":"d","name":"x" } ]' })
    assert rez == { 'rez': [ { 'domain':'d', 'name':'x' } ] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'supersedes', 'txt': '[ { "domain":"d","name":"x" },{ "domain":"d","name":"x2" } ]' })
    assert rez == { 'rez': [ { 'domain':'d', 'name':'x' },{ 'domain':'d', 'name':'x2' } ] }
    
    # throttle_fires_per_mins
    rez = await tpost("/api/alert2/renderValue", {'name': 'throttle_fires_per_mins', 'txt': '[2,4]' })
    assert rez == { 'rez': [2,4] }
    #    problem is that "1" is a string, not an int
    rez = await tpost("/api/alert2/renderValue", {'name': 'throttle_fires_per_mins', 'txt': '["1",4]' })
    assert re.search('not a valid value', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'throttle_fires_per_mins', 'txt': 'null' })
    assert rez == { 'rez': None }
    rez = await tpost("/api/alert2/renderValue", {'name': 'throttle_fires_per_mins', 'txt': '[-3,4]' })
    assert re.search('not a valid value', rez['error'])

    # priority
    rez = await tpost("/api/alert2/renderValue", {'name': 'priority', 'txt': 'low' })
    assert rez == { 'rez': 'low' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'priority', 'txt': 'foo' })
    assert re.search('must be one of', rez['error'])
    
    # friendly_name
    rez = await tpost("/api/alert2/renderValue", {'name': 'friendly_name', 'txt': 'joe  ' })
    assert rez == { 'rez': 'joe' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'friendly_name', 'txt': '{{ "joe"+"sss" }}' })
    assert rez == { 'rez': 'joesss' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'friendly_name', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }
    
    # title
    rez = await tpost("/api/alert2/renderValue", {'name': 'title', 'txt': 'joe  ' })
    assert rez == { 'rez': 'joe' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'title', 'txt': '{{ "joe"+"sss" }}' })
    assert rez == { 'rez': 'joesss' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'title', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }

    # target
    rez = await tpost("/api/alert2/renderValue", {'name': 'target', 'txt': 'joe  ' })
    assert rez == { 'rez': 'joe' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'target', 'txt': '{{ "joe"+"sss" }}' })
    assert rez == { 'rez': 'joesss' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'target', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }

    # data
    rez = await tpost("/api/alert2/renderValue", {'name': 'data', 'txt': '{ a: b, c: "d" }' })
    assert rez == { 'rez': { 'a': 'b', 'c': 'd' } }
    rez = await tpost("/api/alert2/renderValue", {'name': 'data', 'txt': '"{ e:f}"' })
    assert re.search('expected dict', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'data', 'txt': '{}' })
    assert rez == { 'rez': {} }

    # domain
    rez = await tpost("/api/alert2/renderValue", {'name': 'domain', 'txt': 'foo' })
    assert rez == { 'rez': 'foo' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'domain', 'txt': '"bar"' })
    assert rez == { 'rez': 'bar' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'domain', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }

    # name
    rez = await tpost("/api/alert2/renderValue", {'name': 'name', 'txt': 'foo' })
    assert rez == { 'rez': 'foo' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'name', 'txt': '"bar"' })
    assert rez == { 'rez': 'bar' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'name', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }

    # message
    rez = await tpost("/api/alert2/renderValue", {'name': 'message', 'txt': 'foo' })
    assert rez == { 'rez': 'foo' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'message', 'txt': '{ "ick' })
    assert rez == { 'rez': '{ "ick' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'message', 'txt': '"bar"' })
    assert rez == { 'rez': 'bar' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'message', 'txt': '{{ "joe"+"ggg" }}' })
    assert rez == { 'rez': 'joeggg' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'message', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }

    # done_message
    rez = await tpost("/api/alert2/renderValue", {'name': 'done_message', 'txt': 'foo' })
    assert rez == { 'rez': 'foo' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'done_message', 'txt': '"bar"' })
    assert rez == { 'rez': 'bar' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'done_message', 'txt': '{{ "joe"+"ggg" }}' })
    assert rez == { 'rez': 'joeggg' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'done_message', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }
    
    # trigger
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger', 'txt': "[{'platform':'state','entity_id':'sensor.zz'}]" })
    assert rez == { 'rez': [{'platform':'state','entity_id':'sensor.zz'}] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger', 'txt': "[{'trigger':'template','value_template':'{{ true }}'}]" })
    assert rez == { 'rez': [{'platform':'template','value_template':'{{ true }}'}] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger', 'txt': "yes" })
    assert re.search("'bool' is not iterable", rez['error'])

    # trigger_on
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger_on', 'txt': "[{'platform':'state','entity_id':'sensor.zz'}]" })
    assert rez == { 'rez': [{'platform':'state','entity_id':'sensor.zz'}] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger_on', 'txt': "[{'trigger':'template','value_template':'{{ true }}'}]" })
    assert rez == { 'rez': [{'platform':'template','value_template':'{{ true }}'}] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger_on', 'txt': "yes" })
    assert re.search("'bool' is not iterable", rez['error'])
    
    # trigger_off
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger_off', 'txt': "[{'platform':'state','entity_id':'sensor.zz'}]" })
    assert rez == { 'rez': [{'platform':'state','entity_id':'sensor.zz'}] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger_off', 'txt': "[{'trigger':'template','value_template':'{{ true }}'}]" })
    assert rez == { 'rez': [{'platform':'template','value_template':'{{ true }}'}] }
    rez = await tpost("/api/alert2/renderValue", {'name': 'trigger_off', 'txt': "yes" })
    assert re.search("'bool' is not iterable", rez['error'])
    
    # condition
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition', 'txt': 'on' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition', 'txt': '{{ "n" + "o" }}' })
    assert rez == { 'rez': False }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition', 'txt': '{{ ggg }}' , 'extraVars': { 'ggg': 'yes' }})
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition', 'txt': '{{ ggg }}' , 'extraVars': { 'ggg': 'no' }})
    assert rez == { 'rez': False }
    await setAndWait(hass, 'sensor.a', 'on')
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition', 'txt': 'sensor.a' })
    assert rez == { 'rez': True }
    await setAndWait(hass, 'sensor.a', 'off')
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition', 'txt': 'sensor.a' })
    assert rez == { 'rez': False }

    # condition_on
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition_on', 'txt': 'on' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition_on', 'txt': '{{ "n" + "o" }}' })
    assert rez == { 'rez': False }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition_on', 'txt': '{{ ggg }}' , 'extraVars': { 'ggg': 'yes' }})
    assert rez == { 'rez': True }

    # condition_off
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition_off', 'txt': 'on' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition_off', 'txt': '{{ "n" + "o" }}' })
    assert rez == { 'rez': False }
    rez = await tpost("/api/alert2/renderValue", {'name': 'condition_off', 'txt': '{{ ggg }}' , 'extraVars': { 'ggg': 'yes' }})
    assert rez == { 'rez': True }

    # early_start
    rez = await tpost("/api/alert2/renderValue", {'name': 'early_start', 'txt': 'yes' })
    assert rez == { 'rez': True }
    rez = await tpost("/api/alert2/renderValue", {'name': 'early_start', 'txt': '{{ true }}' })
    assert re.search('invalid boolean value', rez['error'])

    # threshold: value
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.value', 'txt': 'foo' })
    assert re.search('not a float', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.value', 'txt': '3' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.value', 'txt': '"3"' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.value', 'txt': '{{ 5+6 }}' })
    assert rez == { 'rez': 11 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.value', 'txt': '{{ 5 + ggg }}' , 'extraVars': { 'ggg': 7 }})
    assert rez == { 'rez': 12 }

    # threshold: hysteresis
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.hysteresis', 'txt': 'foo' })
    assert re.search('expected float', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.hysteresis', 'txt': '-3' })
    assert re.search('be at least', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.hysteresis', 'txt': '3' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.hysteresis', 'txt': '"3"' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.hysteresis', 'txt': '{{ 5+6 }}' })
    assert re.search('expected float', rez['error'])

    # threshold: minimum
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.minimum', 'txt': 'foo' })
    assert re.search('expected float', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.minimum', 'txt': '3' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.minimum', 'txt': '"3"' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.minimum', 'txt': '{{ 5+6 }}' })
    assert re.search('expected float', rez['error'])

    # threshold: maximum
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.maximum', 'txt': 'foo' })
    assert re.search('expected float', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.maximum', 'txt': '3' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.maximum', 'txt': '"3"' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'threshold.maximum', 'txt': '{{ 5+6 }}' })
    assert re.search('expected float', rez['error'])

    # delay_on_secs
    rez = await tpost("/api/alert2/renderValue", {'name': 'delay_on_secs', 'txt': 'foo' })
    assert re.search('expected float', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'delay_on_secs', 'txt': '-3' })
    assert re.search('be at least', rez['error'])
    rez = await tpost("/api/alert2/renderValue", {'name': 'delay_on_secs', 'txt': '3' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'delay_on_secs', 'txt': '"3"' })
    assert rez == { 'rez': 3 }
    rez = await tpost("/api/alert2/renderValue", {'name': 'delay_on_secs', 'txt': '{{ 5+6 }}' })
    assert re.search('expected float', rez['error'])

    # generator_name
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator_name', 'txt': 'foo' })
    assert rez == { 'rez': 'foo' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator_name', 'txt': '"bar"' })
    assert rez == { 'rez': 'bar' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator_name', 'txt': '{{"bar"}}' })
    assert re.search('Illegal characters', rez['error'])

    # generator
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': 'foo' })
    assert rez == { 'rez': {'list': ['foo'], 'len': 1, 'firstElemVars': {'genRaw': 'foo', 'genElem': 'foo'}} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': '"fooz"' })
    assert rez == { 'rez': {'list': ['fooz'], 'len': 1, 'firstElemVars': {'genRaw': 'fooz', 'genElem': 'fooz'}} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': '{{ "a"+"b"}}' })
    assert rez == { 'rez': {'list': ['ab'], 'len': 1, 'firstElemVars': {'genRaw': 'ab', 'genElem': 'ab'}} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': '{{ ["a"+"b", "c"] }}' })
    assert rez == { 'rez': {'list': ['ab','c'], 'len': 2, 'firstElemVars': {'genRaw': 'ab', 'genElem': 'ab'}} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': '\'{{ "a"+"b"}}\'' })
    assert rez == { 'rez': {'list': ['ab'], 'len': 1, 'firstElemVars': {'genRaw': 'ab', 'genElem': 'ab'}} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': '[aa,bb]' })
    assert rez == { 'rez': {'list': ['aa','bb'], 'len': 2, 'firstElemVars': {'genRaw': 'aa', 'genElem': 'aa'}} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': '["aa",bb]' })
    assert rez == { 'rez': {'list': ['aa','bb'], 'len': 2, 'firstElemVars': {'genRaw': 'aa', 'genElem': 'aa'}} }
    await setAndWait(hass, 'sensor.ff', 'ick')
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': 'sensor.ff' })
    assert rez == { 'rez': {'list': ['sensor.ff'], 'len': 1, 'firstElemVars': {'genRaw': 'sensor.ff', 'genEntityId': 'sensor.ff'}} }
    await setAndWait(hass, 'sensor.ff2', 'ick2')
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': "{{ states.sensor|selectattr('entity_id', 'match', 'sensor.ff.*') | map(attribute='entity_id')|list }}" })
    assert rez == { 'rez': {'list': ['sensor.ff', 'sensor.ff2'], 'len': 2,
                            'firstElemVars': {'genRaw': 'sensor.ff', 'genEntityId': 'sensor.ff' }} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': "{{ states|entity_regex('sensor.(ff.*)')|list }}" })
    assert rez == { 'rez': {'list': [{'genEntityId':'sensor.ff', 'genGroups':['ff']},
                                     {'genEntityId':'sensor.ff2', 'genGroups':['ff2']}], 'len': 2,
                            'firstElemVars': {'genRaw': {'genEntityId':'sensor.ff', 'genGroups':['ff']}, 'genEntityId': 'sensor.ff', 'genGroups': ['ff'] }} }
    rez = await tpost("/api/alert2/renderValue", {'name': 'generator', 'txt': "{{ {'a':3, 'b':'ff' } }}"})
    _LOGGER.warning(rez)
    assert rez == { 'rez': {'list': [{'a':3, 'b':'ff' }], 'len': 1,
                            'firstElemVars': {'genRaw': {'a':3, 'b':'ff' }, 'a': 3, 'b': 'ff' }} }

    # display_msg
    rez = await tpost("/api/alert2/renderValue", {'name': 'display_msg', 'txt': 'joe  ' })
    assert rez == { 'rez': 'joe' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'display_msg', 'txt': '{{ "joe"+"sss" }}' })
    assert rez == { 'rez': 'joesss' }
    rez = await tpost("/api/alert2/renderValue", {'name': 'display_msg', 'txt': '{{ "joe"+ggg }}' , 'extraVars': { 'ggg': 'yay' }})
    assert rez == { 'rez': 'joeyay' }




    
async def test_validate(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2': {} }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)

    # condition alert
    rez = await tpost("/api/alert2/manageAlert", {'validate': { 'domain':'d', 'name':'n', 'condition':'on' } })
    assert rez == {}
    rez = await tpost("/api/alert2/manageAlert", {'validate': { 'domain':'d', 'name':'n', 'condition':'on',
                                                                'throttle_fires_per_mins':'[3,4]' } })
    assert rez == {}
    rez = await tpost("/api/alert2/manageAlert", {'validate': { 'domain':'d', 'name':'n', 'condition':'on',
                                                                'threshold': { 'value': '4', 'hysteresis': '5', 'minimum': '6' } }})
    assert rez == {}
    
    # generator
    rez = await tpost("/api/alert2/manageAlert", {'validate': { 'domain':'d', 'name':'n', 'condition':'on',
                                                                'generator': 'foo' } })
    assert re.search('required key not provided', rez['error'])
    rez = await tpost("/api/alert2/manageAlert", {'validate': { 'domain':'d', 'name':'n', 'condition':'on',
                                                                'generator': 'foo', 'generator_name': 'ick' } })
    assert rez == {}

    # event alert
    rez = await tpost("/api/alert2/manageAlert", {'validate': { 'domain':'d', 'name':'n', 'condition':'on',
                                                                'trigger': "[{'platform':'state','entity_id':'sensor.zz'}]" } })
    assert rez == {}


async def test_create(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2': {} }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)

    await setAndWait(hass, 'sensor.a', 'off')
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n1', 'condition':'sensor.a' } })
    assert rez == {}
    n1 = gad.alerts['d']['n1']
    assert hass.states.get('alert2.d_n1').state == 'off'
    assert hass_storage['alert2.storage']['data']['config']['alerts'][0]['name'] == 'n1'
    assert service_calls.isEmpty()
    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'd.n1: turned on')
    await setAndWait(hass, 'sensor.a', 'off')
    service_calls.popNotifyEmpty('persistent_notification', 'd.n1: turned off')

    # Create dup should fail
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n1', 'condition':'sensor.a' } })
    assert re.search('Duplicate declaration', rez['error'])
    # validation fails
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n2' } })
    assert re.search('Must specify', rez['error'])
    # bad delete
    resp = await client.post("/api/alert2/manageAlert", json={'delete': { 'domain':'d' } })
    assert resp.status == 400
    # delete nonexistent
    rez = await tpost("/api/alert2/manageAlert", {'delete': { 'domain':'d', 'name':'n3' } })
    assert re.search('can not find existing', rez['error'])
    assert service_calls.isEmpty()

    # load
    rez = await tpost("/api/alert2/manageAlert", {'load': { 'domain':'d', 'name':'n3' } })
    assert re.search('alert not found', rez['error'])
    rez = await tpost("/api/alert2/manageAlert", {'load': { 'domain':'d', 'name':'n1' } })
    assert rez == {'condition': 'sensor.a', 'domain': 'd', 'name': 'n1'} 
    assert service_calls.isEmpty()
    
    # delete alert
    rez = await tpost("/api/alert2/manageAlert", {'delete': { 'domain':'d', 'name':'n1' } })
    assert rez == {}
    assert gad.alerts == {}
    assert hass.states.get('alert2.d_n1') == None
    assert 'alerts' not in hass_storage['alert2.storage']['data']['config']
    assert service_calls.isEmpty()

    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n1', 'condition':'sensor.a' } })
    assert rez == {}
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n2', 'condition':'sensor.a' } })
    assert rez == {}
    assert service_calls.isEmpty()

    # Search
    rez = await tpost("/api/alert2/manageAlert", {'search': { 'str':'' } })
    assert rez == { 'results': [
        { 'domain':'d', 'name':'n1', 'id':'alert2.d_n1' },
        { 'domain':'d', 'name':'n2', 'id':'alert2.d_n2' }
    ]}
    rez = await tpost("/api/alert2/manageAlert", {'search': { 'str':'d_n' } })
    assert rez == { 'results': [
        { 'domain':'d', 'name':'n1', 'id':'alert2.d_n1' },
        { 'domain':'d', 'name':'n2', 'id':'alert2.d_n2' }
    ]}
    rez = await tpost("/api/alert2/manageAlert", {'search': { 'str':'alert2.d_n' } })
    assert rez == { 'results': [
        { 'domain':'d', 'name':'n1', 'id':'alert2.d_n1' },
        { 'domain':'d', 'name':'n2', 'id':'alert2.d_n2' }
    ]}
    rez = await tpost("/api/alert2/manageAlert", {'search': { 'str':'d_n1' } })
    assert rez == { 'results': [
        { 'domain':'d', 'name':'n1', 'id':'alert2.d_n1' },
    ]}
    rez = await tpost("/api/alert2/manageAlert", {'search': { 'str':'d_n2' } })
    assert rez == { 'results': [
        { 'domain':'d', 'name':'n2', 'id':'alert2.d_n2' },
    ]}
    rez = await tpost("/api/alert2/manageAlert", {'search': { 'str':'d_n3' } })
    assert rez == { 'results': [] }
    
    # Update
    assert set(gad.alerts['d'].keys()) == set([ 'n1', 'n2' ])
    assert hass.states.get('alert2.d_n1').state == 'off'
    assert hass.states.get('alert2.d_n2').state == 'off'
    # Redo an alert
    rez = await tpost("/api/alert2/manageAlert", {'update': { 'domain':'d', 'name':'n1', 'condition':'off', 'delay_on_secs':'4', 'threshold': { 'value': '4', 'hysteresis': '5', 'minimum': '6' } } })
    assert rez == {}
    assert set(gad.alerts['d'].keys()) == set([ 'n1', 'n2' ])
    assert hass.states.get('alert2.d_n1').state == 'off'
    rez = await tpost("/api/alert2/manageAlert", {'load': { 'domain':'d', 'name':'n1' } })
    assert rez == {'condition': 'off', 'domain': 'd', 'name': 'n1', 'delay_on_secs':'4',
                   'threshold': { 'value': '4', 'hysteresis': '5', 'minimum': '6' }}
    # delay_on_secs goes away when deleted
    rez = await tpost("/api/alert2/manageAlert", {'update': { 'domain':'d', 'name':'n1', 'condition':'off',
                                                              'threshold': { 'value': '4', 'hysteresis': '5', 'maximum': '6' }} })
    assert rez == {}
    assert set(gad.alerts['d'].keys()) == set([ 'n1', 'n2' ])
    assert hass.states.get('alert2.d_n1').state == 'off'
    rez = await tpost("/api/alert2/manageAlert", {'load': { 'domain':'d', 'name':'n1' } })
    assert rez == {'condition': 'off', 'domain': 'd', 'name': 'n1',
                   'threshold': { 'value': '4', 'hysteresis': '5', 'maximum': '6' }}
    # threshold also disappears
    rez = await tpost("/api/alert2/manageAlert", {'update': { 'domain':'d', 'name':'n1', 'condition':'false' } })
    assert rez == {}
    assert set(gad.alerts['d'].keys()) == set([ 'n1', 'n2' ])
    assert hass.states.get('alert2.d_n1').state == 'off'
    rez = await tpost("/api/alert2/manageAlert", {'load': { 'domain':'d', 'name':'n1' } })
    assert rez == {'condition': 'false', 'domain': 'd', 'name': 'n1' }
    
    # can't create new alert via update
    rez = await tpost("/api/alert2/manageAlert", {'update': { 'domain':'d', 'name':'n3', 'condition':'off' } })
    assert re.search('can not find existing', rez['error'])

async def test_create2(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2': {} }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)

    await setAndWait(hass, 'sensor.a', 'off')

    # Create should do data prep
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n2', 'condition':'sensor.a',
                                                              'throttle_fires_per_mins': '[3,4]'} })
    assert rez == {}
    # Update should do data prep
    rez = await tpost("/api/alert2/manageAlert", {'update': { 'domain':'d', 'name':'n2', 'condition':'sensor.a',
                                                              'throttle_fires_per_mins': '[3,5]'} })
    assert rez == {}
    rez = await tpost("/api/alert2/manageAlert", {'delete': { 'domain':'d', 'name':'n2' } })
    assert rez == {}

    #######
    # try lifecycle ops with generators
    #
    rez = await tpost("/api/alert2/manageAlert", {'create':
            { 'domain':'d', 'name':'{{genElem}}', 'condition':'sensor.a', 'generator_name':'g1', 'generator': 'n5' } })
    assert rez == {}
    n5 = gad.alerts['d']['n5']
    g1 = gad.generators['g1']
    assert set(gad.alerts['d'].keys()) == set([ 'n5' ])
    assert hass.states.get('alert2.d_n5').state == 'off'
    assert hass.states.get('sensor.alert2generator_g1').state == '1'
    assert hass_storage['alert2.storage']['data']['config']['alerts'][0]['name'] == '{{genElem}}'
    assert service_calls.isEmpty()

    # try load
    rez = await tpost("/api/alert2/manageAlert", {'load': { 'domain': GENERATOR_DOMAIN, 'name':'g1' } })
    assert rez == { 'domain':'d', 'name':'{{genElem}}', 'condition':'sensor.a', 'generator_name':'g1', 'generator': 'n5' }
    
    # same gen is duplicate
    rez = await tpost("/api/alert2/manageAlert", {'create':
            { 'domain':'d', 'name':'{{genElem}}2', 'condition':'sensor.a', 'generator_name':'g1', 'generator': 'n5' } })
    assert re.search('Duplicate generator', rez['error'])

    # Update to different name doesn't leave behind n5 entity from first generation
    rez = await tpost("/api/alert2/manageAlert", {'update':
            { 'domain':'d', 'name':'{{genElem}}z', 'condition':'sensor.a', 'generator_name':'g1', 'generator': 'n5' } })
    assert rez == {}
    assert set(gad.alerts['d'].keys()) == set([ 'n5z' ])
    assert hass.states.get('alert2.d_n5') == None
    assert hass.states.get('alert2.d_n5z').state == 'off'

    # can't delete non-existent
    rez = await tpost("/api/alert2/manageAlert", {'update':
            { 'domain':'d', 'name':'{{genElem}}z', 'condition':'sensor.a', 'generator_name':'g2', 'generator': 'n5' } })
    assert re.search('can not find existing', rez['error'])

    # delete generator removes alerts with it
    assert 'alerts' in hass_storage['alert2.storage']['data']['config']
    assert hass.states.get('sensor.alert2generator_g1').state == '1'
    rez = await tpost("/api/alert2/manageAlert", {'delete': { 'domain': GENERATOR_DOMAIN, 'name': 'g1' } })
    assert rez == {}
    assert hass.states.get('sensor.alert2generator_g1') == None
    assert hass.states.get('alert2.d_n5z') == None
    assert gad.generators == {}
    assert gad.alerts == {}
    assert not 'alerts' in hass_storage['alert2.storage']['data']['config']

async def test_create3(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2': {} }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)

    # create n1
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n1', 'condition':'off' } })
    assert rez == {}
    n1 = gad.alerts['d']['n1']
    assert hass.states.get('alert2.d_n1').state == 'off'

    # do update that fails validate.  Alert should still exist
    rez = await tpost("/api/alert2/manageAlert", {'update': { 'domain':'d', 'name':'n1', 'condition':'{{ick' } })
    assert re.search('invalid template', rez['error'])
    n1 = gad.alerts['d']['n1']
    assert hass.states.get('alert2.d_n1').state == 'off'
    
    
async def test_reload(hass, service_calls, hass_client, hass_storage, monkeypatch):
    cfg = { 'alert2' : {
    } }
    uiCfg = { 'defaults' : { },
              'alerts': [
                  { 'domain': 'd', 'name': 'n1', 'condition':'off', 'throttle_fires_per_mins': '[3,4]' }
              ]
             }
    hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                       'data': { 'config': uiCfg } }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)
    assert hass.states.get('alert2.d_n1').state == 'off'
    assert set(gad.alerts['d'].keys()) == set([ 'n1' ])

    rez = await tpost("/api/alert2/manageAlert", {'create':
            { 'domain':'d', 'name':'n2', 'condition':'off', 'throttle_fires_per_mins': '[4,5]' } })
    assert rez == {}
    assert set(gad.alerts['d'].keys()) == set([ 'n1', 'n2' ])
    assert service_calls.isEmpty()

    async def fake_cfg(thass):
        return cfg
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    assert set(gad.alerts['d'].keys()) == set([ 'n1', 'n2' ])

async def test_conflict1(hass, service_calls, hass_client, hass_storage):
    # Make sure UI alert can not overwrite a YAML alert.
    cfg = { 'alert2': {
        'alerts': [
            { 'domain': 'd', 'name': 'n1', 'condition':'off' },
            { 'domain': 'd', 'name': 'n2', 'condition':'off' }
        ] } }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)
    rez = await tpost("/api/alert2/manageAlert", {'create': { 'domain':'d', 'name':'n1', 'condition':'on' } })
    assert re.search('Duplicate declaration.*name=n1', rez['error'])
    n1 = gad.alerts['d']['n1']
    assert hass.states.get('alert2.d_n1').state == 'off'

    rez = await tpost("/api/alert2/manageAlert", {'create': {
        'domain':'d', 'name':'{{genElem}}', 'condition':'on', 'generator_name': 'g1', 'generator': 'n2' } })
    assert rez == {}
    service_calls.popNotifyEmpty('persistent_notification', 'Duplicate declaration.*name=n2')
    n1 = gad.alerts['d']['n2']
    assert hass.states.get('alert2.d_n2').state == 'off'

    rez = await tpost("/api/alert2/manageAlert", {'delete': { 'domain':'d', 'name':'n1' } })
    assert re.search('can not find', rez['error'])
    n1 = gad.alerts['d']['n1']
    assert hass.states.get('alert2.d_n1').state == 'off'
    
async def test_conflict2(hass, service_calls, hass_client, hass_storage):
    # Make sure UI alert can not overwrite a YAML alert at startup
    cfg = { 'alert2': {
        'alerts': [
            { 'domain': 'd', 'name': 'n1', 'condition':'off' }
        ] } }
    uiCfg = { 'defaults' : { },
              'alerts': [
                  { 'domain': 'd', 'name': 'n1', 'condition':'on' }
              ]
             }
    hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                       'data': { 'config': uiCfg } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    gad = hass.data[DOMAIN]
    service_calls.popNotifyEmpty('persistent_notification', 'Duplicate declaration.*name=n1')
    n1 = gad.alerts['d']['n1']
    assert hass.states.get('alert2.d_n1').state == 'off'

async def checkNoMsg(aclient):
    with pytest.raises(TimeoutError) as excinfo:
        async with asyncio.timeout(0.05):
            msg = await aclient.receive_json()
async def test_display_msg(hass, service_calls, hass_client, hass_ws_client, monkeypatch):
    async def getEvent(aclient, msg_id, rtxt):
        msg = await aclient.receive_json()
        await hass.async_block_till_done()
        assert service_calls.isEmpty()
        assert msg["id"] == msg_id
        assert msg["type"] == "event"
        result = msg["event"]['rendered']
        assert result == rtxt
                
    await setAndWait(hass, 'sensor.a', '')
    cfg = { 'alert2': {
        'alerts': [
            { 'domain': 'd', 'name': 'n2', 'condition':'off', 'display_msg': '{{ states("sensor.a") }}' },
            { 'domain': 'd', 'name': 'n3', 'condition':'off', 'display_msg': None },
        ]} }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # HA hasn't started yet
    
    websocket_client2 = await hass_ws_client(hass)
    msg_id2 = 5
    await websocket_client2.send_json({ "id": msg_id2, "type": "alert2_watch_display_msg",
                                       'domain': 'd', 'name': 'n2' } )
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # Now get reply from server
    msg = await websocket_client2.receive_json()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    #_LOGGER.warning(f'first resp {msg}')
    assert msg["type"] == wsapi.TYPE_RESULT
    assert msg["success"], msg['error']
    assert msg["result"] is None
    await checkNoMsg(websocket_client2)

    # HA starts
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()

    # Should now get event
    await getEvent(websocket_client2, msg_id2, '')
    await checkNoMsg(websocket_client2)
    
    websocket_client = await hass_ws_client(hass)
    msg_id = 6
    await websocket_client.send_json({ "id": msg_id, "type": "alert2_watch_display_msg",
                                       'domain': 'd', 'name': 'n2' } )
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    # Now get reply from server
    await getEvent(websocket_client, msg_id, '')
    
    async with asyncio.timeout(0.1):
        msg = await websocket_client.receive_json()
    assert msg["type"] == wsapi.TYPE_RESULT
    assert msg["success"], msg['error']
    assert msg["result"] is None
    # Should be no more messages
    await checkNoMsg(websocket_client)
    
    # Now if template changes, should get update msg
    await setAndWait(hass, 'sensor.a', 'bb')
    async with asyncio.timeout(0.1):
        await getEvent(websocket_client, msg_id, 'bb')
    await checkNoMsg(websocket_client)
    # and check client2
    async with asyncio.timeout(0.1):
        await getEvent(websocket_client2, msg_id2, 'bb')
    await checkNoMsg(websocket_client2)

    # Should get update msg even if empty
    await setAndWait(hass, 'sensor.a', '')
    async with asyncio.timeout(0.1):
        await getEvent(websocket_client, msg_id, '')
    await checkNoMsg(websocket_client)
    # and check client2
    async with asyncio.timeout(0.1):
        await getEvent(websocket_client2, msg_id2, '')
    await checkNoMsg(websocket_client2)

    # n3 has display_msg set to None, so should not get any updates
    websocket_client3 = await hass_ws_client(hass)
    msg_id3 = 7
    await websocket_client3.send_json({ "id": msg_id3, "type": "alert2_watch_display_msg",
                                       'domain': 'd', 'name': 'n3' } )
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    async with asyncio.timeout(0.1):
        msg = await websocket_client3.receive_json()
    assert msg["type"] == wsapi.TYPE_RESULT
    assert msg['error']['code'] == 'no_display_msg'

    # Should be no more messages
    await checkNoMsg(websocket_client)
    await checkNoMsg(websocket_client2)

    # Now reload YAML, should get updated messages
    async def fake_cfg(thass):
        return cfg
    cfg['alert2']['alerts'][0]['display_msg'] = '{{ states("sensor.a") }}z'
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        _LOGGER.info(f'requesting reload')
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    async with asyncio.timeout(0.1):
        await getEvent(websocket_client, msg_id, 'z')
    await checkNoMsg(websocket_client)
    async with asyncio.timeout(0.1):
        await getEvent(websocket_client2, msg_id2, 'z')
    await checkNoMsg(websocket_client2)

    # Let's let one unsubscribe
    await websocket_client.close()
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    assert service_calls.isEmpty()
    
    # Now reload again where display_msg doesn't exist anymore
    cfg['alert2']['alerts'][0]['display_msg'] = None
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    gad = hass.data[DOMAIN]
    assert gad.alerts['d']['n2']._display_msg_template == None
    async with asyncio.timeout(0.1):
        msg = await websocket_client2.receive_json()
        assert msg["type"] == wsapi.TYPE_RESULT
        assert msg['error']['code'] == 'no_display_msg'
    await checkNoMsg(websocket_client2)

    await websocket_client2.close()
    await websocket_client3.close()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    
async def test_display_msg2(hass, service_calls, hass_storage, caplog):
    # Check null values for display_msg and notifier and summary_notifier
    cfg = { 'alert2': { } }
    uiCfg = { 'defaults' : { },
              'alerts': [
                  { 'domain': 'd', 'name': 'n2', 'condition':'on', 'notifier': 'null', 'display_msg': 'null', 'message': 'happy' },
                  { 'domain': 'd', 'name': 'n5', 'condition':'sensor.b', 'notifier': 'null' },
                  { 'domain': 'd', 'name': 'n3', 'condition':'sensor.a', 'notifier': 'null', 'summary_notifier': 'yes' },
                  { 'domain': 'd', 'name': 'n4', 'condition':'sensor.a', 'summary_notifier': 'null' },
              ]
             }
    hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                       'data': { 'config': uiCfg } }
    await setAndWait(hass, 'sensor.a', 'off')
    await setAndWait(hass, 'sensor.b', 'off')
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    gad = hass.data[DOMAIN]
    #assert service_calls.popNotifySearch('persistent_notification', 'n2', 'n2 turned on')
    assert service_calls.isEmpty()
    n2 = gad.alerts['d']['n2']
    n3 = gad.alerts['d']['n3']
    n4 = gad.alerts['d']['n4']
    n5 = gad.alerts['d']['n4']
    assert hass.states.get('alert2.d_n2').state == 'on'
    assert n2._display_msg_template is None
    assert 'Activity alert2.d_n2 turned on' in caplog.text
    assert 'd_n2: happy' in caplog.text
    await setAndWait(hass, 'sensor.b', 'on')
    assert hass.states.get('alert2.d_n5').state == 'on'
    assert 'Activity alert2.d_n5 turned on' in caplog.text
    assert 'd_n5: turned on' in caplog.text

    await setAndWait(hass, 'sensor.a', 'on')
    #await asyncio.sleep(0.05)
    assert 'Activity alert2.d_n3 turned on' in caplog.text
    assert 'd_n3: turned on' in caplog.text
    assert 'Activity alert2.d_n4 turned on' in caplog.text
    assert 'd_n4: turned on' in caplog.text
    #_LOGGER.info(service_calls.allCalls)
    service_calls.popNotifyEmpty('persistent_notification', 'n4: turned on')

    # Snooze n3 and n4
    now = rawdt.datetime.now(rawdt.timezone.utc)
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.d_n3', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.services.async_call('alert2','notification_control',
        {'entity_id': 'alert2.d_n4', 'enable': True, 'snooze_until': now + rawdt.timedelta(seconds=1) })
    await hass.async_block_till_done()
    assert isinstance(n3.notification_control, rawdt.datetime)
    assert isinstance(n4.notification_control, rawdt.datetime)
    await setAndWait(hass, 'sensor.a', 'off')
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    assert 'Activity alert2.d_n3 turned off' in caplog.text
    assert 'Activity alert2.d_n4 turned off' in caplog.text
    await setAndWait(hass, 'sensor.a', 'on')
    await setAndWait(hass, 'sensor.a', 'off')
    assert service_calls.isEmpty()
    
    # snooze expires, should get no summary notifications
    await asyncio.sleep(2)
    assert n3.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert n4.notification_control == a2Entities.NOTIFICATIONS_ENABLED
    assert service_calls.isEmpty()
    assert 'Summary: Alert2 d_n4 fired 1x' in caplog.text
    assert 'Summary: Alert2 d_n3 fired 1x' in caplog.text

async def test_display_msg3(hass, service_calls, hass_ws_client):
    # Purpose is to both test an event alert
    # and to check subscribing to more than one entity over a single websocket connection
    #
    async def getEvent(aclient, msg_id, rtxt):
        msg = await aclient.receive_json()
        await hass.async_block_till_done()
        assert service_calls.isEmpty()
        _LOGGER.info(f'in getEvent, got {msg}')
        assert msg["id"] == msg_id
        assert msg["type"] == "event"
        result = msg["event"]['rendered']
        assert result == rtxt
    async def getResult(aclient, msg_id, result='bogus'):
        async with asyncio.timeout(0.1):
            msg = await aclient.receive_json()
        await hass.async_block_till_done()
        assert service_calls.isEmpty()
        _LOGGER.info(f'in getResult, got {msg}')
        assert msg['id'] == msg_id
        assert msg["type"] == wsapi.TYPE_RESULT
        assert msg["success"], msg['error']
        assert msg["result"] is None
        
    await setAndWait(hass, 'sensor.a1', 'foo')
    await setAndWait(hass, 'sensor.a2', 'foo2')
    await setAndWait(hass, 'sensor.b', '')
    cfg = { 'alert2': {
        'alerts': [
            { 'domain': 'd', 'name': 'n1', 'condition':'off', 'display_msg': '{{ states("sensor.a1") }}' },
            { 'domain': 'd', 'name': 'n2', 'trigger': [{'platform':'state','entity_id':'sensor.b'}], 'display_msg': '{{ states("sensor.a2") }}' },
        ]} }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    n1 = gad.alerts['d']['n1']
    n2 = gad.tracked['d']['n2']
    
    wsc = await hass_ws_client(hass)
    msg_id = 1
    await wsc.send_json({ "id": msg_id, "type": "alert2_watch_display_msg",
                          'domain': 'd', 'name': 'n1' } )
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getEvent(wsc, msg_id, 'foo')
    await getResult(wsc, msg_id, None)
    await checkNoMsg(wsc)

    msg_id2 = 2
    await wsc.send_json({ "id": msg_id2, "type": "alert2_watch_display_msg",
                          'domain': 'd', 'name': 'n2' } )
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getEvent(wsc, msg_id2, 'foo2')
    await getResult(wsc, msg_id2, None)
    await checkNoMsg(wsc)

    await setAndWait(hass, 'sensor.a1', 'z')
    await getEvent(wsc, msg_id, 'z')
    await checkNoMsg(wsc)
    
    await setAndWait(hass, 'sensor.a2', 'z2')
    await getEvent(wsc, msg_id2, 'z2')
    await checkNoMsg(wsc)

async def test_display_cfg(hass, service_calls, hass_client, hass_ws_client, monkeypatch):
    async def getEvent(aclient, msg_id):
        msg = await aclient.receive_json()
        await hass.async_block_till_done()
        assert service_calls.isEmpty()
        assert msg["id"] == msg_id
        assert msg["type"] == "event"
        assert msg['event']['configChange'] == True
    async def getResult(aclient, msg_id, result='bogus', errorCode=None):
        msg = await aclient.receive_json()
        await hass.async_block_till_done()
        _LOGGER.info(f'got result {msg}')
        assert msg["type"] == wsapi.TYPE_RESULT
        assert msg['id'] == msg_id
        if errorCode is not None:
            _LOGGER.info(msg)
            assert msg['error']['code'] == errorCode
        else:
            assert result is not 'bogus'
            assert not 'error' in msg
            assert msg["result"] == result
        await checkNoMsg(aclient)
                
    cfg = { 'alert2': {
        'alerts': [
            { 'domain': 'd', 'name': 'n1', 'condition':'off' },
            { 'domain': 'd', 'name': 'n2', 'condition':'off', 'supersedes': [ { 'domain':'d','name':'n1'} ], 'priority':'medium' }
        ] } }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)

    wsc = await hass_ws_client(hass)
    msg_id = 1
    # missing dn_list
    await wsc.send_json({ "id": msg_id, "type": "alert2_get_display_config" })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getResult(wsc, msg_id, errorCode = 'invalid_format')

    # get non-existent entity
    msg_id += 1
    await wsc.send_json({ "id": msg_id, "type": "alert2_get_display_config",
                          'dn_list': [ { 'domain': 'd', 'name': 'nx' } ]
                         })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getResult(wsc, msg_id, result = [])

    # existing entity but no supersededBy
    msg_id += 1
    await wsc.send_json({ "id": msg_id, "type": "alert2_get_display_config",
                          'dn_list': [ { 'domain': 'd', 'name': 'n2' } ]
                         })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getResult(wsc, msg_id, result = [{'entityId': 'alert2.d_n2', 'config': {'supersededByList': [], 'priority':'medium'}}])

    # existing entity and supersededBy
    msg_id += 1
    await wsc.send_json({ "id": msg_id, "type": "alert2_get_display_config",
                          'dn_list': [ { 'domain': 'd', 'name': 'n1' } ]
                         })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getResult(wsc, msg_id, result = [{'entityId': 'alert2.d_n1', 'config': {'supersededByList': [ 'alert2.d_n2' ], 'priority':'low'}}])
    msg_id += 1
    await wsc.send_json({ "id": msg_id, "type": "alert2_get_display_config",
                          'dn_list': [ { 'domain': 'd', 'name': 'n1' },{ 'domain': 'd', 'name': 'n2' } ]
                         })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await getResult(wsc, msg_id, result = [
        {'entityId': 'alert2.d_n1', 'config': {'supersededByList': [ 'alert2.d_n2' ], 'priority':'low'}},
        {'entityId': 'alert2.d_n2', 'config': {'supersededByList': [ ], 'priority':'medium'}},
    ])
    
    # Now check subscription
    msg_id += 1
    await wsc.send_json({ "id": msg_id, "type": "alert2_watch_display_config" })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    async with asyncio.timeout(0.1):
        await getResult(wsc, msg_id, result = None)
    await checkNoMsg(wsc)
    
    # Reload should trigger a change event
    async def fake_cfg(thass):
        return cfg
    with monkeypatch.context() as m:
        m.setattr(conf_util, 'async_hass_config_yaml', fake_cfg)
        await hass.services.async_call('alert2','reload', {})
        await hass.async_block_till_done()
    async with asyncio.timeout(0.2):
        await getEvent(wsc, msg_id)
    await checkNoMsg(wsc)

    # Adding a new alert should
    rez = await tpost("/api/alert2/manageAlert", {'create': {
        'domain':'d', 'name':'n3', 'condition':'off', 'supersedes': "[ { 'domain':'d','name':'n2'} ]" }})
    assert rez == {}
    async with asyncio.timeout(0.2):
        await getEvent(wsc, msg_id)
    await checkNoMsg(wsc)

    # Add second client
    wsc2 = await hass_ws_client(hass)
    msg_id2 = 1
    await wsc2.send_json({ "id": msg_id2, "type": "alert2_watch_display_config" })
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    async with asyncio.timeout(0.1):
        await getResult(wsc2, msg_id2, result = None)
    await checkNoMsg(wsc)
    await checkNoMsg(wsc2)

    # Remove alert should trigger event on both
    rez = await tpost("/api/alert2/manageAlert", {'delete': {'domain':'d', 'name':'n3'}})
    assert rez == {}
    async with asyncio.timeout(0.2):
        await getEvent(wsc, msg_id)
        await getEvent(wsc2, msg_id2)
    await checkNoMsg(wsc)
    await checkNoMsg(wsc2)

    # Cancel first subscription, should still get notifications on second
    await wsc.close()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    await checkNoMsg(wsc2)
    rez = await tpost("/api/alert2/manageAlert", {'create': {
        'domain':'d', 'name':'n3', 'condition':'off', 'supersedes': "[ { 'domain':'d','name':'n2'} ]" }})
    assert rez == {}
    async with asyncio.timeout(0.2):
        await getEvent(wsc2, msg_id2)
    await checkNoMsg(wsc2)

async def test_event(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2': {
        'alerts': [
        ] } }
    (tpost, client, gad) = await startAndTpost(hass, service_calls, hass_client, cfg)
    await setAndWait(hass, 'sensor.a', 'off')
    rez = await tpost("/api/alert2/manageAlert", {'create': {
        'domain':'d', 'name':'n1', 'trigger': "[{'platform':'state','entity_id':'sensor.a'}]" } })
    assert rez == {}
    assert service_calls.isEmpty()
    n1 = gad.tracked['d']['n1']

    await setAndWait(hass, 'sensor.a', 'on')
    service_calls.popNotifyEmpty('persistent_notification', 'Alert2 d_n1')
