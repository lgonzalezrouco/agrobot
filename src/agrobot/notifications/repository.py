import uuid
from collections.abc import Sequence
from datetime import date, datetime
from itertools import batched
from typing import NamedTuple

from sqlalchemy import CursorResult, delete, exists, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.alerts.models import Alert
from agrobot.fields.models import Field
from agrobot.forecasts.models import Forecast
from agrobot.notifications.models import (
    MESSAGE_MAX_NOTIFICATIONS,
    Notification,
    NotificationStatus,
)
from agrobot.notifications.sender import NotificationContent
from agrobot.users.models import User


async def alert_exists(session: AsyncSession, alert_id: uuid.UUID) -> bool:
    return await session.get(Alert, alert_id) is not None


async def list_for_alert(session: AsyncSession, alert_id: uuid.UUID) -> Sequence[Notification]:
    return (
        await session.scalars(
            select(Notification).where(Notification.alert_id == alert_id).order_by(Notification.day)
        )
    ).all()


async def create_due(session: AsyncSession, today: date) -> int:
    due = (
        select(Alert.id, Forecast.day, Forecast.probability, Alert.threshold)
        .join(Field, Field.id == Alert.field_id)
        .join(
            Forecast,
            (Forecast.location_id == Field.location_id)
            & (Forecast.weather_event_type == Alert.weather_event_type),
        )
        .where(
            Alert.active,
            Forecast.day >= today,
            Forecast.probability >= Alert.threshold,
            ~exists().where(Notification.alert_id == Alert.id, Notification.day == Forecast.day),
        )
        .with_for_update(read=True, of=Field)
    )
    result: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
        insert(Notification)
        .from_select(["alert_id", "day", "probability", "threshold"], due)
        .on_conflict_do_nothing(index_elements=[Notification.alert_id, Notification.day])
    )
    return result.rowcount


async def delete_pending_for_field(session: AsyncSession, field_id: uuid.UUID) -> int:
    result: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
        delete(Notification).where(
            Notification.status == NotificationStatus.PENDING,
            Notification.alert_id.in_(select(Alert.id).where(Alert.field_id == field_id)),
        )
    )
    return result.rowcount


async def delete_pending_not_applying(session: AsyncSession, alert: Alert) -> int:
    result: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
        delete(Notification).where(
            Notification.status == NotificationStatus.PENDING,
            Notification.alert_id == alert.id,
            Notification.probability < alert.threshold if alert.active else true(),
        )
    )
    return result.rowcount


async def expire_past(session: AsyncSession, today: date) -> int:
    result: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
        update(Notification)
        .where(
            Notification.id.in_(
                select(Notification.id)
                .where(Notification.status == NotificationStatus.PENDING, Notification.day < today)
                .with_for_update(skip_locked=True)
            )
        )
        .values(status=NotificationStatus.EXPIRED)
    )
    return result.rowcount


class Message(NamedTuple):
    phone_number: str
    notifications: list[Notification]
    contents: list[NotificationContent]


async def claim_due(
    session: AsyncSession, due_by: datetime, limit: int
) -> tuple[int, list[Message]]:
    first_due = (
        select(Notification.day, Notification.next_attempt_at)
        .join(Alert, Alert.id == Notification.alert_id)
        .join(Field, Field.id == Alert.field_id)
        .where(
            Field.user_id == User.id,
            Notification.status == NotificationStatus.PENDING,
            Notification.next_attempt_at <= due_by,
        )
        .order_by(Notification.day, Notification.next_attempt_at)
        .limit(1)
        .lateral()
    )
    user_ids = (
        await session.scalars(
            select(User.id)
            .join(first_due, true())
            .order_by(first_due.c.day, first_due.c.next_attempt_at)
            .limit(limit)
            .with_for_update(of=User, skip_locked=True)
        )
    ).all()
    rows = await session.execute(
        select(Notification, User.phone_number, Field.name, Alert.weather_event_type)
        .join(Alert, Alert.id == Notification.alert_id)
        .join(Field, Field.id == Alert.field_id)
        .join(User, User.id == Field.user_id)
        .where(User.id.in_(user_ids), Notification.status == NotificationStatus.PENDING)
        .order_by(Notification.day, Notification.next_attempt_at)
        .with_for_update(of=Notification, skip_locked=True)
    )
    by_phone: dict[str, list[tuple[Notification, NotificationContent]]] = {}
    for notification, phone_number, field_name, weather_event_type in rows:
        by_phone.setdefault(phone_number, []).append(
            (
                notification,
                NotificationContent(
                    field_name,
                    weather_event_type,
                    notification.day,
                    notification.probability,
                    notification.threshold,
                ),
            )
        )
    return len(user_ids), [
        Message(phone_number, [n for n, _ in chunk], [c for _, c in chunk])
        for phone_number, claims in by_phone.items()
        if any(n.next_attempt_at <= due_by for n, _ in claims)
        for chunk in batched(claims, MESSAGE_MAX_NOTIFICATIONS, strict=False)
    ]


async def lock_pending(session: AsyncSession, ids: list[uuid.UUID]) -> Sequence[Notification]:
    return (
        await session.scalars(
            select(Notification)
            .where(Notification.id.in_(ids), Notification.status == NotificationStatus.PENDING)
            .with_for_update()
        )
    ).all()
