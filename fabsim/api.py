"""JSON API + dashboard server (standard library only).

    python -m fabsim.run --db sqlite:///fab.db        # create some data first
    python -m fabsim.api --db sqlite:///fab.db        # http://localhost:8000

Endpoints (all GET, JSON) - the contract a front end (this page, or Angular) consumes:
  /api/runs                       list of runs with headline KPIs
  /api/kpis?run=ID                full run summary
  /api/weekly?run=ID              weekly cycle time + on-time
  /api/utilization?run=ID         PROD / DOWN fraction per tool group
  /api/heatmap?run=ID             avg queue time per tool group x week
  /api/wip?run=ID                 avg WIP per tool group
  /api/steps?run=ID               avg queue time per route step
  /api/study                      dispatch-policy experiment summary (results/)
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import DB

from .export_static import DASHBOARD  # noqa: E402


def make_handler(db: DB):
    from .export_static import make_routes
    r = make_routes(db)
    routes = {f"/api/{k}": v for k, v in r.items()}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")   # lets an Angular dev server call it
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
            fn = routes.get(u.path)
            if not fn:
                return self._send(404, b'{"error":"not found"}', "application/json")
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                data = fn(q)
                code = 200
            except Exception as e:  # report errors as JSON instead of a dropped connection
                data, code = {"error": str(e)}, 500
            self._send(code, json.dumps(data, default=float).encode(), "application/json")

        def log_message(self, *a):
            pass

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///fab.db")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(DB(a.db)))
    print(f"Dashboard: http://localhost:{a.port}   (data: {a.db})  Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
