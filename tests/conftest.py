import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from agrobot.api.app import create_app
from agrobot.api.deps import get_session
from agrobot.core.config import Settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.fields.models import Field
from agrobot.locations import service as locations
from agrobot.models import Base
from agrobot.users.models import User

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_KEY = "test-api-key"
TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")


def local_evening_after_utc_midnight() -> tuple[datetime, date]:
    instant = datetime.combine(datetime.now(UTC).date() + timedelta(days=1), time(1), UTC)
    local_today = instant.astimezone(TIMEZONE).date()
    assert local_today < instant.date()
    return instant, local_today


def freeze_clock(monkeypatch: pytest.MonkeyPatch, module: ModuleType, instant: datetime) -> None:
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=instant.astimezone))


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:18", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def settings(postgres_url: str) -> Settings:
    return Settings(database_url=postgres_url, api_key=SecretStr(API_KEY), log_level="WARNING")


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def run_alembic(connection: Connection, config: Config, action: str, revision: str) -> None:
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


@pytest.fixture(scope="session")
async def engine(settings: Settings, alembic_config: Config) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(run_alembic, alembic_config, "upgrade", "head")
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    # create_savepoint turns commit() in code under test into a savepoint release.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with session_factory() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
async def committed_session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield create_session_factory(engine)
    async with engine.begin() as connection:
        tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def app(settings: Settings, db_session: AsyncSession) -> FastAPI:
    app = create_app(settings)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return app


def api_client(app: FastAPI, headers: dict[str, str] | None = None) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with api_client(app, {"X-API-Key": API_KEY}) as client:
        yield client


async def register_user(client: AsyncClient, phone_number: str = "+5491122334455") -> str:
    response = await client.post("/users", json={"name": "Ana", "phone_number": phone_number})
    assert response.status_code == status.HTTP_201_CREATED
    user_id: str = response.json()["id"]
    return user_id


async def register_field(
    client: AsyncClient,
    user_id: str,
    latitude: float = 1,
    longitude: float = 1,
    name: str = "Lote 1",
) -> dict[str, Any]:
    response = await client.post(
        f"/users/{user_id}/fields",
        json={"name": name, "latitude": latitude, "longitude": longitude},
    )
    assert response.status_code == status.HTTP_201_CREATED
    body: dict[str, Any] = response.json()
    return body


async def create_field(
    session_factory: async_sessionmaker[AsyncSession], latitude: float = 1, longitude: float = 1
) -> Field:
    async with session_factory() as session:
        user = User(name="Ana", phone_number=f"+549{uuid.uuid4().int % 10**10:010d}")
        location = await locations.get_or_create(session, latitude, longitude)
        session.add(user)
        await session.flush()
        field = Field(
            user_id=user.id, name="Lote", latitude=latitude, longitude=longitude, location=location
        )
        session.add(field)
        await session.commit()
        return field
