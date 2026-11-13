import asyncio
import os
import signal
from datetime import UTC, datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo

import pytest
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.core.config import Settings, get_settings
from agrobot.forecasts.service import ingest
from agrobot.notifications.sender import FakeNotificationSender
from agrobot.notifications.service import evaluate, notify
from agrobot.worker import service as job_runs
from agrobot.worker.__main__ import JOBS, Command, Jobs, JobSpec, check, main, parse_command
from agrobot.worker.models import JobOutcome, JobRun
from agrobot.worker.runner import Job, PeriodicRunner
from tests.conftest import TIMEZONE

REQUIRED_SETTINGS = {"database_url": "postgresql+asyncpg://unused/unused"}
SETTINGS = Settings(
    database_url=REQUIRED_SETTINGS["database_url"], log_level="WARNING", _env_file=None
)


def _runner(
    job: Job, recorded: list[JobRun], time_limit_seconds: float = 60, interval_seconds: float = 3600
) -> PeriodicRunner:
    async def record(run: JobRun) -> None:
        recorded.append(run)

    return PeriodicRunner(
        job,
        name="fake",
        interval_seconds=interval_seconds,
        time_limit_seconds=time_limit_seconds,
        record=record,
    )


async def test_successful_run_is_recorded_with_its_counters() -> None:
    async def job() -> dict[str, int]:
        return {"sent": 2}

    recorded: list[JobRun] = []
    await _runner(job, recorded).run_once()

    [run] = recorded
    assert run.job == "fake"
    assert run.outcome == JobOutcome.SUCCEEDED
    assert run.counters == {"sent": 2}
    assert run.started_at <= run.finished_at
    assert run.last_succeeded_at == run.finished_at


@pytest.mark.parametrize("error", [RuntimeError("boom"), TimeoutError()])
async def test_failing_run_is_recorded_as_failed(error: Exception) -> None:
    async def job() -> dict[str, int]:
        raise error

    recorded: list[JobRun] = []
    await _runner(job, recorded).run_once()

    [run] = recorded
    assert run.outcome == JobOutcome.FAILED
    assert run.counters == {}
    assert run.last_succeeded_at is None


