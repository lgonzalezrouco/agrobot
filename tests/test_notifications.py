import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import structlog
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agrobot.alerts import service as alerts
from agrobot.alerts.models import Alert
from agrobot.fields import service as fields
from agrobot.fields.models import Field
from agrobot.forecasts import repository as forecasts
from agrobot.forecasts.provider import ProviderForecast
from agrobot.locations import service as locations
from agrobot.notifications import models as notification_models
from agrobot.notifications import repository
from agrobot.notifications import service as notifications
from agrobot.notifications.models import Notification, NotificationStatus
from agrobot.notifications.sender import (
    FakeNotificationSender,
    NotificationContent,
    PermanentDeliveryError,
)
from agrobot.users.models import User
from agrobot.weather import WeatherEventType
from tests.conftest import (
    TIMEZONE,
    create_field,
    freeze_clock,
    local_evening_after_utc_midnight,
    wait_until_blocked,
)

SessionFactory = async_sessionmaker[AsyncSession]
FROST = WeatherEventType.FROST
BATCH_SIZE = 100
TIMEOUT_SECONDS = 10.0


def _day(offset: int) -> date:
    return datetime.now(TIMEZONE).date() + timedelta(days=offset)


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


async def _evaluate(session_factory: SessionFactory) -> None:
    await notifications.evaluate(session_factory, timezone=TIMEZONE)


async def _notified(session_factory: SessionFactory, alert: Alert) -> dict[date, tuple[int, int]]:
    async with session_factory() as session:
        stored = await repository.list_for_alert(session, alert.id)
    return {n.day: (n.probability, n.threshold) for n in stored}


async def test_each_day_at_or_above_threshold_gets_its_own_notification_from_today_on(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    for offset, probability in [(-1, 90), (0, 70), (1, 40), (2, 50), (6, 80)]:
        await _forecast(committed_session_factory, probability, day=_day(offset))

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {
        _day(0): (70, 50),
        _day(2): (50, 50),
        _day(6): (80, 50),
    }


async def test_forecast_for_the_local_today_fires_after_utc_midnight(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    instant, local_today = local_evening_after_utc_midnight()
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 70, day=local_today)
    freeze_clock(monkeypatch, notifications, instant)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {local_today: (70, 50)}


async def test_paused_alert_produces_no_notification(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=10, active=False)
    await _forecast(committed_session_factory, 90)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {}


async def test_forecast_for_another_weather_event_type_or_location_produces_nothing(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=10)
    await _create_alert(committed_session_factory, threshold=100, latitude=2, longitude=2)
    await _forecast(committed_session_factory, 90, weather_event_type=WeatherEventType.RAIN)
    await _forecast(committed_session_factory, 90, latitude=2, longitude=2)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {}


async def test_alerts_on_fields_sharing_a_location_each_get_notifications(
    committed_session_factory: SessionFactory,
) -> None:
    first = await _create_alert(committed_session_factory, threshold=40, latitude=1.01)
    second = await _create_alert(committed_session_factory, threshold=60, latitude=1.02)
    await _forecast(committed_session_factory, 70)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, first) == {_day(1): (70, 40)}
    assert await _notified(committed_session_factory, second) == {_day(1): (70, 60)}


async def test_second_run_keeps_the_original_notification_after_changes(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60)
    await _evaluate(committed_session_factory)
    await _forecast(committed_session_factory, 95)
    await _update_alert(committed_session_factory, alert, threshold=20)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {_day(1): (60, 50)}


async def test_lowering_threshold_fires_for_days_not_yet_notified(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=80)
    await _forecast(committed_session_factory, 90, day=_day(1))
    await _forecast(committed_session_factory, 60, day=_day(2))
    await _evaluate(committed_session_factory)
    await _update_alert(committed_session_factory, alert, threshold=50)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {
        _day(1): (90, 80),
        _day(2): (60, 50),
    }


async def test_resumed_alert_fires_on_the_next_run(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50, active=False)
    await _forecast(committed_session_factory, 60)
    await _evaluate(committed_session_factory)
    await _update_alert(committed_session_factory, alert, active=True)

    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {_day(1): (60, 50)}


async def test_new_alert_fires_on_the_next_run_for_existing_forecasts(
    committed_session_factory: SessionFactory,
) -> None:
    await _forecast(committed_session_factory, 60)
    await _evaluate(committed_session_factory)
    alert = await _create_alert(committed_session_factory, threshold=50)

    await _evaluate(committed_session_factory)

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

    await asyncio.gather(*(_evaluate(committed_session_factory) for _ in range(4)))

    for alert in alerts:
        assert len(await _notified(committed_session_factory, alert)) == 7


@pytest.mark.parametrize("deleted", [Alert, Field, User])
async def test_deleting_alert_field_or_user_deletes_its_notifications(
    committed_session_factory: SessionFactory, deleted: type[Alert | Field | User]
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=10)
    await _forecast(committed_session_factory, 50)
    await _evaluate(committed_session_factory)
    async with committed_session_factory() as session:
        field = await session.get_one(Field, alert.field_id)
        target_id = {Alert: alert.id, Field: field.id, User: field.user_id}[deleted]
        await session.execute(delete(deleted).where(deleted.id == target_id))
        await session.commit()

    assert await _notified(committed_session_factory, alert) == {}


