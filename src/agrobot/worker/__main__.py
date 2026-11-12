import argparse
import asyncio
import signal
from collections.abc import Callable, Mapping, Sequence
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.core.config import Settings, get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.logging import configure_logging
from agrobot.forecasts.provider import FakeWeatherProvider
from agrobot.forecasts.service import ingest
from agrobot.notifications.sender import FakeNotificationSender
from agrobot.notifications.service import evaluate, notify
from agrobot.worker.runner import Job, PeriodicRunner

JobFactory = Callable[[Settings, async_sessionmaker[AsyncSession]], Job]
Interval = Callable[[Settings], float]

Jobs = Mapping[str, tuple[JobFactory, Interval]]

JOBS: Jobs = {
    "ingest": (
        lambda settings, session_factory: partial(
            ingest,
            session_factory,
            FakeWeatherProvider(),
            concurrency=settings.ingest_concurrency,
            timeout_seconds=settings.provider_timeout_seconds,
        ),
        lambda settings: settings.ingest_interval_seconds,
    ),
    "evaluate": (
        lambda _, session_factory: partial(evaluate, session_factory),
        lambda settings: settings.evaluate_interval_seconds,
    ),
    "notify": (
        lambda settings, session_factory: partial(
            notify,
            session_factory,
            FakeNotificationSender(),
            batch_size=settings.notify_batch_size,
            max_attempts=settings.notify_max_attempts,
            timeout_seconds=settings.send_timeout_seconds,
        ),
        lambda settings: settings.notify_interval_seconds,
    ),
}


def parse_job(argv: Sequence[str] | None = None, jobs: Jobs = JOBS) -> str:
    parser = argparse.ArgumentParser(prog="python -m agrobot.worker")
    parser.add_argument("job", choices=jobs)
    job: str = parser.parse_args(argv).job
    return job


async def main(job: str, settings: Settings, jobs: Jobs = JOBS) -> None:
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_engine(settings)
    build_job, interval = jobs[job]
    runner = PeriodicRunner(
        build_job(settings, create_session_factory(engine)), interval_seconds=interval(settings)
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
    asyncio.run(main(parse_job(), get_settings()))
