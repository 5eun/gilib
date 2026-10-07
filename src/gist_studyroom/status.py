from __future__ import annotations

from datetime import date, datetime

from .config import AppConfig
from .database import Database
from .domain import ExitCode, Mode
from .fixture import SEOUL


def status_report(config: AppConfig, fixture: bool = False) -> tuple[ExitCode, str]:
    mode = Mode.FIXTURE if fixture else Mode.LIVE
    path = config.fixture_db_path if fixture else config.live_db_path
    with Database(path) as database:
        attempts = database.rows(
            "SELECT id,status,ended_at,target_date FROM runs WHERE mode=? ORDER BY started_at DESC,id DESC",
            (mode,),
        )
        complete = database.rows(
            "SELECT DISTINCT target_date,ended_at FROM runs WHERE mode=? AND status='SUCCESS' ORDER BY ended_at DESC",
            (mode,),
        )
        zero = database.rows(
            "SELECT DISTINCT target_date FROM runs WHERE mode=? AND status='SUCCESS' AND observed_count=0",
            (mode,),
        )
        failures = database.rows(
            "SELECT DISTINCT target_date FROM runs WHERE mode=? AND status IN ('PARTIAL','FAILED','AUTH_REQUIRED','INTERRUPTED')",
            (mode,),
        )
        facilities = database.rows(
            "SELECT facility_id,status FROM facility_results WHERE run_id=(SELECT id FROM runs WHERE mode=? ORDER BY started_at DESC,id DESC LIMIT 1) ORDER BY facility_id",
            (mode,),
        )
    latest = attempts[0] if attempts else None
    complete_dates = {str(row[0]) for row in complete}
    today = datetime.now(SEOUL).date()
    end = (
        None
        if config.study_start is None
        else config.study_start.fromordinal(
            config.study_start.toordinal() + config.duration_days - 1
        )
    )
    elapsed_end = None if end is None else min(today, end)
    period = (
        []
        if config.study_start is None or elapsed_end is None
        else [
            date.fromordinal(config.study_start.toordinal() + offset).isoformat()
            for offset in range((elapsed_end - config.study_start).days + 1)
            if elapsed_end >= config.study_start
        ]
    )
    missing = [value for value in period if value not in complete_dates]
    full_success = complete[0] if complete else None
    elapsed = (
        "none"
        if full_success is None
        else str(datetime.now(SEOUL) - datetime.fromisoformat(str(full_success[1])))
    )
    bounded_complete = (
        {value for value in complete_dates if value in period} if period else complete_dates
    )
    report = f"mode={mode}; latest_attempt={latest}; latest_full_success={full_success}; elapsed={elapsed}; total_calendar_days={config.duration_days if config.study_start else 0}; elapsed_calendar_days={len(period)}; latest_facility_results={facilities}; complete_dates={len(bounded_complete)}; successful_zero_dates={len([row for row in zero if str(row[0]) in period]) if period else len(zero)}; partial_failed_dates={[row[0] for row in failures if not period or str(row[0]) in period]}; missing_dates={missing}"
    if latest is not None:
        status = str(latest[1])
        if status in ("FAILED", "INTERRUPTED"):
            return ExitCode.ERROR, report
        if status == "AUTH_REQUIRED":
            return ExitCode.AUTH_REQUIRED, report
        if status == "SKIPPED_DUPLICATE":
            return ExitCode.DUPLICATE_LOCK, report
        if status == "PARTIAL":
            return ExitCode.PARTIAL, report
    if not complete:
        return ExitCode.STALE, report
    if (
        full_success is not None
        and (datetime.now(SEOUL) - datetime.fromisoformat(str(full_success[1]))).total_seconds()
        > config.max_lag_hours * 3600
    ):
        return ExitCode.STALE, report
    return ExitCode.SUCCESS, report
