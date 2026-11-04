# Wafer Fab Simulator & Dispatch Optimizer

A discrete-event simulation of a small semiconductor fab, used to test **dispatch
rules** and **release policies** and to measure their effect on cycle time,
throughput, WIP and on-time delivery. Results are backed by paired statistics, and the
simulator is validated against queueing theory. It also includes a root-cause case
study, a line dashboard and an LLM agent that runs what-if studies.

![Dashboard](docs/dashboard.png)

## Headline results

**Dispatch policy study:** 8 policies × 30 paired replications (240 runs), 200 days each,
variable (Poisson) order arrivals, ~243 wafers/day. Every policy sees the same tool
failures and lots for a given seed (common random numbers), so policies are compared
with paired t-tests (Holm-adjusted) and a randomized-block ANOVA.
Full report: [`results/dispatch_study/report.md`](results/dispatch_study/report.md)

| Policy | Mean cycle time (h) | P90 CT (h) | On-time % | Avg WIP (lots) | Wafers/day |
|---|---|---|---|---|---|
| FIFO (baseline) | 77.7 ± 3.1 | 108.3 ± 8.0 | 66.3 ± 4.6 | 32.3 | 243.4 |
| SPT | 77.6 ± 3.1 | 108.0 ± 7.8 | 66.5 ± 4.6 | 32.2 | 243.4 |
| EDD | 73.7 ± 2.3 | 98.2 ± 4.8 | 75.2 ± 5.0 | 30.6 | 243.2 |
| Least slack | 73.0 ± 2.3 | 97.0 ± 4.7 | 79.4 ± 4.9 | 30.3 | 243.2 |
| **Critical ratio (CR)** | 74.6 ± 1.9 | 97.9 ± 3.3 | **79.8 ± 4.6** | 31.0 | 243.3 |
| **FIFO + CONWIP** | **69.4 ± 0.9** | **82.1 ± 1.0** | 65.3 ± 5.5 | 28.8 | 243.4 |
| CR + CONWIP | 70.1 ± 0.9 | 88.5 ± 1.0 | 73.5 ± 6.3 | 29.1 | 243.3 |
| CR + drum-buffer-rope | 70.2 ± 1.0 | 89.2 ± 1.3 | 73.0 ± 6.0 | 29.1 | 243.2 |

Mean ± 95% CI (confidence interval) across replications.

* **CR dispatch** raises on-time delivery from **66.3% to 79.8% (+13.5 pts, p < 0.001)**
  at unchanged throughput (ANOVA p = 0.62).
* **CONWIP release** (WIP-capped) cuts mean fab cycle time **10.6%**, P90 cycle time **24%**
  and cycle-time standard deviation **50%** (all p < 0.001) at equal throughput.
* **Trade-offs:**
  * WIP control moves waiting from inside the fab to the order queue, so the total order lead time doesn't change (p = 0.99).
  * Due-date rules (EDD, CR, slack) raise Q-time (queue-time limit) violations from 1.1% to 1.7–2.4%.
  * SPT doesn't help in this fab, because process times at a given tool group are nearly identical.
* **Validation:**
  * Little's Law (WIP = throughput × cycle time) holds within 3.1% on all 240 runs.
  * An M/M/2 test case matches the Erlang-C formula.

![Cycle time by policy](results/dispatch_study/cycle_time_mean_h.png)
![On-time by policy](results/dispatch_study/on_time_pct.png)

## Root-cause case study

A 14-day outage of one litho tool (`LITHO_02`) is injected. Then the spike is traced
with SQL only, as an IE would: weekly cycle time → which queue exploded → which tool
was down → capacity math (litho utilization would need to be 137% → WIP piles up
~2.7 lots/day). Finally, countermeasures are compared over 20 paired replications.
Full report with the SQL: [`results/case_study/report.md`](results/case_study/report.md)

| Scenario | Mean CT (h) | Peak weekly CT (h) | On-time % |
|---|---|---|---|
| No incident (reference) | 64.6 | 76.6 | 89.8 |
| As-is (FIFO, push release) | 95.8 | 207.7 | 60.1 |
| CR dispatch | 83.6 | 148.8 | 66.6 |
| CR + DBR rope | 71.9 | 88.9 | 56.8 |
| Expedite repair (14 → 5 days) | 69.0 | 111.8 | 81.6 |
| Expedite + CR + DBR | **66.5** | **78.3** | **89.4** |

![Weekly cycle time](results/case_study/weekly_cycle_time.png)

## The fab model

