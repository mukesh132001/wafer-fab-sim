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
import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import DB

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard" / "index.html"
STUDY = ROOT / "results" / "dispatch_study" / "summary.csv"


def make_handler(db: DB):
    def runs(_):
        rows = db.query("SELECT run_id, scenario, dispatch_rule, release_policy, seed, sim_hours, "
                        "warmup_hours, created_at, summary_json FROM runs ORDER BY created_at DESC")
        out = []
        for r in rows:
            s = json.loads(r.pop("summary_json") or "{}")
            r["kpis"] = {k: s.get(k) for k in ("throughput_wafers_per_day", "cycle_time_mean_h",
                                               "on_time_pct", "avg_wip_lots", "bottleneck")}
            out.append(r)
        return out

    def kpis(q):
        r = db.query("SELECT summary_json FROM runs WHERE run_id = ?", (q["run"],))
        return json.loads(r[0]["summary_json"] or "{}") if r else {}

    def weekly(q):
        return db.query("SELECT week, lots_out, mean_ct_h, on_time_frac FROM v_weekly_cycle_time "
                        "WHERE run_id = ? ORDER BY week", (q["run"],))

    def utilization(q):
        return db.query("SELECT tool_group, AVG(prod_frac) AS prod, AVG(down_frac) AS down "
                        "FROM v_tool_utilization WHERE run_id = ? GROUP BY tool_group "
                        "ORDER BY AVG(prod_frac) DESC", (q["run"],))

    def heatmap(q):
        return db.query("SELECT tool_group, week, avg_queue_h, moves FROM v_queue_heatmap "
                        "WHERE run_id = ? ORDER BY tool_group, week", (q["run"],))

    def wip(q):
        return db.query("SELECT tool_group, avg_queued, avg_in_process, max_wip FROM v_wip_by_group "
                        "WHERE run_id = ? ORDER BY avg_queued + avg_in_process DESC", (q["run"],))

    def steps(q):
        return db.query("SELECT step_idx, recipe, tool_group, avg_queue_h, avg_process_h "
                        "FROM v_step_queue WHERE run_id = ? ORDER BY step_idx", (q["run"],))

    def study(_):
        if not STUDY.exists():
            return {"error": "Run `python -m fabsim.experiment` first."}
        with open(STUDY) as f:
            return list(csv.DictReader(f))

    routes = {"/api/runs": runs, "/api/kpis": kpis, "/api/weekly": weekly,
              "/api/utilization": utilization, "/api/heatmap": heatmap, "/api/wip": wip,
              "/api/steps": steps, "/api/study": study}

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
