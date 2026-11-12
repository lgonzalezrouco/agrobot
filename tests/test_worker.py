import asyncio
import os
import signal
from functools import partial

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from agrobot.core.config import Settings
from agrobot.forecasts.service import ingest
from agrobot.worker.__main__ import JOBS, Jobs, main, parse_job
from agrobot.worker.runner import PeriodicRunner

SETTINGS = Settings(database_url="postgresql+asyncpg://unused/unused", log_level="WARNING")


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


def test_ingest_is_a_known_job() -> None:
    assert parse_job(["ingest"]) == "ingest"


@pytest.mark.parametrize("argv", [[], ["bogus"]])
def test_unknown_or_missing_job_fails(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_job(argv)

    assert exc_info.value.code == 2


async def test_main_runs_the_job_named_on_the_command_line() -> None:
    calls = 0

    async def stop_after_first_run() -> None:
        nonlocal calls
        calls += 1
        os.kill(os.getpid(), signal.SIGTERM)

    jobs: Jobs = {"fake": (lambda *_: stop_after_first_run, lambda _: 3600)}
    handlers_before = [signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)]

    await asyncio.wait_for(main(parse_job(["fake"], jobs), SETTINGS, jobs), timeout=5)

    assert calls == 1
    assert [signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)] == handlers_before


def test_ingest_job_uses_the_ingest_settings() -> None:
    build_job, interval = JOBS["ingest"]
    settings = SETTINGS.model_copy(update={"ingest_interval_seconds": 42, "ingest_concurrency": 3})

    job = build_job(settings, async_sessionmaker())

    assert interval(settings) == 42
    assert isinstance(job, partial)
    assert job.func is ingest
    assert job.keywords == {"concurrency": 3}
