"""Администрирование пользователей: список, создание, блокировка, роль, лимит, сброс пароля.

Пароли хранятся только хешем scrypt; сброшенный пароль возвращается один раз в ответе.
Последнего активного администратора нельзя заблокировать или лишить прав (409).
"""

import logging
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, model_validator

from app.db import get_db
from app.deps import CurrentUser, generate_password, hash_password, require_admin

log = logging.getLogger(__name__)

router = APIRouter()

USERNAME_PATTERN = r"^[A-Za-z0-9._-]{3,32}$"


class User(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    daily_limit_micro_usd: int | None
    created_at: datetime


class UserList(BaseModel):
    items: list[User]


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=256)
    is_admin: bool = False


class UserPatch(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    daily_limit_micro_usd: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _not_empty(self) -> "UserPatch":
        if not self.model_fields_set:
            raise ValueError("Нечего менять")
        for name in ("is_active", "is_admin"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name}: нужно true или false")
        return self


class PasswordReset(BaseModel):
    password: str


def user_out(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        daily_limit_micro_usd=row["daily_limit_micro_usd"],
        created_at=row["created_at"],
    )


def _get_user(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return row


@router.get("/admin/users", response_model=UserList)
def list_users(
    _: CurrentUser = Depends(require_admin), db: sqlite3.Connection = Depends(get_db)
) -> UserList:
    rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return UserList(items=[user_out(row) for row in rows])


@router.post("/admin/users", response_model=User, status_code=201)
def create_user(
    body: UserCreate,
    admin: CurrentUser = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> User:
    try:
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (body.username, hash_password(body.password), int(body.is_admin)),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Такой логин уже есть") from None
    log.info("%s создал пользователя %s", admin.username, body.username)
    return user_out(_get_user(db, cursor.lastrowid))


@router.patch("/admin/users/{id}", response_model=User)
def update_user(
    body: UserPatch,
    id: int = Path(ge=1),
    admin: CurrentUser = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> User:
    # Проверка «последний администратор» и запись — одной транзакцией без гонок.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    row = _get_user(db, id)
    changes = body.model_dump(include=body.model_fields_set)
    is_active = changes.get("is_active", bool(row["is_active"]))
    is_admin = changes.get("is_admin", bool(row["is_admin"]))
    if row["is_admin"] and row["is_active"] and not (is_admin and is_active):
        others = db.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1 AND id != ?", (id,)
        ).fetchone()[0]
        if others == 0:
            raise HTTPException(
                status_code=409, detail="Нельзя отключить последнего администратора"
            )
    db.execute(
        "UPDATE users SET is_active = ?, is_admin = ?, daily_limit_micro_usd = ? WHERE id = ?",
        (
            int(is_active),
            int(is_admin),
            changes.get("daily_limit_micro_usd", row["daily_limit_micro_usd"]),
            id,
        ),
    )
    log.info("%s изменил пользователя %s: %s", admin.username, row["username"], sorted(changes))
    return user_out(_get_user(db, id))


@router.post("/admin/users/{id}/reset-password", response_model=PasswordReset)
def reset_user_password(
    id: int = Path(ge=1),
    admin: CurrentUser = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
) -> PasswordReset:
    row = _get_user(db, id)
    password = generate_password()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), id))
    # Сам пароль в лог не пишется; старые сессии пользователя перестают действовать.
    log.info("%s сбросил пароль пользователя %s", admin.username, row["username"])
    return PasswordReset(password=password)
