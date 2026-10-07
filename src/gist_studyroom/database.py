from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from ._database_schema import SCHEMA
from .domain import FacilityPayload, Mode, Observation, RunStatus

__all__ = ("Database", "SCHEMA")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> Database:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._migrate()
        return self

    def _migrate(self) -> None:
        columns = {
            str(row[1]) for row in self._connection().execute("PRAGMA table_info(observations)")
        }
        for name in ("comparison_key", "identity_basis"):
            if name not in columns:
                self._connection().execute(f"ALTER TABLE observations ADD COLUMN {name} TEXT")

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not open")
        return self.connection

    def recover_running(self, ended_at: str) -> None:
        with self._connection():
            self._connection().execute(
                "UPDATE runs SET status=?, ended_at=?, error_code=? WHERE status=?",
                (RunStatus.INTERRUPTED, ended_at, "INTERRUPTED", RunStatus.RUNNING),
            )

    def start_run(self, target_date: str, mode: Mode, facilities: int, started_at: str) -> str:
        run_id = uuid4().hex
        with self._connection():
            self._connection().execute(
                "INSERT INTO runs(id,started_at,target_date,collector_version,mode,status,target_facility_count) VALUES(?,?,?,?,?,?,?)",
                (run_id, started_at, target_date, "0.1.0", mode, RunStatus.RUNNING, facilities),
            )
        return run_id

    def fail_run(
        self, run_id: str, status: RunStatus, ended_at: str, code: str, message: str
    ) -> None:
        with self._connection():
            self._connection().execute(
                "UPDATE runs SET status=?,ended_at=?,error_code=?,error_message=? WHERE id=?",
                (status, ended_at, code, message, run_id),
            )

    def save_facility(self, run_id: str, payload: FacilityPayload, observed_at: str) -> int:
        connection = self._connection()
        with connection:
            connection.execute(
                "INSERT INTO facility_results(run_id,facility_id,facility_name,status,observed_count,error_message) VALUES(?,?,?,?,?,?)",
                (
                    run_id,
                    payload.facility.id,
                    payload.facility.name,
                    payload.status,
                    len(payload.observations),
                    payload.error_message,
                ),
            )
            connection.executemany(
                """INSERT INTO observations(run_id,observed_at,reservation_date,facility_id,facility_name,start_at,end_at,
                department_raw,department_normalized,student_level,source_reservation_id,source_status,comparison_key,identity_basis)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    self._observation_values(run_id, observed_at, observation)
                    for observation in payload.observations
                ],
            )
        return len(payload.observations)

    def _observation_values(
        self, run_id: str, observed_at: str, observation: Observation
    ) -> tuple[
        str,
        str,
        str,
        str,
        str,
        str,
        str | None,
        str,
        str,
        str,
        str | None,
        str | None,
        str,
        str,
    ]:
        stable_id = observation.source_reservation_id
        basis = "SOURCE_ID" if stable_id else "OBSERVED_FIELDS"
        comparison = (
            stable_id
            or sha256(
                "|".join(
                    (
                        observation.facility.id,
                        observation.reservation_date.isoformat(),
                        observation.start_at.isoformat(),
                        observation.end_at.isoformat() if observation.end_at else "",
                        observation.department_raw,
                        str(observation.student_level),
                        observation.source_status or "",
                    )
                ).encode()
            ).hexdigest()
        )
        return (
            run_id,
            observed_at,
            observation.reservation_date.isoformat(),
            observation.facility.id,
            observation.facility.name,
            observation.start_at.isoformat(),
            observation.end_at.isoformat() if observation.end_at else None,
            observation.department_raw,
            observation.department_normalized,
            str(observation.student_level),
            observation.source_reservation_id,
            observation.source_status,
            comparison,
            basis,
        )

    def finalize(
        self, run_id: str, status: RunStatus, ended_at: str, observations: int, successes: int
    ) -> None:
        connection = self._connection()
        with connection:
            connection.execute(
                "UPDATE runs SET status=?,ended_at=?,observed_count=?,success_facility_count=? WHERE id=?",
                (status, ended_at, observations, successes, run_id),
            )
            if status is RunStatus.SUCCESS:
                for table in ("observations", "facility_results"):
                    connection.execute(
                        f"""DELETE FROM {table} WHERE run_id IN (
                        SELECT id FROM runs WHERE target_date=(SELECT target_date FROM runs WHERE id=?)
                        AND mode=(SELECT mode FROM runs WHERE id=?) AND id!=?)""",
                        (run_id, run_id, run_id),
                    )

    def observation_count(self) -> int:
        return int(self._connection().execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def snapshot_count(self) -> int:
        return int(self._connection().execute(self._snapshot_sql("COUNT(*)")).fetchone()[0])

    def _snapshot_sql(self, columns: str) -> str:
        return f"""WITH latest AS (
            SELECT fr.run_id, fr.facility_id, r.target_date,
            ROW_NUMBER() OVER (PARTITION BY r.target_date,fr.facility_id ORDER BY r.started_at DESC,r.id DESC) AS ranking
            FROM facility_results fr JOIN runs r ON r.id=fr.run_id
            WHERE fr.status IN ('SUCCESS','EMPTY')
        ) SELECT {columns} FROM observations o JOIN latest latest_run
        ON latest_run.run_id=o.run_id AND latest_run.facility_id=o.facility_id
        WHERE latest_run.ranking=1"""

    def facility_statuses(self) -> list[str]:
        return [
            str(row[0])
            for row in self._connection().execute(
                "SELECT status FROM facility_results ORDER BY status"
            )
        ]

    def latest_run_status(self) -> str:
        row = (
            self._connection()
            .execute("SELECT status FROM runs ORDER BY started_at DESC,id DESC LIMIT 1")
            .fetchone()
        )
        return str(row[0]) if row else ""

    def run_statuses(self) -> list[str]:
        return [
            str(row[0])
            for row in self._connection().execute("SELECT status FROM runs ORDER BY started_at,id")
        ]

    def first_observation_end(self) -> str | None:
        row = self._connection().execute("SELECT end_at FROM observations LIMIT 1").fetchone()
        return None if row is None or row[0] is None else str(row[0])

    def first_observation_date(self) -> str:
        return str(
            self._connection()
            .execute("SELECT reservation_date FROM observations LIMIT 1")
            .fetchone()[0]
        )

    def rows(
        self, query: str, parameters: tuple[str, ...] = ()
    ) -> list[tuple[str | int | None, ...]]:
        return [tuple(row) for row in self._connection().execute(query, parameters).fetchall()]

    def backup(self, destination: Path) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        if destination.resolve() == self.path.resolve() or destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as target:
            self._connection().backup(target)
