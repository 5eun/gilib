from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gist_studyroom.cli import main
from gist_studyroom.config import load_config
from gist_studyroom.database import Database
from gist_studyroom.domain import ConfigError, ExitCode
from gist_studyroom.export import export_csv
from gist_studyroom.locking import CollectorLock
from gist_studyroom.pipeline import collect_fixture, collect_once
from gist_studyroom.status import status_report


def config_path(tmp_path: Path, *, same_database: bool = False) -> Path:
    path = tmp_path / "config.toml"
    fixture_database = "live.sqlite3" if same_database else "fixture.sqlite3"
    path.write_text(
        f"""[site]
base_url = ""
reservations_url = ""
[paths]
live_db = "live.sqlite3"
fixture_db = "{fixture_database}"
auth_state = "private/auth.json"
exports_dir = "exports"
backups_dir = "backups"
lock_file = "lock"
log_file = "private/collector.log"
[study]
start_date = "2026-01-01"
duration_days = 3
max_lag_hours = 26
[department_normalization]
Raw = "Mapped"
[[facilities]]
id = "a"
name = "A"
""",
        encoding="utf-8",
    )
    return path


def fixture_path(tmp_path: Path, target_date: str, status: str = "success") -> Path:
    path = tmp_path / f"{target_date}.json"
    observations = [] if status == "empty" else [{"start_at": f"{target_date}T09:00:00+00:00"}]
    path.write_text(
        json.dumps(
            {
                "target_date": target_date,
                "auth": "ok",
                "structure": "ok",
                "facilities": [
                    {"id": "a", "name": "A", "status": status, "observations": observations}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_period_export_status_and_fixture_separation(tmp_path: Path) -> None:
    config = load_config(config_path(tmp_path))
    assert collect_fixture(config, fixture_path(tmp_path, "2026-01-01")).exit_code == 0
    assert collect_fixture(config, fixture_path(tmp_path, "2026-01-02", "empty")).exit_code == 0

    paths = export_csv(
        config.fixture_db_path, config.exports_dir / "fixture", "2026-01-02", "2026-01-02"
    )
    code, report = status_report(config, fixture=True)

    assert "2026-01-02" in paths.runs.read_text(encoding="utf-8-sig")
    assert "2026-01-01" not in paths.runs.read_text(encoding="utf-8-sig")
    assert code == ExitCode.SUCCESS
    assert "complete_dates=2" in report
    assert "successful_zero_dates=1" in report
    assert not (config.exports_dir / "live" / "runs.csv").exists()


def test_payload_defaults_identity_and_terminal_failures(tmp_path: Path) -> None:
    config = load_config(config_path(tmp_path))
    fixture = tmp_path / "unknown.json"
    fixture.write_text(
        json.dumps(
            {
                "target_date": "2026-01-01",
                "auth": "ok",
                "structure": "ok",
                "facilities": [
                    {
                        "id": "a",
                        "name": "A",
                        "status": "success",
                        "observations": [
                            {
                                "start_at": "2026-01-01T00:30:00+00:00",
                                "department_raw": "",
                                "student_level": "",
                                "source_reservation_id": "",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert collect_fixture(config, fixture).exit_code == 0
    with Database(config.fixture_db_path) as database:
        row = database.rows(
            "SELECT department_raw,department_normalized,student_level,start_at,identity_basis,comparison_key FROM observations"
        )[0]
        assert row[:3] == ("UNKNOWN", "UNKNOWN", "UNKNOWN")
        assert "+09:00" in str(row[3])
        assert row[4] == "OBSERVED_FIELDS"
        assert row[5]

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "target_date": "2026-01-02",
                "auth": "ok",
                "structure": "ok",
                "facilities": [
                    {"id": "a", "name": "Wrong", "status": "success", "observations": []}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert collect_fixture(config, bad).exit_code == 30
    with Database(config.fixture_db_path) as database:
        assert "RUNNING" not in database.run_statuses()


def test_config_backup_and_unconfigured_live_are_safe(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(config_path(tmp_path, same_database=True))
    config = load_config(config_path(tmp_path))
    assert collect_once(config).exit_code == 30
    with Database(config.live_db_path) as database:
        assert database.latest_run_status() == "FAILED"
    with pytest.raises(FileExistsError), Database(config.fixture_db_path) as database:
        database.backup(config.fixture_db_path)


def test_save_failure_terminalizes_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = load_config(config_path(tmp_path))

    def broken_save(_database: Database, _run_id: str, _payload: str, _observed_at: str) -> int:
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(Database, "save_facility", broken_save)
    result = collect_fixture(config, fixture_path(tmp_path, "2026-01-01"))

    assert result.exit_code == ExitCode.ERROR
    with Database(config.fixture_db_path) as database:
        assert "RUNNING" not in database.run_statuses()
        assert database.latest_run_status() == "FAILED"


def test_duplicate_lock_creates_terminal_ledger_row(tmp_path: Path) -> None:
    config = load_config(config_path(tmp_path))
    with CollectorLock(config.lock_path):
        result = collect_fixture(config, fixture_path(tmp_path, "2026-01-01"))

    assert result.exit_code == ExitCode.DUPLICATE_LOCK
    with Database(config.fixture_db_path) as database:
        assert database.latest_run_status() == "SKIPPED_DUPLICATE"


def test_status_excludes_future_missing_and_empty_facility_is_not_zero(tmp_path: Path) -> None:
    config = load_config(config_path(tmp_path))
    assert (
        collect_fixture(config, fixture_path(tmp_path, "2030-01-01")).exit_code == ExitCode.SUCCESS
    )
    code, report = status_report(config, fixture=True)

    assert code == ExitCode.SUCCESS
    assert "successful_zero_dates=0" in report
    assert "2030-01-03" not in report.split("missing_dates=")[1]


def test_cli_rejects_half_date_range(tmp_path: Path) -> None:
    config = config_path(tmp_path)
    assert main(["--config", str(config), "export-csv", "--from", "2026-01-01"]) == ExitCode.ERROR
