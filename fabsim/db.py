"""Tiny DB helper shared by the API server and the agent (SQLite or PostgreSQL)."""
from __future__ import annotations

import re
import sqlite3


class DB:
    def __init__(self, url: str):
        self.url = url
        if url.startswith("sqlite:///"):
            self.kind = "sqlite"
            self.conn = sqlite3.connect(url[len("sqlite:///"):], check_same_thread=False)
        elif url.startswith(("postgresql://", "postgres://")):
            import psycopg
            self.kind = "postgres"
            self.conn = psycopg.connect(url, autocommit=True)
        else:
            raise ValueError(f"Unsupported DB url: {url}")

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.kind == "postgres":
            sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    READ_ONLY = re.compile(r"^\s*(WITH|SELECT)\b", re.I)
    FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|PRAGMA|COPY|GRANT|TRUNCATE)\b", re.I)

    def safe_select(self, sql: str, limit: int = 200) -> list[dict]:
        """Run a single read-only SELECT (used by the agent's text-to-SQL tool)."""
        body = sql.strip().rstrip(";")
        if ";" in body or not self.READ_ONLY.match(body) or self.FORBIDDEN.search(body):
            raise ValueError("Only a single read-only SELECT/WITH query is allowed.")
        rows = self.query(f"SELECT * FROM ({body}) AS q LIMIT {int(limit)}")
        return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]

    def schema(self) -> str:
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent / "sql"
        return (root / "schema.sql").read_text() + "\n" + (root / "views.sql").read_text()