async def _update_field(
    session_factory: SessionFactory,
    alert: Alert,
    latitude: float | None = None,
    name: str | None = None,
) -> None:
    async with session_factory() as session:
        await fields.update(session, alert.field_id, name, latitude, None)


async def test_moving_field_to_another_location_deletes_only_its_pending_notifications(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    other = await _create_alert(committed_session_factory, threshold=50)
    statuses = list(NotificationStatus)
    async with committed_session_factory() as session:
        for offset, status in enumerate(statuses, start=1):
            session.add(
                Notification(
                    alert_id=alert.id, day=_day(offset), probability=60, threshold=50, status=status
                )
            )
        session.add(Notification(alert_id=other.id, day=_day(1), probability=60, threshold=50))
        await session.commit()

    await _update_field(committed_session_factory, alert, latitude=5)

    assert set(await _notified(committed_session_factory, alert)) == {
        _day(offset)
        for offset, status in enumerate(statuses, start=1)
        if status != NotificationStatus.PENDING
    }
    assert set(await _notified(committed_session_factory, other)) == {_day(1)}


@pytest.mark.parametrize(
    ("latitude", "name"), [(None, "Renamed"), (1.04, None)], ids=["rename", "same-location"]
)
async def test_renaming_field_or_moving_it_within_its_location_keeps_pending_notifications(
    committed_session_factory: SessionFactory, latitude: float | None, name: str | None
) -> None:
    alert = await _pending(committed_session_factory)

    await _update_field(committed_session_factory, alert, latitude=latitude, name=name)

    assert await _status(committed_session_factory, alert) == NotificationStatus.PENDING


async def test_after_a_move_evaluate_notifies_days_not_yet_notified_from_the_new_location(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60, day=_day(1))
    await _forecast(committed_session_factory, 60, day=_day(2))
    await _evaluate(committed_session_factory)
    await _update_notification(committed_session_factory, alert, status=NotificationStatus.SENT)
    await _forecast(committed_session_factory, 60, day=_day(3))
    await _evaluate(committed_session_factory)
    for offset, probability in [(1, 90), (2, 80), (3, 70), (4, 40)]:
        await _forecast(committed_session_factory, probability, day=_day(offset), latitude=5)

    await _update_field(committed_session_factory, alert, latitude=5)
    await _evaluate(committed_session_factory)

    assert await _notified(committed_session_factory, alert) == {
        _day(1): (60, 50),
        _day(2): (60, 50),
        _day(3): (70, 50),
    }


async def test_evaluate_overlapping_a_move_waits_and_skips_the_old_location(
    committed_session_factory: SessionFactory, engine: AsyncEngine
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60)
    async with committed_session_factory() as moving:
        field = (
            await moving.scalars(
                select(Field).where(Field.id == alert.field_id).with_for_update(of=Field)
            )
        ).one()
        field.location = await locations.get_or_create(moving, 5, 1)
        await moving.flush()
        evaluating = asyncio.create_task(_evaluate(committed_session_factory))
        await wait_until_blocked(engine)
        await moving.commit()
    await asyncio.wait_for(evaluating, timeout=5)

    assert await _notified(committed_session_factory, alert) == {}


async def test_move_overlapping_evaluate_waits_and_deletes_what_it_created(
    committed_session_factory: SessionFactory, engine: AsyncEngine
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    async with committed_session_factory() as evaluating:
        await evaluating.execute(
            select(Field).where(Field.id == alert.field_id).with_for_update(read=True, of=Field)
        )
        evaluating.add(Notification(alert_id=alert.id, day=_day(1), probability=60, threshold=50))
        await evaluating.flush()
        moving = asyncio.create_task(_update_field(committed_session_factory, alert, latitude=5))
        await wait_until_blocked(engine)
        await evaluating.commit()
    await asyncio.wait_for(moving, timeout=5)

    assert await _notified(committed_session_factory, alert) == {}


async def test_evaluate_overlapping_a_pause_waits_and_creates_nothing(
    committed_session_factory: SessionFactory, engine: AsyncEngine
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60)
    async with committed_session_factory() as pausing:
        await pausing.execute(update(Alert).where(Alert.id == alert.id).values(active=False))
        evaluating = asyncio.create_task(_evaluate(committed_session_factory))
        await wait_until_blocked(engine)
        await pausing.commit()
    await asyncio.wait_for(evaluating, timeout=5)

    assert await _notified(committed_session_factory, alert) == {}


async def test_new_notification_is_pending_and_due_now(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 60)
    before = datetime.now(UTC)

    await _evaluate(committed_session_factory)

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


class StubNotificationSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, NotificationContent]] = []
        self.messages: list[tuple[str, list[NotificationContent]]] = []
        self.failing: set[str] = set()
        self.hanging: set[str] = set()
        self.slow: set[date] = set()
        self.started = asyncio.Event()
        self.released = asyncio.Event()

    async def send(self, phone_number: str, contents: Sequence[NotificationContent]) -> None:
        self.started.set()
        await asyncio.sleep(0)
        field_names = {content.field_name for content in contents}
        if field_names & self.hanging:
            await self.released.wait()
        if contents[0].day in self.slow:
            await asyncio.sleep(0.1)
        if field_names & self.failing:
            raise RuntimeError("sender unavailable")
        self.messages.append((phone_number, list(contents)))
        self.sent.extend((phone_number, content) for content in contents)


