"""Заглушка из T01. Владелец файла: T02 (см. docs/OWNERSHIP.md)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _todo() -> HTTPException:
    return HTTPException(status_code=501, detail="Не реализовано: T02")


@router.get("/health")
def get_health() -> None:
    raise _todo()
