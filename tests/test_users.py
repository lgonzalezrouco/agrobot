import uuid

import pytest
from fastapi import status
from httpx import AsyncClient


async def test_register_user_returns_created_user(client: AsyncClient) -> None:
    response = await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["name"] == "Ana"
    assert body["phone_number"] == "+5491122334455"
    assert body["id"]


@pytest.mark.parametrize(
    "phone_number",
    ["011 2233-4455", "5491122334455", "+0491122334455", "+1234567890123456"],
    ids=["formatted", "missing-plus", "leading-zero", "over-15-digits"],
)
async def test_register_user_rejects_non_e164_phone_number(
    client: AsyncClient, phone_number: str
) -> None:
    response = await client.post("/users", json={"name": "Ana", "phone_number": phone_number})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_register_user_rejects_nul_in_name(client: AsyncClient) -> None:
    response = await client.post(
        "/users", json={"name": "A\u0000na", "phone_number": "+5491122334455"}
    )

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


async def test_get_user_by_phone_number_returns_registered_user(client: AsyncClient) -> None:
    created = (
        await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})
    ).json()

    response = await client.get("/users", params={"phone_number": "+5491122334455"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == created


async def test_get_user_by_unregistered_phone_number_returns_404(client: AsyncClient) -> None:
    response = await client.get("/users", params={"phone_number": "+5491122334455"})

    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_get_deleted_user_by_phone_number_returns_404(client: AsyncClient) -> None:
    created = (
        await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})
    ).json()
    await client.delete(f"/users/{created['id']}")

    response = await client.get("/users", params={"phone_number": "+5491122334455"})

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
    "params",
    [{}, {"phone_number": "011 2233-4455"}, {"phone_number": "5491122334455"}],
    ids=["missing", "formatted", "missing-plus"],
)
async def test_get_user_rejects_missing_or_non_e164_phone_number(
    client: AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get("/users", params=params)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_get_user_by_unencoded_plus_phone_number_returns_422(client: AsyncClient) -> None:
    await client.post("/users", json={"name": "Ana", "phone_number": "+5491122334455"})

    response = await client.get("/users?phone_number=+5491122334455")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
