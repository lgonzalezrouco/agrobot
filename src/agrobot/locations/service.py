from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.locations import repository
from agrobot.locations.models import Location

GRID_STEP = Decimal("0.1")


def _snap_to_grid(coordinate: float) -> Decimal:
    # str() keeps the decimal the client sent, so 0.05 rounds up instead of to float noise.
    return Decimal(str(coordinate)).quantize(GRID_STEP, rounding=ROUND_HALF_UP)


async def get_or_create(session: AsyncSession, latitude: float, longitude: float) -> Location:
    snapped_longitude = _snap_to_grid(longitude)
    if snapped_longitude == 180:  # same meridian as -180, keep one Location for it
        snapped_longitude = Decimal("-180.0")
    return await repository.get_or_create(session, _snap_to_grid(latitude), snapped_longitude)
