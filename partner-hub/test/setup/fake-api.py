import http.server, json, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['content-length'])))
        key = open(sys.argv[2]).read().strip()
        ok = self.headers.get('x-partner-key') == key
        out = {"ok": True, "action": body["action"], "data": {"sendable": True, "stock": [{"title": "GREY CONVICT SWEATS - XS", "inStock": 79}]}} if ok else {"ok": False, "error": "Missing or wrong X-Partner-Key header."}
        b = json.dumps(out).encode(); self.send_response(200 if ok else 401); self.send_header('content-type','application/json'); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
