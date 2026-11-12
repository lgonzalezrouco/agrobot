from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from agrobot.api.app import create_app
from agrobot.api.deps import get_session
from agrobot.core.config import Settings
from agrobot.core.db import create_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:18", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def settings(postgres_url: str) -> Settings:
    return Settings(database_url=postgres_url, log_level="WARNING")


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
def app(settings: Settings, db_session: AsyncSession) -> FastAPI:
    app = create_app(settings)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
