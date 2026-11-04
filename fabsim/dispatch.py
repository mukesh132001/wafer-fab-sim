"""Dispatch rules: decide which waiting lot(s) an idle tool processes next.

A rule is a function priority(entry, now) -> sort key (lower = served first).
Batch formation is shared logic, so every rule automatically works on batch
tools too. Ties are broken by arrival time, then lot id (deterministic).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Lot
    from .config import Step, ToolGroupSpec


@dataclass
class QueueEntry:
    lot: "Lot"
    step: "Step"
    arrive_time: float


PriorityFn = Callable[[QueueEntry, float], tuple]


def fifo(entry: QueueEntry, now: float) -> tuple:
    """First in, first out (by arrival at this tool group's queue)."""
    return (entry.arrive_time, entry.lot.lot_id)


def spt(entry: QueueEntry, now: float) -> tuple:
    """Shortest processing time at this step first."""
    return (entry.step.process_hours, entry.arrive_time, entry.lot.lot_id)


def edd(entry: QueueEntry, now: float) -> tuple:
    """Earliest due date first."""
    return (entry.lot.due_time, entry.arrive_time, entry.lot.lot_id)


def critical_ratio(entry: QueueEntry, now: float) -> tuple:
    """CR = time until due / remaining raw process time. CR < 1 means the lot
    cannot make its due date even with zero queueing; lowest CR first."""
    cr = (entry.lot.due_time - now) / entry.step.remaining_hours
    return (cr, entry.arrive_time, entry.lot.lot_id)


def least_slack(entry: QueueEntry, now: float) -> tuple:
    """Slack = time until due - remaining raw process time; least slack first."""
    slack = entry.lot.due_time - now - entry.step.remaining_hours
    return (slack, entry.arrive_time, entry.lot.lot_id)


RULES: dict[str, PriorityFn] = {
    "FIFO": fifo,
    "SPT": spt,
    "EDD": edd,
    "CR": critical_ratio,
    "LEAST_SLACK": least_slack,
}


def select(queue: list[QueueEntry], group: "ToolGroupSpec", rule: PriorityFn,
           now: float) -> list[QueueEntry]:
    """Pick the lot (or batch of lots) to start next. Empty list = wait."""
    if not queue:
        return []
    ordered = sorted(queue, key=lambda e: rule(e, now))
    if not group.is_batch:
        return [ordered[0]]

    # Batch tool: lots can only share a batch if they run the same recipe.
    # Walk lots in priority order; start the first recipe whose batch is
    # full enough, or whose oldest lot has waited past max_batch_wait.
    seen: set[str] = set()
    for lead in ordered:
        recipe = lead.step.recipe
        if recipe in seen:
            continue
        seen.add(recipe)
        same = [e for e in ordered if e.step.recipe == recipe]
        oldest_wait = now - min(e.arrive_time for e in same)
        if len(same) >= group.batch_min or oldest_wait >= group.max_batch_wait - 1e-9:
            return same[: group.batch_max]
    return []
