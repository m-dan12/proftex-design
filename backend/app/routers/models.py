"""Заглушка из T01. Владелец файла: T04 (см. docs/OWNERSHIP.md)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _todo() -> HTTPException:
    return HTTPException(status_code=501, detail="Не реализовано: T04")


@router.get("/models")
def list_models() -> None:
    raise _todo()
