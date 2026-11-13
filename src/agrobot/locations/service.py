import uuid
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.locations import repository
from agrobot.locations.models import Location

GRID_STEP = Decimal("0.1")


def _snap_to_grid(coordinate: float) -> Decimal:
    return Decimal(str(coordinate)).quantize(GRID_STEP, rounding=ROUND_HALF_UP)


async def get_or_create(session: AsyncSession, latitude: float, longitude: float) -> Location:
    snapped_longitude = _snap_to_grid(longitude)
    if snapped_longitude == 180:
        snapped_longitude = Decimal("-180.0")
    return await repository.get_or_create(session, _snap_to_grid(latitude), snapped_longitude)


async def list_with_fields(session: AsyncSession) -> Sequence[Location]:
    return await repository.list_with_fields(session)


async def ids_with_fields_after(
    session: AsyncSession, after: uuid.UUID, limit: int
) -> Sequence[uuid.UUID]:
    return await repository.ids_with_fields_after(session, after, limit)
