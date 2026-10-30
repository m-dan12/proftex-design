"""Зависимости FastAPI для авторизации.

T01 фиксирует сигнатуры, реализацию на подписанной cookie-сессии пишет T08.
В тестах других задач `current_user` подменяется через `app.dependency_overrides`.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    is_admin: bool


def current_user(request: Request) -> CurrentUser:
    """Пользователь текущей сессии.

    401, если сессии нет, она истекла или пользователь заблокирован.
    """
    raise HTTPException(status_code=501, detail="Не реализовано: T08")


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Тот же пользователь, но только администратор; иначе 403."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Нужны права администратора")
    return user
