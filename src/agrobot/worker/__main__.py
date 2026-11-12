import argparse
import asyncio
import signal
from collections.abc import Callable, Sequence
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.core.config import Settings, get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.logging import configure_logging
from agrobot.forecasts.provider import FakeWeatherProvider
from agrobot.forecasts.service import ingest
from agrobot.worker.runner import Job, PeriodicRunner

JobFactory = Callable[[Settings, async_sessionmaker[AsyncSession]], Job]
Interval = Callable[[Settings], float]

JOBS: dict[str, tuple[JobFactory, Interval]] = {
    "ingest": (
        lambda settings, session_factory: partial(
            ingest, session_factory, FakeWeatherProvider(), concurrency=settings.ingest_concurrency
        ),
        lambda settings: settings.ingest_interval_seconds,
    ),
}


def parse_job(argv: Sequence[str] | None = None) -> str:
    parser = argparse.ArgumentParser(prog="python -m agrobot.worker")
    parser.add_argument("job", choices=JOBS)
    job: str = parser.parse_args(argv).job
    return job


async def main(job: str, settings: Settings) -> None:
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_engine(settings)
    build_job, interval = JOBS[job]
    runner = PeriodicRunner(
        build_job(settings, create_session_factory(engine)), interval_seconds=interval(settings)
    )

    loop = asyncio.get_running_loop()
    signals = (signal.SIGTERM, signal.SIGINT)
    for sig in signals:
        loop.add_signal_handler(sig, runner.stop)

    try:
        await runner.run()
    finally:
        for sig in signals:
            loop.remove_signal_handler(sig)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(parse_job(), get_settings()))
