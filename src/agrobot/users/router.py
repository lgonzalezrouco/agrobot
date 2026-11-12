import uuid

from fastapi import APIRouter, HTTPException, status

from agrobot.api.deps import SessionDep
from agrobot.core.errors import ConflictError, NotFoundError
from agrobot.users import service
from agrobot.users.models import User
from agrobot.users.schemas import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def register_user(payload: UserCreate, session: SessionDep) -> User:
    try:
        return await service.register(session, payload.name, payload.phone_number)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, session: SessionDep) -> User:
    try:
        return await service.get(session, user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, session: SessionDep) -> None:
    try:
        await service.delete(session, user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
