import asyncio
import enum
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from itertools import batched
from typing import NamedTuple
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.alerts.models import Alert
from agrobot.core.errors import NotFoundError
from agrobot.locations import service as locations
from agrobot.notifications import repository
from agrobot.notifications.models import MESSAGE_MAX_NOTIFICATIONS, Notification, retry_delay
from agrobot.notifications.sender import NotificationSender, PermanentDeliveryError

logger = structlog.get_logger(__name__)


async def delete_pending_for_field(session: AsyncSession, field_id: uuid.UUID) -> int:
    return await repository.delete_pending_for_field(session, field_id)


async def withdraw_pending(session: AsyncSession, alert: Alert) -> int:
    return await repository.delete_pending_for_alert(
        session, alert.id, below=alert.threshold if alert.active else None
    )


async def list_for_alert(
    session: AsyncSession, alert_id: uuid.UUID, limit: int, before: date | None
) -> Sequence[Notification]:
    if not await repository.alert_exists(session, alert_id):
        raise NotFoundError("alert not found")
    return await repository.list_for_alert(session, alert_id, limit, before)


async def evaluate(
    session_factory: async_sessionmaker[AsyncSession], *, batch_size: int, timezone: ZoneInfo
) -> None:
    today = datetime.now(timezone).date()
    created = 0
    after: uuid.UUID | None = None
    while True:
        async with session_factory() as session:
            location_ids = await locations.ids_with_fields_after(session, after, batch_size)
            created += await repository.create_due(session, today, location_ids)
            await session.commit()
        if len(location_ids) < batch_size:
            break
        after = location_ids[-1]
    logger.info("notifications.evaluated", created=created)


class Outcome(enum.StrEnum):
    SENT = "sent"
    RETRIED = "retried"
    FAILED = "failed"
    EXPIRED = "expired"


class Message(NamedTuple):
    phone_number: str
    claims: list[repository.ClaimedNotification]


def _messages_by_user(
    claims: list[repository.ClaimedNotification], due_by: datetime, now: datetime
) -> list[list[Message]]:
    by_user: dict[str, list[repository.ClaimedNotification]] = {}
    for claim in claims:
        by_user.setdefault(claim.phone_number, []).append(claim)
    return [
        [
            Message(phone_number, list(chunk))
            for chunk in batched(user_claims, MESSAGE_MAX_NOTIFICATIONS, strict=False)
        ]
        for phone_number, user_claims in by_user.items()
        if any(claim.notification.next_attempt_at <= due_by for claim in user_claims)
        and not any(
            claim.notification.leased_until is not None and claim.notification.leased_until > now
            for claim in user_claims
        )
    ]


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    batch_size: int,
    timeout_seconds: float,
    timezone: ZoneInfo,
) -> None:
    started_at = datetime.now(UTC)
    lease_per_message = timedelta(seconds=2 * timeout_seconds)
    outcomes: Counter[str] = Counter()
    async with session_factory() as session:
        outcomes[Outcome.EXPIRED] = await repository.expire_past(
            session, datetime.now(timezone).date()
        )
        await session.commit()

    async def deliver(message: Message, today: date) -> None:
        ids = [claim.notification.id for claim in message.claims]
        contents = [claim.content for claim in message.claims if claim.content.day >= today]
        delivery = Outcome.EXPIRED
        if contents:
            try:
                async with asyncio.timeout(timeout_seconds):
                    await sender.send(message.phone_number, contents)
                delivery = Outcome.SENT
            except PermanentDeliveryError:
                logger.warning("notifications.send_rejected", notification_ids=ids)
                delivery = Outcome.FAILED
            except Exception:
                logger.exception("notifications.send_failed", notification_ids=ids)
                delivery = Outcome.RETRIED
        recorded: Counter[str] = Counter()
        try:
            async with session_factory() as session:
                stored = await repository.lock_pending(session, ids)
                attempts = max((notification.attempts for notification in stored), default=0)
                retry_at = datetime.now(UTC) + retry_delay(attempts + 1)
                for notification in stored:
                    outcome = Outcome.EXPIRED if notification.day < today else delivery
                    match outcome:
                        case Outcome.EXPIRED:
                            notification.mark_expired()
                        case Outcome.SENT:
                            notification.mark_sent()
                        case Outcome.FAILED:
                            notification.mark_failed()
                        case Outcome.RETRIED:
                            notification.mark_send_failed(retry_at)
                    recorded[outcome] += 1
                await session.commit()
        except SQLAlchemyError:
            logger.exception("notifications.record_failed", notification_ids=ids)
            outcomes["errors"] += 1
            return
        outcomes.update(recorded)

    async def deliver_in_order(messages: list[Message], today: date) -> None:
        for message in messages:
            await deliver(message, today)

    while True:
        async with session_factory() as session:
            now = datetime.now(UTC)
            user_ids = await repository.claim_users(session, started_at, now, batch_size)
            claims = await repository.pending_for_users(session, user_ids)
            messages_by_user = _messages_by_user(claims, started_at, now)
            for messages in messages_by_user:
                leased_until = now + lease_per_message * len(messages)
                for message in messages:
                    for claim in message.claims:
                        claim.notification.leased_until = leased_until
            await session.commit()
        today = datetime.now(timezone).date()
        await asyncio.gather(*(deliver_in_order(messages, today) for messages in messages_by_user))
        if len(user_ids) < batch_size or not messages_by_user:
            break
    logger.info(
        "notifications.notified",
        expired=outcomes[Outcome.EXPIRED],
        sent=outcomes[Outcome.SENT],
        retried=outcomes[Outcome.RETRIED],
        failed=outcomes[Outcome.FAILED],
        errors=outcomes["errors"],
    )
