"""Agent tests with a scripted fake model (no API key or network needed)."""
import json

import pytest

from fabsim.agent import TOOLS, Agent, FabTools
from fabsim.run import run_once
from fabsim.config import load_config
from fabsim.run import DEFAULT_CFG


def test_tool_schemas_match_implementations():
    t = FabTools()
    for spec in TOOLS:
        assert hasattr(t, f"t_{spec['name']}")
        assert spec["input_schema"]["type"] == "object"


def test_capacity_check_flags_overload():
    rows = FabTools().t_capacity_check(tool_counts={"LITHO": 2})
    litho = next(r for r in rows if r["tool_group"] == "LITHO")
    assert litho["expected_util"] > 1.0


def test_run_scenario_paired_comparison():
    out = FabTools().t_run_scenario(tool_counts={"LITHO": 4}, reps=2, days=60)
    ch = out["paired_change_vs_baseline"]["cycle_time_mean_h"]
    assert ch["change"] < 0          # adding a litho tool cuts cycle time


def test_query_db_is_read_only(tmp_path):
    db = f"sqlite:///{tmp_path / 'f.db'}"
    run_once(load_config(DEFAULT_CFG), seed=1, days=40, warmup_days=10, db=db)
    t = FabTools(db_url=db)
    rows = t.t_query_db("SELECT tool_group, avg_queue_h FROM v_queue_time_by_group ORDER BY avg_queue_h DESC")
    assert rows and "tool_group" in rows[0]
    for bad in ["DELETE FROM lots", "SELECT 1; DROP TABLE lots", "UPDATE runs SET seed=2"]:
        with pytest.raises(ValueError):
            t.t_query_db(bad)


def test_agent_loop_with_fake_model():
    script = [
        {"content": [{"type": "text", "text": "Checking capacity."},
                     {"type": "tool_use", "id": "t1", "name": "capacity_check",
                      "input": {"tool_counts": {"LITHO": 2}}}]},
        {"content": [{"type": "text", "text": "LITHO would exceed 100% utilization."}]},
    ]
    sent = []

    def fake(payload, key):
        sent.append(json.loads(json.dumps(payload)))
        return script[len(sent) - 1]

    agent = Agent(FabTools(), api_key="x", transport=fake, verbose=False)
    answer = agent.ask("What if LITHO loses a tool?")
    assert "exceed" in answer
    # second request must carry the tool_result for t1
    last = sent[1]["messages"][-1]
    assert last["role"] == "user" and last["content"][0]["tool_use_id"] == "t1"
    assert "LITHO" in last["content"][0]["content"]
