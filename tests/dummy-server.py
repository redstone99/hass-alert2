#
# JTESTDIR=[parent dir of custom_components] python3 tests/dummy-server.py
#

import os.path
import asyncio
import json
import inspect
import sys
from aiohttp import web
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
if os.environ.get('JTESTDIR'):
    sys.path.append(os.environ['JTESTDIR']) # parent dir of custom_components
else:
    sys.path.insert(0, parentdir)
from testlib import *
from testlib import _LOGGER


class MyServer(TestHelper):
    def __init__(self):
        rootDir = '/home/redstone/tmp/hass-alert2-ui/'
        app = web.Application()
        app.add_routes([web.post('/alert2/loadTopConfig', self.loadTopConfig)])
        app.add_routes([web.post('/alert2test/setCfg', self.setCfg)])
        app.add_routes([web.static('/', rootDir)])
        web.run_app(app, port=8000)

    async def setCfg(self, request):
        data = await request.json()
        _LOGGER.warning(f'setCfg of {data}')
        await self.initCase(data)
        await asyncio.sleep(0.1)
        return web.json_response({})
    async def loadTopConfig(self, request):
        #self.gad.uiMgr.
        return web.json_response({'foo':3})
        
x = MyServer()
fuck        

class handler(SimpleHTTPRequestHandler, TestHelper): #  BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        
        super().__init__(*args, directory=rootDir, **kwargs)

        
    def do_POST(self):
        #print(self.headers)
        idata = self.rfile.read(int(self.headers["Content-Length"]))
        ijson = json.loads(idata)
        print(f'got POST to {self.path} with body={ijson}')




        self.send_response(200)
        self.send_header('Content-type','application/json')
        self.end_headers()

        message = "Hello, World! Here is a POST response"
        self.wfile.write(bytes(message, "utf8"))

with ThreadingHTTPServer(('', 8000), handler) as server:
    server.serve_forever()
