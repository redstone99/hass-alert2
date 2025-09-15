import os
import sys
import re
import pytest
from homeassistant.core import (ServiceRegistry)
if os.environ.get('JTESTDIR'):
    sys.path.insert(0, os.environ['JTESTDIR'])
from custom_components.alert2.util import (     set_shutting_down, )

#
# To get debug logging, run with --log-cli-level=DEBUG
#

#import logging
#_LOGGER = logging.getLogger(None) # get root logger
#_LOGGER.setLevel(logging.INFO)
#logging.basicConfig(level=logging.INFO)

class CallCollector:
    def __init__(self, hass):
        self.allCalls = []
        self.hass = hass
    def recCall(self, domain, service, service_data):
        self.allCalls.append((domain, service, service_data))
    def popNotifySearch(self, service, search, rMsg, useRegex=True, extraFields=None):
        assert len(self.allCalls) > 0
        idx = next((i for i, x in enumerate(self.allCalls) if x[1] == service and search in x[2]['message']), -1)
        assert idx >= 0
        self.doTest(service, rMsg, idx, useRegex, extraFields=extraFields)
    def popNotifyEmpty(self, service, rMsg, extraFields=None):
        self.popNotify(service, rMsg, extraFields=extraFields)
        assert self.isEmpty()
    def popNotify(self, service, rMsg, extraFields=None):
        assert len(self.allCalls) > 0
        self.doTest(service, rMsg, 0, extraFields=extraFields)
    def doTest(self, service, rMsg, idx, useRegex=True, extraFields=None):
        tcall = self.allCalls[idx]
        assert tcall[0] == 'notify'
        assert tcall[1] == service
        assert 'message' in tcall[2]
        #x = re.match(rMsg, 'extra keys not allowed in fowefwefewf')
        #_LOGGER.warning(f'   hmm   {x}')
        #x = re.match(rMsg, "Alert2 alert2_error: top-level alert2 config: extra keys not allowed @ data['foo']")
        #_LOGGER.warning(f'   hmm2   {x} {type(tcall[2]["message"])}')
        if useRegex:
            assert re.search(rMsg, tcall[2]['message'])
        else:
            assert rMsg == tcall[2]['message']
        if extraFields:
            for i, (key, val) in enumerate(extraFields.items()):
                assert key in tcall[2]
                if isinstance(val, dict):
                    assert val == tcall[2][key]
                else:
                    assert re.search(val, tcall[2][key])
        del self.allCalls[idx]
    def isEmpty(self):
        return len(self.allCalls) == 0
    
@pytest.fixture(name='service_calls')
def auto_patch_service_call(enable_custom_integrations, hass, monkeypatch):
    cc = CallCollector(hass)
    # We're using monkeypath rather than tests.common::async_mock_service
    # because async_mock_service is overwritten if the same service is registered later.
    # In our case, we want to override notify, which is registered after the fixture
    # runs.
    originalCall = ServiceRegistry.async_call
    async def mock_async_call(registryObj, domain, service, service_data, *args, **kwargs):
        #_LOGGER.warning(f'got call to {domain}.{service} with data={service_data}')
        if domain == 'notify':
            cc.recCall(domain, service, service_data)
            #return None
            return await originalCall(registryObj, domain, service, service_data, *args, **kwargs)
        else:
            return await originalCall(registryObj, domain, service, service_data, *args, **kwargs)
    monkeypatch.setattr(ServiceRegistry, 'async_call', mock_async_call)
    yield cc
    # Can put fixture teardown code here


# work-around to unblock access to listen on port 8123.
from pytest_socket import enable_socket, disable_socket, socket_allow_hosts
@pytest.hookimpl(trylast=True)
def pytest_runtest_setup():
    enable_socket()
    socket_allow_hosts(["127.0.0.1", "localhost", "::1"], allow_unix_socket=True)

@pytest.fixture(autouse=True)
def global_setup_teardown():
    # setup code for every test
    set_shutting_down(False)
    yield
    # teardown code for every test
