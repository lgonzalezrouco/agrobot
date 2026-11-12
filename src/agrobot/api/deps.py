import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def api_key_guard(api_key: SecretStr) -> Callable[[str | None], Awaitable[None]]:
    expected = api_key.get_secret_value().encode()

    async def check(
        given: Annotated[str | None, Security(APIKeyHeader(name="X-API-Key", auto_error=False))],
    ) -> None:
        if given is None or not secrets.compare_digest(given.encode(), expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key")

    return check
