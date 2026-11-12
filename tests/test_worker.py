import asyncio

import pytest

from agrobot.worker.__main__ import parse_job
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


def test_ingest_is_a_known_job() -> None:
    assert parse_job(["ingest"]) == "ingest"


@pytest.mark.parametrize("argv", [[], ["bogus"]])
def test_unknown_or_missing_job_fails(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_job(argv)

    assert exc_info.value.code == 2
