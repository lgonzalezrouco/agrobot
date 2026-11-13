import enum
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class JobOutcome(enum.StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class JobRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_runs"

    job: Mapped[str] = mapped_column(unique=True)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]
    outcome: Mapped[JobOutcome] = mapped_column(pg_enum(JobOutcome, "job_outcome"))
    duration_seconds: Mapped[float]
    counters: Mapped[dict[str, int]] = mapped_column(JSONB)
    last_succeeded_at: Mapped[datetime | None]
