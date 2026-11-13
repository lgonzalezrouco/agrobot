import argparse
import asyncio
import signal
import sys
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.core.config import Settings, get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.logging import configure_logging
from agrobot.forecasts.provider import FakeWeatherProvider
from agrobot.forecasts.service import ingest
from agrobot.notifications.sender import FakeNotificationSender
from agrobot.notifications.service import evaluate, notify
from agrobot.worker import service as job_runs
from agrobot.worker.runner import Job, PeriodicRunner

JobFactory = Callable[[Settings, async_sessionmaker[AsyncSession]], Job]
SettingSeconds = Callable[[Settings], float]


class JobSpec(NamedTuple):
    build: JobFactory
    interval: SettingSeconds
    time_limit: SettingSeconds


Jobs = Mapping[str, JobSpec]

JOBS: Jobs = {
    "ingest": JobSpec(
        lambda settings, session_factory: partial(
            ingest,
            session_factory,
            FakeWeatherProvider(),
            concurrency=settings.ingest_concurrency,
            timeout_seconds=settings.provider_timeout_seconds,
            timezone=settings.timezone,
        ),
        lambda settings: settings.ingest_interval_seconds,
        lambda settings: settings.ingest_time_limit_seconds,
    ),
    "evaluate": JobSpec(
        lambda settings, session_factory: partial(
            evaluate,
            session_factory,
            batch_size=settings.evaluate_batch_size,
            timezone=settings.timezone,
        ),
        lambda settings: settings.evaluate_interval_seconds,
        lambda settings: settings.evaluate_time_limit_seconds,
    ),
    "notify": JobSpec(
        lambda settings, session_factory: partial(
            notify,
            session_factory,
            FakeNotificationSender(),
            batch_size=settings.notify_batch_size,
            timeout_seconds=settings.send_timeout_seconds,
            timezone=settings.timezone,
        ),
        lambda settings: settings.notify_interval_seconds,
        lambda settings: settings.notify_time_limit_seconds,
    ),
}


class Command(NamedTuple):
    job: str
    check: bool


def parse_command(argv: Sequence[str] | None = None, jobs: Jobs = JOBS) -> Command:
    parser = argparse.ArgumentParser(prog="python -m agrobot.worker")
    commands = parser.add_subparsers(dest="command", required=True)
    for job in jobs:
        commands.add_parser(job)
    commands.add_parser("check").add_argument("job", choices=jobs)
    args = parser.parse_args(argv)
    if args.command == "check":
        return Command(args.job, check=True)
    return Command(args.command, check=False)


async def check(job: str, settings: Settings, jobs: Jobs = JOBS) -> bool:
    spec = jobs[job]
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            return await job_runs.is_healthy(
                session,
                job,
                interval_seconds=spec.interval(settings),
                time_limit_seconds=spec.time_limit(settings),
            )
    finally:
        await engine.dispose()


async def main(job: str, settings: Settings, jobs: Jobs = JOBS) -> None:
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    spec = jobs[job]
    runner = PeriodicRunner(
        spec.build(settings, session_factory),
        name=job,
        interval_seconds=spec.interval(settings),
        time_limit_seconds=spec.time_limit(settings),
        record=partial(job_runs.record, session_factory),
    )

    loop = asyncio.get_running_loop()
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in previous_handlers:
        loop.add_signal_handler(sig, runner.stop)

    try:
        await runner.run()
    finally:
        for sig, handler in previous_handlers.items():
            loop.remove_signal_handler(sig)
            signal.signal(sig, handler)
        await engine.dispose()


if __name__ == "__main__":
    command = parse_command()
    if command.check:
        sys.exit(0 if asyncio.run(check(command.job, get_settings())) else 1)
    asyncio.run(main(command.job, get_settings()))
