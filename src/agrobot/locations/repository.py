from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.fields.models import Field
from agrobot.locations.models import Location


async def get_or_create(session: AsyncSession, latitude: Decimal, longitude: Decimal) -> Location:
    await session.execute(
        insert(Location).values(latitude=latitude, longitude=longitude).on_conflict_do_nothing()
    )
    return (
        await session.scalars(
            select(Location).where(Location.latitude == latitude, Location.longitude == longitude)
        )
    ).one()


async def list_with_fields(session: AsyncSession) -> Sequence[Location]:
    return (
        await session.scalars(
            select(Location)
            .where(select(Field.id).where(Field.location_id == Location.id).exists())
            .order_by(Location.id)
        )
    ).all()
