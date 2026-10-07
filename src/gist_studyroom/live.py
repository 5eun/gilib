from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Final

from playwright.sync_api import APIRequestContext, TimeoutError, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from .config import AppConfig
from .domain import (
    AuthenticationRequired,
    Facility,
    FacilityPayload,
    FacilityStatus,
    FixtureSnapshot,
    LiveError,
    Observation,
    StudentLevel,
)
from .fixture import SEOUL

OCCUPIED_SLOT: Final = "OCCUPIED_SLOT"
OWN_DEPARTMENT: Final = "도전탐색과정"
READ_ENDPOINTS: Final = frozenset({"/hello/getAccount", "/work/getFacilityInfo", "/work/getRoom"})
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonMap = dict[str, JsonValue]


def _token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AuthenticationRequired("No API token exists; run login") from error
    if not token:
        raise AuthenticationRequired("No API token exists; run login")
    return token


def _json(response_text: str) -> JsonMap:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise LiveError("API returned malformed JSON") from error
    if not isinstance(payload, dict):
        raise LiveError("API response must be an object")
    return payload


def _envelope(payload: JsonMap) -> JsonMap:
    if payload.get("status") != 200 or not isinstance(payload.get("data"), dict):
        raise LiveError("API response envelope is invalid")
    data = payload["data"]
    assert isinstance(data, dict)
    return data


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) and value else "UNKNOWN"


def _level(value: str) -> StudentLevel:
    if "학부" in value:
        return StudentLevel.UNDERGRADUATE
    if any(token in value for token in ("대학원", "석사", "박사")):
        return StudentLevel.GRADUATE
    return StudentLevel.UNKNOWN


def _hour(value: int) -> int:
    if value not in range(24):
        raise LiveError("Room response has an invalid reservation hour")
    return value


def _observation(
    facility: Facility,
    target_date: date,
    hour: int,
    department: str,
    level: StudentLevel,
    source_id: str | None,
) -> Observation:
    start_at = datetime.combine(target_date, time(_hour(hour)), SEOUL)
    return Observation(
        facility,
        target_date,
        start_at,
        start_at + timedelta(hours=1),
        department,
        department,
        level,
        source_id,
        OCCUPIED_SLOT,
    )


def parse_room_payload(payload: JsonMap, facility: Facility, target_date: date) -> FacilityPayload:
    data = _envelope(payload)
    own = data.get("room")
    other = data.get("roomOther")
    if not isinstance(own, list) or not isinstance(other, list):
        raise LiveError("Room response has an invalid structure")
    observations: list[Observation] = []
    for row in own:
        if not isinstance(row, dict) or type(row.get("RES_ID")) is not int:
            raise LiveError("Room response has an invalid own slot")
        hour = row.get("RES_HOUR")
        if type(hour) is not int:
            raise LiveError("Room response has an invalid reservation hour")
        observations.append(
            _observation(
                facility,
                target_date,
                hour,
                OWN_DEPARTMENT,
                StudentLevel.UNDERGRADUATE,
                str(row["RES_ID"]),
            )
        )
    for row in other:
        if not isinstance(row, dict):
            raise LiveError("Room response has an invalid other slot")
        hour = row.get("RES_HOUR")
        if type(hour) is not int:
            raise LiveError("Room response has an invalid reservation hour")
        observations.append(
            _observation(
                facility,
                target_date,
                hour,
                _text(row.get("DEPT_NM")),
                _level(_text(row.get("GROUP_NM"))),
                None,
            )
        )
    status = FacilityStatus.SUCCESS if observations else FacilityStatus.EMPTY
    return FacilityPayload(facility, status, tuple(observations))


def _post(
    context: APIRequestContext, endpoint: str, body: dict[str, str | int], retries: int
) -> JsonMap:
    if endpoint not in READ_ENDPOINTS:
        raise AssertionError(f"Endpoint is not allowlisted: {endpoint}")
    for attempt in range(retries + 1):
        try:
            response = context.post(endpoint, data=body)
        except TimeoutError:
            if attempt == retries:
                raise LiveError("API request timed out") from None
            continue
        except PlaywrightError as error:
            if attempt == retries or "net::" not in str(error):
                raise LiveError("API network request failed") from error
            continue
        if response.status < 500 or response.status >= 600 or attempt == retries:
            return _json(response.text())
    raise AssertionError("Retry loop must return or raise")


def _facility_info(context: APIRequestContext, config: AppConfig, target_date: date) -> None:
    month_start = target_date.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    data = _envelope(
        _post(
            context,
            "/work/getFacilityInfo",
            {
                "START_DT_YYYYMMDD": month_start.strftime("%Y%m%d"),
                "END_DT_YYYYMMDD": next_month.strftime("%Y%m%d"),
                "RES_YYYYMMDD": target_date.strftime("%Y%m%d"),
            },
            config.max_retries,
        )
    )
    rows = data.get("facility")
    if not isinstance(rows, list):
        raise LiveError("Facility response has an invalid structure")
    for facility in config.facilities:
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("ROOM_ID") == _room_id(facility)
            and row.get("FAC_NM") == facility.name
        ]
        if len(matches) != 1:
            raise LiveError("Configured facilities do not match the API response")


def _room_id(facility: Facility) -> int:
    try:
        identifier = int(facility.id)
    except ValueError as error:
        raise LiveError("Configured facility ID must be an integer") from error
    if identifier < 1 or str(identifier) != facility.id:
        raise LiveError("Configured facility ID must be a canonical positive integer")
    return identifier


def collect_live(config: AppConfig, target_date: date) -> FixtureSnapshot:
    token = _token(config.api_token_path)
    with sync_playwright() as playwright:
        context = playwright.request.new_context(
            base_url=config.api_url,
            extra_http_headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=config.request_timeout_seconds * 1000,
        )
        try:
            try:
                probe = context.post("/hello/getAccount", data={})
                if probe.status != 200:
                    raise AuthenticationRequired("Saved API token is no longer valid")
                _envelope(_json(probe.text()))
            except (LiveError, PlaywrightError, TimeoutError) as error:
                raise AuthenticationRequired("Saved API token is no longer valid") from error
            _facility_info(context, config, target_date)
            month_start = target_date.replace(day=1)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            payloads: list[FacilityPayload] = []
            for facility in config.facilities:
                try:
                    payloads.append(
                        parse_room_payload(
                            _post(
                                context,
                                "/work/getRoom",
                                {
                                    "START_DT_YYYYMMDD": month_start.strftime("%Y%m%d"),
                                    "END_DT_YYYYMMDD": next_month.strftime("%Y%m%d"),
                                    "ROOM_ID": _room_id(facility),
                                    "RES_YYYYMMDD": target_date.strftime("%Y%m%d"),
                                },
                                config.max_retries,
                            ),
                            facility,
                            target_date,
                        )
                    )
                except LiveError as error:
                    payloads.append(
                        FacilityPayload(facility, FacilityStatus.FAILED, (), str(error))
                    )
        finally:
            context.dispose()
    return FixtureSnapshot(target_date, tuple(payloads))
