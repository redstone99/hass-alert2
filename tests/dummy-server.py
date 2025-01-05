import os.path
import http.server
from http.server import SimpleHTTPRequestHandler, BaseHTTPRequestHandler, ThreadingHTTPServer

rootDir = '/home/redstone/tmp/hass-alert2-ui'

class handler(SimpleHTTPRequestHandler): #  BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=rootDir, **kwargs)
        
    def do_POST(self):
        print(self.headers)
        print('got POST')
        self.rfile.read(int(self.headers["Content-Length"]))

        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()

        message = "Hello, World! Here is a POST response"
        self.wfile.write(bytes(message, "utf8"))

with ThreadingHTTPServer(('', 8000), handler) as server:
    server.serve_forever()
