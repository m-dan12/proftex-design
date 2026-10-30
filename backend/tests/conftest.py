"""Общие фикстуры pytest.

Каждый тест получает свою пустую папку данных и чистое окружение без ключа OpenAI,
поэтому ни один тест не трогает настоящий `/data` и не уходит в OpenAI.

Основное для тестов других задач:
- `client` — TestClient с выполненным стартом (база создана);
- `db` — подключение к базе этого теста;
- `make_user`, `user`, `admin` — пользователи в базе;
- `login_as(user)` — подменить `current_user` без настоящего входа (T08 не нужен);
- `make_generation` — работа в базе с разумными значениями по умолчанию.
"""

import sqlite3
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.config import Settings, get_settings, reset_settings
from app.deps import CurrentUser, current_user
from app.main import app as fastapi_app

ENV_VARS = (
    "OPENAI_API_KEY",
    "SECRET_KEY",
    "DATA_DIR",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "COOKIE_SECURE",
    "MAX_PARALLEL",
    "TRUSTED_PROXIES",
    "SPEND_CAP_DAILY_USD",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Изолированное окружение: пустая папка данных, режим заглушки, без потолка трат.

    Чтобы поменять переменную в тесте: `env.setenv(...)`, затем `reset_settings()`.
    """
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    reset_settings()
    yield monkeypatch
    reset_settings()
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def data_dir(settings: Settings) -> Path:
    return settings.data_dir


@pytest.fixture
def app() -> Any:
    return fastapi_app


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    """Клиент с выполненным стартом сервиса (lifespan): база создана и мигрирована."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Подключение к базе теста; база создаётся, если старта ещё не было."""
    dbmod.init_db(settings)
    conn = dbmod.connect(settings.db_path)
    yield conn
    conn.close()


@pytest.fixture
def make_user(db: sqlite3.Connection) -> Callable[..., CurrentUser]:
    """Создать пользователя: `make_user("anna")`, `make_user("boss", is_admin=True)`."""

    def factory(
        username: str | None = None,
        *,
        is_admin: bool = False,
        is_active: bool = True,
        password_hash: str = "test-hash",
    ) -> CurrentUser:
        username = username or f"user-{uuid.uuid4().hex[:8]}"
        with db:
            cursor = db.execute(
                "INSERT INTO users (username, password_hash, is_admin, is_active)"
                " VALUES (?, ?, ?, ?)",
                (username, password_hash, int(is_admin), int(is_active)),
            )
        return CurrentUser(id=cursor.lastrowid, username=username, is_admin=is_admin)

    return factory


@pytest.fixture
def user(make_user: Callable[..., CurrentUser]) -> CurrentUser:
    return make_user("designer")


@pytest.fixture
def admin(make_user: Callable[..., CurrentUser]) -> CurrentUser:
    return make_user("admin", is_admin=True)


@pytest.fixture
def login_as(app: Any) -> Callable[[CurrentUser | None], None]:
    """Подменить текущего пользователя для запросов; `login_as(None)` — снова аноним."""

    def switch(who: CurrentUser | None) -> None:
        if who is None:
            app.dependency_overrides.pop(current_user, None)
        else:
            app.dependency_overrides[current_user] = lambda: who

    return switch


@pytest.fixture
def make_generation(db: sqlite3.Connection) -> Callable[..., int]:
    """Создать работу: `make_generation(user.id, status="done", shared=0)`; возвращает id."""

    def factory(user_id: int, **fields: Any) -> int:
        row = {
            "batch_id": uuid.uuid4().hex,
            "variant_idx": 0,
            "model": "gpt-image-1",
            "quality": "medium",
            "size": "1024x1024",
            "output_format": "jpeg",
            "prompt": "тестовый промпт",
            "status": "done",
            **fields,
            "user_id": user_id,
        }
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with db:
            cursor = db.execute(
                f"INSERT INTO generations ({columns}) VALUES ({marks})", tuple(row.values())
            )
        return cursor.lastrowid

    return factory
