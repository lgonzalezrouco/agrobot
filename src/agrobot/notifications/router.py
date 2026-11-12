import uuid
from collections.abc import Sequence

from fastapi import APIRouter

from agrobot.api.deps import SessionDep
from agrobot.notifications import service
from agrobot.notifications.models import Notification
from agrobot.notifications.schemas import NotificationRead

router = APIRouter(tags=["notifications"])


@router.get("/alerts/{alert_id}/notifications", response_model=list[NotificationRead])
async def list_alert_notifications(
    alert_id: uuid.UUID, session: SessionDep
) -> Sequence[Notification]:
    return await service.list_for_alert(session, alert_id)
