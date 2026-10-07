from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .database import SCHEMA
from .domain import Mode, RunStatus


def record_terminal_attempt(
    path: Path, target_date: str, mode: Mode, facilities: int, started_at: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=0.1)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO runs(id,started_at,ended_at,target_date,collector_version,mode,status,target_facility_count,error_code) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                started_at,
                started_at,
                target_date,
                "0.1.0",
                mode,
                RunStatus.SKIPPED_DUPLICATE,
                facilities,
                "SKIPPED_DUPLICATE",
            ),
        )
