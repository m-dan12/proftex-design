"""Заглушка из T01. Владелец файла: T08 (см. docs/OWNERSHIP.md)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _todo() -> HTTPException:
    return HTTPException(status_code=501, detail="Не реализовано: T08")


@router.post("/auth/login")
def login() -> None:
    raise _todo()


@router.post("/auth/logout")
def logout() -> None:
    raise _todo()


@router.get("/me")
def get_me() -> None:
    raise _todo()


@router.post("/me/password")
def change_my_password() -> None:
    raise _todo()
