import asyncio
import uuid
from typing import Any

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agrobot.alerts import service as alerts
from agrobot.alerts.models import Alert
from agrobot.core.errors import NotFoundError
from agrobot.fields import service as fields
from agrobot.fields.models import Field
from agrobot.locations.models import Location
from agrobot.users import service as users
from agrobot.users.models import User
from agrobot.weather import WeatherEventType
from tests.conftest import register_field, register_user


async def _configure_alert(
    client: AsyncClient, field_id: str, weather_event_type: str = "frost", threshold: int = 70
) -> dict[str, Any]:
    response = await client.post(
        f"/fields/{field_id}/alerts",
        json={"weather_event_type": weather_event_type, "threshold": threshold},
    )
    assert response.status_code == status.HTTP_201_CREATED
    body: dict[str, Any] = response.json()
    return body


async def test_configure_alert_is_active_by_default(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]

    response = await client.post(
        f"/fields/{field_id}/alerts", json={"weather_event_type": "frost", "threshold": 70}
    )

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["field_id"] == field_id
    assert body["weather_event_type"] == "frost"
    assert body["threshold"] == 70
    assert body["active"] is True


async def test_configure_alert_can_start_paused(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]

    response = await client.post(
        f"/fields/{field_id}/alerts",
        json={"weather_event_type": "hail", "threshold": 30, "active": False},
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["active"] is False


@pytest.mark.parametrize(
    "weather_event_type", ["frost", "rain", "hail", "heat_wave", "strong_wind"]
)
async def test_configure_alert_accepts_every_weather_event_type(
    client: AsyncClient, weather_event_type: str
) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]

    alert = await _configure_alert(client, field_id, weather_event_type)

    assert alert["weather_event_type"] == weather_event_type


@pytest.mark.parametrize("weather_event_type", ["snow", "FROST", "", None])
async def test_configure_alert_rejects_unknown_weather_event_type(
    client: AsyncClient, weather_event_type: str | None
) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]

    response = await client.post(
        f"/fields/{field_id}/alerts",
        json={"weather_event_type": weather_event_type, "threshold": 50},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize("threshold", [0, 100])
async def test_configure_alert_accepts_threshold_bounds(
    client: AsyncClient, threshold: int
) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]

    alert = await _configure_alert(client, field_id, threshold=threshold)

    assert alert["threshold"] == threshold


@pytest.mark.parametrize("threshold", [-1, 101, 50.5, 50.0, "50", "high", True, None])
async def test_configure_alert_rejects_invalid_threshold(
    client: AsyncClient, threshold: object
) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]

    response = await client.post(
        f"/fields/{field_id}/alerts", json={"weather_event_type": "frost", "threshold": threshold}
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_configure_second_alert_for_same_weather_event_type_returns_409(
    client: AsyncClient,
) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    await _configure_alert(client, field_id, "frost", 50)

    response = await client.post(
        f"/fields/{field_id}/alerts", json={"weather_event_type": "frost", "threshold": 80}
    )

    assert response.status_code == status.HTTP_409_CONFLICT


async def test_configure_alert_for_unknown_field_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/fields/{uuid.uuid4()}/alerts", json={"weather_event_type": "frost", "threshold": 50}
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_list_alerts_returns_the_fields_alerts(client: AsyncClient) -> None:
    user_id = await register_user(client)
    field_id = (await register_field(client, user_id))["id"]
    other_field = await register_field(client, user_id, 2, 2)
    frost = await _configure_alert(client, field_id, "frost", 50)
    rain = await _configure_alert(client, field_id, "rain", 80)
    await _configure_alert(client, other_field["id"], "frost", 50)

    response = await client.get(f"/fields/{field_id}/alerts")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [frost, rain]


async def test_list_alerts_for_unknown_field_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/fields/{uuid.uuid4()}/alerts")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_get_alert_returns_configured_alert(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    alert = await _configure_alert(client, field_id)

    response = await client.get(f"/alerts/{alert['id']}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == alert


async def test_get_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/alerts/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_update_alert_threshold(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    alert = await _configure_alert(client, field_id, threshold=50)

    response = await client.patch(f"/alerts/{alert['id']}", json={"threshold": 90})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["threshold"] == 90
    assert body["active"] is True
    assert (await client.get(f"/alerts/{alert['id']}")).json() == body


async def test_pause_and_resume_alert(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    alert = await _configure_alert(client, field_id, threshold=50)

    paused = await client.patch(f"/alerts/{alert['id']}", json={"active": False})
    resumed = await client.patch(f"/alerts/{alert['id']}", json={"active": True})

    assert paused.json()["active"] is False
    assert paused.json()["threshold"] == 50
    assert resumed.json()["active"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"weather_event_type": "rain"},
        {"threshold": 101},
        {"threshold": -1},
        {"threshold": "50"},
        {"threshold": True},
        {"threshold": None},
        {"active": None},
    ],
)
async def test_update_alert_rejects_invalid_changes(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    alert = await _configure_alert(client, field_id)

    response = await client.patch(f"/alerts/{alert['id']}", json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert (await client.get(f"/alerts/{alert['id']}")).json() == alert


async def test_update_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.patch(f"/alerts/{uuid.uuid4()}", json={"threshold": 10})

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_alert_removes_it(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    alert = await _configure_alert(client, field_id)

    response = await client.delete(f"/alerts/{alert['id']}")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert (await client.get(f"/alerts/{alert['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_delete_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"/alerts/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_deleting_a_field_deletes_its_alerts(client: AsyncClient) -> None:
    field_id = (await register_field(client, await register_user(client)))["id"]
    alert = await _configure_alert(client, field_id)

    await client.delete(f"/fields/{field_id}")

    assert (await client.get(f"/alerts/{alert['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_deleting_a_user_deletes_alerts_on_all_their_fields(client: AsyncClient) -> None:
    user_id = await register_user(client)
    field_id = (await register_field(client, user_id))["id"]
    other_field = await register_field(client, user_id, 2, 2)
    first = await _configure_alert(client, field_id)
    second = await _configure_alert(client, other_field["id"])

    await client.delete(f"/users/{user_id}")

    for alert in (first, second):
        response = await client.get(f"/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("threshold", [-1, 101])
async def test_database_rejects_out_of_range_threshold(
    client: AsyncClient, db_session: AsyncSession, threshold: int
) -> None:
    field = await register_field(client, await register_user(client))
    db_session.add(
        Alert(
            field_id=uuid.UUID(field["id"]),
            weather_event_type=WeatherEventType.FROST,
            threshold=threshold,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_configure_alert_on_a_field_deleted_concurrently_raises_not_found(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = await users.register(setup, "Ana", "+5491100000001")
        field = await fields.register(setup, user.id, "Lote 1", 46.01, 46.01)
    async with AsyncSession(engine) as deleter, AsyncSession(engine) as configurer:
        try:
            await deleter.execute(delete(Field).where(Field.id == field.id))
            racing = asyncio.create_task(
                alerts.configure(configurer, field.id, WeatherEventType.FROST, 50, True)
            )
            await asyncio.sleep(0.2)
            await deleter.commit()

            with pytest.raises(NotFoundError):
                await racing
        finally:
            await configurer.rollback()
            await deleter.execute(delete(User).where(User.id == user.id))
            await deleter.execute(delete(Location).where(Location.id == field.location_id))
            await deleter.commit()
