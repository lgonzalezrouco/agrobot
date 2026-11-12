import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from agrobot.core.config import get_settings
from agrobot.models import Base

config = context.config
# Tests pass an open connection here; they own logging and the event loop.
handed_connection: Connection | None = config.attributes.get("connection")

if config.config_file_name is not None and handed_connection is None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if handed_connection is not None:
    do_run_migrations(handed_connection)
else:
    asyncio.run(run_async_migrations())