| | |
|---|---|
| Tool groups | 10 (29 tools): CLEAN, DIFF (batch furnace), LITHO, ETCH, IMPLANT, DEPO, CMP, PVD, METRO, PROBE |
| Route | 33 steps, **re-entrant**: FEOL → 2 device layers → 3 metal layers → wafer sort. LITHO and ETCH are each visited 6× |
| Flow unit | lots of 25 wafers |
| Variability | gamma process times (CV 0.3); exponential failures (MTBF/MTTR) that interrupt jobs mid-process; scheduled incidents |
| Batching | DIFF furnaces batch up to 6 lots of one recipe; start at ≥ 3 lots or after a 3 h max wait |
| Q-time limits | max queue time at oxidation, anneal and deposition steps |
| Yield | per-wafer scrap at ETCH, CMP and PROBE → line yield |
| Due dates | per-lot flow factor 1.3–2.2 × raw process time |
| Dispatch rules | FIFO, SPT, EDD, critical ratio, least slack (`fabsim/dispatch.py`) |
| Release policies | push (constant or Poisson), CONWIP (WIP cap), drum-buffer-rope (rope on the litho buffer) |

Everything is set in [`config/fab_default.toml`](config/fab_default.toml).

## Quick start

```bash
pip install -r requirements.txt          # + optional: pip install matplotlib (charts)

python -m fabsim.run --capacity          # static capacity / bottleneck table
python -m fabsim.run --rule CR           # one 120-day run
python -m fabsim.run --db sqlite:///fab.db --days 180          # log every event to SQLite
python -m fabsim.experiment              # the 240-run policy study (~4 min)
python -m fabsim.casestudy               # the root-cause case study
python -m fabsim.api --db sqlite:///fab.db   # dashboard at http://localhost:8000
pytest -q
```

PostgreSQL: `docker compose up -d`, then use `--db postgresql://fab:fab@localhost:5432/fab`.

### AI agent

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
python -m fabsim.agent "What if LITHO loses one tool for 10 days starting day 60?"
python -m fabsim.agent --db sqlite:///fab.db "Which route step had the worst queue time and why?"
```

The agent (Claude tool use, standard library HTTP) has six tools:

* `list_fab`
* `capacity_check`
* `run_scenario`: paired comparison vs baseline, with CIs and p-values
* `compare_rules`
* `get_schema`
* `query_db`: read-only text-to-SQL, guarded to a single SELECT

The tools run the simulations and SQL, so every number in an answer comes from a real
run. The model is set with `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`).

## Architecture

```
config/fab_default.toml   fab definition (tool groups, route modules, release, Q-time limits)
fabsim/config.py          TOML -> typed specs, capacity analysis, what-if overrides
fabsim/model.py           SimPy model: lots, tool groups, tools, failures, incidents, release gate
fabsim/dispatch.py        dispatch rules (priority functions) + batch formation
fabsim/metrics.py         run summary, Little's Law check, Q-time, on-time
fabsim/stats.py           CIs, paired/Welch t, one-way + randomized-block ANOVA, Holm (no SciPy)
fabsim/queueing.py        Erlang-C (M/M/c), Kingman approximation
fabsim/experiment.py      replicated policy study -> report, CSV, charts
fabsim/casestudy.py       incident -> SQL trace -> countermeasures
fabsim/logger.py, db.py   PostgreSQL / SQLite logging and queries
fabsim/api.py             JSON API + dashboard server (standard library)
fabsim/agent.py           LLM what-if agent
dashboard/index.html      line dashboard (no build step; light/dark)
sql/schema.sql, views.sql tables + metric views (portable PostgreSQL/SQLite)
```

### Data model

| Table | One row per |
|---|---|
| `runs` | simulation run (rule, release policy, seed, horizon, config + summary JSON) |
| `lots` | lot: release, due, completion, wafers in/out |
| `lot_moves` | lot × route step: arrive / start / end, tool, batch |
| `tool_states` | tool PROD or DOWN interval |
| `wip_snapshots` | tool group × 4-hour snapshot |

Views:

* `v_lot_cycle_time`
* `v_queue_time_by_group`
* `v_tool_utilization`
* `v_daily_outs`
* `v_line_yield`
* `v_weekly_cycle_time`
* `v_queue_heatmap`
* `v_wip_by_group`
* `v_step_queue`

## Validation & testing

* **Little's Law**: checked against time-weighted WIP on every run.
* **M/M/c**: a single-group fab with Poisson arrivals and exponential service matches
  Erlang-C queue time within 8%.
* **Invariants**:
  * lots are conserved
  * batches never mix recipes
  * no tool produces while it is down
  * timestamps are ordered
  * SQL views match the in-memory statistics
* **Statistics module**: checked against SciPy (t, F, ANOVA, paired/Welch tests).
* **Agent**: tested with a scripted model; the SQL tool rejects anything other than a single SELECT.
* **CI** (GitHub Actions): runs the tests with real SimPy, logs runs to a PostgreSQL 16 service,
  queries the views and smoke-tests the API, the experiment and the case study.

## Roadmap

- [ ] Angular front end on the existing JSON API (`/api/*`, CORS enabled)
- [ ] Multiple products and hot lots; Q-time-aware dispatching
- [ ] Yield root-cause analysis on the UCI SECOM dataset (SPC charts, feature selection)
