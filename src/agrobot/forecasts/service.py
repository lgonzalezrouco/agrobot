from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.forecasts import repository
from agrobot.forecasts.provider import WeatherProvider
from agrobot.locations import repository as locations

HORIZON_DAYS = 7

logger = structlog.get_logger(__name__)


async def ingest(
    session_factory: async_sessionmaker[AsyncSession], provider: WeatherProvider
) -> None:
    today = datetime.now(UTC).date()
    days = [today + timedelta(days=offset) for offset in range(HORIZON_DAYS)]
    async with session_factory() as session:
        targets = await locations.list_with_fields(session)
    for location in targets:
        forecasts = await provider.get_forecasts(location, days)
        async with session_factory() as session:
            await repository.upsert(session, location.id, forecasts)
            await session.commit()
    logger.info("forecasts.ingested", locations=len(targets))
