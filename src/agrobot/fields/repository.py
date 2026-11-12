import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.fields.models import Field


async def get(session: AsyncSession, field_id: uuid.UUID) -> Field | None:
    return await session.get(Field, field_id)


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Field]:
    return (
        await session.scalars(select(Field).where(Field.user_id == user_id).order_by(Field.id))
    ).all()


async def save(session: AsyncSession, field: Field) -> None:
    session.add(field)
    await session.flush()
    await session.refresh(field)


async def delete(session: AsyncSession, field: Field) -> None:
    await session.delete(field)
