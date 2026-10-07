from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum, StrEnum
from pathlib import Path


class ExitCode(IntEnum):
    SUCCESS = 0
    PARTIAL = 10
    AUTH_REQUIRED = 20
    ERROR = 30
    DUPLICATE_LOCK = 40
    STALE = 50


class Mode(StrEnum):
    LIVE = "LIVE"
    FIXTURE = "FIXTURE"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INTERRUPTED = "INTERRUPTED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


class FacilityStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class StudentLevel(StrEnum):
    UNDERGRADUATE = "UNDERGRADUATE"
    GRADUATE = "GRADUATE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Facility:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Observation:
    facility: Facility
    reservation_date: date
    start_at: datetime
    end_at: datetime | None
    department_raw: str
    department_normalized: str
    student_level: StudentLevel
    source_reservation_id: str | None
    source_status: str | None


@dataclass(frozen=True, slots=True)
class FacilityPayload:
    facility: Facility
    status: FacilityStatus
    observations: tuple[Observation, ...]
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class FixtureSnapshot:
    target_date: date
    facilities: tuple[FacilityPayload, ...]


@dataclass(frozen=True, slots=True)
class CollectionResult:
    exit_code: ExitCode
    status: RunStatus
    message: str


@dataclass(frozen=True, slots=True)
class ExportPaths:
    observations: Path
    snapshot: Path
    runs: Path

    def __iter__(self):
        return iter((self.observations, self.snapshot, self.runs))

    def __len__(self) -> int:
        return 3


class StudyRoomError(Exception):
    pass


class ConfigError(StudyRoomError):
    pass


class FixtureError(StudyRoomError):
    pass


class LiveError(StudyRoomError):
    pass


class AuthenticationRequired(StudyRoomError):
    pass


class LockUnavailable(StudyRoomError):
    pass


class ValidationError(StudyRoomError):
    pass
