import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.core.errors import NotFoundError
from agrobot.fields import repository
from agrobot.fields.models import Field
from agrobot.locations import service as locations
from agrobot.notifications import service as notifications
from agrobot.users import service as users

logger = structlog.get_logger(__name__)


async def register(
    session: AsyncSession, user_id: uuid.UUID, name: str, latitude: float, longitude: float
) -> Field:
    await users.get(session, user_id)
    location = await locations.get_or_create(session, latitude, longitude)
    field = Field(
        user_id=user_id, name=name, latitude=latitude, longitude=longitude, location=location
    )
    await repository.save(session, field)
    await session.commit()
    logger.info("fields.registered", field_id=field.id, location_id=location.id)
    return field


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Field]:
    await users.get(session, user_id)
    return await repository.list_for_user(session, user_id)


async def get(session: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await repository.get(session, field_id)
    if field is None:
        raise NotFoundError("field not found")
    return field


async def update(
    session: AsyncSession,
    field_id: uuid.UUID,
    name: str | None,
    latitude: float | None,
    longitude: float | None,
) -> Field:
    field = await get(session, field_id)
    dropped = 0
    if name is not None:
        field.name = name
    if latitude is not None or longitude is not None:
        field.latitude = field.latitude if latitude is None else latitude
        field.longitude = field.longitude if longitude is None else longitude
        location = await locations.get_or_create(session, field.latitude, field.longitude)
        if location.id != field.location_id:
            dropped = await notifications.delete_pending_for_field(session, field.id)
        field.location = location
    await repository.save(session, field)
    await session.commit()
    logger.info(
        "fields.updated",
        field_id=field.id,
        location_id=field.location_id,
        dropped_notifications=dropped,
    )
    return field


async def delete(session: AsyncSession, field_id: uuid.UUID) -> None:
    field = await get(session, field_id)
    await repository.delete(session, field)
    await session.commit()
    logger.info("fields.deleted", field_id=field_id)
