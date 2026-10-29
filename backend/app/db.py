"""SQLite: подключение, схема, миграции и восстановление после перезапуска.

База — один файл `DATA_DIR/app.db` в режиме WAL с включёнными внешними ключами.
Версия схемы хранится в `PRAGMA user_version`; новая версия схемы — новый элемент
в `MIGRATIONS`, старые элементы не меняются.

Время хранится строкой ISO 8601 в UTC (`2026-10-29T13:36:33Z`), деньги — целыми
микродолларами (`cost_micro_usd`), флаги — 0 и 1.
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

STATUSES = ("pending", "running", "done", "error")
INTERRUPTED_ERROR = "прервано перезапуском сервиса"
BUSY_TIMEOUT_MS = 5000

_NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"

MIGRATIONS: list[str] = [
    # 1: три таблицы из раздела 5 ТЗ.
    f"""
    CREATE TABLE users (
        id                    INTEGER PRIMARY KEY,
        username              TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        password_hash         TEXT    NOT NULL,
        is_admin              INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
        is_active             INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        daily_limit_micro_usd INTEGER CHECK (daily_limit_micro_usd >= 0),
        created_at            TEXT    NOT NULL DEFAULT ({_NOW_SQL})
    );

    CREATE TABLE generations (
        id                 INTEGER PRIMARY KEY,
        user_id            INTEGER NOT NULL REFERENCES users (id),
        parent_id          INTEGER REFERENCES generations (id) ON DELETE SET NULL,
        batch_id           TEXT    NOT NULL,
        variant_idx        INTEGER NOT NULL DEFAULT 0 CHECK (variant_idx BETWEEN 0 AND 3),
        model              TEXT    NOT NULL,
        quality            TEXT    NOT NULL,
        size               TEXT    NOT NULL,
        input_fidelity     TEXT    CHECK (input_fidelity IN ('low', 'high')),
        output_format      TEXT    NOT NULL DEFAULT 'jpeg'
                                   CHECK (output_format IN ('jpeg', 'png', 'webp')),
        prompt             TEXT    NOT NULL,
        status             TEXT    NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending', 'running', 'done', 'error')),
        error              TEXT,
        shared             INTEGER NOT NULL DEFAULT 1 CHECK (shared IN (0, 1)),
        input_text_tokens  INTEGER NOT NULL DEFAULT 0 CHECK (input_text_tokens >= 0),
        input_image_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_image_tokens >= 0),
        output_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
        cost_micro_usd     INTEGER NOT NULL DEFAULT 0 CHECK (cost_micro_usd >= 0),
        result_path        TEXT,
        thumb_path         TEXT,
        created_at         TEXT    NOT NULL DEFAULT ({_NOW_SQL}),
        finished_at        TEXT,
        UNIQUE (batch_id, variant_idx)
    );

    CREATE TABLE generation_inputs (
        id                   INTEGER PRIMARY KEY,
        generation_id        INTEGER NOT NULL REFERENCES generations (id) ON DELETE CASCADE,
        idx                  INTEGER NOT NULL CHECK (idx >= 0),
        path                 TEXT    NOT NULL,
        source_generation_id INTEGER REFERENCES generations (id) ON DELETE SET NULL,
        filename             TEXT,
        UNIQUE (generation_id, idx)
    );

    -- Галереи: «Мои» и фильтр по автору в «Общей», курсор по id.
    CREATE INDEX ix_generations_user ON generations (user_id, id);
    -- «Общая»: только видимые всем, курсор по id.
    CREATE INDEX ix_generations_shared ON generations (id) WHERE shared = 1;
    -- Расходы и дневной потолок: за период, всего и по пользователю.
    CREATE INDEX ix_generations_created ON generations (created_at);
    CREATE INDEX ix_generations_user_created ON generations (user_id, created_at);
    -- Очередь и восстановление после перезапуска.
    CREATE INDEX ix_generations_active ON generations (status)
        WHERE status IN ('pending', 'running');
    -- Внешние ключи с ON DELETE SET NULL без полного просмотра таблиц.
    CREATE INDEX ix_generations_parent ON generations (parent_id);
    CREATE INDEX ix_inputs_source ON generation_inputs (source_generation_id);
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)
TABLES = ("users", "generations", "generation_inputs")


def now_iso() -> str:
    """Текущее время в формате, в котором оно хранится в базе."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Новое подключение с нужными PRAGMA. Подключения не делятся между потоками."""
    path = get_settings().db_path if path is None else path
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    # В WAL обычной синхронизации достаточно: при сбое питания теряется только последняя запись.
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def session(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Подключение на один блок работы: коммит при успехе, откат при исключении."""
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """Зависимость FastAPI: `db: sqlite3.Connection = Depends(get_db)`."""
    with session() as conn:
        yield conn


def migrate(conn: sqlite3.Connection) -> int:
    """Довести схему до `SCHEMA_VERSION`. Возвращает версию до миграции."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"База новее кода: версия схемы {current}, код знает до {SCHEMA_VERSION}"
        )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        # executescript коммитит сам, поэтому транзакцию открываем явно внутри скрипта.
        conn.executescript(
            f"BEGIN;\n{MIGRATIONS[version - 1]}\nPRAGMA user_version = {version};\nCOMMIT;"
        )
        log.info("Схема базы обновлена до версии %d", version)
    return current


def recover_interrupted(conn: sqlite3.Connection) -> int:
    """Задачи, оставшиеся в `pending`/`running` после перезапуска, переводятся в `error`.

    Стоимость ставится 0, хотя запрос к OpenAI мог уйти и быть оплачен (риск из раздела 12 ТЗ).
    """
    with conn:
        cursor = conn.execute(
            "UPDATE generations SET status = 'error', error = ?, cost_micro_usd = 0,"
            " finished_at = ? WHERE status IN ('pending', 'running')",
            (INTERRUPTED_ERROR, now_iso()),
        )
    return cursor.rowcount


def init_db(settings: Settings | None = None) -> int:
    """Старт сервиса: папка данных, WAL, схема, восстановление прерванных задач.

    Повторный вызов на готовой базе ничего не меняет, кроме восстановления.
    Возвращает число задач, переведённых в `error`.
    """
    settings = get_settings() if settings is None else settings
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if mode != "wal":
            raise RuntimeError(f"SQLite не включил WAL (journal_mode={mode})")
        migrate(conn)
        interrupted = recover_interrupted(conn)
    finally:
        conn.close()
    if interrupted:
        log.warning("Прервано перезапуском: %d задач переведены в error", interrupted)
    return interrupted
