import logging
import re
import pytest
from homeassistant.core import (ServiceRegistry)
_LOGGER = logging.getLogger(None) # get root logger

class CallCollector:
    def __init__(self, hass):
        self.allCalls = []
        self.hass = hass
    def recCall(self, domain, service, service_data):
        self.allCalls.append((domain, service, service_data))
    def popNotifySearch(self, service, search, rMsg, useRegex=True):
        assert len(self.allCalls) > 0
        idx = next((i for i, x in enumerate(self.allCalls) if x[1] == service and search in x[2]['message']), -1)
        assert idx >= 0
        self.doTest(service, rMsg, idx, useRegex)
    def popNotifyEmpty(self, service, rMsg):
        self.popNotify(service, rMsg)
        assert self.isEmpty()
    def popNotify(self, service, rMsg):
        assert len(self.allCalls) > 0
        self.doTest(service, rMsg, 0)
    def doTest(self, service, rMsg, idx, useRegex=True):
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
        _LOGGER.warning(f'got call to {domain}.{service} with data={service_data}')
        if domain == 'notify':
            cc.recCall(domain, service, service_data)
            return None
        else:
            return await originalCall(registryObj, domain, service, service_data, *args, **kwargs)
    monkeypatch.setattr(ServiceRegistry, 'async_call', mock_async_call)
    yield cc
    # Can put fixture teardown code here

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield

# Make sure at end of each test there are no extra notifications we haven't processed
@pytest.fixture(autouse=True)
def auto_check_empty_calls(service_calls):
    yield
    assert service_calls.isEmpty()
    
# work-around to unblock access to listen on port 8123.
from pytest_socket import enable_socket, disable_socket, socket_allow_hosts
@pytest.hookimpl(trylast=True)
def pytest_runtest_setup():
    enable_socket()
    socket_allow_hosts(["127.0.0.1", "localhost", "::1"], allow_unix_socket=True)