async def test_run_over_its_time_limit_is_cancelled_and_the_next_one_still_runs() -> None:
    calls = 0
    recorded: list[JobRun] = []

    async def job() -> dict[str, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(3600)
        runner.stop()
        return {}

    runner = _runner(job, recorded, time_limit_seconds=0.05, interval_seconds=0)
    with structlog.testing.capture_logs() as logs:
        await asyncio.wait_for(runner.run(), timeout=5)

    assert [run.outcome for run in recorded] == [JobOutcome.TIMED_OUT, JobOutcome.SUCCEEDED]
    assert "worker.iteration_timed_out" in [log["event"] for log in logs]


async def test_failing_record_does_not_fail_the_run() -> None:
    async def job() -> dict[str, int]:
        return {}

    async def record(_: JobRun) -> None:
        raise RuntimeError("database down")

    runner = PeriodicRunner(
        job, name="fake", interval_seconds=60, time_limit_seconds=60, record=record
    )
    with structlog.testing.capture_logs() as logs:
        await runner.run_once()

    assert "worker.record_failed" in [log["event"] for log in logs]


async def test_stop_interrupts_the_wait_between_iterations() -> None:
    started = asyncio.Event()

    async def job() -> dict[str, int]:
        started.set()
        return {}

    runner = _runner(job, [])
    task = asyncio.create_task(runner.run())
    await started.wait()

    runner.stop()

    await asyncio.wait_for(task, timeout=1)


@pytest.mark.parametrize("job", ["ingest", "evaluate", "notify"])
def test_known_jobs_are_accepted(job: str) -> None:
    assert parse_command([job]) == Command(job, check=False)
    assert parse_command(["check", job]) == Command(job, check=True)


@pytest.mark.parametrize("argv", [[], ["bogus"], ["check"], ["check", "bogus"]])
def test_unknown_or_missing_job_fails(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_command(argv)

    assert exc_info.value.code == 2


FAKE_JOBS: Jobs = {"fake": JobSpec(lambda *_: _no_counters, lambda _: 60, lambda _: 100)}
STALE_AFTER = timedelta(seconds=job_runs.STALE_AFTER_RUNS * 100)


async def _no_counters() -> dict[str, int]:
    return {}


async def _record(
    session_factory: async_sessionmaker[AsyncSession], outcome: JobOutcome, finished_at: datetime
) -> None:
    await job_runs.record(
        session_factory,
        JobRun(
            job="fake",
            started_at=finished_at,
            finished_at=finished_at,
            outcome=outcome,
            duration_seconds=0,
            counters={},
            last_succeeded_at=finished_at if outcome == JobOutcome.SUCCEEDED else None,
        ),
    )


async def test_check_passes_for_a_fresh_success(
    settings: Settings, committed_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _record(committed_session_factory, JobOutcome.SUCCEEDED, datetime.now(UTC))

    assert await check("fake", settings, FAKE_JOBS)


async def test_check_fails_for_a_stale_success(
    settings: Settings, committed_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    stale = datetime.now(UTC) - STALE_AFTER - timedelta(seconds=1)
    await _record(committed_session_factory, JobOutcome.SUCCEEDED, stale)

    assert not await check("fake", settings, FAKE_JOBS)


async def test_check_fails_when_the_job_never_succeeded(
    settings: Settings, committed_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert not await check("fake", settings, FAKE_JOBS)

    await _record(committed_session_factory, JobOutcome.FAILED, datetime.now(UTC))

    assert not await check("fake", settings, FAKE_JOBS)


async def test_failed_run_keeps_the_last_success(
    settings: Settings, committed_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _record(committed_session_factory, JobOutcome.SUCCEEDED, datetime.now(UTC))
    await _record(committed_session_factory, JobOutcome.TIMED_OUT, datetime.now(UTC))

    assert await check("fake", settings, FAKE_JOBS)


async def test_main_runs_the_job_named_on_the_command_line_and_records_it(
    settings: Settings, committed_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    calls = 0

    async def stop_after_first_run() -> dict[str, int]:
        nonlocal calls
        calls += 1
        os.kill(os.getpid(), signal.SIGTERM)
        return {"sent": 1}

    jobs: Jobs = {"fake": JobSpec(lambda *_: stop_after_first_run, lambda _: 3600, lambda _: 60)}
    handlers_before = [signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)]

    await asyncio.wait_for(main(parse_command(["fake"], jobs).job, settings, jobs), timeout=5)

    assert calls == 1
    assert [signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)] == handlers_before
    assert await check("fake", settings, jobs)


def test_ingest_job_uses_the_ingest_settings() -> None:
    build_job, interval, _ = JOBS["ingest"]
    settings = SETTINGS.model_copy(update={"ingest_interval_seconds": 42, "ingest_concurrency": 3})

    job = build_job(settings, async_sessionmaker())

    assert interval(settings) == 42
    assert isinstance(job, partial)
    assert job.func is ingest
    assert job.keywords == {
        "concurrency": 3,
        "timeout_seconds": 10,
        "timezone": TIMEZONE,
    }


def test_evaluate_job_uses_the_evaluate_interval() -> None:
    build_job, interval, _ = JOBS["evaluate"]
    settings = SETTINGS.model_copy(update={"evaluate_interval_seconds": 7})
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker()

    job = build_job(settings, session_factory)

    assert interval(settings) == 7
    assert isinstance(job, partial)
    assert job.func is evaluate
    assert job.args == (session_factory,)
    assert job.keywords == {"batch_size": settings.evaluate_batch_size, "timezone": TIMEZONE}


@pytest.mark.parametrize("value", [0, -1])
def test_evaluate_interval_must_be_positive(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({**REQUIRED_SETTINGS, "evaluate_interval_seconds": value})


def test_evaluate_interval_defaults_to_5_minutes() -> None:
    assert SETTINGS.evaluate_interval_seconds == 300


def test_notify_job_uses_the_fake_sender_and_notify_settings() -> None:
    build_job, interval, _ = JOBS["notify"]
    settings = SETTINGS.model_copy(update={"notify_interval_seconds": 9, "notify_batch_size": 4})
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker()

    job = build_job(settings, session_factory)

    assert interval(settings) == 9
    assert isinstance(job, partial)
    assert job.func is notify
    assert job.args[0] is session_factory
    assert isinstance(job.args[1], FakeNotificationSender)
    assert job.keywords == {
        "batch_size": 4,
        "timeout_seconds": 10,
        "timezone": TIMEZONE,
    }


@pytest.mark.parametrize("setting", ["notify_interval_seconds", "notify_batch_size"])
@pytest.mark.parametrize("value", [0, -1])
def test_notify_settings_must_be_positive(setting: str, value: int) -> None:
    with pytest.raises(ValidationError, match=setting):
        Settings.model_validate({**REQUIRED_SETTINGS, setting: value})


def test_notify_settings_default_to_30_seconds_and_100_per_batch() -> None:
    assert SETTINGS.notify_interval_seconds == 30
    assert SETTINGS.notify_batch_size == 100


@pytest.mark.parametrize("setting", ["provider_timeout_seconds", "send_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1])
def test_timeouts_must_be_positive(setting: str, value: float) -> None:
    with pytest.raises(ValidationError, match=setting):
        Settings.model_validate({**REQUIRED_SETTINGS, setting: value})


def test_timeouts_default_to_10_seconds() -> None:
    assert SETTINGS.provider_timeout_seconds == 10
    assert SETTINGS.send_timeout_seconds == 10


def test_timezone_defaults_to_buenos_aires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIMEZONE", raising=False)

    settings = Settings(database_url=REQUIRED_SETTINGS["database_url"], _env_file=None)

    assert settings.timezone == ZoneInfo("America/Argentina/Buenos_Aires")


def test_invalid_timezone_env_var_fails_loading_startup_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in REQUIRED_SETTINGS.items():
        monkeypatch.setenv(name.upper(), value)
    monkeypatch.setenv("TIMEZONE", "Mars/Olympus_Mons")
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="invalid timezone: Mars/Olympus_Mons"):
        get_settings()

    get_settings.cache_clear()
