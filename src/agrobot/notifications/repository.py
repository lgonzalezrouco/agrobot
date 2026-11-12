import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import NamedTuple

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.alerts.models import Alert
from agrobot.fields.models import Field
from agrobot.forecasts.models import Forecast
from agrobot.notifications.models import Notification, NotificationStatus
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
        .where(Alert.active, Forecast.day >= today, Forecast.probability >= Alert.threshold)
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


class ClaimedNotification(NamedTuple):
    notification: Notification
    phone_number: str
    content: NotificationContent


async def claim_due(
    session: AsyncSession, due_by: datetime, limit: int
) -> list[ClaimedNotification]:
    rows = await session.execute(
        select(Notification, User.phone_number, Field.name, Alert.weather_event_type)
        .join(Alert, Alert.id == Notification.alert_id)
        .join(Field, Field.id == Alert.field_id)
        .join(User, User.id == Field.user_id)
        .where(
            Notification.status == NotificationStatus.PENDING,
            Notification.next_attempt_at <= due_by,
        )
        .order_by(Notification.day, Notification.next_attempt_at)
        .limit(limit)
        .with_for_update(of=Notification, skip_locked=True)
    )
    return [
        ClaimedNotification(
            notification,
            phone_number,
            NotificationContent(
                field_name,
                weather_event_type,
                notification.day,
                notification.probability,
                notification.threshold,
            ),
        )
        for notification, phone_number, field_name, weather_event_type in rows
    ]
