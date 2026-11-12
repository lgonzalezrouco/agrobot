import asyncio
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.alerts.models import Alert
from agrobot.forecasts import repository
from agrobot.forecasts import service as forecasts
from agrobot.forecasts.models import Forecast
from agrobot.forecasts.provider import FakeWeatherProvider, ProviderForecast
from agrobot.locations import service as locations
from agrobot.locations.models import Location
from agrobot.weather import WeatherEventType
from tests.conftest import TIMEZONE, create_field, freeze_clock, next_22h_in_buenos_aires

SessionFactory = async_sessionmaker[AsyncSession]
FORECASTS_PER_RUN = len(WeatherEventType) * forecasts.HORIZON_DAYS
CONCURRENCY = 10


class StubWeatherProvider:
    def __init__(self, probability: int = 50) -> None:
        self.probability = probability
        self.calls: list[uuid.UUID] = []
        self.omit: set[tuple[WeatherEventType, date]] = set()
        self.failing: set[uuid.UUID] = set()
        self.unstorable: set[uuid.UUID] = set()
        self.hanging: set[uuid.UUID] = set()
        self.in_flight = 0
        self.peak_in_flight = 0

    async def get_forecasts(
        self, location: Location, days: Sequence[date]
    ) -> list[ProviderForecast]:
        self.calls.append(location.id)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            if location.id in self.hanging:
                await asyncio.Event().wait()
        finally:
            self.in_flight -= 1
        if location.id in self.failing:
            raise RuntimeError("provider unavailable")
        probability = 101 if location.id in self.unstorable else self.probability
        return [
            ProviderForecast(weather_event_type, day, probability)
            for weather_event_type in WeatherEventType
            for day in days
            if (weather_event_type, day) not in self.omit
        ]


async def _ingest(
    session_factory: SessionFactory,
    provider: StubWeatherProvider,
    concurrency: int = CONCURRENCY,
    timeout_seconds: float = 10,
) -> None:
    await forecasts.ingest(
        session_factory,
        provider,
        concurrency=concurrency,
        timeout_seconds=timeout_seconds,
        timezone=TIMEZONE,
    )


def _horizon() -> list[date]:
    today = datetime.now(TIMEZONE).date()
    return [today + timedelta(days=offset) for offset in range(forecasts.HORIZON_DAYS)]


async def _create_field(
    session_factory: SessionFactory, latitude: float = 1, longitude: float = 1
) -> uuid.UUID:
    return (await create_field(session_factory, latitude, longitude)).location_id


async def _stored(
    session_factory: SessionFactory, location_id: uuid.UUID
) -> dict[tuple[WeatherEventType, date], int]:
    async with session_factory() as session:
        forecasts = await repository.list_for_location(session, location_id)
    return {(f.weather_event_type, f.day): f.probability for f in forecasts}


