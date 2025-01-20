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
from homeassistant.util import json as json_util
from homeassistant.helpers import json as json_helper
from   homeassistant.helpers import template as template_helper

a2Ui.SAVE_DELAY = 0

async def test_defaults(hass, service_calls, hass_client, hass_storage):
    cfg = { 'alert2' : {
        'defaults' : {
            'notifier' : 'n',
            'summary_notifier' : 'sn',
            'reminder_frequency_mins': [3],
            'throttle_fires_per_mins': [1,2]
        },
        'alerts': [
            { 'domain': 'test', 'name': 't1', 'condition': 'off' }
        ],
        'skip_internal_errors': True,
        'notifier_startup_grace_secs': 4,
        'defer_startup_notifications': True,
    } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
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
    client = await hass_client()
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

    async def tpost(url, adict):
        resp = await client.post(url, json=adict)
        assert resp.status == 200
        rez = await resp.json()
        await hass.async_block_till_done()
        return rez
    
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

    ########################
    # Now try full save
    uiCfg = { 'defaults' : {
        'notifier' : 'n2',
        'summary_notifier' : 'sn2',
        'reminder_frequency_mins': '[4]',
        'throttle_fires_per_mins': '[1,3]',
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
    _LOGGER.warning(rez)
    assert rez['rawUi'] == { 'defaults': {} }
    rez = await tpost("/api/alert2/loadTopConfig", {})
    assert rez['rawUi'] == { 'defaults': {} }
    rez = await tpost("/api/alert2/saveTopConfig", {'topConfig': '' })
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
        },
        'alerts': [
            { 'domain': 'test', 'name': 't1', 'condition': 'off' }
        ],
        #'skip_internal_errors': True,   UI overrides base
        'notifier_startup_grace_secs': 4, # UI overrides yaml
        'defer_startup_notifications': True, # yaml comes through
    } }
    cfga = cfg['alert2']
    #fix so is stirngs only
    assert False
    uiCfg = { 'defaults' : { 'reminder_frequency_mins': [4],
                              'throttle_fires_per_mins': [5,6]
                             },
               'skip_internal_errors': 'true',
               'notifier_startup_grace_secs': 7,
              }
    hass_storage['alert2.storage'] = { 'version': 1, 'minor_version': 1, 'key': 'alert2.storage',
                                       'data': { 'config': uiCfg } }
    assert await async_setup_component(hass, DOMAIN, cfg)
    await hass.async_start()
    await hass.async_block_till_done()
    assert service_calls.isEmpty()
    gad = hass.data[DOMAIN]
    # Test top-level flags were set
    assert hass.states.get('alert2.alert2_error') is None # skip_internal_errors
    cfga = cfg['alert2']
    assert gad.delayedNotifierMgr.notifier_startup_grace_secs == uiCfg['notifier_startup_grace_secs']
    assert gad.delayedNotifierMgr.defer_startup_notifications == cfga['defer_startup_notifications']
    t1 = gad.alerts['test']['t1']
    # and check all the defaults
    assert t1._notifier_list_template.template == cfga['defaults']['notifier']
    assert t1._summary_notifier == False
    assert t1.reminder_frequency_mins == uiCfg['defaults']['reminder_frequency_mins']
    assert t1.movingSum.maxCount == uiCfg['defaults']['throttle_fires_per_mins'][0]
    assert t1.movingSum.intervalSecs == uiCfg['defaults']['throttle_fires_per_mins'][1]*60

    # And test overriding all at once
