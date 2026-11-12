import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agrobot.alerts.models import Alert
from agrobot.fields.models import Field
from agrobot.forecasts import repository as forecasts
from agrobot.forecasts.provider import ProviderForecast
from agrobot.locations import service as locations
from agrobot.notifications import repository
from agrobot.notifications import service as notifications
from agrobot.notifications.models import Notification, NotificationStatus
from agrobot.users.models import User
from agrobot.weather import WeatherEventType
from tests.conftest import create_field

SessionFactory = async_sessionmaker[AsyncSession]
FROST = WeatherEventType.FROST


def _day(offset: int) -> date:
    return datetime.now(UTC).date() + timedelta(days=offset)


async def _create_alert(
    session_factory: SessionFactory,
    threshold: int,
    *,
    weather_event_type: WeatherEventType = FROST,
    latitude: float = 1,
    longitude: float = 1,
    active: bool = True,
) -> Alert:
    field = await create_field(session_factory, latitude, longitude)
    async with session_factory() as session:
        alert = Alert(
            field_id=field.id,
            weather_event_type=weather_event_type,
            threshold=threshold,
            active=active,
        )
        session.add(alert)
        await session.commit()
        return alert


async def _update_alert(session_factory: SessionFactory, alert: Alert, **values: object) -> None:
    async with session_factory() as session:
        await session.execute(update(Alert).where(Alert.id == alert.id).values(**values))
        await session.commit()


async def _forecast(
    session_factory: SessionFactory,
    probability: int,
    *,
    day: date | None = None,
    weather_event_type: WeatherEventType = FROST,
    latitude: float = 1,
    longitude: float = 1,
) -> None:
    async with session_factory() as session:
        location = await locations.get_or_create(session, latitude, longitude)
        await forecasts.upsert(
            session,
            location.id,
            [ProviderForecast(weather_event_type, day or _day(1), probability)],
        )
        await session.commit()


async def _notified(session_factory: SessionFactory, alert: Alert) -> dict[date, tuple[int, int]]:
    async with session_factory() as session:
        stored = await repository.list_for_alert(session, alert.id)
    return {n.day: (n.probability, n.threshold) for n in stored}


@pytest.mark.parametrize(
    ("probability", "expected"),
    [(60, {(60, 60)}), (61, {(61, 60)}), (59, set())],
    ids=["equal", "above", "below"],
)
async def test_alert_fires_at_or_above_its_threshold_never_below(
    committed_session_factory: SessionFactory, probability: int, expected: set[tuple[int, int]]
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=60)
    await _forecast(committed_session_factory, probability)

    await notifications.evaluate(committed_session_factory)

    assert set((await _notified(committed_session_factory, alert)).values()) == expected


async def test_each_day_at_or_above_threshold_gets_its_own_notification_from_today_on(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    for offset, probability in [(-1, 90), (0, 70), (1, 40), (2, 50), (6, 80)]:
        await _forecast(committed_session_factory, probability, day=_day(offset))

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {
        _day(0): (70, 50),
        _day(2): (50, 50),
        _day(6): (80, 50),
    }


async def test_paused_alert_produces_no_notification(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=10, active=False)
    await _forecast(committed_session_factory, 90)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {}


async def test_forecast_for_another_weather_event_type_or_location_produces_nothing(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=10)
    await _create_alert(committed_session_factory, threshold=100, latitude=2, longitude=2)
    await _forecast(committed_session_factory, 90, weather_event_type=WeatherEventType.RAIN)
    await _forecast(committed_session_factory, 90, latitude=2, longitude=2)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {}


async def test_alerts_on_fields_sharing_a_location_each_get_notifications(
    committed_session_factory: SessionFactory,
) -> None:
    first = await _create_alert(committed_session_factory, threshold=40, latitude=1.01)
    second = await _create_alert(committed_session_factory, threshold=60, latitude=1.02)
    await _forecast(committed_session_factory, 70)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, first) == {_day(1): (70, 40)}
    assert await _notified(committed_session_factory, second) == {_day(1): (70, 60)}


