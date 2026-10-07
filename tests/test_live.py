from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain, repeat
from pathlib import Path

import pytest

from gist_studyroom.config import load_config
from gist_studyroom.database import Database
from gist_studyroom.domain import (
    AuthenticationRequired,
    Facility,
    FacilityStatus,
    LiveError,
    StudentLevel,
)
from gist_studyroom.live import JsonMap, collect_live, parse_room_payload
from gist_studyroom.pipeline import collect_once


def _config(tmp_path: Path, api_url: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'''[site]
base_url = "https://example.invalid"
reservations_url = "https://example.invalid/#/facilityReservation"
api_url = "{api_url}"
[paths]
live_db = "live.sqlite3"
fixture_db = "fixture.sqlite3"
auth_state = "private/auth-state.json"
api_token = "private/access-token"
exports_dir = "exports"
backups_dir = "backups"
lock_file = "private/collector.lock"
[study]
start_date = ""
duration_days = 60
max_lag_hours = 26
[[facilities]]
id = "101"
name = "Room 101"
[[facilities]]
id = "102"
name = "Room 102"
''',
        encoding="utf-8",
    )
    return path


def test_parse_room_slots_maps_safe_fields_and_midnight() -> None:
    # Given
    facility = Facility("101", "Room 101")
    result = parse_room_payload(
        {
            "status": 200,
            "message": "ok",
            "data": {
                "room": [{"RES_ID": 12, "RES_HOUR": 23}],
                "roomOther": [
                    {
                        "DEPT_NM": "Physics",
                        "GROUP_NM": "대학원",
                        "REMARK": "excluded",
                        "RES_HOUR": 8,
                    }
                ],
            },
        },
        facility,
        date(2026, 1, 2),
    )

    # Then
    assert result.status is FacilityStatus.SUCCESS
    first, second = result.observations
    assert first.end_at is not None
    assert second.end_at is not None
    assert [
        (first.start_at.hour, first.end_at.hour),
        (second.start_at.hour, second.end_at.hour),
    ] == [(23, 0), (8, 9)]
    assert result.observations[0].source_reservation_id == "12"
    assert result.observations[1].source_reservation_id is None
    assert [
        (observation.department_raw, observation.department_normalized, observation.student_level)
        for observation in result.observations
    ] == [
        ("도전탐색과정", "도전탐색과정", StudentLevel.UNDERGRADUATE),
        ("Physics", "Physics", StudentLevel.GRADUATE),
    ]
    assert all("excluded" not in observation.department_raw for observation in result.observations)
    assert result.observations[0].source_status == "OCCUPIED_SLOT"


def test_parse_room_empty_unknown_and_malformed() -> None:
    # Given
    facility = Facility("101", "Room 101")

    # When
    empty = parse_room_payload(
        {"status": 200, "message": "ok", "data": {"room": [], "roomOther": []}},
        facility,
        date(2026, 1, 2),
    )

    # Then
    assert empty.status is FacilityStatus.EMPTY
    assert empty.observations == ()
    with pytest.raises(LiveError):
        parse_room_payload(
            {"status": 200, "data": {"room": [{"RES_HOUR": 24}]}}, facility, date.today()
        )


class FakeApi(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict[str, str | int]]] = []
    fail_room = False

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        FakeApi.requests.append((self.path, body))
        if self.path == "/hello/getAccount":
            if self.headers.get("Authorization") != "Bearer fake-token":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"not json")
                return
            self._send(
                {
                    "status": 200,
                    "message": "ok",
                    "data": {"DEPARTMENT_NM": "Engineering", "KOREAN_NM": "학부"},
                }
            )
            return
        if self.path == "/work/getFacilityInfo":
            self._send(
                {
                    "status": 200,
                    "message": "ok",
                    "data": {
                        "facility": [
                            {"ROOM_ID": 101, "FAC_NM": "Room 101", "FLOOR": "1"},
                            {"ROOM_ID": 102, "FAC_NM": "Room 102", "FLOOR": "1"},
                        ],
                        "info": {"DEPARTMENT_NM": "Engineering", "KOREAN_NM": "학부"},
                    },
                }
            )
            return
        if self.path == "/work/getRoom":
            if FakeApi.fail_room and body.get("ROOM_ID") == 102:
                self._send(
                    {"status": 200, "message": "ok", "data": {"room": "bad", "roomOther": []}}
                )
            else:
                self._send(
                    {
                        "status": 200,
                        "message": "ok",
                        "data": {"room": [{"RES_ID": 1, "RES_HOUR": 9}], "roomOther": []},
                    }
                )
            return
        self.send_error(405, "read-only API fake rejected endpoint")

    def _send(self, payload: JsonMap) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *_args: str) -> None:
        return


def test_collect_once_uses_captured_date_and_only_allowlisted_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    FakeApi.requests = []
    FakeApi.fail_room = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = load_config(_config(tmp_path, f"http://127.0.0.1:{server.server_port}"))
    config.api_token_path.parent.mkdir(parents=True)
    config.api_token_path.write_text("fake-token", encoding="utf-8")
    target_date = "2026-01-02"
    timestamps = chain(
        ("2026-01-02T23:59:59+09:00",),
        repeat("2026-01-03T00:00:00+09:00"),
    )
    monkeypatch.setattr("gist_studyroom.pipeline.now", lambda: next(timestamps))

    # When
    try:
        result = collect_once(config)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    # Then
    assert result.exit_code == 10
    assert {path for path, _body in FakeApi.requests} == {
        "/hello/getAccount",
        "/work/getFacilityInfo",
        "/work/getRoom",
    }
    request_bodies = [body for path, body in FakeApi.requests if path != "/hello/getAccount"]
    assert all(body["RES_YYYYMMDD"] == "20260102" for body in request_bodies)
    room_bodies = [body for path, body in FakeApi.requests if path == "/work/getRoom"]
    assert all(type(body["ROOM_ID"]) is int for body in room_bodies)
    with Database(config.live_db_path) as database:
        assert database.latest_run_status() == "PARTIAL"
        assert database.observation_count() == 1
        assert database.facility_statuses() == ["FAILED", "SUCCESS"]
        assert database.rows("SELECT target_date FROM runs") == [(target_date,)]
        assert database.rows("SELECT reservation_date FROM observations") == [(target_date,)]


def test_collect_live_missing_or_invalid_token_requires_authentication(tmp_path: Path) -> None:
    # Given
    config = load_config(_config(tmp_path, "http://127.0.0.1:9"))

    # When / Then
    with pytest.raises(AuthenticationRequired):
        collect_live(config, date(2026, 1, 2))
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    invalid_root = tmp_path / "invalid"
    invalid_root.mkdir()
    invalid = load_config(_config(invalid_root, f"http://127.0.0.1:{server.server_port}"))
    invalid.api_token_path.parent.mkdir(parents=True)
    invalid.api_token_path.write_text("invalid-token", encoding="utf-8")
    try:
        with pytest.raises(AuthenticationRequired):
            collect_live(invalid, date(2026, 1, 2))
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
