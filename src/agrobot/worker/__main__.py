import argparse
import asyncio
import signal
from collections.abc import Sequence
from functools import partial

from agrobot.core.config import get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.logging import configure_logging
from agrobot.forecasts.provider import FakeWeatherProvider
from agrobot.forecasts.service import ingest
from agrobot.worker.runner import PeriodicRunner

JOBS = ("ingest",)


def parse_job(argv: Sequence[str] | None = None) -> str:
    parser = argparse.ArgumentParser(prog="python -m agrobot.worker")
    parser.add_argument("job", choices=JOBS)
    job: str = parser.parse_args(argv).job
    return job


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    runner = PeriodicRunner(
        partial(ingest, session_factory, FakeWeatherProvider()),
        interval_seconds=settings.ingest_interval_seconds,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.stop)

    try:
        await runner.run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parse_job()
    asyncio.run(main())
