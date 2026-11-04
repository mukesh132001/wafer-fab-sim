"""LLM agent that runs what-if studies on the fab simulator and queries its database.

    set ANTHROPIC_API_KEY=sk-ant-...            (PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-...")
    python -m fabsim.agent "What if LITHO loses one tool?"
    python -m fabsim.agent --db sqlite:///fab.db "Which step had the worst queue time and why?"
    python -m fabsim.agent                       # interactive

The model decides which tools to call; the tools do the real work (simulation,
statistics, SQL), so every number in an answer comes from a run, not the model.
Uses the Claude Messages API over HTTPS with the standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

import numpy as np

from . import stats
from .config import capacity_table, load_config
from .db import DB
from .dispatch import RULES
from .run import DEFAULT_CFG, run_once

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
API_VERSION = os.environ.get("ANTHROPIC_VERSION", "2026-10-21")

SYSTEM = """You are an industrial-engineering assistant for a simulated 300 mm wafer fab
(10 tool groups, 33-step re-entrant route, LITHO is the usual bottleneck).
Answer what-if and diagnostic questions by calling tools - never invent numbers.
- For capacity questions, call capacity_check first (instant), then run_scenario to confirm.
- run_scenario always compares against a baseline with the same random seeds and returns
  paired differences with p-values. Report effects as mean change with the 95% CI, and say
  whether p < 0.05. With few reps, say the result is preliminary.
- For questions about logged runs, inspect get_schema, then write ONE read-only SELECT for
  query_db. Times are in hours; weeks = floor(time/168).