async def _add_alert(
    session_factory: SessionFactory,
    alert: Alert,
    *,
    field_name: str | None = None,
    weather_event_type: WeatherEventType = FROST,
) -> Alert:
    async with session_factory() as session:
        field_id = alert.field_id
        if field_name is not None:
            field = await session.get_one(Field, alert.field_id)
            other = Field(
                user_id=field.user_id,
                name=field_name,
                latitude=field.latitude,
                longitude=field.longitude,
                location_id=field.location_id,
            )
            session.add(other)
            await session.flush()
            field_id = other.id
        added = Alert(field_id=field_id, weather_event_type=weather_event_type, threshold=50)
        session.add(added)
        await session.commit()
        return added


async def _add_pending(
    session_factory: SessionFactory, alert: Alert, *offsets: int, **values: object
) -> None:
    async with session_factory() as session:
        for offset in offsets:
            session.add(
                Notification(
                    alert_id=alert.id, day=_day(offset), probability=70, threshold=50, **values
                )
            )
        await session.commit()


async def _phone_number(session_factory: SessionFactory, alert: Alert) -> str:
    async with session_factory() as session:
        field = await session.get_one(Field, alert.field_id)
        user = await session.get_one(User, field.user_id)
    return user.phone_number


async def _pending(
    session_factory: SessionFactory,
    *,
    day: date | None = None,
    probability: int = 70,
    threshold: int = 50,
    latitude: float = 1,
) -> Alert:
    alert = await _create_alert(session_factory, threshold, latitude=latitude)
    async with session_factory() as session:
        session.add(
            Notification(
                alert_id=alert.id, day=day or _day(1), probability=probability, threshold=threshold
            )
        )
        await session.commit()
    return alert


async def _mark_broken(session_factory: SessionFactory, *alerts: Alert) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Field)
            .where(Field.id.in_([alert.field_id for alert in alerts]))
            .values(name="Broken")
        )
        await session.commit()


async def _hang(
    session_factory: SessionFactory, sender: StubNotificationSender, *alerts: Alert
) -> None:
    await _mark_broken(session_factory, *alerts)
    sender.hanging.add("Broken")


async def _notify(
    session_factory: SessionFactory,
    sender: StubNotificationSender,
    batch_size: int = BATCH_SIZE,
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> None:
    await notifications.notify(
        session_factory,
        sender,
        batch_size=batch_size,
        timeout_seconds=timeout_seconds,
        timezone=TIMEZONE,
    )


async def _update_notification(
    session_factory: SessionFactory, alert: Alert, **values: object
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Notification).where(Notification.alert_id == alert.id).values(**values)
        )
        await session.commit()


async def _make_due(session_factory: SessionFactory, alert: Alert, **values: object) -> None:
    await _update_notification(session_factory, alert, next_attempt_at=datetime.now(UTC), **values)


async def _status(session_factory: SessionFactory, alert: Alert) -> NotificationStatus:
    async with session_factory() as session:
        [notification] = await repository.list_for_alert(session, alert.id)
    return notification.status


async def test_pending_notification_is_sent_to_the_users_phone(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory, day=_day(2), probability=80, threshold=60)
    sender = StubNotificationSender()
    before = datetime.now(UTC)

    await _notify(committed_session_factory, sender)

    async with committed_session_factory() as session:
        field = await session.get_one(Field, alert.field_id)
        user = await session.get_one(User, field.user_id)
        [notification] = await repository.list_for_alert(session, alert.id)
    assert sender.sent == [(user.phone_number, NotificationContent("Lote", FROST, _day(2), 80, 60))]
    assert notification.status == NotificationStatus.SENT
    assert notification.attempts == 1
    assert notification.sent_at is not None
    assert before <= notification.sent_at <= datetime.now(UTC)


async def test_user_gets_one_message_with_all_pending_notifications_across_alerts_and_fields(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory, day=_day(1))
    rain = await _add_alert(
        committed_session_factory, alert, weather_event_type=WeatherEventType.RAIN
    )
    north = await _add_alert(committed_session_factory, alert, field_name="Norte")
    await _add_pending(committed_session_factory, rain, 2)
    await _add_pending(committed_session_factory, north, 0)
    other = await _pending(committed_session_factory, day=_day(3), latitude=2)
    sender = StubNotificationSender()

    await _notify(committed_session_factory, sender)

    assert sorted(sender.messages) == sorted(
        [
            (
                await _phone_number(committed_session_factory, alert),
                [
                    NotificationContent("Norte", FROST, _day(0), 70, 50),
                    NotificationContent("Lote", FROST, _day(1), 70, 50),
                    NotificationContent("Lote", WeatherEventType.RAIN, _day(2), 70, 50),
                ],
            ),
            (
                await _phone_number(committed_session_factory, other),
                [NotificationContent("Lote", FROST, _day(3), 70, 50)],
            ),
        ]
    )


