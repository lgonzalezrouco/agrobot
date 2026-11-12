import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.notifications import repository
from agrobot.notifications.models import Notification
from agrobot.notifications.sender import NotificationContent, NotificationSender

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
    max_attempts: int,
    timeout_seconds: float,
) -> None:
    sent = retried = failed = 0
    now = datetime.now(UTC)
    async with session_factory() as session:
        expired = await repository.expire_past(session, now.date())
        await session.commit()
        claimed = await repository.claim_due(session, now, batch_size)
        today = datetime.now(UTC).date()
        due = []
        for notification, phone_number, content in claimed:
            if notification.day < today:
                notification.mark_expired()
                expired += 1
            else:
                due.append((notification, phone_number, content))

        async def send(
            notification: Notification, phone_number: str, content: NotificationContent
        ) -> bool:
            try:
                async with asyncio.timeout(timeout_seconds):
                    await sender.send(phone_number, content)
            except Exception:
                logger.exception("notifications.send_failed", notification_id=notification.id)
                return False
            return True

        results = await asyncio.gather(*(send(*claim) for claim in due))
        for (notification, _, _), delivered in zip(due, results, strict=True):
            if delivered:
                notification.mark_sent()
                sent += 1
            elif notification.mark_send_failed(max_attempts):
                failed += 1
            else:
                retried += 1
        await session.commit()
    logger.info(
        "notifications.notified",
        expired=expired,
        sent=sent,
        retried=retried,
        failed=failed,
    )
