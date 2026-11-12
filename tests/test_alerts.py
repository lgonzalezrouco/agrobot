import uuid
from typing import Any

import pytest
from fastapi import status
from httpx import AsyncClient


async def _register_field(client: AsyncClient) -> tuple[str, str]:
    user = await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})
    user_id: str = user.json()["id"]
    field = await client.post(
        f"/users/{user_id}/fields", json={"name": "Lote 1", "latitude": 1, "longitude": 1}
    )
    field_id: str = field.json()["id"]
    return user_id, field_id


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
    _, field_id = await _register_field(client)

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
    _, field_id = await _register_field(client)

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
    _, field_id = await _register_field(client)

    alert = await _configure_alert(client, field_id, weather_event_type)

    assert alert["weather_event_type"] == weather_event_type


@pytest.mark.parametrize("weather_event_type", ["snow", "FROST", "", None])
async def test_configure_alert_rejects_unknown_weather_event_type(
    client: AsyncClient, weather_event_type: str | None
) -> None:
    _, field_id = await _register_field(client)

    response = await client.post(
        f"/fields/{field_id}/alerts",
        json={"weather_event_type": weather_event_type, "threshold": 50},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize("threshold", [0, 100])
async def test_configure_alert_accepts_threshold_bounds(
    client: AsyncClient, threshold: int
) -> None:
    _, field_id = await _register_field(client)

    alert = await _configure_alert(client, field_id, threshold=threshold)

    assert alert["threshold"] == threshold


@pytest.mark.parametrize("threshold", [-1, 101, 50.5, "high", None])
async def test_configure_alert_rejects_invalid_threshold(
    client: AsyncClient, threshold: object
) -> None:
    _, field_id = await _register_field(client)

    response = await client.post(
        f"/fields/{field_id}/alerts", json={"weather_event_type": "frost", "threshold": threshold}
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_configure_second_alert_for_same_weather_event_type_returns_409(
    client: AsyncClient,
) -> None:
    _, field_id = await _register_field(client)
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
    user_id, field_id = await _register_field(client)
    other_field = await client.post(
        f"/users/{user_id}/fields", json={"name": "Lote 2", "latitude": 2, "longitude": 2}
    )
    frost = await _configure_alert(client, field_id, "frost", 50)
    rain = await _configure_alert(client, field_id, "rain", 80)
    await _configure_alert(client, other_field.json()["id"], "frost", 50)

    response = await client.get(f"/fields/{field_id}/alerts")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [frost, rain]


async def test_list_alerts_for_unknown_field_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/fields/{uuid.uuid4()}/alerts")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_get_alert_returns_configured_alert(client: AsyncClient) -> None:
    _, field_id = await _register_field(client)
    alert = await _configure_alert(client, field_id)

    response = await client.get(f"/alerts/{alert['id']}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == alert


async def test_get_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/alerts/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_update_alert_threshold(client: AsyncClient) -> None:
    _, field_id = await _register_field(client)
    alert = await _configure_alert(client, field_id, threshold=50)

    response = await client.patch(f"/alerts/{alert['id']}", json={"threshold": 90})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["threshold"] == 90
    assert body["active"] is True
    assert (await client.get(f"/alerts/{alert['id']}")).json() == body


async def test_pause_and_resume_alert(client: AsyncClient) -> None:
    _, field_id = await _register_field(client)
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
        {"threshold": None},
        {"active": None},
    ],
)
async def test_update_alert_rejects_invalid_changes(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    _, field_id = await _register_field(client)
    alert = await _configure_alert(client, field_id)

    response = await client.patch(f"/alerts/{alert['id']}", json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert (await client.get(f"/alerts/{alert['id']}")).json() == alert


async def test_update_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.patch(f"/alerts/{uuid.uuid4()}", json={"threshold": 10})

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_alert_removes_it(client: AsyncClient) -> None:
    _, field_id = await _register_field(client)
    alert = await _configure_alert(client, field_id)

    response = await client.delete(f"/alerts/{alert['id']}")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert (await client.get(f"/alerts/{alert['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_delete_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"/alerts/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_deleting_a_field_deletes_its_alerts(client: AsyncClient) -> None:
    _, field_id = await _register_field(client)
    alert = await _configure_alert(client, field_id)

    await client.delete(f"/fields/{field_id}")

    assert (await client.get(f"/alerts/{alert['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_deleting_a_user_deletes_alerts_on_all_their_fields(client: AsyncClient) -> None:
    user_id, field_id = await _register_field(client)
    other_field = await client.post(
        f"/users/{user_id}/fields", json={"name": "Lote 2", "latitude": 2, "longitude": 2}
    )
    first = await _configure_alert(client, field_id)
    second = await _configure_alert(client, other_field.json()["id"])

    await client.delete(f"/users/{user_id}")

    for alert in (first, second):
        response = await client.get(f"/alerts/{alert['id']}")
        assert response.status_code == status.HTTP_404_NOT_FOUND
