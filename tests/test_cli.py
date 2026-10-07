from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_fixture_init_status_export_and_backup(tmp_path: Path) -> None:
    # Given
    config = tmp_path / "config.toml"
    config.write_text(
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
""",
        encoding="utf-8",
    )
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "target_date": "2026-01-02",
                "auth": "ok",
                "structure": "ok",
                "facilities": [
                    {"id": "a", "name": "A Room", "status": "empty", "observations": []}
                ],
            },
        ),
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "gist_studyroom", "--config", str(config)]

    # When
    init = subprocess.run(
        [*command, "init-db", "--fixture"], check=False, capture_output=True, text=True
    )
    collect = subprocess.run(
        [*command, "collect-fixture", "--fixture", str(fixture)],
        check=False,
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        [*command, "status", "--fixture"], check=False, capture_output=True, text=True
    )
    exported = subprocess.run(
        [*command, "export-csv", "--fixture"], check=False, capture_output=True, text=True
    )
    backup = subprocess.run(
        [*command, "backup", "--fixture"], check=False, capture_output=True, text=True
    )

    # Then
    assert [
        init.returncode,
        collect.returncode,
        status.returncode,
        exported.returncode,
        backup.returncode,
    ] == [0, 0, 0, 0, 0]
    assert "SUCCESS" in collect.stdout
    assert "mode=FIXTURE" in status.stdout
    assert (tmp_path / "exports" / "fixture" / "snapshot.csv").exists()
    assert (tmp_path / "backups" / "fixture.sqlite3").exists()
