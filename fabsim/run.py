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

DEFAULT_CFG = Path(__file__).resolve().parent.parent / "config" / "fab_default.yaml"


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
    p.add_argument("--capacity", action="store_true", help="print static capacity table and exit")
    p.add_argument("--json", action="store_true", help="print summary as JSON")
    a = p.parse_args(argv)

    cfg = load_config(a.config)
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


if __name__ == "__main__":
    main()
