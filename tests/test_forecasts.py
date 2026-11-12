import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.fields.models import Field
from agrobot.forecasts import repository
from agrobot.forecasts import service as ingestion
from agrobot.forecasts.models import Forecast
from agrobot.forecasts.provider import FakeWeatherProvider, ProviderForecast
from agrobot.locations import service as locations
from agrobot.locations.models import Location
from agrobot.users.models import User
from agrobot.weather import WeatherEventType

SessionFactory = async_sessionmaker[AsyncSession]


class StubWeatherProvider:
    def __init__(self, probability: int = 50) -> None:
        self.probability = probability
        self.calls: list[uuid.UUID] = []
        self.omit: set[tuple[WeatherEventType, date]] = set()

    async def get_forecasts(
        self, location: Location, days: Sequence[date]
    ) -> list[ProviderForecast]:
        self.calls.append(location.id)
        return [
            ProviderForecast(weather_event_type, day, self.probability)
            for weather_event_type in WeatherEventType
            for day in days
            if (weather_event_type, day) not in self.omit
        ]


def _horizon() -> list[date]:
    today = datetime.now(UTC).date()
    return [today + timedelta(days=offset) for offset in range(ingestion.HORIZON_DAYS)]


async def _create_field(
    session_factory: SessionFactory, latitude: float = 1, longitude: float = 1
) -> uuid.UUID:
    async with session_factory() as session:
        user = User(name="Ana", phone_number=f"+549{uuid.uuid4().int % 10**10:010d}")
        location = await locations.get_or_create(session, latitude, longitude)
        session.add(user)
        await session.flush()
        session.add(
            Field(
                user_id=user.id,
                name="Lote",
                latitude=latitude,
                longitude=longitude,
                location=location,
            )
        )
        await session.commit()
        return location.id


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

    await ingestion.ingest(committed_session_factory, StubWeatherProvider(probability=42))

    assert await _stored(committed_session_factory, location_id) == {
        (weather_event_type, day): 42
        for weather_event_type in WeatherEventType
        for day in _horizon()
    }


async def test_location_without_fields_gets_no_forecasts(
    committed_session_factory: SessionFactory,
) -> None:
    async with committed_session_factory() as session:
        empty = await locations.get_or_create(session, 10, 10)
        await session.commit()
    provider = StubWeatherProvider()

    await ingestion.ingest(committed_session_factory, provider)

    assert await _stored(committed_session_factory, empty.id) == {}
    assert provider.calls == []


async def test_fields_sharing_a_location_get_one_provider_call(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory, 1.01, 1.01)
    assert await _create_field(committed_session_factory, 1.02, 1.02) == location_id
    provider = StubWeatherProvider()

    await ingestion.ingest(committed_session_factory, provider)

    assert provider.calls == [location_id]
    assert len(await _stored(committed_session_factory, location_id)) == 35


async def test_second_run_overwrites_probabilities(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    await ingestion.ingest(committed_session_factory, StubWeatherProvider(probability=10))

    await ingestion.ingest(committed_session_factory, StubWeatherProvider(probability=90))

    assert set((await _stored(committed_session_factory, location_id)).values()) == {90}


async def test_forecast_omitted_by_the_provider_keeps_its_previous_value(
    committed_session_factory: SessionFactory,
) -> None:
    location_id = await _create_field(committed_session_factory)
    await ingestion.ingest(committed_session_factory, StubWeatherProvider(probability=10))
    revised = StubWeatherProvider(probability=90)
    omitted = (WeatherEventType.HAIL, _horizon()[3])
    revised.omit.add(omitted)

    await ingestion.ingest(committed_session_factory, revised)

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
