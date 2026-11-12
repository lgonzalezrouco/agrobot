import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from agrobot.core.db import create_session_factory
from agrobot.worker.jobs import heartbeat
from agrobot.worker.runner import PeriodicRunner


async def test_run_once_executes_the_job() -> None:
    calls = 0

    async def job() -> None:
        nonlocal calls
        calls += 1

    await PeriodicRunner(job, interval_seconds=60).run_once()

    assert calls == 1


async def test_failing_iteration_does_not_crash_the_runner() -> None:
    async def job() -> None:
        raise RuntimeError("boom")

    await PeriodicRunner(job, interval_seconds=60).run_once()


async def test_stop_interrupts_the_wait_between_iterations() -> None:
    started = asyncio.Event()

    async def job() -> None:
        started.set()

    runner = PeriodicRunner(job, interval_seconds=3600)
    task = asyncio.create_task(runner.run())
    await started.wait()

    runner.stop()

    await asyncio.wait_for(task, timeout=1)


async def test_heartbeat_reaches_the_database(engine: AsyncEngine) -> None:
    await heartbeat(create_session_factory(engine))
