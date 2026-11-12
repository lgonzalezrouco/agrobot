from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from agrobot.models import Base
from tests.conftest import run_alembic


def _pending_diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection)
    return list(compare_metadata(context, Base.metadata))


async def test_models_and_migrations_are_in_sync(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        diff = await connection.run_sync(_pending_diff)

    assert diff == [], f"Models differ from migrations (autogenerate a revision): {diff}"


async def test_migrations_downgrade_and_upgrade_cleanly(
    engine: AsyncEngine, alembic_config: Config
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(run_alembic, alembic_config, "downgrade", "base")
        await connection.run_sync(run_alembic, alembic_config, "upgrade", "head")
