import uuid

from fastapi import APIRouter, status

from agrobot.api.deps import SessionDep
from agrobot.users import service
from agrobot.users.models import User
from agrobot.users.schemas import E164PhoneNumber, UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def register_user(payload: UserCreate, session: SessionDep) -> User:
    return await service.register(session, payload.name, payload.phone_number)


@router.get("", response_model=UserRead)
async def find_user_by_phone_number(phone_number: E164PhoneNumber, session: SessionDep) -> User:
    return await service.get_by_phone_number(session, phone_number)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, session: SessionDep) -> User:
    return await service.get(session, user_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, session: SessionDep) -> None:
    await service.delete(session, user_id)
