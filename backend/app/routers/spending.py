"""Заглушка из T01. Владелец файла: T10 (см. docs/OWNERSHIP.md)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _todo() -> HTTPException:
    return HTTPException(status_code=501, detail="Не реализовано: T10")


@router.get("/spending/me")
def get_my_spending() -> None:
    raise _todo()


@router.get("/admin/spending")
def get_admin_spending() -> None:
    raise _todo()


@router.get("/admin/spending.csv")
def get_admin_spending_csv() -> None:
    raise _todo()
