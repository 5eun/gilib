from __future__ import annotations

import csv
from pathlib import Path

from .database import Database
from .domain import ExportPaths

OBSERVATION_HEADER = [
    "run_id",
    "observed_at",
    "reservation_date",
    "facility_id",
    "facility_name",
    "start_at",
    "end_at",
    "department_raw",
    "department_normalized",
    "student_level",
    "source_reservation_id",
    "source_status",
    "comparison_key",
    "identity_basis",
]
RUN_HEADER = [
    "run_id",
    "started_at",
    "ended_at",
    "target_date",
    "collector_version",
    "mode",
    "status",
    "observed_count",
    "target_facility_count",
    "success_facility_count",
    "error_code",
    "error_message",
]


def _write(path: Path, header: list[str], rows: list[tuple[str | int | None, ...]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def export_csv(
    database_path: Path, output_dir: Path, date_from: str | None = None, date_to: str | None = None
) -> ExportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = ExportPaths(
        output_dir / "observations.csv", output_dir / "snapshot.csv", output_dir / "runs.csv"
    )
    where = " WHERE reservation_date>=? AND reservation_date<=?" if date_from and date_to else ""
    run_where = " WHERE target_date>=? AND target_date<=?" if date_from and date_to else ""
    parameters = (date_from, date_to) if date_from and date_to else ()
    with Database(database_path) as database:
        _write(
            paths.observations,
            OBSERVATION_HEADER,
            database.rows(
                "SELECT run_id,observed_at,reservation_date,facility_id,facility_name,start_at,end_at,department_raw,department_normalized,student_level,source_reservation_id,source_status,comparison_key,identity_basis FROM observations"
                + where
                + " ORDER BY id",
                parameters,
            ),
        )
        _write(
            paths.snapshot,
            OBSERVATION_HEADER,
            database.rows(
                database._snapshot_sql(
                    "o.run_id,o.observed_at,o.reservation_date,o.facility_id,o.facility_name,o.start_at,o.end_at,o.department_raw,o.department_normalized,o.student_level,o.source_reservation_id,o.source_status,o.comparison_key,o.identity_basis"
                )
                + (" AND o.reservation_date>=? AND o.reservation_date<=?" if parameters else "")
                + " ORDER BY o.reservation_date,o.facility_id,o.start_at",
                parameters,
            ),
        )
        _write(
            paths.runs,
            RUN_HEADER,
            database.rows(
                "SELECT id,started_at,ended_at,target_date,collector_version,mode,status,observed_count,target_facility_count,success_facility_count,error_code,error_message FROM runs"
                + run_where
                + " ORDER BY started_at,id",
                parameters,
            ),
        )
    return paths
