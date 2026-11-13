import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

import structlog

from agrobot.worker.models import JobOutcome, JobRun

logger = structlog.get_logger(__name__)

Job = Callable[[], Awaitable[Mapping[str, int]]]
Record = Callable[[JobRun], Awaitable[None]]


class PeriodicRunner:
    def __init__(
        self,
        job: Job,
        *,
        name: str,
        interval_seconds: float,
        time_limit_seconds: float,
        record: Record,
    ) -> None:
        self._job = job
        self._name = name
        self._interval_seconds = interval_seconds
        self._time_limit_seconds = time_limit_seconds
        self._record = record
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> None:
        started_at = datetime.now(UTC)
        started = time.monotonic()
        counters: Mapping[str, int] = {}
        try:
            async with asyncio.timeout(self._time_limit_seconds) as scope:
                counters = await self._job()
            outcome = JobOutcome.SUCCEEDED
        except Exception:
            if scope.expired():
                logger.warning(
                    "worker.iteration_timed_out", time_limit_seconds=self._time_limit_seconds
                )
                outcome = JobOutcome.TIMED_OUT
            else:
                logger.exception("worker.iteration_failed")
                outcome = JobOutcome.FAILED
        finished_at = datetime.now(UTC)
        run = JobRun(
            job=self._name,
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome,
            duration_seconds=time.monotonic() - started,
            counters=dict(counters),
            last_succeeded_at=finished_at if outcome == JobOutcome.SUCCEEDED else None,
        )
        try:
            await self._record(run)
        except Exception:
            logger.exception("worker.record_failed", job=self._name)

    async def run(self) -> None:
        logger.info("worker.started", job=self._name, interval_seconds=self._interval_seconds)
        while not self._stop_event.is_set():
            await self.run_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
        logger.info("worker.stopped", job=self._name)
