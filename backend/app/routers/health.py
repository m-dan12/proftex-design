"""`GET /api/health` и действия при старте сервиса.

Старт подключён как lifespan этого роутера: `main.py` (владелец T01) подключает роутер,
и FastAPI выполняет его lifespan при запуске приложения.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from shutil import disk_usage
from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from app.config import Mode, get_settings, setup_logging
from app.db import init_db

log = logging.getLogger(__name__)

DEGRADED_BELOW_PCT = 10.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings)
    init_db(settings)
    log.info("Сервис запущен: режим %s, данные в %s", settings.mode, settings.data_dir)
    yield


router = APIRouter(lifespan=lifespan)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    mode: Mode
    disk_free_pct: float


def disk_free_pct(path: Path) -> float:
    """Свободное место на томе с данными, в процентах (по ближайшей существующей папке)."""
    while not path.exists() and path != path.parent:
        path = path.parent
    usage = disk_usage(path)
    return round(usage.free * 100 / usage.total, 1) if usage.total else 0.0


@router.get("/health", response_model=Health)
def get_health() -> Health:
    settings = get_settings()
    free = disk_free_pct(settings.data_dir)
    status = "degraded" if free < DEGRADED_BELOW_PCT else "ok"
    return Health(status=status, mode=settings.mode, disk_free_pct=free)
