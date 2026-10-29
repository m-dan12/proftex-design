"""Заглушка из T01. Владелец файла: T09 (см. docs/OWNERSHIP.md)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _todo() -> HTTPException:
    return HTTPException(status_code=501, detail="Не реализовано: T09")


@router.post("/generations")
def create_generation() -> None:
    raise _todo()


@router.get("/generations")
def list_generations() -> None:
    raise _todo()


@router.get("/generations/{id}")
def get_generation(id: int) -> None:
    raise _todo()


@router.patch("/generations/{id}")
def update_generation(id: int) -> None:
    raise _todo()


@router.delete("/generations/{id}")
def delete_generation(id: int) -> None:
    raise _todo()


@router.get("/generations/{id}/image")
def get_generation_image(id: int) -> None:
    raise _todo()
