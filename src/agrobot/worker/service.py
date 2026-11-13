from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.worker import repository
from agrobot.worker.models import JobRun

STALE_AFTER_RUNS = 3


async def record(session_factory: async_sessionmaker[AsyncSession], run: JobRun) -> None:
    async with session_factory() as session:
        await repository.upsert(session, run)
        await session.commit()


async def is_healthy(
    session: AsyncSession, job: str, *, interval_seconds: float, time_limit_seconds: float
) -> bool:
    max_age = timedelta(seconds=STALE_AFTER_RUNS * max(interval_seconds, time_limit_seconds))
    last_succeeded_at = await repository.last_succeeded_at(session, job)
    return last_succeeded_at is not None and datetime.now(UTC) - last_succeeded_at <= max_age
