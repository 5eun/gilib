SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    target_date TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    observed_count INTEGER NOT NULL DEFAULT 0,
    target_facility_count INTEGER NOT NULL,
    success_facility_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS facility_results (
    run_id TEXT NOT NULL REFERENCES runs(id),
    facility_id TEXT NOT NULL,
    facility_name TEXT NOT NULL,
    status TEXT NOT NULL,
    observed_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    PRIMARY KEY (run_id, facility_id)
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    observed_at TEXT NOT NULL,
    reservation_date TEXT NOT NULL,
    facility_id TEXT NOT NULL,
    facility_name TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    department_raw TEXT NOT NULL,
    department_normalized TEXT NOT NULL,
    student_level TEXT NOT NULL,
    source_reservation_id TEXT,
    source_status TEXT
    ,comparison_key TEXT
    ,identity_basis TEXT
);
CREATE INDEX IF NOT EXISTS observations_snapshot_idx ON observations(reservation_date, facility_id, run_id);
CREATE INDEX IF NOT EXISTS runs_status_idx ON runs(status, started_at);
"""
