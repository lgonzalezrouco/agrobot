from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.notifications import repository
from agrobot.notifications.sender import NotificationSender

logger = structlog.get_logger(__name__)


async def evaluate(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        created = await repository.create_due(session, datetime.now(UTC).date())
        await session.commit()
    logger.info("notifications.evaluated", created=created)


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    batch_size: int,
) -> None:
    sent = 0
    async with session_factory() as session:
        claimed = await repository.claim_due(session, datetime.now(UTC), batch_size)
        for notification, phone_number, content in claimed:
            notification.attempts += 1
            try:
                await sender.send(phone_number, content)
            except Exception:
                logger.exception("notifications.send_failed", notification_id=notification.id)
                continue
            notification.mark_sent()
            sent += 1
        await session.commit()
    logger.info("notifications.sent", sent=sent, failed=len(claimed) - sent)
