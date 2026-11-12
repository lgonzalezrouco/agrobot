import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.users.models import User


async def get(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_by_phone_number(session: AsyncSession, phone_number: str) -> User | None:
    return await session.scalar(select(User).where(User.phone_number == phone_number))


async def add(session: AsyncSession, user: User) -> None:
    session.add(user)
    await session.flush()
    await session.refresh(user)


async def delete(session: AsyncSession, user: User) -> None:
    await session.delete(user)
