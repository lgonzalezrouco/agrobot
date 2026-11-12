import uuid

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient
from pydantic import ValidationError

from agrobot.api.app import create_app
from agrobot.core.config import Settings
from tests.conftest import api_client, register_field, register_user


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
async def test_request_without_the_right_api_key_is_rejected_and_changes_nothing(
    app: FastAPI, client: AsyncClient, headers: dict[str, str]
) -> None:
    user_id = await register_user(client)
    field = await register_field(client, user_id)

    async with api_client(app, headers) as intruder:
        responses = [
            await intruder.post("/users", json={"name": "Beto", "phone_number": "+5491100000000"}),
            await intruder.delete(f"/users/{user_id}"),
            await intruder.delete(f"/fields/{field['id']}"),
            await intruder.post(
                f"/fields/{field['id']}/alerts",
                json={"weather_event_type": "frost", "threshold": 70},
            ),
            await intruder.get(f"/alerts/{uuid.uuid4()}/notifications"),
        ]

    assert [r.status_code for r in responses] == [status.HTTP_401_UNAUTHORIZED] * 5
    assert (await client.get(f"/users/{user_id}")).status_code == status.HTTP_200_OK
    assert (await client.get(f"/fields/{field['id']}")).status_code == status.HTTP_200_OK
    assert (await client.get(f"/fields/{field['id']}/alerts")).json() == []


async def test_health_answers_without_api_key(app: FastAPI) -> None:
    async with api_client(app) as anonymous:
        response = await anonymous.get("/health")

    assert response.status_code == status.HTTP_200_OK


def test_api_does_not_start_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    settings = Settings(database_url="postgresql+asyncpg://unused/unused", _env_file=None)

    with pytest.raises(RuntimeError, match="API_KEY"):
        create_app(settings)


def test_api_key_cannot_be_empty() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        Settings.model_validate(
            {"database_url": "postgresql+asyncpg://unused/unused", "api_key": ""}
        )
