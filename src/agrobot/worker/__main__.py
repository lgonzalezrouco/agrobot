import asyncio
import signal
from functools import partial

from agrobot.core.config import get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.logging import configure_logging
from agrobot.worker.jobs import heartbeat
from agrobot.worker.runner import PeriodicRunner


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    runner = PeriodicRunner(
        partial(heartbeat, session_factory),
        interval_seconds=settings.worker_interval_seconds,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.stop)

    try:
        await runner.run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