async def test_more_than_20_pending_notifications_go_out_in_several_messages_earliest_days_first(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _add_pending(committed_session_factory, alert, *reversed(range(25)))
    sender = StubNotificationSender()
    sender.slow.add(_day(0))

    await _notify(committed_session_factory, sender)

    assert [[content.day for content in contents] for _, contents in sender.messages] == [
        [_day(offset) for offset in range(20)],
        [_day(offset) for offset in range(20, 25)],
    ]


async def test_backlog_larger_than_a_batch_is_fully_sent_in_one_run_earliest_day_first(
    committed_session_factory: SessionFactory,
) -> None:
    for offset in [3, 0, 5, 1, 2]:
        await _pending(committed_session_factory, day=_day(offset), latitude=offset)
    sender = StubNotificationSender()

    await _notify(committed_session_factory, sender, batch_size=2)

    assert [content.day for _, content in sender.sent] == [_day(o) for o in [0, 1, 2, 3, 5]]


async def test_within_a_day_the_longest_waiting_notification_is_claimed_first(
    committed_session_factory: SessionFactory,
) -> None:
    recent = await _pending(committed_session_factory, latitude=1)
    waiting = await _pending(committed_session_factory, latitude=2)
    for alert, minutes in [(recent, 1), (waiting, 5)]:
        await _update_notification(
            committed_session_factory,
            alert,
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=minutes),
        )

    await _notify(committed_session_factory, StubNotificationSender(), batch_size=1)

    async with committed_session_factory() as session:
        [[first], [second]] = [
            await repository.list_for_alert(session, alert.id) for alert in [waiting, recent]
        ]
    assert first.sent_at is not None and second.sent_at is not None
    assert first.sent_at < second.sent_at


