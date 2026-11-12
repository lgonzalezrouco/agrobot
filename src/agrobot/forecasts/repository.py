import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.forecasts.models import Forecast
from agrobot.forecasts.provider import ProviderForecast


async def list_for_location(session: AsyncSession, location_id: uuid.UUID) -> Sequence[Forecast]:
    return (
        await session.scalars(
            select(Forecast)
            .where(Forecast.location_id == location_id)
            .order_by(Forecast.weather_event_type, Forecast.day)
        )
    ).all()


async def upsert(
    session: AsyncSession, location_id: uuid.UUID, forecasts: Sequence[ProviderForecast]
) -> None:
    latest = {(f.weather_event_type, f.day): f.probability for f in forecasts}
    if not latest:
        return
    statement = insert(Forecast).values(
        [
            {
                "location_id": location_id,
                "weather_event_type": weather_event_type,
                "day": day,
                "probability": probability,
            }
            for (weather_event_type, day), probability in latest.items()
        ]
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Forecast.location_id, Forecast.weather_event_type, Forecast.day],
            set_={"probability": statement.excluded.probability, "updated_at": func.now()},
        )
    )
