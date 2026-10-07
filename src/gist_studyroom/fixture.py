from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .domain import (
    AuthenticationRequired,
    Facility,
    FacilityPayload,
    FacilityStatus,
    FixtureError,
    FixtureSnapshot,
    Observation,
    StudentLevel,
    ValidationError,
)

SEOUL = ZoneInfo("Asia/Seoul")


def _string(item: dict[str, str], key: str, *, required: bool = True) -> str | None:
    value = item.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise FixtureError(f"Fixture field {key} must be a string")
    if required and not value:
        raise FixtureError(f"Fixture field {key} cannot be blank")
    return value


def _parse_datetime(value: str, target_date: date, key: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValidationError(f"{key} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{key} must include a timezone offset")
    if parsed.astimezone(SEOUL).date() != target_date:
        raise ValidationError(f"{key} is outside Seoul target date")
    return parsed


def _observation(item: dict[str, str], facility: Facility, target_date: date) -> Observation:
    start_text = _string(item, "start_at")
    assert start_text is not None
    start_at = _parse_datetime(start_text, target_date, "start_at").astimezone(SEOUL)
    end_text = _string(item, "end_at", required=False)
    end_at = (
        None
        if end_text in (None, "")
        else _parse_datetime(end_text, target_date, "end_at").astimezone(SEOUL)
    )
    if end_at is not None and end_at < start_at:
        raise ValidationError("end_at cannot be before start_at")
    level_text = _string(item, "student_level", required=False) or "UNKNOWN"
    try:
        level = StudentLevel(level_text)
    except ValueError as error:
        raise FixtureError("student_level is invalid") from error
    raw = _string(item, "department_raw", required=False) or "UNKNOWN"
    normalized = raw
    source_id = _string(item, "source_reservation_id", required=False)
    status = _string(item, "source_status", required=False)
    return Observation(
        facility,
        target_date,
        start_at,
        end_at,
        raw,
        normalized,
        level,
        source_id or None,
        status or None,
    )


def load_fixture(path: Path) -> FixtureSnapshot:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise FixtureError(f"Cannot read fixture: {path}") from error
    except json.JSONDecodeError as error:
        raise FixtureError(f"Invalid JSON in fixture: {path}") from error
    if not isinstance(raw, dict):
        raise FixtureError("Fixture root must be an object")
    target = raw.get("target_date")
    auth = raw.get("auth")
    structure = raw.get("structure")
    facilities = raw.get("facilities")
    if not isinstance(target, str) or not isinstance(auth, str) or not isinstance(structure, str):
        raise FixtureError("Fixture requires target_date, auth, and structure strings")
    if auth == "required":
        raise AuthenticationRequired("Fixture explicitly reports authentication required")
    if auth != "ok":
        raise FixtureError("Fixture auth must be ok or required")
    if structure != "ok":
        raise FixtureError("Fixture explicitly reports invalid structure")
    try:
        target_date = date.fromisoformat(target)
    except ValueError as error:
        raise FixtureError("target_date must be YYYY-MM-DD") from error
    if not isinstance(facilities, list):
        raise FixtureError("Fixture facilities must be an array")
    parsed: list[FacilityPayload] = []
    for item in facilities:
        if not isinstance(item, dict):
            raise FixtureError("Each fixture facility must be an object")
        identifier = item.get("id")
        name = item.get("name")
        state = item.get("status")
        entries = item.get("observations")
        error_message = item.get("error_message")
        if (
            not isinstance(identifier, str)
            or not isinstance(name, str)
            or not isinstance(state, str)
        ):
            raise FixtureError("Fixture facility id, name, and status must be strings")
        if not isinstance(entries, list):
            raise FixtureError("Fixture observations must be an array")
        try:
            status = FacilityStatus(state.upper())
        except ValueError as error:
            raise FixtureError("Fixture facility status is invalid") from error
        facility = Facility(identifier, name)
        observations: list[Observation] = []
        try:
            for entry in entries:
                if not isinstance(entry, dict) or not all(
                    isinstance(value, str) for value in entry.values()
                ):
                    raise FixtureError("Fixture observation fields must be strings")
                observations.append(_observation(entry, facility, target_date))
        except ValidationError as error:
            parsed.append(FacilityPayload(facility, FacilityStatus.FAILED, (), str(error)))
            continue
        if status is FacilityStatus.SUCCESS and not observations:
            raise FixtureError("SUCCESS facility requires observations")
        if status is FacilityStatus.EMPTY and observations:
            raise FixtureError("EMPTY facility cannot include observations")
        if status is FacilityStatus.FAILED and observations:
            raise FixtureError("FAILED facility cannot include observations")
        if status is FacilityStatus.FAILED and (
            not isinstance(error_message, str) or not error_message
        ):
            raise FixtureError("FAILED facility requires error_message")
        parsed.append(
            FacilityPayload(
                facility,
                status,
                tuple(observations),
                error_message if status is FacilityStatus.FAILED else None,
            )
        )
    return FixtureSnapshot(target_date, tuple(parsed))


def fixture_target_date(path: Path) -> date:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise FixtureError(f"Cannot read fixture: {path}") from error
    except json.JSONDecodeError as error:
        raise FixtureError(f"Invalid JSON in fixture: {path}") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("target_date"), str):
        raise FixtureError("Fixture requires a target_date envelope")
    try:
        return date.fromisoformat(raw["target_date"])
    except ValueError as error:
        raise FixtureError("target_date must be YYYY-MM-DD") from error
