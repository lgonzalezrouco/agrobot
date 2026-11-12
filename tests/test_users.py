import uuid

from fastapi import status
from httpx import AsyncClient


async def test_register_user_returns_created_user(client: AsyncClient) -> None:
    response = await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["name"] == "Ana"
    assert body["phone_number"] == "+5491122334455"
    assert body["id"]


async def test_register_user_rejects_non_e164_phone_number(client: AsyncClient) -> None:
    response = await client.post("/users", json={"name": "Ana", "phone_number": "011 2233-4455"})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_register_user_rejects_taken_phone_number(client: AsyncClient) -> None:
    await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})

    response = await client.post("/users", json={"name": "Beto", "phone_number": "+5491122334455"})

    assert response.status_code == status.HTTP_409_CONFLICT


async def test_get_user_returns_registered_user(client: AsyncClient) -> None:
    created = (
        await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})
    ).json()

    response = await client.get(f"/users/{created['id']}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == created


async def test_get_unknown_user_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/users/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_user_removes_it(client: AsyncClient) -> None:
    created = (
        await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})
    ).json()

    response = await client.delete(f"/users/{created['id']}")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert (await client.get(f"/users/{created['id']}")).status_code == status.HTTP_404_NOT_FOUND


async def test_delete_unknown_user_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"/users/{uuid.uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
