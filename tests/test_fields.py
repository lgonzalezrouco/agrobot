import asyncio
import uuid
from typing import Any

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agrobot.locations import repository as locations
from agrobot.locations.models import Location


async def _register_user(client: AsyncClient, phone_number: str = "+5491122334455") -> str:
    response = await client.post("/users", json={"name": "Ana", "phone_number": phone_number})
    user_id: str = response.json()["id"]
    return user_id


async def _register_field(
    client: AsyncClient, user_id: str, latitude: float, longitude: float, name: str = "Lote 1"
) -> dict[str, Any]:
    response = await client.post(
        f"/users/{user_id}/fields",
        json={"name": name, "latitude": latitude, "longitude": longitude},
    )
    assert response.status_code == status.HTTP_201_CREATED
    body: dict[str, Any] = response.json()
    return body


async def test_register_field_returns_field_with_its_location(client: AsyncClient) -> None:
    user_id = await _register_user(client)

    response = await client.post(
        f"/users/{user_id}/fields",
        json={"name": "Lote 1", "latitude": 12.34, "longitude": 56.78},
    )

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["name"] == "Lote 1"
    assert body["user_id"] == user_id
    assert body["latitude"] == 12.34
    assert body["longitude"] == 56.78
    assert body["location"]["latitude"] == 12.3
    assert body["location"]["longitude"] == 56.8


@pytest.mark.parametrize(
    ("latitude", "longitude", "grid_latitude", "grid_longitude"),
    [
        (-34.65, -58.38, -34.7, -58.4),
        (-34.64, -58.35, -34.6, -58.4),
        (0.05, -0.05, 0.1, -0.1),
        (0.0499, -0.0499, 0.0, 0.0),
        (89.96, 179.96, 90.0, 180.0),
    ],
    ids=["south-west", "south-west-half", "boundary-up", "boundary-down", "edge"],
)
async def test_register_field_rounds_to_nearest_grid_point(
    client: AsyncClient,
    latitude: float,
    longitude: float,
    grid_latitude: float,
    grid_longitude: float,
) -> None:
    user_id = await _register_user(client)

    field = await _register_field(client, user_id, latitude, longitude)

    assert field["location"]["latitude"] == grid_latitude
    assert field["location"]["longitude"] == grid_longitude


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90.1, 0), (-90.1, 0), (0, 180.1), (0, -180.1)],
)
async def test_register_field_rejects_out_of_range_coordinates(
    client: AsyncClient, latitude: float, longitude: float
) -> None:
    user_id = await _register_user(client)

    response = await client.post(
        f"/users/{user_id}/fields",
        json={"name": "Lote 1", "latitude": latitude, "longitude": longitude},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_register_field_for_unknown_user_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/users/{uuid.uuid4()}/fields", json={"name": "Lote 1", "latitude": 1, "longitude": 1}
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_nearby_fields_share_a_location(client: AsyncClient) -> None:
    user_id = await _register_user(client)

    first = await _register_field(client, user_id, -34.61, -58.38)
    second = await _register_field(client, user_id, -34.59, -58.42)

    assert first["location"] == second["location"]


async def test_list_fields_returns_the_users_fields(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    other_user_id = await _register_user(client, "+5491199998888")
    first = await _register_field(client, user_id, 1, 1, name="Norte")
    second = await _register_field(client, user_id, 2, 2, name="Sur")
    await _register_field(client, other_user_id, 3, 3)

    response = await client.get(f"/users/{user_id}/fields")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [first, second]


async def test_list_fields_for_unknown_user_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/users/{uuid.uuid4()}/fields")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_get_field_returns_registered_field(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    field = await _register_field(client, user_id, 1, 1)

    response = await client.get(f"/fields/{field['id']}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == field


async def test_get_unknown_field_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/fields/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_update_field_name_keeps_its_location(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    field = await _register_field(client, user_id, -34.61, -58.38)

    response = await client.patch(f"/fields/{field['id']}", json={"name": "Renamed"})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["latitude"] == -34.61
    assert body["location"] == field["location"]


async def test_update_field_coordinates_moves_it_to_a_new_location(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    field = await _register_field(client, user_id, -34.61, -58.38)

    response = await client.patch(f"/fields/{field['id']}", json={"latitude": -31.42})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["latitude"] == -31.42
    assert body["longitude"] == -58.38
    assert body["location"]["latitude"] == -31.4
    assert body["location"]["longitude"] == -58.4
    assert (await client.get(f"/fields/{field['id']}")).json() == body


async def test_update_field_rejects_out_of_range_coordinates(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    field = await _register_field(client, user_id, 1, 1)

    response = await client.patch(f"/fields/{field['id']}", json={"longitude": 181})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_update_unknown_field_returns_404(client: AsyncClient) -> None:
    response = await client.patch(f"/fields/{uuid.uuid4()}", json={"name": "Renamed"})

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_field_removes_it(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    field = await _register_field(client, user_id, 1, 1)

    response = await client.delete(f"/fields/{field['id']}")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert (await client.get(f"/fields/{field['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_delete_unknown_field_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"/fields/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_deleting_a_user_deletes_their_fields(client: AsyncClient) -> None:
    user_id = await _register_user(client)
    field = await _register_field(client, user_id, 1, 1)

    await client.delete(f"/users/{user_id}")

    assert (await client.get(f"/fields/{field['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_concurrent_registrations_share_one_location(engine: AsyncEngine) -> None:
    # Not through HTTP: the client shares one session, and this needs two real transactions.
    async with AsyncSession(engine) as first, AsyncSession(engine) as second:
        created_id = (await locations.get_or_create(first, 45.01, 45.01)).id
        try:
            racing = asyncio.create_task(locations.get_or_create(second, 45.02, 44.98))
            await asyncio.sleep(0.2)  # let the second insert block on the first's uncommitted row
            await first.commit()

            assert (await racing).id == created_id
        finally:
            await second.rollback()
            await first.execute(delete(Location).where(Location.id == created_id))
            await first.commit()
