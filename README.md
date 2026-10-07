# GIST Study Room Collector

An offline-testable, one-shot CLI for recording daily GIST Study Room reservation observations. A fully successful collection replaces prior observations and facility results for the same target date and mode, while retaining every run ledger entry for audit history. Partial, failed, and authentication-required attempts never prune prior data. This is not a reservation client, web service, scheduler, or usage-time tracker.

## Live Collector Boundary

The verified read-only contract uses `https://library.gist.ac.kr` for login and `https://library.gist.ac.kr:8443` for API requests. `collect-once` uses no browser and only sends `POST` requests to `/hello/getAccount`, `/work/getFacilityInfo`, and `/work/getRoom`. It never implements or calls reservation creation, cancellation, update, or deletion endpoints. A blank `api_url` is rejected.

`collect-once` captures its Seoul target date once at startup and requests only that date; it never collects a future or missed date. `config.example.toml` covers all 44 verified facilities. Every source row is an occupied one-hour reservation observation, including separate consecutive rows; it is not evidence of actual room use. Own `data.room` rows start as `도전탐색과정` and `UNDERGRADUATE`, independent of account data. `roomOther` continues to use its department and group fields, has no stable source ID, and excludes free-text `REMARK`. Department normalization remains local configuration after this raw classification.

## Setup

This bootstrap was created in WSL2 with CPython 3.14.4. The project requires Python 3.14 or newer.

```bash
uv sync
uv run playwright install chromium
cp config.example.toml config.toml
uv run gist-studyroom --config config.toml init-db
uv run gist-studyroom --config config.toml collect-fixture --fixture fixtures/example.json
```

`uv run playwright install chromium` installs a browser locally; it does not perform login or collection. Paths in `config.toml` are resolved from the config file, never the scheduler working directory.

## Commands

```text
gist-studyroom --config config.toml init-db [--fixture]
gist-studyroom --config config.toml login [--from-env] [--replace]
gist-studyroom --config config.toml collect-once
gist-studyroom --config config.toml collect-fixture --fixture fixtures/example.json
gist-studyroom --config config.toml status [--fixture]
gist-studyroom --config config.toml export-csv [--fixture] [--from YYYY-MM-DD --to YYYY-MM-DD]
gist-studyroom --config config.toml backup [--fixture] [--destination PATH]
```

`login` opens headed Chromium at `site.reservations_url`. Without `--from-env`, complete normal password, MFA, and CAPTCHA steps yourself. With `--from-env`, it reads only `ID` and `PASSWORD` from `.env` beside the config, fills the verified selectors, and waits for `#/facilityReservation`. Both modes save Playwright storage state and the separate `sessionStorage.accessToken` file configured by `paths.api_token`; existing files require `--replace`. Neither credentials nor token are printed. Scheduled `collect-once` reads only that saved token and reports `AUTH_REQUIRED` after session expiry. It never auto-relogs in.

On POSIX, auth/token directories are owner-only (`0700`) and both saved files are `0600`. On Windows, keep the project under the collecting account and ensure its account ACL does not grant other users access.

Exit codes are `0` success, `10` partial facility success, `20` authentication required, `30` configuration/validation/general error, `40` another collector owns the lock, and `50` stale or absent successful live collection. A validated empty facility is `EMPTY`, not failure; authentication and structure errors are never zero observations.

## Data and Reporting

`live_db` and `fixture_db` must resolve to different files. `collect-fixture` never opens a page, uses auth state, contacts a network, or writes the live database. `status --fixture` reports fixture ledger quality only; it never satisfies live freshness. `export-csv --from YYYY-MM-DD --to YYYY-MM-DD` applies inclusive bounds, defaults to the configured study range, and writes separate `exports/live` or `exports/fixture` files. `backup` rejects a missing source, source-equal destination, or pre-existing destination and uses `sqlite3.Connection.backup()`.

See [docs/data-model.md](docs/data-model.md) for snapshot semantics and research limits. `status` is only a DB-derived freshness check: it cannot alert while the computer, process, or scheduler is stopped, and fixture success never satisfies live health.

## Scheduling

Do not register a scheduler from this project. Start with one run per hour in Asia/Seoul and consider a final observation before the site's daily data disappears only after observing its day-transition behavior. Every live run observes only the Seoul date captured when it starts; a missed day cannot be reconstructed by a later run.

Use absolute paths, not a scheduler working directory. Examples are in [docs/scheduling.md](docs/scheduling.md). Logs can be redirected by the scheduler. Ensure the OS does not sleep through the planned window and review `status` plus `runs.csv`; the OS lock prevents two local processes from overlapping.

## Desktop Migration

1. Stop source collection and its scheduler. Transfer the cleanly closed `data/live.sqlite3` separately, not through Git.
2. On the Desktop, clone the tracked code, recreate `config.toml` and `.env`, and create fresh local auth with `login --from-env --replace`.
3. Verify the copied DB checksum before any collection. Do not run `collect-once` on the migration date, 2026-10-06.
4. Keep the Desktop scheduler disabled until the next Asia/Seoul date, then collect that new date and enable scheduling only after verification.

Never transfer auth state, `.env`, or `private/`, and never let two PCs write the same SQLite database. The complete procedure is in [docs/desktop-migration.md](docs/desktop-migration.md).
