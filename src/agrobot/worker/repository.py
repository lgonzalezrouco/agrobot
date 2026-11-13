from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.worker.models import JobRun

OVERWRITTEN = ("started_at", "finished_at", "outcome", "duration_seconds", "counters")


async def upsert(session: AsyncSession, run: JobRun) -> None:
    statement = insert(JobRun).values(
        job=run.job,
        last_succeeded_at=run.last_succeeded_at,
        **{column: getattr(run, column) for column in OVERWRITTEN},
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[JobRun.job],
            set_={
                **{column: statement.excluded[column] for column in OVERWRITTEN},
                "last_succeeded_at": func.coalesce(
                    statement.excluded.last_succeeded_at, JobRun.last_succeeded_at
                ),
                "updated_at": func.now(),
            },
        )
    )


async def last_succeeded_at(session: AsyncSession, job: str) -> datetime | None:
    return await session.scalar(select(JobRun.last_succeeded_at).where(JobRun.job == job))
