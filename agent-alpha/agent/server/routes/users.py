from __future__ import annotations

from fastapi import APIRouter

from agent.server.deps import state_store
from agent.server.models import UserInfo, UserPatch

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserInfo])
def list_users():
    return [UserInfo(**user) for user in state_store.list_users()]


@router.get("/current", response_model=UserInfo)
def get_current_user():
    return UserInfo(**state_store.list_users()[0])


@router.patch("/current", response_model=UserInfo)
def update_current_user(body: UserPatch):
    return UserInfo(**state_store.update_current_user(body.model_dump(exclude_none=True)))

