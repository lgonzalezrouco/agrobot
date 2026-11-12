import asyncio
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.core.errors import NotFoundError
from agrobot.notifications import repository
from agrobot.notifications.models import Notification, NotificationStatus
from agrobot.notifications.sender import NotificationSender

logger = structlog.get_logger(__name__)


async def delete_pending_for_field(session: AsyncSession, field_id: uuid.UUID) -> int:
    return await repository.delete_pending_for_field(session, field_id)


async def list_for_alert(session: AsyncSession, alert_id: uuid.UUID) -> Sequence[Notification]:
    if not await repository.alert_exists(session, alert_id):
        raise NotFoundError("alert not found")
    return await repository.list_for_alert(session, alert_id)


async def evaluate(
    session_factory: async_sessionmaker[AsyncSession], *, timezone: ZoneInfo
) -> None:
    async with session_factory() as session:
        created = await repository.create_due(session, datetime.now(timezone).date())
        await session.commit()
    logger.info("notifications.evaluated", created=created)


_MARKS = {
    "expired": Notification.mark_expired,
    "sent": Notification.mark_sent,
    "retried": Notification.mark_send_failed,
}


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    batch_size: int,
    timeout_seconds: float,
    timezone: ZoneInfo,
) -> None:
    started_at = datetime.now(UTC)
    lease = timedelta(seconds=batch_size * timeout_seconds)
    outcomes: Counter[str] = Counter()
    async with session_factory() as session:
        outcomes["expired"] = await repository.expire_past(session, datetime.now(timezone).date())
        await session.commit()

    async def deliver(claim: repository.ClaimedNotification, today: date) -> str:
        outcome = "expired"
        if claim.notification.day >= today:
            try:
                async with asyncio.timeout(timeout_seconds):
                    await sender.send(claim.phone_number, claim.content)
                outcome = "sent"
            except Exception:
                logger.exception("notifications.send_failed", notification_id=claim.notification.id)
                outcome = "retried"
        async with session_factory() as session:
            notification = await session.get(
                Notification, claim.notification.id, with_for_update=True
            )
            if notification is not None and notification.status == NotificationStatus.PENDING:
                _MARKS[outcome](notification)
                await session.commit()
        return outcome

    while True:
        async with session_factory() as session:
            claimed = await repository.claim_due(session, started_at, batch_size)
            leased_until = datetime.now(UTC) + lease
            for claim in claimed:
                claim.notification.lease_until(leased_until)
            await session.commit()
        today = datetime.now(timezone).date()
        outcomes.update(await asyncio.gather(*(deliver(claim, today) for claim in claimed)))
        if len(claimed) < batch_size:
            break
    logger.info(
        "notifications.notified",
        expired=outcomes["expired"],
        sent=outcomes["sent"],
        retried=outcomes["retried"],
    )
