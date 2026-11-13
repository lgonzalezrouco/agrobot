import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agrobot.core.config import Settings
from agrobot.core.db import create_engine


async def test_query_exceeding_statement_timeout_fails(settings: Settings) -> None:
    engine = create_engine(settings.model_copy(update={"statement_timeout_seconds": 0.5}))
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="statement timeout"):
                await connection.execute(text("SELECT pg_sleep(5)"))
    finally:
        await engine.dispose()
