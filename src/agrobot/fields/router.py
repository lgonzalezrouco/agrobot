import uuid
from collections.abc import Sequence

from fastapi import APIRouter, status

from agrobot.api.deps import SessionDep
from agrobot.fields import service
from agrobot.fields.models import Field
from agrobot.fields.schemas import FieldCreate, FieldRead, FieldUpdate

router = APIRouter(tags=["fields"])


@router.post(
    "/users/{user_id}/fields", status_code=status.HTTP_201_CREATED, response_model=FieldRead
)
async def register_field(user_id: uuid.UUID, payload: FieldCreate, session: SessionDep) -> Field:
    return await service.register(
        session, user_id, payload.name, payload.latitude, payload.longitude
    )


@router.get("/users/{user_id}/fields", response_model=list[FieldRead])
async def list_fields(user_id: uuid.UUID, session: SessionDep) -> Sequence[Field]:
    return await service.list_for_user(session, user_id)


@router.get("/fields/{field_id}", response_model=FieldRead)
async def get_field(field_id: uuid.UUID, session: SessionDep) -> Field:
    return await service.get(session, field_id)


@router.patch("/fields/{field_id}", response_model=FieldRead)
async def update_field(field_id: uuid.UUID, payload: FieldUpdate, session: SessionDep) -> Field:
    return await service.update(
        session, field_id, payload.name, payload.latitude, payload.longitude
    )


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(field_id: uuid.UUID, session: SessionDep) -> None:
    await service.delete(session, field_id)
