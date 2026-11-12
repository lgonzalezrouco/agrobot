import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from agrobot.core.config import Settings
from tests.conftest import register_field, register_user

ANA = {"name": "Ana", "phone_number": "+5491122334455"}


def unauthenticated(app: FastAPI, headers: dict[str, str]) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
async def test_request_without_the_right_api_key_is_rejected_and_changes_nothing(
    app: FastAPI, client: AsyncClient, headers: dict[str, str]
) -> None:
    user_id = await register_user(client)
    field = await register_field(client, user_id)

    async with unauthenticated(app, headers) as intruder:
        responses = [
            await intruder.post("/users", json={**ANA, "phone_number": "+5491100000000"}),
            await intruder.delete(f"/users/{user_id}"),
            await intruder.delete(f"/fields/{field['id']}"),
            await intruder.post(
                f"/fields/{field['id']}/alerts",
                json={"weather_event_type": "frost", "threshold": 70},
            ),
        ]

    assert [r.status_code for r in responses] == [status.HTTP_401_UNAUTHORIZED] * 4
    assert (await client.get(f"/users/{user_id}")).status_code == status.HTTP_200_OK
    assert (await client.get(f"/fields/{field['id']}")).status_code == status.HTTP_200_OK
    assert (await client.get(f"/fields/{field['id']}/alerts")).json() == []


async def test_request_with_the_right_api_key_is_served(client: AsyncClient) -> None:
    response = await client.post("/users", json=ANA)

    assert response.status_code == status.HTTP_201_CREATED


async def test_health_answers_without_api_key(app: FastAPI) -> None:
    async with unauthenticated(app, {}) as anonymous:
        response = await anonymous.get("/health")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("api_key", [None, ""])
def test_settings_require_api_key(monkeypatch: pytest.MonkeyPatch, api_key: str | None) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    if api_key is not None:
        monkeypatch.setenv("API_KEY", api_key)

    with pytest.raises(ValidationError, match="api_key"):
        Settings(database_url="postgresql+asyncpg://unused/unused", _env_file=None)
