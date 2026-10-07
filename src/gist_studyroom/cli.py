from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

from .auth import login_from_env, manual_login
from .config import AppConfig, load_config
from .database import Database
from .domain import ConfigError, ExitCode, StudyRoomError
from .export import export_csv
from .pipeline import collect_fixture, collect_once
from .status import status_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gist-studyroom")
    parser.add_argument(
        "--config", type=Path, default=Path("config.toml"), help="Path to TOML configuration"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-db", help="Initialize a database without deleting data")
    init.add_argument(
        "--fixture", action="store_true", help="Initialize the separate fixture database"
    )
    login = commands.add_parser("login", help="Open a headed browser for manual login")
    login.add_argument(
        "--replace", action="store_true", help="Replace existing local storage state"
    )
    login.add_argument(
        "--from-env",
        action="store_true",
        help="Fill the observed login form from .env ID and PASSWORD",
    )
    commands.add_parser("collect-once", help="Run one explicitly configured live collection")
    fixture = commands.add_parser("collect-fixture", help="Run the offline fixture pipeline")
    fixture.add_argument("--fixture", type=Path, required=True, help="Strict JSON fixture path")
    status = commands.add_parser("status", help="Report LIVE collection freshness and quality")
    status.add_argument("--fixture", action="store_true", help=argparse.SUPPRESS)
    export = commands.add_parser("export-csv", help="Write history, snapshot, and run CSV files")
    export.add_argument("--fixture", action="store_true", help="Export the fixture database")
    export.add_argument("--from", dest="date_from", help="Inclusive Seoul date YYYY-MM-DD")
    export.add_argument("--to", dest="date_to", help="Inclusive Seoul date YYYY-MM-DD")
    backup = commands.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("--fixture", action="store_true", help="Back up the fixture database")
    backup.add_argument(
        "--destination", type=Path, help="Backup destination relative to config when not absolute"
    )
    return parser


def _db(config: AppConfig, fixture: bool) -> Path:
    return config.fixture_db_path if fixture else config.live_db_path


def _run(args: argparse.Namespace, config: AppConfig) -> int:
    match args.command:
        case "init-db":
            with Database(_db(config, args.fixture)):
                pass
            print("Database initialized")
            return ExitCode.SUCCESS
        case "login":
            if args.from_env:
                login_from_env(config, args.replace)
            else:
                manual_login(config, args.replace)
            print(f"Saved authentication files: {config.auth_state_path}, {config.api_token_path}")
            return ExitCode.SUCCESS
        case "collect-once":
            result = collect_once(config)
            print(result.message)
            return result.exit_code
        case "collect-fixture":
            fixture = (
                args.fixture if args.fixture.is_absolute() else config.path.parent / args.fixture
            )
            result = collect_fixture(config, fixture)
            print(result.message)
            return result.exit_code
        case "status":
            code, report = status_report(config, args.fixture)
            print(report)
            return code
        case "export-csv":
            if bool(args.date_from) != bool(args.date_to):
                raise ConfigError("--from and --to must be provided together")
            if args.date_from and args.date_to:
                try:
                    start = date.fromisoformat(args.date_from)
                    end = date.fromisoformat(args.date_to)
                except ValueError as error:
                    raise ConfigError("--from and --to must be YYYY-MM-DD") from error
                if start > end:
                    raise ConfigError("--from must be on or before --to")
            date_from = args.date_from or (
                config.study_start.isoformat() if config.study_start else None
            )
            date_to = args.date_to or (
                config.study_start.fromordinal(
                    config.study_start.toordinal() + config.duration_days - 1
                ).isoformat()
                if config.study_start
                else None
            )
            output = config.exports_dir / ("fixture" if args.fixture else "live")
            paths = export_csv(_db(config, args.fixture), output, date_from, date_to)
            print("\n".join(str(path) for path in paths))
            return ExitCode.SUCCESS
        case "backup":
            database_path = _db(config, args.fixture)
            if not database_path.is_file():
                raise FileNotFoundError(database_path)
            destination = args.destination or config.backups_dir / database_path.name
            destination = (
                destination if destination.is_absolute() else config.path.parent / destination
            )
            with Database(database_path) as database:
                database.backup(destination)
            print(destination)
            return ExitCode.SUCCESS
        case unreachable:
            raise AssertionError(f"Unknown command {unreachable}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(_run(args, load_config(args.config)))
    except (ConfigError, StudyRoomError, OSError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return int(ExitCode.ERROR)
