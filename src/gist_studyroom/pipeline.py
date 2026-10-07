from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import AppConfig
from .database import Database
from .domain import (
    AuthenticationRequired,
    CollectionResult,
    ExitCode,
    FacilityStatus,
    FixtureError,
    FixtureSnapshot,
    LiveError,
    LockUnavailable,
    Mode,
    RunStatus,
)
from .fixture import SEOUL, fixture_target_date, load_fixture
from .ledger import record_terminal_attempt
from .locking import CollectorLock


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _result(status: RunStatus, message: str) -> CollectionResult:
    match status:  # noqa: F401 # noqa: MATCH_OK
        case RunStatus.SUCCESS:
            return CollectionResult(ExitCode.SUCCESS, status, message)
        case RunStatus.PARTIAL:
            return CollectionResult(ExitCode.PARTIAL, status, message)
        case RunStatus.AUTH_REQUIRED:
            return CollectionResult(ExitCode.AUTH_REQUIRED, status, message)
        case RunStatus.FAILED:
            return CollectionResult(ExitCode.ERROR, status, message)
        case unreachable:
            raise AssertionError(f"No command result for {unreachable}")


def _normalized_snapshot(
    snapshot: FixtureSnapshot, mapping: tuple[tuple[str, str], ...]
) -> FixtureSnapshot:
    labels = dict(mapping)
    facilities = tuple(
        replace(
            payload,
            observations=tuple(
                replace(
                    observation,
                    department_normalized=labels.get(
                        observation.department_raw, observation.department_normalized
                    ),
                )
                for observation in payload.observations
            ),
        )
        for payload in snapshot.facilities
    )
    return replace(snapshot, facilities=facilities)


def collect_fixture(config: AppConfig, fixture_path: Path) -> CollectionResult:
    try:
        with CollectorLock(config.lock_path), Database(config.fixture_db_path) as database:
            database.recover_running(now())
            try:
                target_date = fixture_target_date(fixture_path)
            except FixtureError as error:
                return _result(RunStatus.FAILED, str(error))
            run_id = database.start_run(
                target_date.isoformat(), Mode.FIXTURE, len(config.facilities), now()
            )
            try:
                snapshot = load_fixture(fixture_path)
            except AuthenticationRequired as error:
                database.fail_run(
                    run_id, RunStatus.AUTH_REQUIRED, now(), "AUTH_REQUIRED", str(error)
                )
                return _result(RunStatus.AUTH_REQUIRED, str(error))
            except FixtureError as error:
                database.fail_run(run_id, RunStatus.FAILED, now(), "FIXTURE_INVALID", str(error))
                return _result(RunStatus.FAILED, str(error))
            return _finish_snapshot(database, run_id, snapshot, config)
    except LockUnavailable as error:
        _record_duplicate(config.fixture_db_path, Mode.FIXTURE, config)
        return CollectionResult(ExitCode.DUPLICATE_LOCK, RunStatus.SKIPPED_DUPLICATE, str(error))


def collect_once(config: AppConfig) -> CollectionResult:
    try:
        with CollectorLock(config.lock_path), Database(config.live_db_path) as database:
            started_at = now()
            target_date = datetime.fromisoformat(started_at).date()
            database.recover_running(now())
            run_id = database.start_run(
                target_date.isoformat(), Mode.LIVE, len(config.facilities), started_at
            )
            if not config.api_url.strip():
                message = "Live collection is unconfigured: set api_url"
                database.fail_run(run_id, RunStatus.FAILED, now(), "LIVE_UNCONFIGURED", message)
                return _result(RunStatus.FAILED, message)
            from .live import collect_live

            try:
                snapshot = collect_live(config, target_date)
            except AuthenticationRequired as error:
                database.fail_run(
                    run_id, RunStatus.AUTH_REQUIRED, now(), "AUTH_REQUIRED", str(error)
                )
                return _result(RunStatus.AUTH_REQUIRED, str(error))
            except LiveError as error:
                database.fail_run(run_id, RunStatus.FAILED, now(), "LIVE_INVALID", str(error))
                return _result(RunStatus.FAILED, str(error))
            return _finish_snapshot(database, run_id, snapshot, config)
    except LockUnavailable as error:
        _record_duplicate(config.live_db_path, Mode.LIVE, config)
        return CollectionResult(ExitCode.DUPLICATE_LOCK, RunStatus.SKIPPED_DUPLICATE, str(error))


def _record_duplicate(path: Path, mode: Mode, config: AppConfig) -> None:
    try:
        record_terminal_attempt(
            path, datetime.now(SEOUL).date().isoformat(), mode, len(config.facilities), now()
        )
    except sqlite3.Error:
        return


def _finish_snapshot(
    database: Database, run_id: str, snapshot: FixtureSnapshot, config: AppConfig
) -> CollectionResult:
    snapshot = _normalized_snapshot(snapshot, config.department_mapping)
    expected = {facility.id: facility.name for facility in config.facilities}
    supplied = {payload.facility.id: payload.facility.name for payload in snapshot.facilities}
    if expected != supplied or len(supplied) != len(snapshot.facilities):
        message = "Snapshot facilities must exactly match configured facilities"
        database.fail_run(run_id, RunStatus.FAILED, now(), "FACILITY_MISMATCH", message)
        return _result(RunStatus.FAILED, message)
    observations = 0
    successes = 0
    try:
        for payload in snapshot.facilities:
            observations += database.save_facility(run_id, payload, now())
            if payload.status in (FacilityStatus.SUCCESS, FacilityStatus.EMPTY):
                successes += 1
    except sqlite3.Error:
        database.fail_run(
            run_id, RunStatus.FAILED, now(), "DATABASE_ERROR", "Database write failed"
        )
        return _result(RunStatus.FAILED, "Database write failed")
    status = (
        RunStatus.SUCCESS
        if successes == len(config.facilities)
        else RunStatus.PARTIAL
        if successes
        else RunStatus.FAILED
    )
    database.finalize(run_id, status, now(), observations, successes)
    return _result(
        status,
        f"{status}: {observations} observations across {successes}/{len(config.facilities)} facilities",
    )
