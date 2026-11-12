import uuid
from collections.abc import Sequence

from fastapi import APIRouter, status

from agrobot.alerts import service
from agrobot.alerts.models import Alert
from agrobot.alerts.schemas import AlertCreate, AlertRead, AlertUpdate
from agrobot.api.deps import SessionDep

router = APIRouter(tags=["alerts"])


@router.post(
    "/fields/{field_id}/alerts", status_code=status.HTTP_201_CREATED, response_model=AlertRead
)
async def configure_alert(field_id: uuid.UUID, payload: AlertCreate, session: SessionDep) -> Alert:
    return await service.configure(
        session, field_id, payload.weather_event_type, payload.threshold, payload.active
    )


@router.get("/fields/{field_id}/alerts", response_model=list[AlertRead])
async def list_alerts(field_id: uuid.UUID, session: SessionDep) -> Sequence[Alert]:
    return await service.list_for_field(session, field_id)


@router.get("/alerts/{alert_id}", response_model=AlertRead)
async def get_alert(alert_id: uuid.UUID, session: SessionDep) -> Alert:
    return await service.get(session, alert_id)


@router.patch("/alerts/{alert_id}", response_model=AlertRead)
async def update_alert(alert_id: uuid.UUID, payload: AlertUpdate, session: SessionDep) -> Alert:
    return await service.update(session, alert_id, payload.threshold, payload.active)


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert_id: uuid.UUID, session: SessionDep) -> None:
    await service.delete(session, alert_id)
