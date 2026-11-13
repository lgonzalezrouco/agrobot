import asyncio
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.alerts.models import Alert
from agrobot.core.errors import NotFoundError
from agrobot.notifications import repository
from agrobot.notifications.models import Notification, retry_delay
from agrobot.notifications.sender import NotificationSender, PermanentDeliveryError

logger = structlog.get_logger(__name__)


async def delete_pending_for_field(session: AsyncSession, field_id: uuid.UUID) -> int:
    return await repository.delete_pending_for_field(session, field_id)


async def delete_pending_not_applying(session: AsyncSession, alert: Alert) -> int:
    return await repository.delete_pending_not_applying(session, alert)


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


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    batch_size: int,
    timeout_seconds: float,
    timezone: ZoneInfo,
) -> None:
    started_at = datetime.now(UTC)
    lease = timedelta(seconds=2 * timeout_seconds)
    outcomes: Counter[str] = Counter()
    async with session_factory() as session:
        outcomes["expired"] = await repository.expire_past(session, datetime.now(timezone).date())
        await session.commit()

    async def deliver(message: repository.Message, today: date) -> None:
        ids = [notification.id for notification in message.notifications]
        contents = [content for content in message.contents if content.day >= today]
        result = "expired"
        if contents:
            try:
                async with asyncio.timeout(timeout_seconds):
                    await sender.send(message.phone_number, contents)
                result = "sent"
            except PermanentDeliveryError:
                logger.warning("notifications.send_rejected", notification_ids=ids)
                result = "failed"
            except Exception:
                logger.exception("notifications.send_failed", notification_ids=ids)
                result = "retried"
        recorded: Counter[str] = Counter()
        try:
            async with session_factory() as session:
                stored = await repository.lock_pending(session, ids)
                attempts = max((notification.attempts for notification in stored), default=0)
                retry_at = datetime.now(UTC) + retry_delay(attempts + 1)
                for notification in stored:
                    outcome = "expired" if notification.day < today else result
                    match outcome:
                        case "expired":
                            notification.mark_expired()
                        case "sent":
                            notification.mark_sent()
                        case "failed":
                            notification.mark_failed()
                        case _:
                            notification.mark_send_failed(retry_at)
                    recorded[outcome] += 1
                await session.commit()
        except SQLAlchemyError:
            logger.exception("notifications.record_failed", notification_ids=ids)
            outcomes["errors"] += 1
            return
        outcomes.update(recorded)

    while True:
        async with session_factory() as session:
            claimed_users, messages = await repository.claim_due(session, started_at, batch_size)
            leased_until = datetime.now(UTC) + lease
            for message in messages:
                for notification in message.notifications:
                    notification.next_attempt_at = max(notification.next_attempt_at, leased_until)
            await session.commit()
        today = datetime.now(timezone).date()
        await asyncio.gather(*(deliver(message, today) for message in messages))
        if claimed_users < batch_size:
            break
    logger.info(
        "notifications.notified",
        expired=outcomes["expired"],
        sent=outcomes["sent"],
        retried=outcomes["retried"],
        failed=outcomes["failed"],
        errors=outcomes["errors"],
    )