- Explain the mechanism (utilization, queueing, Little's Law: WIP = throughput x cycle time).
Be concise: a short answer, then a compact table of the key numbers."""

KEYS = ["throughput_wafers_per_day", "cycle_time_mean_h", "cycle_time_p90_h", "on_time_pct",
        "avg_wip_lots", "qtime_violation_pct"]

TOOLS = [
    {"name": "list_fab",
     "description": "List tool groups (tool counts, MTBF/MTTR, batch settings), dispatch rules and release policies.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "capacity_check",
     "description": "Instant static capacity analysis: expected utilization per tool group after optional changes. Utilization >= 1 means the fab cannot keep up.",
     "input_schema": {"type": "object", "properties": {
         "tool_counts": {"type": "object", "description": "e.g. {\"LITHO\": 2}", "additionalProperties": {"type": "integer"}},
         "interarrival_hours": {"type": "number", "description": "hours between lot starts (default 2.4)"}}}},
    {"name": "run_scenario",
     "description": "Simulate a what-if scenario and compare it with the baseline (FIFO, constant release, current config) using the same seeds. Returns mean +/- 95% CI for both and paired differences with p-values.",
     "input_schema": {"type": "object", "properties": {
         "rule": {"type": "string", "enum": list(RULES), "description": "dispatch rule (default FIFO)"},
         "release_policy": {"type": "string", "enum": ["constant", "poisson", "conwip", "dbr"]},
         "wip_cap": {"type": "integer", "description": "CONWIP WIP cap (lots)"},
         "drum_buffer_lots": {"type": "integer", "description": "DBR buffer target (lots)"},
         "tool_counts": {"type": "object", "additionalProperties": {"type": "integer"}},
         "group_params": {"type": "object", "description": "e.g. {\"LITHO\": {\"mttr\": 10}}"},
         "interarrival_hours": {"type": "number"},
         "incident": {"type": "object", "description": "long outage, e.g. {\"tool\": \"LITHO_02\", \"start_day\": 60, \"end_day\": 70}"},
         "reps": {"type": "integer", "description": "replications (default 5, max 30)"},
         "days": {"type": "number", "description": "simulated days incl. 30-day warm-up (default 150)"}}}},
    {"name": "compare_rules",
     "description": "Compare several dispatch rules under the same conditions (paired seeds) and rank them.",
     "input_schema": {"type": "object", "properties": {
         "rules": {"type": "array", "items": {"type": "string", "enum": list(RULES)}},
         "release_policy": {"type": "string", "enum": ["constant", "poisson", "conwip", "dbr"]},
         "interarrival_hours": {"type": "number"},
         "reps": {"type": "integer"}}, "required": ["rules"]}},
    {"name": "get_schema",
     "description": "Return the SQL schema and metric views of the run database.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "query_db",
     "description": "Run ONE read-only SELECT against the run database and return up to 200 rows.",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}},
]


class FabTools:
    def __init__(self, cfg_path=DEFAULT_CFG, db_url: str | None = None, max_reps: int = 30):
        self.cfg_path, self.db_url, self.max_reps = cfg_path, db_url, max_reps
        self.base = load_config(cfg_path)
        self._db = None

    @property
    def db(self) -> DB:
        if not self.db_url:
            raise ValueError("No database configured. Start the agent with --db sqlite:///fab.db")
        if self._db is None:
            self._db = DB(self.db_url)
        return self._db

    def call(self, name: str, args: dict):
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            raise ValueError(f"Unknown tool {name}")
        return fn(**args)

    # ---- tools ----------------------------------------------------------
    def t_list_fab(self):
        return {"tool_groups": [{"name": g.name, "tools": g.tools, "mtbf_h": g.mtbf, "mttr_h": g.mttr,
                                 "availability": round(g.availability, 3), "batch_max": g.batch_max,
                                 "tool_ids": [f"{g.name}_{i + 1:02d}" for i in range(g.tools)]}
                                for g in self.base.tool_groups.values()],
                "route_steps": len(self.base.route), "raw_process_time_h": round(self.base.raw_process_time, 1),
                "interarrival_hours": self.base.release["interarrival_hours"],
                "dispatch_rules": list(RULES), "release_policies": ["constant", "poisson", "conwip", "dbr"]}

    def t_capacity_check(self, tool_counts=None, interarrival_hours=None):
        cfg = self.base.with_overrides(tool_counts=tool_counts, interarrival_hours=interarrival_hours)
        return capacity_table(cfg)

    def _cfg(self, release_policy=None, wip_cap=None, drum_buffer_lots=None, tool_counts=None,
             group_params=None, interarrival_hours=None, incident=None):
        rel = {}
        if release_policy:
            rel["policy"] = release_policy
            if release_policy == "poisson":
                rel["arrivals"] = "poisson"
        if wip_cap:
            rel["wip_cap"] = wip_cap
        if drum_buffer_lots:
            rel["drum_buffer_lots"] = drum_buffer_lots
        return self.base.with_overrides(tool_counts=tool_counts, group_params=group_params,
                                        interarrival_hours=interarrival_hours, release=rel or None,
                                        incidents=[incident] if incident else None)

    def _runs(self, cfg, rule, reps, days):
        return [run_once(cfg, seed=s, rule=rule, days=days, warmup_days=30) for s in range(1, reps + 1)]

    @staticmethod
    def _summ(runs):
        out = {}
        for k in KEYS:
            vals = [r[k] for r in runs if r[k] is not None]
            m, hw, _ = stats.mean_ci(vals) if len(vals) > 1 else (float(np.mean(vals)), float("nan"), 0)
            out[k] = {"mean": round(m, 2), "ci95": round(hw, 2)}
        util = {g: round(float(np.mean([r["utilization"][g]["prod"] + r["utilization"][g]["down"] for r in runs])), 3)
                for g in runs[0]["utilization"]}
        out["busy_or_down_fraction_top3"] = dict(sorted(util.items(), key=lambda kv: -kv[1])[:3])
        out["littles_law_max_err_pct"] = max(abs(r["littles_law"]["rel_error_pct"]) for r in runs)
        return out

    def t_run_scenario(self, rule="FIFO", reps=5, days=150, **kw):
        reps = max(2, min(int(reps), self.max_reps))
        base_runs = self._runs(self.base, "FIFO", reps, days)
        scen_runs = self._runs(self._cfg(**kw), rule, reps, days)
        diff = {}
        for k in KEYS:
            a = [r[k] for r in scen_runs]
            b = [r[k] for r in base_runs]
            if None in a or None in b:
                continue
            t = stats.paired_t(a, b)
            diff[k] = {"change": round(t["mean_diff"], 2), "ci95": round(t["ci_half_width"], 2),
                       "pct": round(100 * t["mean_diff"] / np.mean(b), 1) if np.mean(b) else None,
                       "p": round(t["p"], 4)}
        return {"reps": reps, "days": days, "scenario": {"rule": rule, **kw},
                "baseline": self._summ(base_runs), "result": self._summ(scen_runs),
                "paired_change_vs_baseline": diff}

    def t_compare_rules(self, rules, release_policy=None, interarrival_hours=None, reps=5):
        reps = max(2, min(int(reps), self.max_reps))
        cfg = self._cfg(release_policy=release_policy, interarrival_hours=interarrival_hours)
        res = {r: self._runs(cfg, r, reps, 150) for r in rules}
        table = {r: self._summ(v) for r, v in res.items()}
        first = rules[0]
        tests = {}
        for r in rules[1:]:
            tests[r] = {k: round(stats.paired_t([x[k] for x in res[r]], [x[k] for x in res[first]])["p"], 4)
                        for k in ("cycle_time_mean_h", "on_time_pct")}
        return {"reps": reps, "results": table, f"paired_p_values_vs_{first}": tests}

    def t_get_schema(self):
        return self.db.schema()

    def t_query_db(self, sql):
        return self.db.safe_select(sql)


def call_claude(payload: dict, api_key: str) -> dict:
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), method="POST", headers={
        "x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude API error {e.code}: {e.read().decode()[:500]}") from None


class Agent:
    def __init__(self, tools: FabTools, api_key: str | None = None, transport=call_claude,
                 max_turns: int = 10, verbose: bool = True):
        self.tools, self.transport, self.max_turns, self.verbose = tools, transport, max_turns, verbose
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.messages: list[dict] = []

    def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        for _ in range(self.max_turns):
            resp = self.transport({"model": MODEL, "max_tokens": 2000, "system": SYSTEM,
                                   "tools": TOOLS, "messages": self.messages}, self.api_key)
            content = resp["content"]
            self.messages.append({"role": "assistant", "content": content})
            calls = [b for b in content if b["type"] == "tool_use"]
            if not calls:
                return "".join(b.get("text", "") for b in content if b["type"] == "text")
            results = []
            for c in calls:
                if self.verbose:
                    print(f"  -> {c['name']}({json.dumps(c['input'])[:160]})", flush=True)
                try:
                    out, err = self.tools.call(c["name"], c["input"]), False
                except Exception as e:  # tool errors go back to the model so it can correct itself
                    out, err = f"Error: {e}", True
                results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": err,
                                "content": out if isinstance(out, str) else json.dumps(out, default=float)})
            self.messages.append({"role": "user", "content": results})
        return "(stopped: too many tool calls)"


def main(argv=None):
    p = argparse.ArgumentParser(description="Fab what-if agent")
    p.add_argument("question", nargs="*")
    p.add_argument("--db", default=None, help="sqlite:///fab.db or postgresql://...")
    p.add_argument("--config", default=str(DEFAULT_CFG))
    a = p.parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first (https://console.anthropic.com).")
    agent = Agent(FabTools(a.config, a.db))
    if a.question:
        print("\n" + agent.ask(" ".join(a.question)))
        return
    print(f"Fab agent ({MODEL}). Ask a what-if question; empty line to quit.")
    while True:
        q = input("\n> ").strip()
        if not q:
            break
        print("\n" + agent.ask(q))


if __name__ == "__main__":
    main()
