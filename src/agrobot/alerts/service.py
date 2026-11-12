import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.alerts import repository
from agrobot.alerts.models import Alert
from agrobot.core.errors import ConflictError, NotFoundError
from agrobot.fields import service as fields
from agrobot.weather import WeatherEventType

logger = structlog.get_logger(__name__)

FOREIGN_KEY_VIOLATION = "23503"


async def configure(
    session: AsyncSession,
    field_id: uuid.UUID,
    weather_event_type: WeatherEventType,
    threshold: int,
    active: bool,
) -> Alert:
    await fields.get(session, field_id)
    alert = Alert(
        field_id=field_id,
        weather_event_type=weather_event_type,
        threshold=threshold,
        active=active,
    )
    try:
        await repository.save(session, alert)
    except IntegrityError as exc:
        await session.rollback()
        if getattr(exc.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION:
            raise NotFoundError("field not found") from exc
        raise ConflictError("field already has an alert for this weather event type") from exc
    await session.commit()
    logger.info("alerts.configured", alert_id=alert.id, field_id=field_id)
    return alert


async def list_for_field(session: AsyncSession, field_id: uuid.UUID) -> Sequence[Alert]:
    await fields.get(session, field_id)
    return await repository.list_for_field(session, field_id)


async def get(session: AsyncSession, alert_id: uuid.UUID) -> Alert:
    alert = await repository.get(session, alert_id)
    if alert is None:
        raise NotFoundError("alert not found")
    return alert


async def update(
    session: AsyncSession, alert_id: uuid.UUID, threshold: int | None, active: bool | None
) -> Alert:
    alert = await get(session, alert_id)
    if threshold is not None:
        alert.threshold = threshold
    if active is not None:
        alert.active = active
    await repository.save(session, alert)
    await session.commit()
    logger.info("alerts.updated", alert_id=alert.id, threshold=alert.threshold, active=alert.active)
    return alert


async def delete(session: AsyncSession, alert_id: uuid.UUID) -> None:
    alert = await get(session, alert_id)
    await repository.delete(session, alert)
    await session.commit()
    logger.info("alerts.deleted", alert_id=alert_id)
