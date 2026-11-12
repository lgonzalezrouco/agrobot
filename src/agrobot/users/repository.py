import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.users.models import User


async def get(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def add(session: AsyncSession, user: User) -> None:
    session.add(user)
    await session.flush()
    await session.refresh(user)


async def delete(session: AsyncSession, user: User) -> None:
    await session.delete(user)
