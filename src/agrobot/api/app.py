from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agrobot.api import health
from agrobot.core.config import Settings, get_settings
from agrobot.core.db import create_engine, create_session_factory
from agrobot.core.logging import configure_logging
from agrobot.users import router as users


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
    app.include_router(health.router)
    app.include_router(users.router)
    return app
