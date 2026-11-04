"""CLI: run one simulation and (optionally) log it to a database.

    python -m fabsim.run                                   # quick, no DB
    python -m fabsim.run --db sqlite:///fab.db
    python -m fabsim.run --db postgresql://fab:fab@localhost:5432/fab --days 180
    python -m fabsim.run --capacity                        # static capacity check only
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import capacity_table, load_config
from .logger import DBLogger
from .metrics import print_summary, summarize
from .model import Fab

DEFAULT_CFG = Path(__file__).resolve().parent.parent / "config" / "fab_default.toml"


def run_once(cfg, seed=1, rule="FIFO", days=120, warmup_days=30, db=None, scenario="baseline"):
    sim_h, warm_h = days * 24.0, warmup_days * 24.0
    logger = None
    if db:
        logger = DBLogger(db, {"scenario": scenario, "dispatch_rule": rule, "seed": seed,
                               "release_policy": cfg.release["policy"],
                               "sim_hours": sim_h, "warmup_hours": warm_h, "config": cfg.raw})
    fab = Fab(cfg, seed=seed, rule=rule, warmup_hours=warm_h, logger=logger)
    fab.run(sim_h)
    summary = summarize(fab)
    if logger:
        logger.log_open_lots(fab.lots_in_fab.values())
        logger.finish(summary)
        summary["run_id"] = logger.run_id
        logger.close()
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Wafer fab discrete-event simulator")
    p.add_argument("--config", default=str(DEFAULT_CFG))
    p.add_argument("--rule", default="FIFO")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--days", type=float, default=120)
    p.add_argument("--warmup", type=float, default=30, help="warm-up days excluded from stats")
    p.add_argument("--db", default=None, help="sqlite:///fab.db or postgresql://user:pw@host/db")
    p.add_argument("--scenario", default="baseline")
    p.add_argument("--release", choices=["constant", "poisson", "conwip", "dbr"], default=None,
                   help="release policy (default: from config)")
    p.add_argument("--arrivals", choices=["constant", "poisson"], default=None, help="order arrival pattern")
    p.add_argument("--wip-cap", type=int, default=None, help="CONWIP WIP cap (lots)")
    p.add_argument("--drum-buffer", type=int, default=None, help="DBR buffer target (lots)")
    p.add_argument("--interarrival", type=float, default=None, help="hours between planned lot starts")
    p.add_argument("--tools", default=None, help='tool count changes, e.g. "LITHO=2,ETCH=5"')
    p.add_argument("--incident", default=None, help='long outage TOOL:START_DAY:END_DAY, e.g. "LITHO_02:80:94"')
    p.add_argument("--summary-md", default=None, help="also write a Markdown summary to this file")
    p.add_argument("--capacity", action="store_true", help="print static capacity table and exit")
    p.add_argument("--json", action="store_true", help="print summary as JSON")
    a = p.parse_args(argv)

    cfg = load_config(a.config)
    rel = {k: v for k, v in {"policy": a.release, "arrivals": a.arrivals, "wip_cap": a.wip_cap,
                             "drum_buffer_lots": a.drum_buffer}.items() if v is not None}
    tools = dict((k, int(v)) for k, v in (x.split("=") for x in a.tools.split(","))) if a.tools else None
    incidents = None
    if a.incident:
        tool, start, end = a.incident.split(":")
        incidents = [{"tool": tool, "start_day": float(start), "end_day": float(end)}]
    if rel or tools or incidents or a.interarrival:
        cfg = cfg.with_overrides(tool_counts=tools, release=rel or None, incidents=incidents,
                                 interarrival_hours=a.interarrival)
    if a.capacity:
        print(f"{cfg.fab_name}: {len(cfg.route)} steps, raw process time {cfg.raw_process_time:.1f} h, "
              f"release every {cfg.release['interarrival_hours']} h")
        print(f"{'group':8} {'visits':>6} {'tools':>5} {'avail':>6} {'h/lot':>6} {'util':>6}")
        for r in capacity_table(cfg):
            print(f"{r['tool_group']:8} {r['visits']:>6} {r['tools']:>5} {r['availability']:>6} "
                  f"{r['work_h_per_lot']:>6} {r['expected_util']:>6.1%}")
        return

    t0 = time.time()
    s = run_once(cfg, a.seed, a.rule, a.days, a.warmup, a.db, a.scenario)
    if a.json:
        print(json.dumps(s, indent=2))
    else:
        print_summary(s)
        if "run_id" in s:
            print(f"Logged run_id  : {s['run_id']}  -> {a.db}")
        print(f"(wall time {time.time() - t0:.1f}s)")
    if a.summary_md:
        Path(a.summary_md).write_text(summary_markdown(s, a))


def summary_markdown(s: dict, a) -> str:
    ll = s["littles_law"]
    rows = [("Throughput", f"{s['throughput_wafers_per_day']} wafers/day"),
            ("Mean cycle time", f"{s['cycle_time_mean_h']} h (x-factor {s['x_factor']})"),
            ("P90 cycle time", f"{s['cycle_time_p90_h']} h"),
            ("On-time delivery", f"{s['on_time_pct']}%"),
            ("Avg WIP", f"{s['avg_wip_lots']} lots"),
            ("Q-time violations", f"{s['qtime_violation_pct']}%"),
            ("Line yield", f"{100 * s['line_yield']:.2f}%"),
            ("Little's Law (WIP vs TH x CT)", f"{ll['wip_observed']} vs {ll['wip_predicted_TH_x_CT']} ({ll['rel_error_pct']:+.2f}%)"),
            ("Bottleneck", s["bottleneck"])]
    util = sorted(s["utilization"].items(), key=lambda kv: -kv[1]["prod"])
    md = [f"## Simulation: {s['dispatch_rule']} dispatch, {s['release_policy']} release",
          f"{a.days:.0f} days ({a.warmup:.0f}-day warm-up), seed {a.seed}"
          + (f", incident {a.incident}" if a.incident else "") + "\n",
          "| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    md += ["\n| Tool group | Producing | Down |", "|---|---|---|"]
    md += [f"| {g} | {u['prod']:.0%} | {u['down']:.0%} |" for g, u in util]
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    main()
