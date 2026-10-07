from __future__ import annotations

import json
from pathlib import Path

from gist_studyroom.config import load_config
from gist_studyroom.database import Database
from gist_studyroom.export import export_csv
from gist_studyroom.locking import CollectorLock
from gist_studyroom.pipeline import collect_fixture


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[site]
base_url = ""
reservations_url = ""

[paths]
live_db = "live.sqlite3"
fixture_db = "fixture.sqlite3"
auth_state = "auth.json"
exports_dir = "exports"
backups_dir = "backups"
lock_file = "collector.lock"

[study]
start_date = ""
duration_days = 60
max_lag_hours = 26

[[facilities]]
id = "a"
name = "A Room"

[[facilities]]
id = "b"
name = "B Room"
""",
        encoding="utf-8",
    )
    return config_path


def write_fixture(tmp_path: Path, payload: dict[str, object]) -> Path:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    return fixture_path


def observation() -> dict[str, str]:
    return {
        "start_at": "2026-01-02T09:00:00+09:00",
        "end_at": "2026-01-02T10:00:00+09:00",
        "department_raw": "Computer Science",
        "department_normalized": "Computer Science",
        "student_level": "UNDERGRADUATE",
        "source_reservation_id": "stable-1",
        "source_status": "BOOKED",
    }


def normal_fixture() -> dict[str, object]:
    return {
        "target_date": "2026-01-02",
        "auth": "ok",
        "structure": "ok",
        "facilities": [
            {"id": "a", "name": "A Room", "status": "success", "observations": [observation()]},
            {"id": "b", "name": "B Room", "status": "empty", "observations": []},
        ],
    }


def test_collect_fixture_records_normal_and_explicit_empty(tmp_path: Path) -> None:
    # Given
    config = load_config(write_config(tmp_path))
    fixture = write_fixture(tmp_path, normal_fixture())

    # When
    result = collect_fixture(config, fixture)

    # Then
    assert result.exit_code == 0
    with Database(config.fixture_db_path) as database:
        assert database.observation_count() == 1
        assert database.facility_statuses() == ["EMPTY", "SUCCESS"]
        assert database.latest_run_status() == "SUCCESS"


def test_auth_and_structure_failures_preserve_prior_successful_data(tmp_path: Path) -> None:
    # Given
    config = load_config(write_config(tmp_path))

    # When
    successful_result = collect_fixture(config, write_fixture(tmp_path, normal_fixture()))
    auth_result = collect_fixture(
        config,
        write_fixture(
            tmp_path,
            {"target_date": "2026-01-02", "auth": "required", "structure": "ok", "facilities": []},
        ),
    )
    structure_fixture = write_fixture(
        tmp_path,
        {"target_date": "2026-01-02", "auth": "ok", "structure": "invalid", "facilities": []},
    )
    structure_result = collect_fixture(config, structure_fixture)

    # Then
    assert successful_result.exit_code == 0
    assert auth_result.exit_code == 20
    assert structure_result.exit_code == 30
    with Database(config.fixture_db_path) as database:
        assert database.observation_count() == 1
        assert database.run_statuses() == ["SUCCESS", "AUTH_REQUIRED", "FAILED"]


def test_repeated_successful_collection_replaces_same_date_fixture_data(tmp_path: Path) -> None:
    # Given
    config = load_config(write_config(tmp_path))
    fixture = write_fixture(tmp_path, normal_fixture())

    # When
    collect_fixture(config, fixture)
    collect_fixture(config, fixture)

    # Then
    with Database(config.fixture_db_path) as database:
        assert database.observation_count() == 1
        assert database.facility_statuses() == ["EMPTY", "SUCCESS"]
        assert database.run_statuses() == ["SUCCESS", "SUCCESS"]


def test_partial_run_preserves_successful_facility_and_rolls_back_invalid_one(
    tmp_path: Path,
) -> None:
    # Given
    config = load_config(write_config(tmp_path))
    payload = normal_fixture()
    payload["facilities"] = [
        {"id": "a", "name": "A Room", "status": "success", "observations": [observation()]},
        {
            "id": "b",
            "name": "B Room",
            "status": "success",
            "observations": [
                {
                    **observation(),
                    "start_at": "2026-01-02T11:00:00+09:00",
                    "end_at": "2026-01-02T10:00:00+09:00",
                }
            ],
        },
    ]

    # When
    successful_result = collect_fixture(config, write_fixture(tmp_path, normal_fixture()))
    partial_result = collect_fixture(config, write_fixture(tmp_path, payload))

    # Then
    assert successful_result.exit_code == 0
    assert partial_result.exit_code == 10
    with Database(config.fixture_db_path) as database:
        assert database.latest_run_status() == "PARTIAL"
        assert database.observation_count() == 2
        assert database.facility_statuses() == ["EMPTY", "FAILED", "SUCCESS", "SUCCESS"]
        assert database.run_statuses() == ["SUCCESS", "PARTIAL"]


def test_missing_end_is_preserved_and_seoul_boundary_is_validated(tmp_path: Path) -> None:
    # Given
    config = load_config(write_config(tmp_path))
    payload = normal_fixture()
    record = observation()
    record["start_at"] = "2026-01-02T00:30:00+09:00"
    record["end_at"] = ""
    payload["facilities"] = [
        {"id": "a", "name": "A Room", "status": "success", "observations": [record]},
        {"id": "b", "name": "B Room", "status": "empty", "observations": []},
    ]

    # When
    result = collect_fixture(config, write_fixture(tmp_path, payload))

    # Then
    assert result.exit_code == 0
    with Database(config.fixture_db_path) as database:
        assert database.first_observation_end() is None
        assert database.first_observation_date() == "2026-01-02"


def test_lock_blocks_second_collection_and_releases_after_context(tmp_path: Path) -> None:
    # Given
    config = load_config(write_config(tmp_path))
    fixture = write_fixture(tmp_path, normal_fixture())

    # When
    with CollectorLock(config.lock_path):
        blocked = collect_fixture(config, fixture)
    released = collect_fixture(config, fixture)

    # Then
    assert blocked.exit_code == 40
    assert released.exit_code == 0


def test_csv_exports_keep_headers_bom_and_quality_distinctions(tmp_path: Path) -> None:
    # Given
    config = load_config(write_config(tmp_path))
    fixture = write_fixture(tmp_path, normal_fixture())
    collect_fixture(config, fixture)

    # When
    paths = export_csv(config.fixture_db_path, config.exports_dir)

    # Then
    assert len(paths) == 3
    assert all(path.read_bytes().startswith(b"\xef\xbb\xbf") for path in paths)
    assert all(path.read_text(encoding="utf-8-sig").splitlines()[0] for path in paths)
