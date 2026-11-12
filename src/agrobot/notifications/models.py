import enum
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

RETRY_BASE_DELAY_SECONDS = 30
RETRY_MAX_DELAY_SECONDS = 3600


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
        Enum(
            NotificationStatus,
            name="notification_status",
            values_callable=lambda members: [member.value for member in members],
        ),
        server_default=NotificationStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None]

    def mark_sent(self) -> None:
        self.status = NotificationStatus.SENT
        self.sent_at = datetime.now(UTC)

    def mark_send_failed(self, max_attempts: int) -> None:
        if self.attempts >= max_attempts:
            self.status = NotificationStatus.FAILED
            return
        delay = min(RETRY_BASE_DELAY_SECONDS * 2 ** (self.attempts - 1), RETRY_MAX_DELAY_SECONDS)
        self.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
