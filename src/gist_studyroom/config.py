from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .domain import ConfigError, Facility


@dataclass(frozen=True, slots=True)
class AppConfig:
    path: Path
    base_url: str
    reservations_url: str
    api_url: str
    live_db_path: Path
    fixture_db_path: Path
    auth_state_path: Path
    api_token_path: Path
    exports_dir: Path
    backups_dir: Path
    lock_path: Path
    log_file_path: Path
    study_start: date | None
    duration_days: int
    max_lag_hours: int
    facilities: tuple[Facility, ...]
    request_timeout_seconds: int = 30
    max_retries: int = 2
    department_mapping: tuple[tuple[str, str], ...] = ()


def _text(table: dict[str, str], key: str) -> str:
    value = table.get(key)
    if value is None:
        msg = f"Missing {key}"
        raise ConfigError(msg)
    return value


def _path(root: Path, paths: dict[str, str], key: str) -> Path:
    return (root / _text(paths, key)).resolve()


def load_config(path: Path) -> AppConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        msg = f"Cannot read config: {path}"
        raise ConfigError(msg) from error
    except tomllib.TOMLDecodeError as error:
        msg = f"Invalid TOML in {path}"
        raise ConfigError(msg) from error
    site = raw.get("site")
    paths = raw.get("paths")
    study = raw.get("study")
    facilities = raw.get("facilities")
    collection = raw.get("collection", {})
    department_mapping = raw.get("department_normalization", {})
    if not isinstance(site, dict) or not isinstance(paths, dict) or not isinstance(study, dict):
        raise ConfigError("Config requires [site], [paths], and [study] tables")
    if not all(isinstance(value, str) for value in site.values()):
        raise ConfigError("[site] values must be strings")
    if not all(isinstance(value, str) for value in paths.values()):
        raise ConfigError("[paths] values must be strings")
    site_values = {str(key): value for key, value in site.items() if isinstance(value, str)}
    path_values = {str(key): value for key, value in paths.items() if isinstance(value, str)}
    duration = study.get("duration_days")
    lag = study.get("max_lag_hours")
    start = study.get("start_date")
    if not isinstance(duration, int) or duration < 1 or not isinstance(lag, int) or lag < 1:
        raise ConfigError("study duration_days and max_lag_hours must be positive integers")
    if not isinstance(start, str):
        raise ConfigError("study start_date must be a string")
    try:
        study_start = date.fromisoformat(start) if start else None
    except ValueError as error:
        raise ConfigError("study start_date must be YYYY-MM-DD or blank") from error
    if not isinstance(facilities, list) or not facilities:
        raise ConfigError("At least one [[facilities]] entry is required")
    if not isinstance(collection, dict) or not isinstance(department_mapping, dict):
        raise ConfigError("collection and department_normalization must be TOML tables")
    timeout = collection.get("request_timeout_seconds", 30)
    retries = collection.get("max_retries", 2)
    if not isinstance(timeout, int) or timeout < 1 or not isinstance(retries, int) or retries < 0:
        raise ConfigError("collection timeout and retries must be valid integers")
    if not all(
        isinstance(key, str) and isinstance(value, str) for key, value in department_mapping.items()
    ):
        raise ConfigError("department normalization values must be strings")
    parsed_facilities: list[Facility] = []
    for item in facilities:
        if not isinstance(item, dict):
            raise ConfigError("Each facility must be a TOML table")
        identifier = item.get("id")
        name = item.get("name")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(name, str)
            or not name
        ):
            raise ConfigError("Facility id and name must be non-empty strings")
        parsed_facilities.append(Facility(identifier, name))
    if len({facility.id for facility in parsed_facilities}) != len(parsed_facilities):
        raise ConfigError("Facility ids must be unique")
    root = path.resolve().parent
    live_db_path = _path(root, path_values, "live_db")
    fixture_db_path = _path(root, path_values, "fixture_db")
    if live_db_path == fixture_db_path:
        raise ConfigError("live_db and fixture_db must resolve to different files")
    return AppConfig(
        path=path.resolve(),
        base_url=_text(site_values, "base_url"),
        reservations_url=_text(site_values, "reservations_url"),
        api_url=site_values.get("api_url", ""),
        live_db_path=live_db_path,
        fixture_db_path=fixture_db_path,
        auth_state_path=_path(root, path_values, "auth_state"),
        api_token_path=(root / path_values.get("api_token", "private/access-token")).resolve(),
        exports_dir=_path(root, path_values, "exports_dir"),
        backups_dir=_path(root, path_values, "backups_dir"),
        lock_path=_path(root, path_values, "lock_file"),
        log_file_path=(root / path_values.get("log_file", "collector.log")).resolve(),
        study_start=study_start,
        duration_days=duration,
        max_lag_hours=lag,
        facilities=tuple(parsed_facilities),
        request_timeout_seconds=timeout,
        max_retries=retries,
        department_mapping=tuple(
            (str(key), str(value)) for key, value in department_mapping.items()
        ),
    )
