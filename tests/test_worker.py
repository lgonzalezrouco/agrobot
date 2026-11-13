import asyncio
import os
import signal
from functools import partial
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.core.config import Settings, get_settings
from agrobot.forecasts.service import ingest
from agrobot.notifications.sender import FakeNotificationSender
from agrobot.notifications.service import evaluate, notify
from agrobot.worker.__main__ import JOBS, Jobs, main, parse_job
from agrobot.worker.runner import PeriodicRunner
from tests.conftest import TIMEZONE

REQUIRED_SETTINGS = {"database_url": "postgresql+asyncpg://unused/unused"}
SETTINGS = Settings.model_validate({**REQUIRED_SETTINGS, "log_level": "WARNING"})


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


@pytest.mark.parametrize("job", ["ingest", "evaluate", "notify"])
def test_known_jobs_are_accepted(job: str) -> None:
    assert parse_job([job]) == job


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
    assert job.keywords == {
        "concurrency": 3,
        "timeout_seconds": 10,
        "timezone": TIMEZONE,
    }


def test_evaluate_job_uses_the_evaluate_interval() -> None:
    build_job, interval = JOBS["evaluate"]
    settings = SETTINGS.model_copy(update={"evaluate_interval_seconds": 7})
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker()

    job = build_job(settings, session_factory)

    assert interval(settings) == 7
    assert isinstance(job, partial)
    assert job.func is evaluate
    assert job.args == (session_factory,)
    assert job.keywords == {"batch_size": 200, "timezone": TIMEZONE}


@pytest.mark.parametrize("value", [0, -1])
def test_evaluate_interval_must_be_positive(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({**REQUIRED_SETTINGS, "evaluate_interval_seconds": value})


def test_evaluate_interval_defaults_to_5_minutes() -> None:
    assert SETTINGS.evaluate_interval_seconds == 300


def test_notify_job_uses_the_fake_sender_and_notify_settings() -> None:
    build_job, interval = JOBS["notify"]
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
