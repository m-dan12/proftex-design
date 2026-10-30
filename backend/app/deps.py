"""Авторизация: хеши scrypt, подписанная cookie-сессия, `current_user` и `require_admin`.

Сессия — cookie `session` вида `<данные>.<подпись>`: id пользователя, время входа и отпечаток
хеша пароля, подписанные HMAC-SHA256 на `SECRET_KEY`. Состояния на сервере нет; пользователь
читается из базы на каждом запросе, поэтому блокировка действует сразу, а смена или сброс
пароля завершают все старые сессии (меняется отпечаток).

В тестах других задач `current_user` подменяется через `app.dependency_overrides`.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from app.config import Settings, get_settings
from app.db import session

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 30 * 24 * 3600

# Параметры scrypt: 16 МБ памяти на проверку, ~50 мс.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    is_admin: bool


# --- Пароли --------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    """Хеш в формате `scrypt$N$r$p$соль$хеш` (соль и хеш в base64url)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


# Для входа под несуществующим логином: проверка занимает столько же времени.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password(password: str, stored: str | None) -> bool:
    """Сравнить пароль с хешем; неизвестный формат — всегда `False`."""
    try:
        scheme, n, r, p, salt, digest = (stored or _DUMMY_HASH).split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return stored is not None and hmac.compare_digest(actual, expected)


GENERATED_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password(length: int = 12) -> str:
    """Случайный пароль без похожих символов (0/O, 1/l/I); есть строчная, заглавная и цифра."""
    while True:
        password = "".join(secrets.choice(GENERATED_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


# --- Сессия --------------------------------------------------------------------


def _password_mark(password_hash: str) -> str:
    """Отпечаток хеша пароля: после смены пароля старые cookie не проходят проверку."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def _sign(body: str, settings: Settings) -> str:
    mac = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return _b64(mac)


def make_session_token(user_id: int, password_hash: str, settings: Settings | None = None) -> str:
    settings = get_settings() if settings is None else settings
    payload = {"uid": user_id, "iat": int(time.time()), "pwd": _password_mark(password_hash)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body, settings)}"


def read_session_token(token: str, settings: Settings | None = None) -> dict[str, Any] | None:
    """Данные сессии, если подпись верна и срок не истёк; иначе `None`."""
    settings = get_settings() if settings is None else settings
    body, _, signature = token.partition(".")
    if not body or not hmac.compare_digest(signature, _sign(body, settings)):
        return None
    try:
        payload = json.loads(_unb64(body))
        issued = int(payload["iat"])
        int(payload["uid"])
        str(payload["pwd"])
    except (ValueError, TypeError, KeyError):
        return None
    if not 0 <= time.time() - issued < SESSION_MAX_AGE:
        return None
    return payload


def set_session_cookie(response: Response, user_id: int, password_hash: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user_id, password_hash, settings),
        max_age=SESSION_MAX_AGE,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )


def _unauthorized(detail: str = "Нужно войти") -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def current_user(request: Request) -> CurrentUser:
    """Пользователь текущей сессии.

    401, если сессии нет, она истекла, пароль сменился или пользователь заблокирован.
    """
    token = request.cookies.get(SESSION_COOKIE)
    payload = read_session_token(token) if token else None
    if payload is None:
        raise _unauthorized()
    with session() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, is_admin, is_active FROM users WHERE id = ?",
            (payload["uid"],),
        ).fetchone()
    if row is None or not hmac.compare_digest(_password_mark(row["password_hash"]), payload["pwd"]):
        raise _unauthorized("Сессия устарела, войдите снова")
    if not row["is_active"]:
        raise _unauthorized("Пользователь заблокирован")
    return CurrentUser(id=row["id"], username=row["username"], is_admin=bool(row["is_admin"]))


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Тот же пользователь, но только администратор; иначе 403."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Нужны права администратора")
    return user


# --- Ошибки валидации строкой, как в контракте ----------------------------------
# Единый обработчик 422 подключён в `main.py`.


def validation_message(exc: RequestValidationError) -> str:
    """Понятный русский текст первой ошибки вместо списка pydantic."""
    errors = exc.errors()
    if not errors:
        return "Неверные данные"
    error = errors[0]
    loc = [str(part) for part in error.get("loc", ()) if part not in ("body", "path", "query")]
    field = ".".join(loc)
    ctx = error.get("ctx") or {}
    kind = error.get("type", "")
    if kind == "value_error" and ctx.get("error"):
        return str(ctx["error"])
    if kind == "missing":
        return f"Не заполнено поле «{field}»" if field else "Нет тела запроса"
    if kind == "string_too_short":
        return f"Поле «{field}»: не короче {ctx.get('min_length')} символов"
    if kind == "string_too_long":
        return f"Поле «{field}»: не длиннее {ctx.get('max_length')} символов"
    if kind == "string_pattern_mismatch" and field == "username":
        return "Логин: 3–32 символа, латиница, цифры, точка, дефис или подчёркивание"
    if kind in ("greater_than_equal", "greater_than"):
        return f"Поле «{field}»: значение слишком маленькое"
    if not field:
        return "Неверное тело запроса"
    return f"Поле «{field}»: неверное значение"
