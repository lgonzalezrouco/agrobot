import asyncio
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.notifications import repository
from agrobot.notifications.models import Notification, NotificationStatus
from agrobot.notifications.sender import NotificationSender

logger = structlog.get_logger(__name__)


async def delete_pending_for_field(session: AsyncSession, field_id: uuid.UUID) -> int:
    return await repository.delete_pending_for_field(session, field_id)


async def evaluate(
    session_factory: async_sessionmaker[AsyncSession], *, timezone: ZoneInfo
) -> None:
    async with session_factory() as session:
        created = await repository.create_due(session, datetime.now(timezone).date())
        await session.commit()
    logger.info("notifications.evaluated", created=created)


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    batch_size: int,
    timeout_seconds: float,
    timezone: ZoneInfo,
) -> None:
    async with session_factory() as session:
        expired = await repository.expire_past(session, datetime.now(timezone).date())
        await session.commit()
    outcomes: Counter[NotificationStatus] = Counter()
    lease = timedelta(seconds=batch_size * timeout_seconds)
    while True:
        async with session_factory() as session:
            claimed = await repository.claim_due(session, datetime.now(UTC), batch_size, lease)
            await session.commit()
        today = datetime.now(timezone).date()
        outcomes.update(
            await asyncio.gather(
                *(
                    _deliver(session_factory, sender, claim, today, timeout_seconds)
                    for claim in claimed
                )
            )
        )
        if len(claimed) < batch_size:
            break
    logger.info(
        "notifications.notified",
        expired=expired + outcomes[NotificationStatus.EXPIRED],
        sent=outcomes[NotificationStatus.SENT],
        retried=outcomes[NotificationStatus.PENDING],
    )


async def _deliver(
    session_factory: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    claim: repository.ClaimedNotification,
    today: date,
    timeout_seconds: float,
) -> NotificationStatus:
    outcome = NotificationStatus.EXPIRED
    if claim.notification.day >= today:
        try:
            async with asyncio.timeout(timeout_seconds):
                await sender.send(claim.phone_number, claim.content)
            outcome = NotificationStatus.SENT
        except Exception:
            logger.exception("notifications.send_failed", notification_id=claim.notification.id)
            outcome = NotificationStatus.PENDING
    async with session_factory() as session:
        notification = await session.get(Notification, claim.notification.id, with_for_update=True)
        if notification is not None and notification.status == NotificationStatus.PENDING:
            if outcome == NotificationStatus.SENT:
                notification.mark_sent()
            elif outcome == NotificationStatus.PENDING:
                notification.mark_send_failed()
            else:
                notification.mark_expired()
            await session.commit()
    return outcome
