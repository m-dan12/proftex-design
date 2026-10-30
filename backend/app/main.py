"""Точка входа FastAPI.

Запускается строго одним процессом (`uvicorn app.main:app --workers 1`):
очередь генераций, семафор и счётчик попыток входа живут в памяти процесса.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from app.deps import validation_message
from app.routers import auth, generations, health, models, spending, users

API_PREFIX = "/api"
DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SpaFiles(StaticFiles):
    """Собранный фронтенд: неизвестный адрес вне `/api` отдаёт `index.html` (history-роутер)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            raw = scope["path"]
            if (
                exc.status_code != 404
                or raw.startswith(f"{API_PREFIX}/")
                or ".." in raw.split("/")
                or "." in Path(path).name
            ):
                raise
            return await super().get_response("index.html", scope)


def frontend_dist() -> Path:
    return Path(os.environ.get("FRONTEND_DIST") or DEFAULT_FRONTEND_DIST)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Любая ошибка разбора запроса — 422 с `{"detail": "текст"}`, как в контракте."""
    return JSONResponse(status_code=422, content={"detail": validation_message(exc)})


def create_app() -> FastAPI:
    app = FastAPI(title="design.proftex.tech", version="1.0.0", docs_url=None, redoc_url=None)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    for module in (auth, users, models, generations, spending, health):
        app.include_router(module.router, prefix=API_PREFIX)
    dist = frontend_dist()
    if (dist / "index.html").is_file():
        # Монтируется последним, чтобы не перекрывать маршруты `/api`.
        app.mount("/", SpaFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
