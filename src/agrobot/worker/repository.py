from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.worker.models import JobRun


async def record(session_factory: async_sessionmaker[AsyncSession], run: JobRun) -> None:
    statement = insert(JobRun).values(
        job=run.job,
        started_at=run.started_at,
        finished_at=run.finished_at,
        outcome=run.outcome,
        duration_seconds=run.duration_seconds,
        counters=run.counters,
        last_succeeded_at=run.last_succeeded_at,
    )
    async with session_factory() as session:
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[JobRun.job],
                set_={
                    "started_at": statement.excluded.started_at,
                    "finished_at": statement.excluded.finished_at,
                    "outcome": statement.excluded.outcome,
                    "duration_seconds": statement.excluded.duration_seconds,
                    "counters": statement.excluded.counters,
                    "last_succeeded_at": func.coalesce(
                        statement.excluded.last_succeeded_at, JobRun.last_succeeded_at
                    ),
                    "updated_at": func.now(),
                },
            )
        )
        await session.commit()


async def last_succeeded_at(session: AsyncSession, job: str) -> datetime | None:
    return await session.scalar(select(JobRun.last_succeeded_at).where(JobRun.job == job))
