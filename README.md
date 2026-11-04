# Wafer Fab Simulator & Dispatch Optimizer

A discrete-event simulation of a small semiconductor fab, built to test
scheduling (dispatch) rules and measure their effect on **cycle time,
throughput and WIP**. Every lot move and tool event is written to
PostgreSQL for SQL-based analysis.

> Status: **Week 1 complete.** Fab model, SimPy simulation (FIFO), PostgreSQL/SQLite
> logging, starter metric views, Little's Law and M/M/c validation tests.

## The fab

| | |
|---|---|
| Tool groups | 10: CLEAN, DIFF (batch furnace), LITHO, ETCH, IMPLANT, DEPO, CMP, PVD, METRO, PROBE (29 tools) |
| Route | 33 steps, **re-entrant**: FEOL → 2 device layers → 3 metal layers → wafer sort. LITHO and ETCH are each visited 6× |
| Unit of flow | Lots of 25 wafers (how real fabs move material) |
| Variability | Gamma process times (CV 0.3), random failures (exponential MTBF/MTTR) that interrupt jobs mid-process |
| Batching | DIFF furnaces batch up to 6 lots of the same recipe; start at ≥3 lots or after a 3 h max wait |
| Yield | Per-wafer scrap at ETCH, CMP, PROBE → line yield |
| Release | One lot every 2.4 h (10 lots / 250 wafers per day) |

Everything lives in [`config/fab_default.yaml`](config/fab_default.yaml), so what-if
studies are config changes.

## Quick start

```bash
pip install -r requirements.txt

python -m fabsim.run --capacity              # static capacity / bottleneck table
python -m fabsim.run                         # 120-day run, 30-day warm-up, no DB
python -m fabsim.run --db sqlite:///fab.db   # log to SQLite (zero setup)

docker compose up -d                         # PostgreSQL 16 on localhost:5432
python -m fabsim.run --db postgresql://fab:fab@localhost:5432/fab --seed 1

pytest -q
```

Sample output:

```
=== FIFO | 90 days measured ===
Throughput     : 245.6 wafers/day (10.04 lots/day)
Cycle time     : mean 65.04 h (2.71 d), p90 75.85 h, x-factor 1.37
Avg WIP        : 27.1 lots   On-time: 99.9%   Line yield: 97.78%
Little's Law   : WIP 27.1 vs TH x CT 27.22 (+0.43%)
Utilization    : LITHO 85%  ETCH 78%  DIFF 66%  METRO 63%  PVD 54%  CMP 54% ...
Bottleneck     : LITHO
```

## Baseline (FIFO, 10 replications, 95% CI)

| Metric | Mean ± CI |
|---|---|
| Throughput | 245.3 ± 0.7 wafers/day |
| Cycle time | 63.6 ± 0.8 h |
| X-factor (CT / raw process time) | 1.34 ± 0.02 |
| Avg WIP | 26.5 ± 0.3 lots |
| Little's Law error (WIP vs TH × CT) | within ±1.3% on every run |

## Validation

* **Little's Law**: time-weighted WIP is checked against throughput × cycle time on every run.
* **M/M/c**: a single-group fab with Poisson arrivals and exponential service is compared
  with the Erlang-C formula (`fabsim/queueing.py`); simulated queue time matches theory
  (Wq = 2.84 h at ρ = 0.8, c = 2) within 8%.
* **Invariants** (tests): lot conservation, batches never mix recipes, a tool never
  produces while down, timestamps are ordered, SQL views agree with in-memory stats.

## Architecture

```
config/fab_default.yaml   fab definition (tool groups, modules, route, release)
fabsim/config.py          YAML -> typed specs, capacity analysis, what-if overrides
fabsim/model.py           SimPy model: Lot, ToolGroup, Tool (+ failure process), Fab
fabsim/dispatch.py        dispatch rules (priority functions) + batch formation
fabsim/logger.py          buffered event logging -> PostgreSQL or SQLite
fabsim/metrics.py         run summary, Little's Law check
fabsim/queueing.py        Erlang-C (M/M/c), Kingman approximation
fabsim/run.py             CLI
sql/schema.sql            runs, lots, lot_moves, tool_states, wip_snapshots
sql/views.sql             cycle time, queue time, utilization, daily outs, line yield
```

Dispatch rules are a single function `priority(entry, now) -> sort key`, so adding
SPT, critical ratio or least slack is a few lines in `dispatch.py`; batch tools reuse the
same rule automatically.

### Data model

| Table | One row per |
|---|---|
| `runs` | simulation run (rule, seed, horizon, full config + summary as JSON) |
| `lots` | lot (release, due, completion, wafers in/out) |
| `lot_moves` | lot × route step: arrive / start / end, tool, batch |
| `tool_states` | tool PROD or DOWN interval |
| `wip_snapshots` | tool group × 4-hour snapshot (queued / in process) |

Example:

```sql
SELECT tool_group, ROUND(avg_queue_h::numeric, 2) AS avg_queue_h
FROM v_queue_time_by_group WHERE run_id = '<run_id>' ORDER BY 2 DESC;
```

## Roadmap

- [x] **Week 1**: fab model, SimPy simulation (FIFO), PostgreSQL logging, validation
- [ ] **Week 2**: SPT, critical ratio, least slack, drum-buffer-rope release; 30+ replications,
      confidence intervals, ANOVA / paired t-tests; queue-time vs M/M/c per tool group
- [ ] **Week 3**: full SQL metric views and Angular dashboard (line metrics, bottleneck heatmap, WIP by step)
- [ ] **Week 4**: LLM agent with `run_scenario`, `query_metrics`, `compare_rules` tools;
      root-cause case study; write-up
- [ ] Add-on: yield root-cause analysis on the UCI SECOM dataset (SPC charts, feature selection)
