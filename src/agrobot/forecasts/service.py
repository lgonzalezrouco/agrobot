import asyncio
from datetime import UTC, datetime, timedelta

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
    timeout_seconds: float,
) -> None:
    today = datetime.now(UTC).date()
    days = [today + timedelta(days=offset) for offset in range(HORIZON_DAYS)]
    async with session_factory() as session:
        targets = await locations.list_with_fields(session)
    semaphore = asyncio.Semaphore(concurrency)

    async def ingest_location(location: Location) -> bool:
        try:
            async with semaphore:
                async with asyncio.timeout(timeout_seconds):
                    forecasts = await provider.get_forecasts(location, days)
                async with session_factory() as session:
                    await repository.upsert(session, location.id, forecasts)
                    await session.commit()
        except Exception:
            logger.exception("forecasts.location_failed", location_id=location.id)
            return False
        return True

    results = await asyncio.gather(*(ingest_location(location) for location in targets))
    ingested = sum(results)
    logger.info("forecasts.ingested", ingested=ingested, failed=len(results) - ingested)
