import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.forecasts import repository
from agrobot.forecasts.provider import WeatherProvider
from agrobot.locations import service as locations
from agrobot.locations.models import Location

HORIZON_DAYS = 7

logger = structlog.get_logger(__name__)


async def ingest(
    session_factory: async_sessionmaker[AsyncSession],
    provider: WeatherProvider,
    *,
    concurrency: int,
) -> None:
    today = datetime.now(UTC).date()
    days = [today + timedelta(days=offset) for offset in range(HORIZON_DAYS)]
    async with session_factory() as session:
        targets = await locations.list_with_fields(session)
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(
            _ingest_location(session_factory, provider, semaphore, location, days)
            for location in targets
        )
    )
    ingested = sum(results)
    logger.info("forecasts.ingested", ingested=ingested, failed=len(results) - ingested)


async def _ingest_location(
    session_factory: async_sessionmaker[AsyncSession],
    provider: WeatherProvider,
    semaphore: asyncio.Semaphore,
    location: Location,
    days: Sequence[date],
) -> bool:
    try:
        async with semaphore:
            forecasts = await provider.get_forecasts(location, days)
            async with session_factory() as session:
                await repository.upsert(session, location.id, forecasts)
                await session.commit()
    except Exception:
        logger.exception("forecasts.location_failed", location_id=location.id)
        return False
    return True
