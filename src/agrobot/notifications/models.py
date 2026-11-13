import enum
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum

RETRY_BASE_DELAY_SECONDS = 30
RETRY_MAX_DELAY_SECONDS = 3600
MESSAGE_MAX_NOTIFICATIONS = 20


def retry_delay(attempts: int) -> timedelta:
    return timedelta(
        seconds=min(RETRY_BASE_DELAY_SECONDS * 2 ** (attempts - 1), RETRY_MAX_DELAY_SECONDS)
    )


class NotificationStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    EXPIRED = "expired"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("alert_id", "day"),
        CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
        CheckConstraint("threshold BETWEEN 0 AND 100", name="threshold_range"),
        Index(
            None,
            "day",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    day: Mapped[date]
    probability: Mapped[int]
    threshold: Mapped[int]
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"),
        server_default=NotificationStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None]
    leased_until: Mapped[datetime | None]

    def mark_sent(self) -> None:
        self.attempts += 1
        self.status = NotificationStatus.SENT
        self.sent_at = datetime.now(UTC)

    def mark_expired(self) -> None:
        self.status = NotificationStatus.EXPIRED

    def mark_failed(self) -> None:
        self.attempts += 1
        self.status = NotificationStatus.FAILED

    def mark_send_failed(self, retry_at: datetime) -> None:
        self.attempts += 1
        self.defer(retry_at)

    def defer(self, retry_at: datetime) -> None:
        self.next_attempt_at = retry_at
        self.leased_until = None
