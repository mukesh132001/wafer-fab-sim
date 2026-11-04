"""Export the dashboard + its data as a static site (for GitHub Pages).

    python -m fabsim.export_static --db sqlite:///fab.db --out site

Calls every API endpoint once per run and saves the JSON next to a copy of the
dashboard that reads those files instead of a live server.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import csv

from .db import DB

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard" / "index.html"
STUDY = ROOT / "results" / "dispatch_study" / "summary.csv"

ENDPOINTS = ["kpis", "weekly", "utilization", "heatmap", "wip", "steps"]


def export(db_url: str, out: Path) -> int:
    db = DB(db_url)
    out.mkdir(parents=True, exist_ok=True)
    (out / "api").mkdir(exist_ok=True)
    routes = make_routes(db)
    runs = routes["runs"]({})
    write = lambda name, data: (out / "api" / name).write_text(json.dumps(data, default=float))
    write("runs.json", runs)
    for r in runs:
        for e in ENDPOINTS:
            write(f"{e}_{r['run_id']}.json", routes[e]({"run": r["run_id"]}))
    write("study.json", routes["study"]({}))
    html = DASHBOARD.read_text().replace("const STATIC = false;", "const STATIC = true;")
    (out / "index.html").write_text(html)
    (out / ".nojekyll").write_text("")
    return len(runs)


def make_routes(db: DB) -> dict:
    """Same queries as fabsim.api, returned as plain functions."""
    def runs(_):
        rows = db.query("SELECT run_id, scenario, dispatch_rule, release_policy, seed, sim_hours, "
                        "warmup_hours, created_at, summary_json FROM runs ORDER BY created_at DESC")
        for r in rows:
            s = json.loads(r.pop("summary_json") or "{}")
            r["kpis"] = {k: s.get(k) for k in ("throughput_wafers_per_day", "cycle_time_mean_h",
                                               "on_time_pct", "avg_wip_lots", "bottleneck")}
        return rows

    def q(sql):
        return lambda a: db.query(sql, (a["run"],))

    def study(_):
        if not STUDY.exists():
            return {"error": "No policy study results in this build."}
        with open(STUDY) as f:
            return list(csv.DictReader(f))

    return {
        "runs": runs,
        "kpis": lambda a: json.loads(db.query("SELECT summary_json FROM runs WHERE run_id = ?",
                                              (a["run"],))[0]["summary_json"] or "{}"),
        "weekly": q("SELECT week, lots_out, mean_ct_h, on_time_frac FROM v_weekly_cycle_time "
                    "WHERE run_id = ? ORDER BY week"),
        "utilization": q("SELECT tool_group, AVG(prod_frac) AS prod, AVG(down_frac) AS down "
                         "FROM v_tool_utilization WHERE run_id = ? GROUP BY tool_group "
                         "ORDER BY AVG(prod_frac) DESC"),
        "heatmap": q("SELECT tool_group, week, avg_queue_h, moves FROM v_queue_heatmap "
                     "WHERE run_id = ? ORDER BY tool_group, week"),
        "wip": q("SELECT tool_group, avg_queued, avg_in_process, max_wip FROM v_wip_by_group "
                 "WHERE run_id = ? ORDER BY avg_queued + avg_in_process DESC"),
        "steps": q("SELECT step_idx, recipe, tool_group, avg_queue_h, avg_process_h "
                   "FROM v_step_queue WHERE run_id = ? ORDER BY step_idx"),
        "study": study,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///fab.db")
    p.add_argument("--out", default="site")
    a = p.parse_args(argv)
    n = export(a.db, Path(a.out))
    print(f"Exported {n} runs -> {a.out}/index.html")


if __name__ == "__main__":
    main()
