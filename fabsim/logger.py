"""Event logging to PostgreSQL (production) or SQLite (zero-setup fallback).

Every lot move, lot release/completion, tool state interval (PROD / DOWN) and a
periodic WIP snapshot is written, buffered, with executemany.

    DB URLs:  postgresql://fab:fab@localhost:5432/fab
              sqlite:///fab.db
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


class NullLogger:
    """Discards events - used for fast replications that only need summaries."""
    run_id = None

    def lot_release(self, lot): pass
    def lot_complete(self, lot): pass
    def lot_move(self, *a): pass
    def tool_state(self, *a): pass
    def wip_snapshot(self, *a): pass
    def flush(self): pass
    def finish(self, summary): pass
    def close(self): pass


def _statements(sql: str) -> list[str]:
    sql = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in sql.split(";") if s.strip()]


class DBLogger(NullLogger):
    BUFFER = 5000

    def __init__(self, url: str, run_meta: dict):
        self.url = url
        if url.startswith("sqlite:///"):
            self.kind, self.ph = "sqlite", "?"
            self.conn = sqlite3.connect(url[len("sqlite:///"):])
        elif url.startswith(("postgresql://", "postgres://")):
            import psycopg  # imported lazily so SQLite users don't need it
            self.kind, self.ph = "postgres", "%s"
            self.conn = psycopg.connect(url)
        else:
            raise ValueError(f"Unsupported DB url: {url}")
        self._init_schema()
        self.run_id = run_meta.get("run_id") or uuid.uuid4().hex[:12]
        self._buf: dict[str, list[tuple]] = {}
        self._insert("runs", [(
            self.run_id, run_meta.get("scenario", "baseline"), run_meta["dispatch_rule"],
            run_meta.get("release_policy", "constant"), run_meta["seed"],
            run_meta["sim_hours"], run_meta["warmup_hours"],
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(run_meta.get("config", {})), None,
        )])
        self.conn.commit()

    # ---- schema -----------------------------------------------------------
    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        for stmt in _statements((SQL_DIR / "schema.sql").read_text()):
            cur.execute(stmt)
        for stmt in _statements((SQL_DIR / "views.sql").read_text()):
            name = re.search(r"CREATE\s+VIEW\s+(\w+)", stmt, re.I).group(1)
            cur.execute(f"DROP VIEW IF EXISTS {name}")
            cur.execute(stmt)
        self.conn.commit()

    # ---- buffered inserts -------------------------------------------------
    COLUMNS = {
        "runs": "run_id, scenario, dispatch_rule, release_policy, seed, sim_hours, "
                "warmup_hours, created_at, config_json, summary_json",
        "lots": "run_id, lot_id, release_time, due_time, complete_time, wafers_start, wafers_out",
        "lot_moves": "run_id, lot_id, step_idx, recipe, tool_group, tool_id, arrive_time, "
                     "start_time, end_time, batch_id, batch_size, wafers_in, wafers_out",
        "tool_states": "run_id, tool_id, tool_group, state, start_time, end_time, batch_id",
        "wip_snapshots": "run_id, t, tool_group, queued, in_process",
    }

    def _insert(self, table: str, rows: list[tuple]) -> None:
        cols = self.COLUMNS[table]
        n = cols.count(",") + 1
        sql = f"INSERT INTO {table} ({cols}) VALUES ({', '.join([self.ph] * n)})"
        cur = self.conn.cursor()
        cur.executemany(sql, rows)

    def _add(self, table: str, row: tuple) -> None:
        buf = self._buf.setdefault(table, [])
        buf.append((self.run_id, *row))
        if len(buf) >= self.BUFFER:
            self._insert(table, buf)
            buf.clear()

    def lot_release(self, lot):
        pass  # written once on completion (or at flush for lots still in WIP)

    def lot_complete(self, lot):
        self._add("lots", (lot.lot_id, lot.release_time, lot.due_time, lot.complete_time,
                           lot.wafers_start, lot.wafers))

    def lot_move(self, lot_id, step, tool_id, arrive, start, end, batch_id, batch_size,
                 wafers_in, wafers_out):
        self._add("lot_moves", (lot_id, step.index, step.recipe, step.tool_group, tool_id,
                                arrive, start, end, batch_id, batch_size, wafers_in, wafers_out))

    def tool_state(self, tool_id, group, state, start, end, batch_id):
        if end > start:
            self._add("tool_states", (tool_id, group, state, start, end, batch_id))

    def wip_snapshot(self, t, rows):
        for g, (q, p) in rows.items():
            self._add("wip_snapshots", (t, g, q, p))

    def log_open_lots(self, lots):
        """Lots still in the fab at end of run (complete_time NULL)."""
        for lot in lots:
            self._add("lots", (lot.lot_id, lot.release_time, lot.due_time, None,
                               lot.wafers_start, lot.wafers))

    def flush(self):
        for table, buf in self._buf.items():
            if buf:
                self._insert(table, buf)
                buf.clear()
        self.conn.commit()

    def finish(self, summary: dict):
        self.flush()
        cur = self.conn.cursor()
        cur.execute(f"UPDATE runs SET summary_json = {self.ph} WHERE run_id = {self.ph}",
                    (json.dumps(summary), self.run_id))
        self.conn.commit()

    def close(self):
        self.conn.close()
