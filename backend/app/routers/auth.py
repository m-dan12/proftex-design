"""Вход, выход, профиль и смена своего пароля.

Неудачные попытки входа считаются в памяти процесса по IP клиента (сервис работает
одним процессом Uvicorn): не больше 5 за минуту, дальше 429. IP берётся из
`X-Forwarded-For`, только если соединение пришло от доверенного прокси (`TRUSTED_PROXIES`).
"""

import ipaddress
import logging
import sqlite3
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import Settings, get_settings, setup_logging
from app.db import get_db, init_db
from app.deps import (
    CurrentUser,
    clear_session_cookie,
    current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.manage import ensure_admin
from app.routers.users import User, user_out

log = logging.getLogger(__name__)

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_S = 60.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Автосоздание администратора из `ADMIN_USERNAME`/`ADMIN_PASSWORD` при пустой базе.

    Этот lifespan выполняется раньше lifespan из `health.py` (роутер подключён первым),
    поэтому сам готовит базу; повторный `init_db` там безопасен.
    """
    settings = get_settings()
    setup_logging(settings)
    init_db(settings)
    ensure_admin(settings)
    yield


router = APIRouter(lifespan=lifespan)


# --- Лимит попыток входа -------------------------------------------------------


class LoginLimiter:
    """Скользящее окно неудачных попыток по ключу (IP)."""

    def __init__(self, max_failures: int = LOGIN_MAX_FAILURES, window: float = LOGIN_WINDOW_S):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float] | None:
        times = self._failures.get(key)
        while times and now - times[0] >= self.window:
            times.popleft()
        if times is not None and not times:
            del self._failures[key]
            return None
        return times

    def blocked(self, key: str) -> bool:
        with self._lock:
            times = self._recent(key, time.monotonic())
            return times is not None and len(times) >= self.max_failures

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._failures) > 10_000:
                for stale in list(self._failures):
                    self._recent(stale, now)
            self._failures.setdefault(key, deque()).append(now)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginLimiter()


def _is_trusted(address: str, settings: Settings) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in settings.trusted_proxies)


def client_ip(request: Request, settings: Settings | None = None) -> str:
    """IP клиента: адрес соединения, а за доверенным прокси — из `X-Forwarded-For`.

    Цепочка читается справа налево, доверенные прокси пропускаются: первый недоверенный
    адрес и есть клиент (левые элементы клиент мог подставить сам).
    """
    settings = get_settings() if settings is None else settings
    peer = request.client.host if request.client else ""
    if not _is_trusted(peer, settings):
        return peer
    chain = [
        part.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for part in header.split(",")
        if part.strip()
    ]
    for address in reversed(chain):
        if not _is_trusted(address, settings):
            return address
    return chain[0] if chain else peer


# --- Операции ------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


@router.post("/auth/login", response_model=User)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
) -> User:
    ip = client_ip(request)
    if login_limiter.blocked(ip):
        raise HTTPException(status_code=429, detail="Слишком много попыток входа, подождите минуту")
    row = db.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if not verify_password(body.password, row["password_hash"] if row else None):
        login_limiter.fail(ip)
        log.info("Неудачный вход с %s", ip)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Пользователь заблокирован")
    set_session_cookie(response, row["id"], row["password_hash"])
    log.info("Вход: %s", row["username"])
    return user_out(row)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, _: CurrentUser = Depends(current_user)) -> Response:
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=User)
def get_me(
    user: CurrentUser = Depends(current_user), db: sqlite3.Connection = Depends(get_db)
) -> User:
    row = db.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Нужно войти")
    return user_out(row)


@router.post("/me/password", status_code=204)
def change_my_password(
    body: PasswordChange,
    user: CurrentUser = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None or not verify_password(body.old_password, row["password_hash"]):
        # 422, а не 401: фронтенд на любой 401 завершает сессию (так же делает мок MSW).
        raise HTTPException(status_code=422, detail="Старый пароль неверный")
    new_hash = hash_password(body.new_password)
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user.id))
    # Старые сессии (в том числе на других устройствах) больше не действуют, эта продлевается.
    response = Response(status_code=204)
    set_session_cookie(response, user.id, new_hash)
    log.info("Пароль изменён: %s", user.username)
    return response
