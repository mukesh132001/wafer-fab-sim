"""Root-cause case study: a cycle-time spike, traced with SQL, fixed, measured.

    python -m fabsim.casestudy            # writes results/case_study/

Story
  1. Symptom   weekly cycle time spikes (SQL on lot completions)
  2. Locate    which tool group's queue time exploded (SQL on lot_moves)
  3. Cause     which tool was down, and for how long (SQL on tool_states)
  4. Why       capacity math: the bottleneck's utilization goes above 100%
  5. Fix       compare countermeasures over paired replications
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np

from . import stats
from .config import load_config
from .logger import DBLogger
from .metrics import summarize
from .model import Fab
from .run import DEFAULT_CFG

ROOT = Path(__file__).resolve().parent.parent
INCIDENT = {"tool": "LITHO_02", "start_day": 80, "end_day": 94}
DAYS, WARMUP = 180, 30

SCENARIOS = [
    # name, rule, overrides
    ("No incident (reference)", "FIFO", {}),
    ("As-is: incident, FIFO, push release", "FIFO", {"incidents": [INCIDENT]}),
    ("Fix A: CR dispatch", "CR", {"incidents": [INCIDENT]}),
    ("Fix B: CR + DBR rope on litho", "CR",
     {"incidents": [INCIDENT], "release": {"policy": "dbr", "drum_buffer_lots": 10}}),
    ("Fix C: expedite repair (14 -> 5 days)", "FIFO",
     {"incidents": [{**INCIDENT, "end_day": INCIDENT["start_day"] + 5}]}),
    ("Fix C + B (expedite + CR + DBR)", "CR",
     {"incidents": [{**INCIDENT, "end_day": INCIDENT["start_day"] + 5}],
      "release": {"policy": "dbr", "drum_buffer_lots": 10}}),
]


def weekly_ct(fab: Fab) -> dict[int, float]:
    weeks: dict[int, list[float]] = {}
    for l in fab.completed:
        if l.complete_time >= WARMUP * 24 and l.wafers > 0:
            weeks.setdefault(int(l.complete_time // 168), []).append(l.complete_time - l.release_time)
    return {w: float(np.mean(v)) for w, v in sorted(weeks.items())}


def run_scenario(cfg, rule, seed, logger=None):
    fab = Fab(cfg, seed=seed, rule=rule, warmup_hours=WARMUP * 24, logger=logger)
    fab.run(DAYS * 24)
    s = summarize(fab)
    wk = weekly_ct(fab)
    lead = [l.complete_time - l.order_time for l in fab.completed
            if l.complete_time >= WARMUP * 24 and l.wafers > 0]
    s["peak_weekly_ct_h"] = max(wk.values())
    s["lead_time_mean_h"] = float(np.mean(lead))
    return s, wk, fab


SQL = {
    "weekly_ct": """
        SELECT CAST(FLOOR(complete_time / 168) AS INTEGER) AS week,
               COUNT(*) AS lots_out,
               ROUND(AVG(complete_time - release_time), 1) AS mean_ct_h
        FROM lots WHERE run_id = ? AND complete_time IS NOT NULL AND complete_time >= ?
        GROUP BY 1 ORDER BY 1""",
    "queue_by_group_week": """
        SELECT tool_group,
               ROUND(AVG(CASE WHEN arrive_time <  ? THEN start_time - arrive_time END), 2) AS before_h,
               ROUND(AVG(CASE WHEN arrive_time >= ? AND arrive_time < ?
                              THEN start_time - arrive_time END), 2) AS during_h
        FROM lot_moves WHERE run_id = ? AND arrive_time >= ?
        GROUP BY tool_group ORDER BY during_h - before_h DESC""",
    "downtime_by_tool": """
        SELECT tool_id, COUNT(*) AS down_events,
               ROUND(SUM(end_time - start_time), 1) AS down_hours,
               ROUND(MAX(end_time - start_time), 1) AS longest_h
        FROM tool_states
        WHERE run_id = ? AND state = 'DOWN' AND end_time > ? AND start_time < ?
        GROUP BY tool_id ORDER BY down_hours DESC LIMIT 5""",
}


def reading(res, asis) -> str:
    """Plain-language findings computed from the results (not hard-coded)."""
    def pct(n, k):
        return 100 * (np.mean(res[n][k]) / np.mean(res[asis][k]) - 1)
    names = [n for n, _, _ in SCENARIOS]
    ref, a_cr, b_dbr, c_exp, cb = names[0], names[2], names[3], names[4], names[5]
    lines = [
        f"- **Shortening the outage ({c_exp.split(': ')[1]})** is the root-cause fix: "
        f"mean cycle time {pct(c_exp, 'cycle_time_mean_h'):+.0f}%, on-time delivery "
        f"{np.mean(res[asis]['on_time_pct']):.0f}% -> {np.mean(res[c_exp]['on_time_pct']):.0f}%.",
        f"- **CR dispatch** cannot add capacity, but by serving the latest lots first it cuts the peak "
        f"weekly cycle time {pct(a_cr, 'peak_weekly_ct_h'):+.0f}%; the cost is more Q-time violations "
        f"({np.mean(res[asis]['qtime_violation_pct']):.1f}% -> {np.mean(res[a_cr]['qtime_violation_pct']):.1f}%).",
        f"- **DBR rope** holds new lots outside the fab while litho is short: in-fab cycle time "
        f"{pct(b_dbr, 'cycle_time_mean_h'):+.0f}%, but order lead time only "
        f"{pct(b_dbr, 'lead_time_mean_h'):+.0f}% and on-time delivery "
        f"{np.mean(res[b_dbr]['on_time_pct']):.0f}% - the waiting moves to the order queue, it does not disappear.",
        f"- **Combining all three** brings the fab back near its no-incident baseline: on-time "
        f"{np.mean(res[cb]['on_time_pct']):.0f}% (reference {np.mean(res[ref]['on_time_pct']):.0f}%), "
        f"peak weekly cycle time {pct(cb, 'peak_weekly_ct_h'):+.0f}% vs as-is.",
    ]
    return "\n".join(lines)


def md_table(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--reps", type=int, default=20)
    p.add_argument("--out", default=str(ROOT / "results" / "case_study"))
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    base = load_config(DEFAULT_CFG)
    s0, e0 = INCIDENT["start_day"] * 24, INCIDENT["end_day"] * 24

    # ---- 1-3: diagnose one incident run from the database ---------------------
    db_path = out / "case.db"
    db_path.unlink(missing_ok=True)
    cfg = base.with_overrides(incidents=[INCIDENT])
    log = DBLogger(f"sqlite:///{db_path}", {"scenario": "incident", "dispatch_rule": "FIFO",
                                            "seed": 1, "sim_hours": DAYS * 24,
                                            "warmup_hours": WARMUP * 24, "config": cfg.raw})
    s_inc, wk_inc, fab = run_scenario(cfg, "FIFO", 1, log)
    log.log_open_lots(fab.lots_in_fab.values())
    log.finish(s_inc)
    run_id = log.run_id
    log.close()
    con = sqlite3.connect(db_path)
    weekly = con.execute(SQL["weekly_ct"], (run_id, WARMUP * 24)).fetchall()
    queues = con.execute(SQL["queue_by_group_week"], (s0, s0, e0, run_id, WARMUP * 24)).fetchall()
    down = con.execute(SQL["downtime_by_tool"], (run_id, s0, e0)).fetchall()
    con.close()

    g = base.tool_groups["LITHO"]
    lam = 1 / base.release["interarrival_hours"]
    work = sum(st.process_hours for st in base.route if st.tool_group == "LITHO")
    u3 = lam * work / (g.tools * g.availability)
    u2 = lam * work / ((g.tools - 1) * g.availability)
    pileup = (lam - (g.tools - 1) * g.availability / work) * 24  # lots/day accumulating

    # ---- 5: compare countermeasures over paired replications ------------------
    keys = [("cycle_time_mean_h", "Mean CT (h)"), ("peak_weekly_ct_h", "Peak weekly CT (h)"),
            ("on_time_pct", "On-time %"), ("qtime_violation_pct", "Q-time viol. %"),
            ("throughput_wafers_per_day", "Wafers/day"), ("lead_time_mean_h", "Order lead time (h)")]
    res = {n: {k: [] for k, _ in keys} for n, _, _ in SCENARIOS}
    weekly_curves = {}
    for seed in range(1, a.reps + 1):
        for n, rule, ov in SCENARIOS:
            s, wk, _ = run_scenario(base.with_overrides(**ov), rule, seed)
            for k, _ in keys:
                res[n][k].append(s[k])
            if seed == 1:
                weekly_curves[n] = wk
        print(f"  replication {seed}/{a.reps}", flush=True)

    asis = SCENARIOS[1][0]
    rows = []
    for n, _, _ in SCENARIOS:
        r = [n]
        for k, _ in keys:
            m, hw, _ = stats.mean_ci(res[n][k])
            cell = f"{m:.1f} ± {hw:.1f}"
            if n != asis and n != SCENARIOS[0][0]:
                t = stats.paired_t(res[n][k], res[asis][k])
                cell += f" ({100 * t['mean_diff'] / np.mean(res[asis][k]):+.0f}%{'*' if t['p'] < 0.05 else ''})"
            r.append(cell)
        rows.append(r)

    # ---- report -------------------------------------------------------------
    peak_week = max(weekly, key=lambda r: r[2])
    pre = [r[2] for r in weekly if r[0] * 168 < s0]
    L = ["# Root-cause case study: cycle-time spike\n",
         f"Incident injected: **{INCIDENT['tool']}** out of service from day {INCIDENT['start_day']} "
         f"to day {INCIDENT['end_day']} (e.g. a stage part on back-order). "
         "The analysis below uses only the logged data, the way an IE would investigate.\n",
         "## 1. Symptom: weekly cycle time\n",
         f"Mean cycle time was ~{np.mean(pre):.0f} h before the event and peaked at "
         f"**{peak_week[2]:.0f} h in week {peak_week[0]}**.\n",
         "```sql" + SQL["weekly_ct"] + "\n```\n",
         md_table(["week", "lots out", "mean CT (h)"], weekly), "\n",
         "## 2. Locate: which queue exploded?\n",
         "Average queue time per tool group, before vs during the event window:\n",
         "```sql" + SQL["queue_by_group_week"] + "\n```\n",
         md_table(["tool group", "before (h)", "during (h)"], queues), "\n",
         "## 3. Cause: which tool was down?\n",
         "```sql" + SQL["downtime_by_tool"] + "\n```\n",
         md_table(["tool", "down events", "down hours", "longest (h)"], down), "\n",
         "## 4. Why one tool hurts this much: capacity math\n",
         f"LITHO is the bottleneck and every lot visits it {sum(st.tool_group == 'LITHO' for st in base.route)} "
         f"times ({work:.1f} h of litho work per lot). With 3 tools its utilization is "
         f"{u3:.0%}; with 2 it would need to be **{u2:.0%}**, i.e. demand exceeds capacity, so "
         f"WIP grows by about {pileup:.1f} lots/day for as long as the tool is out, and "
         "takes weeks to drain afterwards. No dispatch rule can create capacity; "
         "it can only decide who waits.\n",
         f"## 5. Countermeasures ({a.reps} paired replications, mean ± 95% CI)\n",
         "% = paired change vs as-is; * = p < 0.05 (paired t-test).\n",
         md_table(["Scenario"] + [lbl for _, lbl in keys], rows), "\n",
         "### Reading the result\n",
         reading(res, asis), "\n"]
    (out / "report.md").write_text("\n".join(L))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
        for n, wk in weekly_curves.items():
            ax.plot([w * 7 for w in wk], list(wk.values()), label=n, lw=1.6)
        ax.axvspan(INCIDENT["start_day"], INCIDENT["end_day"], color="#e45756", alpha=0.12,
                   label=f"{INCIDENT['tool']} down")
        ax.set_xlabel("simulation day")
        ax.set_ylabel("weekly mean cycle time (h)")
        ax.set_title("Cycle-time spike and recovery (seed 1)", fontsize=10)
        ax.legend(fontsize=6.5, frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out / "weekly_cycle_time.png")
    except ImportError:
        pass
    print((out / "report.md").read_text())


if __name__ == "__main__":
    main()
