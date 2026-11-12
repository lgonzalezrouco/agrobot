import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

Job = Callable[[], Awaitable[None]]


class PeriodicRunner:
    def __init__(self, job: Job, *, interval_seconds: float) -> None:
        self._job = job
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> None:
        try:
            await self._job()
        except Exception:
            logger.exception("worker.iteration_failed")

    async def run(self) -> None:
        logger.info("worker.started", interval_seconds=self._interval_seconds)
        while not self._stop_event.is_set():
            await self.run_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
        logger.info("worker.stopped")