@pytest.mark.parametrize(
    ("changes", "kept"),
    [
        ({"active": False}, {3, 4, 5}),
        ({"threshold": 70}, {2, 3, 4, 5}),
        ({"threshold": 40}, {1, 2, 3, 4, 5}),
        ({"active": True}, {1, 2, 3, 4, 5}),
    ],
    ids=["pause", "raise-threshold", "lower-threshold", "resume"],
)
async def test_pausing_or_raising_threshold_withdraws_pending_notifications_that_no_longer_apply(
    committed_session_factory: SessionFactory, changes: dict[str, Any], kept: set[int]
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    async with committed_session_factory() as session:
        for offset, probability, status in [
            (1, 60, NotificationStatus.PENDING),
            (2, 80, NotificationStatus.PENDING),
            (3, 60, NotificationStatus.SENT),
            (4, 60, NotificationStatus.EXPIRED),
            (5, 60, NotificationStatus.FAILED),
        ]:
            session.add(
                Notification(
                    alert_id=alert.id,
                    day=_day(offset),
                    probability=probability,
                    threshold=50,
                    status=status,
                )
            )
        await session.commit()

    async with committed_session_factory() as session:
        await alerts.update(session, alert.id, changes.get("threshold"), changes.get("active"))

    assert set(await _notified(committed_session_factory, alert)) == {_day(o) for o in kept}


async def test_failed_send_is_retried_later_without_stopping_the_batch(
    committed_session_factory: SessionFactory,
) -> None:
    failing = await _pending(committed_session_factory, day=_day(0), latitude=1)
    delivered = await _pending(committed_session_factory, day=_day(1), latitude=2)
    await _mark_broken(committed_session_factory, failing)
    sender = StubNotificationSender()
    sender.failing.add("Broken")
    before = datetime.now(UTC)

    await _notify(committed_session_factory, sender)

    async with committed_session_factory() as session:
        [failed] = await repository.list_for_alert(session, failing.id)
        [sent] = await repository.list_for_alert(session, delivered.id)
    assert failed.status == NotificationStatus.PENDING
    assert failed.attempts == 1
    assert failed.sent_at is None
    assert failed.next_attempt_at > before + timedelta(seconds=10)
    assert sent.status == NotificationStatus.SENT
    assert [content.field_name for _, content in sender.sent] == ["Lote"]


async def test_send_that_never_answers_is_retried_later_without_stopping_the_batch(
    committed_session_factory: SessionFactory,
) -> None:
    hanging = await _pending(committed_session_factory, day=_day(0), latitude=1)
    delivered = await _pending(committed_session_factory, day=_day(1), latitude=2)
    sender = StubNotificationSender()
    await _hang(committed_session_factory, sender, hanging)
    before = datetime.now(UTC)

    await asyncio.wait_for(
        _notify(committed_session_factory, sender, timeout_seconds=0.05), timeout=5
    )

    async with committed_session_factory() as session:
        [retried] = await repository.list_for_alert(session, hanging.id)
        [sent] = await repository.list_for_alert(session, delivered.id)
    assert retried.status == NotificationStatus.PENDING
    assert retried.attempts == 1
    assert retried.next_attempt_at > before + timedelta(seconds=10)
    assert sent.status == NotificationStatus.SENT


async def test_retry_delay_doubles_per_attempt_up_to_one_hour(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory)
    sender = StubNotificationSender()
    sender.failing.add("Lote")
    delays: list[int] = []

    for _ in range(9):
        before = datetime.now(UTC)
        await _notify(committed_session_factory, sender)
        async with committed_session_factory() as session:
            [notification] = await repository.list_for_alert(session, alert.id)
        delays.append(round((notification.next_attempt_at - before).total_seconds()))
        await _make_due(committed_session_factory, alert)

    assert delays == [30, 60, 120, 240, 480, 960, 1920, 3600, 3600]


async def test_notification_keeps_retrying_past_many_failures_until_the_sender_recovers(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory)
    sender = StubNotificationSender()
    sender.failing.add("Lote")
    failures = 8
    for _ in range(failures):
        await _notify(committed_session_factory, sender)
        await _make_due(committed_session_factory, alert)
    sender.failing.clear()

    await _notify(committed_session_factory, sender)

    async with committed_session_factory() as session:
        [notification] = await repository.list_for_alert(session, alert.id)
    assert notification.status == NotificationStatus.SENT
    assert notification.attempts == failures + 1
    assert len(sender.sent) == 1


async def test_notification_that_keeps_failing_until_its_day_has_passed_expires(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory, day=_day(0))
    sender = StubNotificationSender()
    sender.failing.add("Lote")
    await _notify(committed_session_factory, sender)
    await _make_due(committed_session_factory, alert, day=_day(-1))

    await _notify(committed_session_factory, sender)

    assert await _status(committed_session_factory, alert) == NotificationStatus.EXPIRED


async def test_failing_notifications_back_off_so_due_ones_still_go_out(
    committed_session_factory: SessionFactory,
) -> None:
    broken = [
        await _pending(committed_session_factory, day=_day(0), latitude=latitude)
        for latitude in [1, 2]
    ]
    await _pending(committed_session_factory, day=_day(1), latitude=3)
    await _mark_broken(committed_session_factory, *broken)
    sender = StubNotificationSender()
    sender.failing.add("Broken")

    await _notify(committed_session_factory, sender, batch_size=2)
    await _notify(committed_session_factory, sender, batch_size=2)

    assert [content.day for _, content in sender.sent] == [_day(1)]


async def test_concurrent_runs_send_each_user_one_message_with_each_notification_once(
    committed_session_factory: SessionFactory,
) -> None:
    alerts = [await _pending(committed_session_factory, latitude=n) for n in range(20)]
    for alert in alerts:
        await _add_pending(committed_session_factory, alert, 2, 3)
    sender = StubNotificationSender()

    await asyncio.gather(
        *(_notify(committed_session_factory, sender, batch_size=3) for _ in range(10))
    )

    assert len(sender.messages) == len(alerts)
    assert len({phone_number for phone_number, _ in sender.messages}) == len(alerts)
    assert len(sender.sent) == 3 * len(alerts)


async def test_user_with_a_message_in_flight_is_skipped_even_with_a_new_due_notification(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory, day=_day(1))
    in_flight_sender = StubNotificationSender()
    await _hang(committed_session_factory, in_flight_sender, alert)
    in_flight = asyncio.create_task(_notify(committed_session_factory, in_flight_sender))
    await in_flight_sender.started.wait()
    await _add_pending(committed_session_factory, alert, 2)
    sender = StubNotificationSender()

    await asyncio.wait_for(_notify(committed_session_factory, sender, batch_size=1), timeout=5)
    in_flight_sender.released.set()
    await in_flight

    assert sender.sent == []
    assert [content.day for _, content in in_flight_sender.sent] == [_day(1)]
    await _notify(committed_session_factory, sender)
    assert [content.day for _, content in sender.sent] == [_day(2)]


async def test_failed_message_backs_off_all_its_notifications_and_rides_along_with_the_next_due(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory, day=_day(1))
    await _add_pending(committed_session_factory, alert, 2, attempts=2)
    sender = StubNotificationSender()
    sender.failing.add("Lote")
    before = datetime.now(UTC)

    await _notify(committed_session_factory, sender)

    async with committed_session_factory() as session:
        stored = await repository.list_for_alert(session, alert.id)
    assert [(n.status, n.attempts) for n in stored] == [
        (NotificationStatus.PENDING, 1),
        (NotificationStatus.PENDING, 3),
    ]
    assert stored[0].next_attempt_at == stored[1].next_attempt_at
    assert stored[0].next_attempt_at >= before + timedelta(seconds=120)

    sender.failing.clear()
    await _add_pending(committed_session_factory, alert, 3)
    await _notify(committed_session_factory, sender)

    assert [[content.day for content in contents] for _, contents in sender.messages] == [
        [_day(1), _day(2), _day(3)]
    ]


async def test_database_error_recording_one_message_does_not_stop_the_others(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = await _pending(committed_session_factory, latitude=1)
    delivered = await _pending(committed_session_factory, latitude=2)
    async with committed_session_factory() as session:
        [broken_notification] = await repository.list_for_alert(session, broken.id)
    lock_pending = repository.lock_pending

    async def lock_pending_failing_for_broken(session: AsyncSession, ids: Any) -> Any:
        if broken_notification.id in ids:
            raise OperationalError("UPDATE notifications", {}, ConnectionError("lost"))
        return await lock_pending(session, ids)

    monkeypatch.setattr(repository, "lock_pending", lock_pending_failing_for_broken)

    with structlog.testing.capture_logs() as logs:
        await _notify(committed_session_factory, StubNotificationSender())

    assert await _status(committed_session_factory, broken) == NotificationStatus.PENDING
    assert await _status(committed_session_factory, delivered) == NotificationStatus.SENT
    assert {
        "event": "notifications.notified",
        "expired": 0,
        "sent": 1,
        "retried": 0,
        "failed": 0,
        "errors": 1,
        "log_level": "info",
    } in logs


async def test_run_logs_how_many_notifications_were_sent_and_retried(
    committed_session_factory: SessionFactory,
) -> None:
    await _pending(committed_session_factory, latitude=1)
    broken = [await _pending(committed_session_factory, latitude=n) for n in [2, 3]]
    await _mark_broken(committed_session_factory, *broken)
    sender = StubNotificationSender()
    sender.failing.add("Broken")

    with structlog.testing.capture_logs() as logs:
        await _notify(committed_session_factory, sender)

    assert {
        "event": "notifications.notified",
        "expired": 0,
        "sent": 1,
        "retried": 2,
        "failed": 0,
        "errors": 0,
        "log_level": "info",
    } in logs


async def test_fake_sender_logs_the_contents_and_rejects_numbers_ending_in_0000() -> None:
    content = NotificationContent("Lote", FROST, _day(1), 80, 60)

    with structlog.testing.capture_logs() as logs:
        await FakeNotificationSender().send("+5491122334455", [content])

    assert logs == [
        {
            "event": "notifications.fake_sent",
            "log_level": "info",
            "notifications": [content._asdict()],
        }
    ]
    with pytest.raises(PermanentDeliveryError):
        await FakeNotificationSender().send("+5491122330000", [content])


async def test_permanently_rejected_message_fails_all_its_notifications_for_good(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory, day=_day(1))
    await _add_pending(committed_session_factory, alert, 2)
    async with committed_session_factory() as session:
        field = await session.get_one(Field, alert.field_id)
        await session.execute(
            update(User).where(User.id == field.user_id).values(phone_number="+5491122330000")
        )
        await session.commit()

    await notifications.notify(
        committed_session_factory,
        FakeNotificationSender(),
        batch_size=BATCH_SIZE,
        timeout_seconds=TIMEOUT_SECONDS,
        timezone=TIMEZONE,
    )
    await _make_due(committed_session_factory, alert)
    sender = StubNotificationSender()
    await _notify(committed_session_factory, sender)

    async with committed_session_factory() as session:
        stored = await repository.list_for_alert(session, alert.id)
    assert [(n.status, n.attempts) for n in stored] == [(NotificationStatus.FAILED, 1)] * 2
    assert sender.sent == []


async def test_notification_not_yet_due_is_not_claimed(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory)
    await _update_notification(
        committed_session_factory, alert, next_attempt_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    sender = StubNotificationSender()

    await _notify(committed_session_factory, sender)

    assert sender.sent == []


async def test_run_skips_a_notification_locked_by_another_run_without_waiting(
    committed_session_factory: SessionFactory,
) -> None:
    locked = await _pending(committed_session_factory, day=_day(0), latitude=1)
    await _pending(committed_session_factory, day=_day(1), latitude=2)
    sender = StubNotificationSender()

    async with committed_session_factory() as other_run:
        await other_run.execute(
            select(Notification).where(Notification.alert_id == locked.id).with_for_update()
        )
        await asyncio.wait_for(_notify(committed_session_factory, sender), timeout=5)

    assert [content.day for _, content in sender.sent] == [_day(1)]


async def test_run_ends_when_every_claimed_user_has_their_due_notifications_locked(
    committed_session_factory: SessionFactory,
) -> None:
    locked = await _pending(committed_session_factory, day=_day(0), latitude=1)
    await _pending(committed_session_factory, day=_day(1), latitude=2)

    async with committed_session_factory() as other_run:
        await other_run.execute(
            select(Notification).where(Notification.alert_id == locked.id).with_for_update()
        )
        await asyncio.wait_for(
            _notify(committed_session_factory, StubNotificationSender(), batch_size=1), timeout=5
        )


async def test_pending_notification_for_a_past_day_expires_instead_of_being_sent(
    committed_session_factory: SessionFactory,
) -> None:
    past = await _pending(committed_session_factory, day=_day(-1), latitude=1)
    today = await _pending(committed_session_factory, day=_day(0), latitude=2)
    sender = StubNotificationSender()

    await _notify(committed_session_factory, sender)

    assert await _status(committed_session_factory, past) == NotificationStatus.EXPIRED
    assert await _status(committed_session_factory, today) == NotificationStatus.SENT
    assert [content.day for _, content in sender.sent] == [_day(0)]


async def test_notification_for_the_local_today_is_still_sent_after_utc_midnight(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    instant, local_today = local_evening_after_utc_midnight()
    alert = await _pending(committed_session_factory, day=local_today)
    freeze_clock(monkeypatch, notifications, instant)
    sender = StubNotificationSender()

    await _notify(committed_session_factory, sender)

    assert await _status(committed_session_factory, alert) == NotificationStatus.SENT
    assert [content.day for _, content in sender.sent] == [local_today]


@pytest.mark.parametrize("status", [NotificationStatus.SENT, NotificationStatus.FAILED])
async def test_sent_or_failed_notification_for_a_past_day_is_never_expired(
    committed_session_factory: SessionFactory, status: NotificationStatus
) -> None:
    alert = await _pending(committed_session_factory, day=_day(-1))
    await _update_notification(committed_session_factory, alert, status=status)

    await _notify(committed_session_factory, StubNotificationSender())

    assert await _status(committed_session_factory, alert) == status


async def test_past_day_notifications_do_not_take_batch_slots(
    committed_session_factory: SessionFactory,
) -> None:
    for latitude in range(3):
        await _pending(committed_session_factory, day=_day(-1), latitude=latitude)
    await _pending(committed_session_factory, day=_day(1), latitude=10)
    sender = StubNotificationSender()

    with structlog.testing.capture_logs() as logs:
        await _notify(committed_session_factory, sender, batch_size=2)

    assert [content.day for _, content in sender.sent] == [_day(1)]
    assert {
        "event": "notifications.notified",
        "expired": 3,
        "sent": 1,
        "retried": 0,
        "failed": 0,
        "errors": 0,
        "log_level": "info",
    } in logs


async def test_expiry_skips_a_notification_locked_by_another_run_without_waiting(
    committed_session_factory: SessionFactory,
) -> None:
    locked = await _pending(committed_session_factory, day=_day(-1), latitude=1)
    unlocked = await _pending(committed_session_factory, day=_day(-1), latitude=2)

    async with committed_session_factory() as other_run:
        await other_run.execute(
            select(Notification).where(Notification.alert_id == locked.id).with_for_update()
        )
        await asyncio.wait_for(
            _notify(committed_session_factory, StubNotificationSender()), timeout=5
        )

    assert await _status(committed_session_factory, locked) == NotificationStatus.PENDING
    assert await _status(committed_session_factory, unlocked) == NotificationStatus.EXPIRED


async def test_notification_whose_day_ends_after_it_is_claimed_expires_instead_of_being_sent(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts = [
        await _pending(committed_session_factory, day=_day(0), latitude=latitude)
        for latitude in [1, 2]
    ]
    instant = datetime.now(UTC)
    freeze_clock(monkeypatch, notifications, instant)
    pending_for_users = repository.pending_for_users

    async def pending_for_users_until_midnight(*args: Any) -> Any:
        claimed = await pending_for_users(*args)
        freeze_clock(monkeypatch, notifications, instant + timedelta(days=1))
        return claimed

    monkeypatch.setattr(repository, "pending_for_users", pending_for_users_until_midnight)
    sender = StubNotificationSender()

    with structlog.testing.capture_logs() as logs:
        await _notify(committed_session_factory, sender)

    assert sender.sent == []
    assert [await _status(committed_session_factory, alert) for alert in alerts] == [
        NotificationStatus.EXPIRED,
        NotificationStatus.EXPIRED,
    ]
    assert {
        "event": "notifications.notified",
        "expired": 2,
        "sent": 0,
        "retried": 0,
        "failed": 0,
        "errors": 0,
        "log_level": "info",
    } in logs


async def test_batch_is_sent_concurrently_so_hung_sends_cost_one_time_limit(
    committed_session_factory: SessionFactory,
) -> None:
    hanging = [await _pending(committed_session_factory, latitude=n) for n in range(5)]
    sender = StubNotificationSender()
    await _hang(committed_session_factory, sender, *hanging)

    await asyncio.wait_for(
        _notify(committed_session_factory, sender, timeout_seconds=0.5), timeout=1.5
    )

    for alert in hanging:
        assert await _status(committed_session_factory, alert) == NotificationStatus.PENDING


async def _crash_while_sending(
    session_factory: SessionFactory, hanging: Alert, sender: StubNotificationSender
) -> None:
    await _hang(session_factory, sender, hanging)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_notify(session_factory, sender), timeout=0.5)


async def test_crash_while_sending_one_notification_keeps_the_others_sent(
    committed_session_factory: SessionFactory,
) -> None:
    done = [await _pending(committed_session_factory, latitude=n) for n in [1, 2]]
    hanging = await _pending(committed_session_factory, latitude=3)
    sender = StubNotificationSender()

    await _crash_while_sending(committed_session_factory, hanging, sender)

    assert [await _status(committed_session_factory, alert) for alert in done] == [
        NotificationStatus.SENT,
        NotificationStatus.SENT,
    ]
    assert await _status(committed_session_factory, hanging) == NotificationStatus.PENDING


async def test_notification_claimed_by_a_crashed_run_is_sent_once_its_lease_has_ended(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    hanging = await _pending(committed_session_factory)
    before = datetime.now(UTC)
    await _crash_while_sending(committed_session_factory, hanging, StubNotificationSender())
    after = datetime.now(UTC)
    lease = timedelta(seconds=2 * TIMEOUT_SECONDS)
    sender = StubNotificationSender()

    freeze_clock(monkeypatch, notifications, before + lease - timedelta(seconds=1))
    await _notify(committed_session_factory, sender)
    assert sender.sent == []

    freeze_clock(monkeypatch, notifications, after + lease + timedelta(seconds=1))
    await _notify(committed_session_factory, sender)
    assert len(sender.sent) == 1


async def test_deleting_an_alert_while_its_notification_is_being_sent_does_not_wait(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory)
    sender = StubNotificationSender()
    await _hang(committed_session_factory, sender, alert)
    run = asyncio.create_task(_notify(committed_session_factory, sender))
    await sender.started.wait()

    async with committed_session_factory() as session:
        await asyncio.wait_for(
            session.execute(delete(Alert).where(Alert.id == alert.id)), timeout=2
        )
        await session.commit()
    sender.released.set()
    await run

    async with committed_session_factory() as session:
        assert await repository.list_for_alert(session, alert.id) == []


async def test_notification_expired_by_another_run_while_being_sent_stays_expired(
    committed_session_factory: SessionFactory,
) -> None:
    alert = await _pending(committed_session_factory)
    sender = StubNotificationSender()
    await _hang(committed_session_factory, sender, alert)
    run = asyncio.create_task(_notify(committed_session_factory, sender))
    await sender.started.wait()

    await _update_notification(committed_session_factory, alert, status=NotificationStatus.EXPIRED)
    sender.released.set()
    await run

    assert await _status(committed_session_factory, alert) == NotificationStatus.EXPIRED


class _TickingClock:
    def __init__(self) -> None:
        self.instant = datetime.now(UTC)

    def now(self, tz: Any = None) -> datetime:
        self.instant += timedelta(minutes=1)
        return self.instant.astimezone(tz)


async def test_notification_that_fails_is_not_claimed_again_in_the_same_run(
    committed_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = [await _pending(committed_session_factory, latitude=n) for n in [1, 2]]
    await _mark_broken(committed_session_factory, *broken)
    sender = StubNotificationSender()
    sender.failing.add("Broken")
    clock = _TickingClock()
    for module in [notifications, notification_models]:
        monkeypatch.setattr(module, "datetime", clock)

    await asyncio.wait_for(_notify(committed_session_factory, sender, batch_size=1), timeout=5)

    async with committed_session_factory() as session:
        attempts = [
            notification.attempts
            for alert in broken
            for notification in await repository.list_for_alert(session, alert.id)
        ]
    assert attempts == [1, 1]


async def test_alert_notifications_endpoint_shows_status_and_sent_time_by_day(
    committed_session_factory: SessionFactory, client: AsyncClient
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)
    await _forecast(committed_session_factory, 80, day=_day(2))
    await _evaluate(committed_session_factory)
    await _notify(committed_session_factory, StubNotificationSender())
    await _forecast(committed_session_factory, 60, day=_day(1))
    await _evaluate(committed_session_factory)

    response = await client.get(f"/alerts/{alert.id}/notifications")

    assert response.status_code == status.HTTP_200_OK
    pending, sent = response.json()
    assert pending == {
        "day": _day(1).isoformat(),
        "probability": 60,
        "threshold": 50,
        "status": "pending",
        "attempts": 0,
        "sent_at": None,
    }
    assert {
        key: sent[key] for key in ["day", "probability", "threshold", "status", "attempts"]
    } == {
        "day": _day(2).isoformat(),
        "probability": 80,
        "threshold": 50,
        "status": "sent",
        "attempts": 1,
    }
    assert datetime.fromisoformat(sent["sent_at"]) <= datetime.now(UTC)


async def test_alert_without_notifications_lists_none(
    committed_session_factory: SessionFactory, client: AsyncClient
) -> None:
    alert = await _create_alert(committed_session_factory, threshold=50)

    response = await client.get(f"/alerts/{alert.id}/notifications")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


async def test_notifications_of_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/alerts/{uuid.uuid4()}/notifications")

    assert response.status_code == status.HTTP_404_NOT_FOUND
