from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from agrobot.alerts import router as alerts
from agrobot.api import health
from agrobot.core.config import Settings, get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.errors import ConflictError, NotFoundError
from agrobot.core.logging import configure_logging
from agrobot.fields import router as fields
from agrobot.users import router as users


def _error_handler(status_code: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status_code)

    return handle


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(settings)
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Agrobot", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(NotFoundError, _error_handler(status.HTTP_404_NOT_FOUND))
    app.add_exception_handler(ConflictError, _error_handler(status.HTTP_409_CONFLICT))
    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(fields.router)
    app.include_router(alerts.router)
    return app
