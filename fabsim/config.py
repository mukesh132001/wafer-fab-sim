"""Load the fab definition (TOML) into typed objects + static capacity analysis."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import json
import tomllib


@dataclass(frozen=True)
class ToolGroupSpec:
    name: str
    tools: int
    mtbf: float                    # mean time between failures (h)
    mttr: float                    # mean time to repair (h)
    batch_max: int = 1
    batch_min: int = 1
    max_batch_wait: float = 0.0    # h a lot may wait for a fuller batch
    scrap_rate: float = 0.0        # per-wafer scrap probability per step

    @property
    def is_batch(self) -> bool:
        return self.batch_max > 1

    @property
    def availability(self) -> float:
        return self.mtbf / (self.mtbf + self.mttr)


@dataclass(frozen=True)
class Step:
    index: int                     # 0-based position in the route
    tool_group: str
    process_hours: float           # per lot, or per batch for batch tools
    recipe: str
    remaining_hours: float = 0.0   # raw process time from this step (incl.) to route end
    qtime_limit: float | None = None   # max allowed queue time at this step (h), if any


@dataclass
class FabConfig:
    fab_name: str
    wafers_per_lot: int
    process_time_cv: float
    due_date_flow_factor: float
    release: dict
    tool_groups: dict[str, ToolGroupSpec]
    route: list[Step]
    qtime_limits: dict[str, float] = field(default_factory=dict)
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def raw_process_time(self) -> float:
        """Theoretical minimum cycle time (no queueing), h."""
        return sum(s.process_hours for s in self.route)

    def with_overrides(self, tool_counts: dict[str, int] | None = None,
                       interarrival_hours: float | None = None,
                       release: dict | None = None,
                       group_params: dict[str, dict] | None = None,
                       incidents: list[dict] | None = None) -> "FabConfig":
        """Return a modified copy - used for what-if scenarios.

        tool_counts   {"LITHO": 2}                  change number of tools
        release       {"policy": "dbr", "drum_buffer_lots": 6}
        group_params  {"LITHO": {"mttr": 12}}       change any tool-group field
        incidents     [{"tool": "LITHO_02", "start_day": 80, "end_day": 94}]
        """
        raw = copy.deepcopy(self.raw)
        names = {tg["name"] for tg in raw["tool_groups"]}
        for name in list(tool_counts or {}) + list(group_params or {}):
            if name not in names:
                raise ValueError(f"Unknown tool group {name!r}; choose from {sorted(names)}")
        for tg in raw["tool_groups"]:
            if tool_counts and tg["name"] in tool_counts:
                tg["tools"] = int(tool_counts[tg["name"]])
            if group_params and tg["name"] in group_params:
                tg.update(group_params[tg["name"]])
        if interarrival_hours is not None:
            raw["release"]["interarrival_hours"] = float(interarrival_hours)
        if release:
            raw["release"].update(release)
        if incidents is not None:
            raw["incidents"] = list(incidents)
        return parse_config(raw)


def parse_config(raw: dict) -> FabConfig:
    groups = {g["name"]: ToolGroupSpec(**g) for g in raw["tool_groups"]}
    steps: list[tuple] = []
    for block in raw["route"]:
        module = raw["modules"][block["module"]]
        for _ in range(block.get("repeat", 1)):
            for group, hours, recipe in module:
                if group not in groups:
                    raise ValueError(f"Route uses unknown tool group {group!r}")
                steps.append((group, float(hours), recipe))
    qlim = {k: float(v) for k, v in raw.get("qtime_limits", {}).items()}
    route, remaining = [], 0.0
    for i in range(len(steps) - 1, -1, -1):
        group, hours, recipe = steps[i]
        remaining += hours
        route.append(Step(i, group, hours, recipe, remaining, qlim.get(recipe)))
    steps = route[::-1]
    return FabConfig(
        fab_name=raw["fab_name"],
        wafers_per_lot=int(raw["wafers_per_lot"]),
        process_time_cv=float(raw.get("process_time_cv", 0.0)),
        due_date_flow_factor=float(raw.get("due_date_flow_factor", 3.0)),
        release=dict(raw["release"]),
        tool_groups=groups,
        route=steps,
        qtime_limits=qlim,
        raw=raw,
    )


def load_config(path: str | Path) -> FabConfig:
    """Load a fab definition from .toml (built-in tomllib), .json, or .yaml (needs PyYAML)."""
    path = Path(path)
    if path.suffix == ".toml":
        with open(path, "rb") as f:
            return parse_config(tomllib.load(f))
    if path.suffix == ".json":
        return parse_config(json.loads(path.read_text()))
    if path.suffix in (".yaml", ".yml"):
        import yaml  # optional dependency
        return parse_config(yaml.safe_load(path.read_text()))
    raise ValueError(f"Unsupported config format: {path.suffix}")


def capacity_table(cfg: FabConfig) -> list[dict]:
    """Expected utilization per tool group at the configured release rate.

    u = lambda * sum(process time per visit) / (tools * availability * batch_size)
    Batch groups use batch_max, so their figure is a lower bound (batches are
    not always full). The group with the highest u is the expected bottleneck.
    """
    lam = 1.0 / cfg.release["interarrival_hours"]
    rows = []
    for name, g in cfg.tool_groups.items():
        visits = [s for s in cfg.route if s.tool_group == name]
        work = sum(s.process_hours for s in visits) / g.batch_max
        u = lam * work / (g.tools * g.availability)
        rows.append({"tool_group": name, "visits": len(visits), "tools": g.tools,
                     "availability": round(g.availability, 3),
                     "work_h_per_lot": round(work, 2), "expected_util": round(u, 3)})
    return sorted(rows, key=lambda r: -r["expected_util"])