async def test_ingest_stores_every_weather_event_type_for_the_7_day_horizon(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    horizon = _horizon()

    await _ingest(committed_session_factory, StubWeatherProvider(probability=42))

    assert await _stored(committed_session_factory, location_id) == {
        (weather_event_type, day): 42 for weather_event_type in WeatherEventType for day in horizon
    }


async def test_ingest_horizon_starts_at_the_local_today_after_utc_midnight(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    location_id = await _create_field(committed_session_factory)
    instant = next_22h_in_buenos_aires()
    freeze_clock(monkeypatch, forecasts, instant)

    await _ingest(committed_session_factory, StubWeatherProvider())

    local_today = instant.date() - timedelta(days=1)
    assert {day for _, day in await _stored(committed_session_factory, location_id)} == {
        local_today + timedelta(days=offset) for offset in range(7)
    }


async def test_field_without_alerts_gets_forecasts(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    async with committed_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Alert)) == 0

    await _ingest(committed_session_factory, StubWeatherProvider())

    assert len(await _stored(committed_session_factory, location_id)) == FORECASTS_PER_RUN


async def test_location_without_fields_gets_no_forecasts(
    committed_session_factory: SessionFactory,
) -> None:
    async with committed_session_factory() as session:
        empty = await locations.get_or_create(session, 10, 10)
        await session.commit()
    provider = StubWeatherProvider()

    await _ingest(committed_session_factory, provider)

    assert await _stored(committed_session_factory, empty.id) == {}
    assert provider.calls == []


async def test_fields_sharing_a_location_get_one_provider_call(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory, 1.01, 1.01)
    assert await _create_field(committed_session_factory, 1.02, 1.02) == location_id
    provider = StubWeatherProvider()

    await _ingest(committed_session_factory, provider)

    assert provider.calls == [location_id]
    assert len(await _stored(committed_session_factory, location_id)) == FORECASTS_PER_RUN


async def test_second_run_overwrites_probabilities(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    await _ingest(committed_session_factory, StubWeatherProvider(probability=10))

    await _ingest(committed_session_factory, StubWeatherProvider(probability=90))

    assert set((await _stored(committed_session_factory, location_id)).values()) == {90}


async def test_forecast_omitted_by_the_provider_keeps_its_previous_value(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    omitted = (WeatherEventType.HAIL, _horizon()[3])
    await _ingest(committed_session_factory, StubWeatherProvider(probability=10))
    revised = StubWeatherProvider(probability=90)
    revised.omit.add(omitted)

    await _ingest(committed_session_factory, revised)

    stored = await _stored(committed_session_factory, location_id)
    assert stored.pop(omitted) == 10
    assert set(stored.values()) == {90}


@pytest.mark.parametrize("probability", [-1, 101])
async def test_database_rejects_probability_outside_0_to_100(
    db_session: AsyncSession, probability: int
) -> None:
    location = await locations.get_or_create(db_session, 1, 1)
    db_session.add(
        Forecast(
            location_id=location.id,
            weather_event_type=WeatherEventType.FROST,
            day=date(2026, 1, 1),
            probability=probability,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_fake_provider_is_deterministic_complete_and_in_range() -> None:
    location = Location(latitude=Decimal("-34.6"), longitude=Decimal("-58.4"))
    days = _horizon()
    provider = FakeWeatherProvider()

    first = await provider.get_forecasts(location, days)
    second = await provider.get_forecasts(location, days)

    assert first == second
    assert {(f.weather_event_type, f.day) for f in first} == {
        (weather_event_type, day) for weather_event_type in WeatherEventType for day in days
    }
    assert all(0 <= f.probability <= 100 for f in first)


async def test_duplicate_provider_forecasts_keep_the_last_value(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    day = _horizon()[0]

    async with committed_session_factory() as session:
        await repository.upsert(
            session,
            location_id,
            [
                ProviderForecast(WeatherEventType.RAIN, day, 30),
                ProviderForecast(WeatherEventType.RAIN, day, 60),
            ],
        )
        await session.commit()

    assert await _stored(committed_session_factory, location_id) == {
        (WeatherEventType.RAIN, day): 60
    }


async def test_fake_provider_depends_on_coordinate_values_not_their_spelling() -> None:
    day = _horizon()[0]
    provider = FakeWeatherProvider()

    short = await provider.get_forecasts(
        Location(latitude=Decimal("-34.6"), longitude=Decimal("-58.4")), [day]
    )
    padded = await provider.get_forecasts(
        Location(latitude=Decimal("-34.60"), longitude=Decimal("-58.40")), [day]
    )

    assert short == padded


async def test_provider_failure_for_one_location_does_not_affect_the_others(
    committed_session_factory: SessionFactory,
) -> None:
    failing_id = await _create_field(committed_session_factory, 1, 1)
    healthy_id = await _create_field(committed_session_factory, 2, 2)
    await _ingest(committed_session_factory, StubWeatherProvider(probability=10))
    flaky = StubWeatherProvider(probability=90)
    flaky.failing.add(failing_id)

    await _ingest(committed_session_factory, flaky)

    assert set((await _stored(committed_session_factory, failing_id)).values()) == {10}
    assert set((await _stored(committed_session_factory, healthy_id)).values()) == {90}
    assert sorted(flaky.calls) == sorted([failing_id, healthy_id])


async def test_provider_that_never_answers_for_one_location_does_not_affect_the_others(
    committed_session_factory: SessionFactory,
) -> None:
    hanging_id = await _create_field(committed_session_factory, 1, 1)
    healthy_id = await _create_field(committed_session_factory, 2, 2)
    await _ingest(committed_session_factory, StubWeatherProvider(probability=10))
    provider = StubWeatherProvider(probability=90)
    provider.hanging.add(hanging_id)

    with structlog.testing.capture_logs() as logs:
        await asyncio.wait_for(
            _ingest(committed_session_factory, provider, timeout_seconds=0.05), timeout=5
        )

    assert set((await _stored(committed_session_factory, hanging_id)).values()) == {10}
    assert set((await _stored(committed_session_factory, healthy_id)).values()) == {90}
    assert [log["location_id"] for log in logs if log["event"] == "forecasts.location_failed"] == [
        hanging_id
    ]
    assert [
        (log["ingested"], log["failed"]) for log in logs if log["event"] == "forecasts.ingested"
    ] == [(1, 1)]


async def test_storage_failure_for_one_location_does_not_affect_the_others(
    committed_session_factory: SessionFactory,
) -> None:
    failing_id = await _create_field(committed_session_factory, 1, 1)
    healthy_id = await _create_field(committed_session_factory, 2, 2)
    await _ingest(committed_session_factory, StubWeatherProvider(probability=10))
    corrupt = StubWeatherProvider(probability=90)
    corrupt.unstorable.add(failing_id)

    await _ingest(committed_session_factory, corrupt)

    assert set((await _stored(committed_session_factory, failing_id)).values()) == {10}
    assert set((await _stored(committed_session_factory, healthy_id)).values()) == {90}


async def test_locations_are_fetched_concurrently_up_to_the_limit(
    committed_session_factory: SessionFactory,
) -> None:
    location_ids = [await _create_field(committed_session_factory, n, n) for n in range(5)]
    provider = StubWeatherProvider()

    await _ingest(committed_session_factory, provider, concurrency=2)

    assert provider.peak_in_flight == 2
    for location_id in location_ids:
        assert len(await _stored(committed_session_factory, location_id)) == FORECASTS_PER_RUN
