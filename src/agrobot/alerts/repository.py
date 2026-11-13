import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agrobot.alerts.models import Alert


async def get(session: AsyncSession, alert_id: uuid.UUID) -> Alert | None:
    return await session.get(Alert, alert_id)


async def get_for_update(session: AsyncSession, alert_id: uuid.UUID) -> Alert | None:
    return await session.scalar(
        select(Alert)
        .where(Alert.id == alert_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def list_for_field(session: AsyncSession, field_id: uuid.UUID) -> Sequence[Alert]:
    return (
        await session.scalars(select(Alert).where(Alert.field_id == field_id).order_by(Alert.id))
    ).all()


async def save(session: AsyncSession, alert: Alert) -> None:
    session.add(alert)
    await session.flush()
    await session.refresh(alert)


async def delete(session: AsyncSession, alert: Alert) -> None:
    await session.delete(alert)
