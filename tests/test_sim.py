import sqlite3
from pathlib import Path

import pytest

from fabsim.config import load_config, parse_config
from fabsim.queueing import erlang_c
from fabsim.run import run_once
from fabsim.model import Fab
from fabsim.logger import DBLogger

CFG = Path(__file__).resolve().parent.parent / "config" / "fab_default.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CFG)


def test_route_is_reentrant(cfg):
    assert len(cfg.route) == 33
    assert sum(s.tool_group == "LITHO" for s in cfg.route) == 6
    assert len(cfg.tool_groups) == 10


def test_lot_conservation_and_littles_law(cfg):
    fab = Fab(cfg, seed=7, warmup_hours=30 * 24)
    fab.run(150 * 24)
    released = next(fab.lot_ids) - 1
    assert released == len(fab.completed) + len(fab.lots_in_fab)
    from fabsim.metrics import summarize
    s = summarize(fab)
    assert abs(s["littles_law"]["rel_error_pct"]) < 3.0
    assert s["bottleneck"] == "LITHO"


def test_deterministic_given_seed(cfg):
    a = run_once(cfg, seed=3, days=40, warmup_days=10)
    b = run_once(cfg, seed=3, days=40, warmup_days=10)
    assert a == b


def test_mmc_matches_erlang_c():
    """One tool group, Poisson arrivals, exponential service, no failures -> M/M/2."""
    raw = {
        "fab_name": "mmc", "wafers_per_lot": 25, "process_time_cv": 1.0,  # gamma(k=1) = exp
        "release": {"policy": "poisson", "interarrival_hours": 1.0},
        "tool_groups": [{"name": "Q", "tools": 2, "mtbf": 1e12, "mttr": 1e-9}],
        "modules": {"m": [["Q", 1.6, "R"]]},
        "route": [{"module": "m", "repeat": 1}],
    }
    cfg = parse_config(raw)
    theory = erlang_c(lam=1.0, mu=1 / 1.6, c=2)
    waits = []
    for seed in range(5):
        fab = Fab(cfg, seed=seed, warmup_hours=1000)
        moves = []
        fab.log.lot_move = lambda lot_id, step, tool, arr, st, en, *a: moves.append((arr, st))
        fab.run(40000)
        waits += [st - arr for arr, st in moves if arr >= 1000]
    sim_wq = sum(waits) / len(waits)
    assert sim_wq == pytest.approx(theory["Wq"], rel=0.08), (sim_wq, theory)


def test_sqlite_logging_and_invariants(cfg, tmp_path):
    db = f"sqlite:///{tmp_path/'fab.db'}"
    s = run_once(cfg, seed=11, days=60, warmup_days=15, db=db)
    con = sqlite3.connect(tmp_path / "fab.db")
    q = lambda sql: con.execute(sql).fetchall()

    assert q("SELECT COUNT(*) FROM runs")[0][0] == 1
    n_lots = q("SELECT COUNT(*) FROM lots")[0][0]
    assert n_lots == q("SELECT MAX(lot_id) FROM lots")[0][0]           # every released lot logged
    # batches: same recipe, size within limits
    bad = q("""SELECT batch_id FROM lot_moves GROUP BY batch_id
               HAVING COUNT(DISTINCT recipe) > 1 OR COUNT(*) > 6""")
    assert bad == []
    assert q("SELECT MAX(batch_size) FROM lot_moves WHERE tool_group='DIFF'")[0][0] > 1
    # a tool never produces while it is down
    overlap = q("""SELECT COUNT(*) FROM tool_states p JOIN tool_states d
                   ON p.tool_id = d.tool_id AND p.state='PROD' AND d.state='DOWN'
                   AND p.start_time < d.end_time - 1e-9 AND d.start_time < p.end_time - 1e-9""")
    assert overlap[0][0] == 0
    # queue/process times are non-negative and moves are in time order
    assert q("SELECT COUNT(*) FROM lot_moves WHERE start_time < arrive_time OR end_time < start_time")[0][0] == 0
    # views work and agree with the in-memory summary
    util = dict(q("SELECT tool_group, AVG(prod_frac) FROM v_tool_utilization GROUP BY tool_group"))
    assert util["LITHO"] == pytest.approx(s["utilization"]["LITHO"]["prod"], abs=0.01)
    assert q("SELECT COUNT(*) FROM v_daily_outs")[0][0] > 0
