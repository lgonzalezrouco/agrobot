from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.locations.models import Location

GRID_STEP = Decimal("0.1")


def snap_to_grid(coordinate: float) -> Decimal:
    # str() keeps the decimal the client sent, so 0.05 rounds up instead of to float noise.
    return Decimal(str(coordinate)).quantize(GRID_STEP, rounding=ROUND_HALF_UP)


async def get_or_create(session: AsyncSession, latitude: float, longitude: float) -> Location:
    lat, lon = snap_to_grid(latitude), snap_to_grid(longitude)
    # ON CONFLICT waits for a concurrent insert of the same point instead of failing.
    await session.execute(
        insert(Location).values(latitude=lat, longitude=lon).on_conflict_do_nothing()
    )
    return (
        await session.scalars(
            select(Location).where(Location.latitude == lat, Location.longitude == lon)
        )
    ).one()
