"""Run summary + Little's Law check (computed in memory, no DB needed)."""
from __future__ import annotations

import numpy as np

from .model import Fab


def summarize(fab: Fab) -> dict:
    W, H = fab.warmup, fab.sim_hours
    window = H - W
    done = [l for l in fab.completed if l.complete_time >= W]
    good = [l for l in done if l.wafers > 0]
    ct = np.array([l.complete_time - l.release_time for l in good]) if good else np.array([np.nan])

    th_lots_per_h = len(done) / window
    avg_wip = fab._wip_area / window
    mean_ct = float(np.mean([l.complete_time - l.release_time for l in done])) if done else float("nan")
    ll_pred = th_lots_per_h * mean_ct

    rpt = fab.cfg.raw_process_time
    util = {}
    for g, spec in fab.cfg.tool_groups.items():
        cap = spec.tools * window
        util[g] = {
            "prod": round(fab.state_hours.get((g, "PROD"), 0.0) / cap, 3),
            "down": round(fab.state_hours.get((g, "DOWN"), 0.0) / cap, 3),
        }
    bottleneck = max(util, key=lambda g: util[g]["prod"])
    started_after_w = [l for l in done if l.release_time >= W]

    return {
        "dispatch_rule": fab.rule_name,
        "window_hours": window,
        "lots_out": len(done),
        "wafers_out": int(sum(l.wafers for l in done)),
        "throughput_wafers_per_day": round(sum(l.wafers for l in done) / window * 24, 1),
        "throughput_lots_per_day": round(th_lots_per_h * 24, 2),
        "cycle_time_mean_h": round(float(np.mean(ct)), 2),
        "cycle_time_p90_h": round(float(np.percentile(ct, 90)), 2),
        "cycle_time_mean_days": round(float(np.mean(ct)) / 24, 2),
        "raw_process_time_h": round(rpt, 2),
        "x_factor": round(float(np.mean(ct)) / rpt, 2),
        "on_time_pct": round(100 * np.mean([l.complete_time <= l.due_time for l in good]), 1) if good else None,
        "line_yield": round(sum(l.wafers for l in started_after_w) /
                            max(1, sum(l.wafers_start for l in started_after_w)), 4),
        "avg_wip_lots": round(avg_wip, 2),
        "wip_at_end": len(fab.lots_in_fab),
        "littles_law": {
            "wip_observed": round(avg_wip, 2),
            "wip_predicted_TH_x_CT": round(ll_pred, 2),
            "rel_error_pct": round(100 * (ll_pred - avg_wip) / avg_wip, 2) if avg_wip else None,
        },
        "utilization": util,
        "bottleneck": bottleneck,
    }


def print_summary(s: dict) -> None:
    ll = s["littles_law"]
    print(f"\n=== {s['dispatch_rule']} | {s['window_hours']/24:.0f} days measured ===")
    print(f"Throughput     : {s['throughput_wafers_per_day']} wafers/day ({s['throughput_lots_per_day']} lots/day)")
    print(f"Cycle time     : mean {s['cycle_time_mean_h']} h ({s['cycle_time_mean_days']} d), "
          f"p90 {s['cycle_time_p90_h']} h, x-factor {s['x_factor']}")
    print(f"Avg WIP        : {s['avg_wip_lots']} lots   On-time: {s['on_time_pct']}%   "
          f"Line yield: {s['line_yield']:.2%}")
    print(f"Little's Law   : WIP {ll['wip_observed']} vs TH x CT {ll['wip_predicted_TH_x_CT']} "
          f"({ll['rel_error_pct']:+.2f}%)")
    print("Utilization    : " + "  ".join(
        f"{g} {u['prod']:.0%}" for g, u in sorted(s["utilization"].items(), key=lambda kv: -kv[1]["prod"])))
    print(f"Bottleneck     : {s['bottleneck']}")
