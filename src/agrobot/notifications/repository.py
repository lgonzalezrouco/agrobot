import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import CursorResult, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.alerts.models import Alert
from agrobot.fields.models import Field
from agrobot.forecasts.models import Forecast
from agrobot.notifications.models import Notification, NotificationStatus
from agrobot.users.models import User
from agrobot.weather import WeatherEventType


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
    )
    result: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
        insert(Notification)
        .from_select(["alert_id", "day", "probability", "threshold"], due)
        .on_conflict_do_nothing(index_elements=[Notification.alert_id, Notification.day])
    )
    return result.rowcount


async def claim_due(
    session: AsyncSession, limit: int
) -> Sequence[tuple[Notification, str, str, WeatherEventType]]:
    return (
        (
            await session.execute(
                select(Notification, User.phone_number, Field.name, Alert.weather_event_type)
                .join(Alert, Alert.id == Notification.alert_id)
                .join(Field, Field.id == Alert.field_id)
                .join(User, User.id == Field.user_id)
                .where(
                    Notification.status == NotificationStatus.PENDING,
                    Notification.next_attempt_at <= func.now(),
                )
                .order_by(Notification.day, Notification.next_attempt_at)
                .limit(limit)
                .with_for_update(of=Notification, skip_locked=True)
            )
        )
        .tuples()
        .all()
    )
