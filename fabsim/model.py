"""Discrete-event model of a small re-entrant wafer fab (SimPy).

Entities
  Lot        25 wafers travelling the route step by step
  ToolGroup  shared queue + N identical tools (optionally batch tools)
  Tool       a SimPy process: pick lot(s) via the dispatch rule, process, repeat.
             A second process per tool injects random failures (exp. MTBF/MTTR)
             that interrupt processing; the job resumes after repair.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import simpy

from .config import FabConfig, Step, ToolGroupSpec
from .dispatch import RULES, QueueEntry, select
from .logger import NullLogger


@dataclass
class Lot:
    lot_id: int
    release_time: float
    due_time: float
    wafers: int
    wafers_start: int
    step_idx: int = 0
    complete_time: float | None = None


class ToolGroup:
    def __init__(self, fab: "Fab", spec: ToolGroupSpec):
        self.fab, self.spec = fab, spec
        self.queue: list[QueueEntry] = []
        self._signal: simpy.Event | None = None
        self.tools = [Tool(fab, self, i) for i in range(spec.tools)]

    # Simple broadcast "something changed" event that idle tools wait on.
    def wait(self) -> simpy.Event:
        if self._signal is None or self._signal.triggered:
            self._signal = self.fab.env.event()
        return self._signal

    def notify(self) -> None:
        if self._signal is not None and not self._signal.triggered:
            self._signal.succeed()

    def arrive(self, lot: Lot, step: Step) -> None:
        self.queue.append(QueueEntry(lot, step, self.fab.env.now))
        self.notify()
        if self.spec.is_batch and self.spec.max_batch_wait > 0:
            self.fab.env.process(self._wake_after(self.spec.max_batch_wait))

    def _wake_after(self, delay: float):
        yield self.fab.env.timeout(delay)
        self.notify()


class Tool:
    def __init__(self, fab: "Fab", group: ToolGroup, idx: int):
        self.fab, self.group = fab, group
        self.tool_id = f"{group.spec.name}_{idx + 1:02d}"
        self.up = True
        self.busy = False
        self.repair_done: simpy.Event | None = None
        self.proc = fab.env.process(self.run())
        fab.env.process(self.failures())

    def run(self):
        env, fab, spec = self.fab.env, self.fab, self.group.spec
        while True:
            batch: list[QueueEntry] = []
            while not batch:
                if self.up:
                    batch = select(self.group.queue, spec, fab.rule, env.now)
                if not batch:
                    yield self.group.wait()
            for e in batch:
                self.group.queue.remove(e)
            start = env.now
            batch_id = next(fab.batch_ids)
            step = batch[0].step
            remaining = fab.sample_process_time(step.process_hours)

            self.busy = True
            seg_start = env.now
            while remaining > 1e-9:
                t0 = env.now
                try:
                    yield env.timeout(remaining)
                    remaining = 0.0
                except simpy.Interrupt:              # tool went down mid-job
                    remaining -= env.now - t0
                    fab.record_state(self.tool_id, spec.name, "PROD", seg_start, env.now, batch_id)
                    yield self.repair_done
                    seg_start = env.now
            self.busy = False
            fab.record_state(self.tool_id, spec.name, "PROD", seg_start, env.now, batch_id)

            for e in batch:
                fab.finish_step(e, self.tool_id, start, env.now, batch_id, len(batch))
            self.group.notify()       # let another idle tool re-check the queue

    def failures(self):
        env, spec, rng = self.fab.env, self.group.spec, self.fab.rng
        while True:
            yield env.timeout(rng.exponential(spec.mtbf))
            self.up = False
            self.repair_done = env.event()
            down_at = env.now
            if self.busy:
                self.proc.interrupt("failure")
            yield env.timeout(rng.exponential(spec.mttr))
            self.up = True
            self.fab.record_state(self.tool_id, spec.name, "DOWN", down_at, env.now, None)
            self.repair_done.succeed()
            self.group.notify()


class Fab:
    def __init__(self, cfg: FabConfig, seed: int = 1, rule: str = "FIFO",
                 warmup_hours: float = 0.0, logger=None, snapshot_every: float = 4.0):
        self.cfg = cfg
        self.env = simpy.Environment()
        self.rng = np.random.default_rng(seed)
        self.rule_name = rule
        self.rule = RULES[rule]
        self.warmup = warmup_hours
        self.log = logger or NullLogger()
        self.batch_ids = itertools.count(1)
        self.lot_ids = itertools.count(1)
        self.groups = {n: ToolGroup(self, s) for n, s in cfg.tool_groups.items()}
        self.lots_in_fab: dict[int, Lot] = {}
        self.completed: list[Lot] = []
        self.wafers_started = 0
        self.state_hours: dict[tuple[str, str], float] = {}
        # time-weighted WIP (lots) after warm-up, for Little's Law
        self._wip_area = 0.0
        self._wip_last_t = 0.0
        self.env.process(self.release())
        self.env.process(self.snapshots(snapshot_every))

    # ---- randomness -------------------------------------------------------
    def sample_process_time(self, mean: float) -> float:
        cv = self.cfg.process_time_cv
        if cv <= 0:
            return mean
        k = 1.0 / cv ** 2
        return float(self.rng.gamma(k, mean / k))

    # ---- tool state accounting (post warm-up, in memory + DB) -------------
    def record_state(self, tool_id, group, state, start, end, batch_id) -> None:
        self.log.tool_state(tool_id, group, state, start, end, batch_id)
        lo = max(start, self.warmup)
        if end > lo:
            key = (group, state)
            self.state_hours[key] = self.state_hours.get(key, 0.0) + end - lo

    # ---- WIP accounting ---------------------------------------------------
    def _wip_change(self, delta: int) -> None:
        now = self.env.now
        if now > self.warmup:
            t0 = max(self._wip_last_t, self.warmup)
            self._wip_area += len(self.lots_in_fab) * (now - t0)
        self._wip_last_t = now
        # caller mutates lots_in_fab right after

    # ---- lot flow ---------------------------------------------------------
    def release(self):
        ia = self.cfg.release["interarrival_hours"]
        while True:
            now = self.env.now
            lot = Lot(next(self.lot_ids), now,
                      now + self.cfg.due_date_flow_factor * self.cfg.raw_process_time,
                      self.cfg.wafers_per_lot, self.cfg.wafers_per_lot)
            self._wip_change(+1)
            self.lots_in_fab[lot.lot_id] = lot
            self.wafers_started += lot.wafers
            self.log.lot_release(lot)
            self._send_to_step(lot)
            policy = self.cfg.release["policy"]
            if policy == "constant":
                yield self.env.timeout(ia)
            elif policy == "poisson":                    # exponential interarrivals
                yield self.env.timeout(self.rng.exponential(ia))
            else:
                raise ValueError(f"Unknown release policy {policy!r} (week 2: conwip, dbr)")

    def _send_to_step(self, lot: Lot) -> None:
        step = self.cfg.route[lot.step_idx]
        self.groups[step.tool_group].arrive(lot, step)

    def finish_step(self, e: QueueEntry, tool_id: str, start: float, end: float,
                    batch_id: int, batch_size: int) -> None:
        lot, step = e.lot, e.step
        rate = self.cfg.tool_groups[step.tool_group].scrap_rate
        scrapped = int(self.rng.binomial(lot.wafers, rate)) if rate > 0 else 0
        lot.wafers -= scrapped
        self.log.lot_move(lot.lot_id, step, tool_id, e.arrive_time, start, end,
                          batch_id, batch_size, lot.wafers + scrapped, lot.wafers)
        lot.step_idx += 1
        if lot.wafers == 0 or lot.step_idx >= len(self.cfg.route):
            lot.complete_time = end
            self._wip_change(-1)
            del self.lots_in_fab[lot.lot_id]
            self.completed.append(lot)
            self.log.lot_complete(lot)
        else:
            self._send_to_step(lot)

    def snapshots(self, every: float):
        while True:
            yield self.env.timeout(every)
            at_group = {g: 0 for g in self.groups}
            for lot in self.lots_in_fab.values():
                at_group[self.cfg.route[lot.step_idx].tool_group] += 1
            rows = {g: (len(grp.queue), at_group[g] - len(grp.queue))
                    for g, grp in self.groups.items()}      # (queued, in_process)
            self.log.wip_snapshot(self.env.now, rows)

    # ---- run --------------------------------------------------------------
    def run(self, sim_hours: float) -> None:
        self.env.run(until=sim_hours)
        self._wip_change(0)   # close the WIP integral at the end time
        self.sim_hours = sim_hours
        self.log.flush()