async def test_second_run_keeps_the_original_notification_after_changes(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60)
    await notifications.evaluate(committed_session_factory)
    await _forecast(committed_session_factory, 95)
    await _update_alert(committed_session_factory, alert, threshold=20)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {_day(1): (60, 50)}


async def test_lowering_threshold_fires_for_days_not_yet_notified(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=80)
    await _forecast(committed_session_factory, 90, day=_day(1))
    await _forecast(committed_session_factory, 60, day=_day(2))
    await notifications.evaluate(committed_session_factory)
    await _update_alert(committed_session_factory, alert, threshold=50)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {
        _day(1): (90, 80),
        _day(2): (60, 50),
    }


async def test_resumed_alert_fires_on_the_next_run(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50, active=False)
    await _forecast(committed_session_factory, 60)
    await notifications.evaluate(committed_session_factory)
    await _update_alert(committed_session_factory, alert, active=True)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {_day(1): (60, 50)}


async def test_new_alert_fires_on_the_next_run_for_existing_forecasts(
    committed_session_factory: SessionFactory,
) -> None:
    await _forecast(committed_session_factory, 60)
    await notifications.evaluate(committed_session_factory)
    alert = await _create_alert(committed_session_factory, threshold=50)

    await notifications.evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {_day(1): (60, 50)}


async def test_concurrent_runs_create_each_notification_once(
    committed_session_factory: SessionFactory,
) -> None:
    alerts = [
        await _create_alert(committed_session_factory, threshold=10, latitude=n) for n in range(5)
    ]
    for n in range(5):
        for offset in range(7):
            await _forecast(committed_session_factory, 50, day=_day(offset), latitude=n)

    await asyncio.gather(*(notifications.evaluate(committed_session_factory) for _ in range(4)))

    for alert in alerts:
        assert len(await _notified(committed_session_factory, alert)) == 7


@pytest.mark.parametrize("deleted", [Alert, Field, User])
async def test_deleting_alert_field_or_user_deletes_its_notifications(
    committed_session_factory: SessionFactory, deleted: type[Alert | Field | User]
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=10)
    await _forecast(committed_session_factory, 50)
    await notifications.evaluate(committed_session_factory)
    async with committed_session_factory() as session:
        field = await session.get_one(Field, alert.field_id)
        target_id = {Alert: alert.id, Field: field.id, User: field.user_id}[deleted]
        await session.execute(delete(deleted).where(deleted.id == target_id))
        await session.commit()

    assert await _notified(committed_session_factory, alert) == {}


async def test_new_notification_is_pending_and_due_now(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60)
    before = datetime.now(UTC)

    await notifications.evaluate(committed_session_factory)

    async with committed_session_factory() as session:
        [notification] = await repository.list_for_alert(session, alert.id)
    assert notification.status == NotificationStatus.PENDING
    assert notification.attempts == 0
    assert notification.sent_at is None
    assert before <= notification.next_attempt_at <= datetime.now(UTC)


async def test_database_rejects_a_second_notification_for_the_same_alert_and_day(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    async with committed_session_factory() as session:
        session.add(Notification(alert_id=alert.id, day=_day(1), probability=60, threshold=50))
        await session.commit()
        session.add(Notification(alert_id=alert.id, day=_day(1), probability=70, threshold=50))

        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize(("probability", "threshold"), [(-1, 50), (101, 50), (60, -1), (60, 101)])
async def test_database_rejects_snapshot_outside_0_to_100(
    committed_session_factory: SessionFactory, probability: int, threshold: int
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    async with committed_session_factory() as session:
        session.add(
            Notification(
                alert_id=alert.id, day=_day(1), probability=probability, threshold=threshold
            )
        )

        with pytest.raises(IntegrityError):
            await session.commit()
