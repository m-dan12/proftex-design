"""Точка входа FastAPI.

Запускается строго одним процессом (`uvicorn app.main:app --workers 1`):
очередь генераций, семафор и счётчик попыток входа живут в памяти процесса.
"""

from fastapi import FastAPI

from app.routers import auth, generations, health, models, spending, users

API_PREFIX = "/api"


def create_app() -> FastAPI:
    app = FastAPI(title="design.proftex.tech", version="1.0.0", docs_url=None, redoc_url=None)
    for module in (auth, users, models, generations, spending, health):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
