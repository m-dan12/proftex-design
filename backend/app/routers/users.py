"""Заглушка из T01. Владелец файла: T08 (см. docs/OWNERSHIP.md)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _todo() -> HTTPException:
    return HTTPException(status_code=501, detail="Не реализовано: T08")


@router.get("/admin/users")
def list_users() -> None:
    raise _todo()


@router.post("/admin/users")
def create_user() -> None:
    raise _todo()


@router.patch("/admin/users/{id}")
def update_user(id: int) -> None:
    raise _todo()


@router.post("/admin/users/{id}/reset-password")
def reset_user_password(id: int) -> None:
    raise _todo()
