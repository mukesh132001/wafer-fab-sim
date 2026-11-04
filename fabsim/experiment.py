"""Replicated experiments: compare dispatch + release policies with statistics.

    python -m fabsim.experiment                         # 30 reps x 8 policies
    python -m fabsim.experiment --reps 10 --workers 4   # quicker

Each replication uses the same seed for every policy (common random numbers),
so policies are compared with paired t-tests and a randomized-block ANOVA.
Writes results/<name>/: runs.csv, summary.csv, stats.json, report.md, *.png
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import stats
from .config import load_config
from .run import DEFAULT_CFG, run_once

ROOT = Path(__file__).resolve().parent.parent

# Study design: variable (Poisson) order arrivals, ~240 wafer starts/day.
STUDY_RELEASE = {"arrivals": "poisson", "interarrival_hours": 2.4}

POLICIES = [
    # name,            dispatch rule, release overrides
    ("FIFO",           "FIFO",        {"policy": "constant"}),
    ("SPT",            "SPT",         {"policy": "constant"}),
    ("EDD",            "EDD",         {"policy": "constant"}),
    ("LEAST_SLACK",    "LEAST_SLACK", {"policy": "constant"}),
    ("CR",             "CR",          {"policy": "constant"}),
    ("FIFO+CONWIP",    "FIFO",        {"policy": "conwip", "wip_cap": 34}),
    ("CR+CONWIP",      "CR",          {"policy": "conwip", "wip_cap": 34}),
    ("CR+DBR",         "CR",          {"policy": "dbr", "drum": "LITHO", "drum_buffer_lots": 10}),
]
BASELINE = "FIFO"

METRICS = [  # key, label, better
    ("cycle_time_mean_h", "Mean cycle time (h)", "lower"),
    ("cycle_time_p90_h", "P90 cycle time (h)", "lower"),
    ("cycle_time_std_h", "Cycle time std dev (h)", "lower"),
    ("on_time_pct", "On-time delivery (%)", "higher"),
    ("throughput_wafers_per_day", "Throughput (wafers/day)", "higher"),
    ("avg_wip_lots", "Avg WIP (lots)", "lower"),
    ("qtime_violation_pct", "Q-time violations (%)", "lower"),
    ("lead_time_mean_h", "Order lead time (h)", "lower"),
]


def _one(args):
    cfg_path, name, rule, release, seed, days, warmup = args
    cfg = load_config(cfg_path).with_overrides(release={**STUDY_RELEASE, **release})
    s = run_once(cfg, seed=seed, rule=rule, days=days, warmup_days=warmup)
    row = {"policy": name, "seed": seed}
    row.update({k: s[k] for k, _, _ in METRICS})
    row["littles_law_err_pct"] = s["littles_law"]["rel_error_pct"]
    row["litho_util"] = s["utilization"]["LITHO"]["prod"]
    return row


def run_experiment(reps=30, days=200, warmup=30, workers=None, cfg_path=DEFAULT_CFG,
                   policies=POLICIES, out_dir=None, progress=True):
    jobs = [(str(cfg_path), n, r, rel, seed, days, warmup)
            for seed in range(1, reps + 1) for n, r, rel in policies]
    t0 = time.time()
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    rows = []
    if workers == 1:
        for i, j in enumerate(jobs, 1):
            rows.append(_one(j))
            if progress and i % len(policies) == 0:
                print(f"  replication {i // len(policies)}/{reps}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, row in enumerate(ex.map(_one, jobs, chunksize=2), 1):
                rows.append(row)
                if progress and i % (len(policies) * 5) == 0:
                    print(f"  {i}/{len(jobs)} runs", flush=True)
    result = analyze(rows, [p[0] for p in policies])
    result["design"] = {"reps": reps, "days": days, "warmup_days": warmup,
                        "release": STUDY_RELEASE, "policies": policies,
                        "wall_time_s": round(time.time() - t0, 1)}
    if out_dir:
        write_outputs(rows, result, Path(out_dir))
    return rows, result


def analyze(rows, names):
    by = {n: [r for r in rows if r["policy"] == n] for n in names}
    seeds = sorted({r["seed"] for r in rows})
    out = {"summary": {}, "vs_baseline": {}, "anova": {}, "littles_law_max_abs_err_pct":
           max(abs(r["littles_law_err_pct"]) for r in rows)}
    for key, label, better in METRICS:
        out["summary"][key] = {}
        for n in names:
            m, hw, sd = stats.mean_ci([r[key] for r in by[n]])
            out["summary"][key][n] = {"mean": m, "ci": hw, "std": sd}
        matrix = [[next(r[key] for r in by[n] if r["seed"] == s) for n in names] for s in seeds]
        out["anova"][key] = {"rcbd": stats.anova_rcbd(matrix),
                             "oneway": stats.anova_oneway([[r[key] for r in by[n]] for n in names])}
        base = {r["seed"]: r[key] for r in by[BASELINE]}
        comps = {}
        for n in names:
            if n == BASELINE:
                continue
            a = [next(r[key] for r in by[n] if r["seed"] == s) for s in seeds]
            b = [base[s] for s in seeds]
            t = stats.paired_t(a, b)
            t["pct_change"] = 100 * t["mean_diff"] / np.mean(b) if np.mean(b) else None
            comps[n] = t
        adj = stats.holm([c["p"] for c in comps.values()])
        for c, pa in zip(comps.values(), adj):
            c["p_holm"] = pa
        out["vs_baseline"][key] = comps
    return out


def _fmt_p(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def write_outputs(rows, result, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    names = [p[0] for p in result["design"]["policies"]]
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "policy", "mean", "ci95_half_width", "std",
                    "diff_vs_FIFO", "pct_vs_FIFO", "p_paired", "p_holm"])
        for key, _, _ in METRICS:
            for n in names:
                s = result["summary"][key][n]
                c = result["vs_baseline"][key].get(n, {})
                w.writerow([key, n, round(s["mean"], 4), round(s["ci"], 4), round(s["std"], 4),
                            round(c.get("mean_diff", 0), 4), round(c.get("pct_change") or 0, 2),
                            c.get("p", ""), c.get("p_holm", "")])
    (out / "stats.json").write_text(json.dumps(result, indent=2, default=float))
    (out / "report.md").write_text(render_report(result))
    try:
        make_charts(rows, result, out)
    except ImportError:
        print("  (matplotlib not installed - skipping charts)")


def render_report(r) -> str:
    d = r["design"]
    names = [p[0] for p in d["policies"]]
    L = [f"# Dispatch policy study\n",
         f"{d['reps']} replications x {len(names)} policies, {d['days']} days each "
         f"({d['warmup_days']}-day warm-up), Poisson order arrivals every "
         f"{d['release']['interarrival_hours']} h on average. Common random numbers: "
         f"every policy sees the same tool failures and lots for a given seed.\n",
         "Mean ± 95% CI. Δ = paired difference vs FIFO; p = paired t-test, Holm-adjusted.\n"]
    for key, label, better in METRICS:
        L.append(f"\n## {label}  ({better} is better)\n")
        a = r["anova"][key]["rcbd"]
        L.append(f"Randomized-block ANOVA: F({a['df_treatment']}, {a['df_error']}) = {a['F']:.1f}, "
                 f"p {_fmt_p(a['p'])}\n")
        L.append("| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |\n|---|---|---|---|---|")
        for n in names:
            s = r["summary"][key][n]
            c = r["vs_baseline"][key].get(n)
            if c:
                L.append(f"| {n} | {s['mean']:.2f} ± {s['ci']:.2f} | {c['mean_diff']:+.2f} | "
                         f"{c['pct_change']:+.1f}% | {_fmt_p(c['p_holm'])} |")
            else:
                L.append(f"| {n} (baseline) | {s['mean']:.2f} ± {s['ci']:.2f} | - | - | - |")
    L.append(f"\nLittle's Law check: max |WIP - TH x CT| / WIP across all "
             f"{d['reps'] * len(names)} runs = {r['littles_law_max_abs_err_pct']:.2f}%.\n")
    return "\n".join(L) + "\n"


def make_charts(rows, result, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = [p[0] for p in result["design"]["policies"]]
    for key, label in [("cycle_time_mean_h", "Mean cycle time (h)"),
                       ("on_time_pct", "On-time delivery (%)"),
                       ("cycle_time_p90_h", "P90 cycle time (h)")]:
        s = result["summary"][key]
        fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
        means = [s[n]["mean"] for n in names]
        cis = [s[n]["ci"] for n in names]
        colors = ["#8a8f98" if n == BASELINE else "#2f6fde" for n in names]
        ax.bar(names, means, yerr=cis, capsize=3, color=colors)
        lo = min(m - c for m, c in zip(means, cis))
        hi = max(m + c for m, c in zip(means, cis))
        ax.set_ylim(lo - (hi - lo) * 0.6, hi + (hi - lo) * 0.2)
        ax.set_ylabel(label)
        ax.set_title(f"{label} by policy (mean ± 95% CI, n={result['design']['reps']})", fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        plt.xticks(rotation=25, ha="right", fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"{key}.png")
        plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description="Replicated dispatch-policy experiment")
    p.add_argument("--reps", type=int, default=30)
    p.add_argument("--days", type=float, default=200)
    p.add_argument("--warmup", type=float, default=30)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--config", default=str(DEFAULT_CFG))
    p.add_argument("--out", default=str(ROOT / "results" / "dispatch_study"))
    a = p.parse_args(argv)
    print(f"Running {a.reps} reps x {len(POLICIES)} policies ...")
    _, r = run_experiment(a.reps, a.days, a.warmup, a.workers, a.config, out_dir=a.out)
    print(render_report(r))
    print(f"Wrote {a.out}  ({r['design']['wall_time_s']} s)")


if __name__ == "__main__":
    main()
