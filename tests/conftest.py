import logging
import re
import pytest
from homeassistant.core import (ServiceRegistry)
_LOGGER = logging.getLogger(None) # get root logger

class CallCollector:
    def __init__(self):
        self.allCalls = []
    def recCall(self, domain, service, service_data):
        self.allCalls.append((domain, service, service_data))
    def popNotify(self, service, rMsg):
        assert len(self.allCalls) > 0
        tcall = self.allCalls[0]
        self.allCalls = self.allCalls[1:]
        assert tcall[0] == 'notify'
        assert tcall[1] == service
        assert 'message' in tcall[2]
        #x = re.match(rMsg, 'extra keys not allowed in fowefwefewf')
        #_LOGGER.warning(f'   hmm   {x}')
        #x = re.match(rMsg, "Alert2 alert2_error: top-level alert2 config: extra keys not allowed @ data['foo']")
        #_LOGGER.warning(f'   hmm2   {x} {type(tcall[2]["message"])}')
        assert re.search(rMsg, tcall[2]['message'])
    def isEmpty(self):
        return len(self.allCalls) == 0

@pytest.fixture(name='service_calls')
def auto_patch_service_call(enable_custom_integrations, monkeypatch):
    cc = CallCollector()
    async def mock_async_call(registryObj, domain, service, service_data):
        _LOGGER.warning(f'got call to {domain}.{service} with data={service_data}')
        cc.recCall(domain, service, service_data)
        return None
    monkeypatch.setattr(ServiceRegistry, 'async_call', mock_async_call)
    yield cc
    # Can put fixture teardown code here

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
