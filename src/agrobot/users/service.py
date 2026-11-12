import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.core.errors import ConflictError, NotFoundError
from agrobot.users import repository
from agrobot.users.models import User

logger = structlog.get_logger(__name__)


async def register(session: AsyncSession, name: str, phone_number: str) -> User:
    user = User(name=name, phone_number=phone_number)
    try:
        await repository.add(session, user)
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("phone number already registered") from exc
    await session.commit()
    logger.info("users.registered", user_id=user.id)
    return user


async def get(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await repository.get(session, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return user


async def get_by_phone_number(session: AsyncSession, phone_number: str) -> User:
    user = await repository.get_by_phone_number(session, phone_number)
    if user is None:
        raise NotFoundError("user not found")
    return user


async def delete(session: AsyncSession, user_id: uuid.UUID) -> None:
    user = await get(session, user_id)
    await repository.delete(session, user)
    await session.commit()
    logger.info("users.deleted", user_id=user_id)
