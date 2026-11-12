import uuid
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, status

from agrobot.alerts import service
from agrobot.alerts.models import Alert
from agrobot.alerts.schemas import AlertCreate, AlertRead, AlertUpdate
from agrobot.api.deps import SessionDep
from agrobot.core.errors import ConflictError, NotFoundError

router = APIRouter(tags=["alerts"])


@router.post(
    "/fields/{field_id}/alerts", status_code=status.HTTP_201_CREATED, response_model=AlertRead
)
async def configure_alert(field_id: uuid.UUID, payload: AlertCreate, session: SessionDep) -> Alert:
    try:
        return await service.configure(
            session, field_id, payload.weather_event_type, payload.threshold, payload.active
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/fields/{field_id}/alerts", response_model=list[AlertRead])
async def list_alerts(field_id: uuid.UUID, session: SessionDep) -> Sequence[Alert]:
    try:
        return await service.list_for_field(session, field_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/alerts/{alert_id}", response_model=AlertRead)
async def get_alert(alert_id: uuid.UUID, session: SessionDep) -> Alert:
    try:
        return await service.get(session, alert_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch("/alerts/{alert_id}", response_model=AlertRead)
async def update_alert(alert_id: uuid.UUID, payload: AlertUpdate, session: SessionDep) -> Alert:
    try:
        return await service.update(session, alert_id, payload.threshold, payload.active)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert_id: uuid.UUID, session: SessionDep) -> None:
    try:
        await service.delete(session, alert_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
