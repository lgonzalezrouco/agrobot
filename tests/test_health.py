from collections.abc import AsyncIterator

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from agrobot.api.app import create_app
from agrobot.api.deps import get_session
from agrobot.core.config import Settings


async def test_health_reports_ok_when_database_is_reachable(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_end_to_end_through_app_lifespan(settings: Settings) -> None:
    app = create_app(settings)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/health")

    assert response.status_code == status.HTTP_200_OK


async def test_health_reports_503_when_database_is_unreachable(app: FastAPI) -> None:
    class BrokenSession:
        async def execute(self, *_: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    async def broken_session() -> AsyncIterator[BrokenSession]:
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"status": "degraded", "database": "unavailable"}
