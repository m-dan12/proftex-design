"""T02: конфигурация, база, /api/health, восстановление после перезапуска, логи без секретов.

Номера в названиях тестов — показатели готовности из карточки T02.
"""

import logging
import sqlite3
from collections import namedtuple
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.config import get_settings, load_settings, reset_settings
from app.routers import health

FAKE_KEY = "sk-proj-TESTKEY0123456789abcdefABCDEF_-xyz"
Usage = namedtuple("Usage", "total used free")


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {name for (name,) in rows}
    finally:
        conn.close()


# 1. Пустая папка → app.db со всеми таблицами; повторный старт ничего не ломает.


def test_1_start_on_empty_dir_creates_db(client: TestClient, data_dir: Path) -> None:
    db_path = data_dir / "app.db"
    assert db_path.exists()
    assert set(dbmod.TABLES) <= _tables(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
    conn.close()


def test_1_restart_keeps_data(app, data_dir: Path, make_user, make_generation) -> None:
    anna = make_user("anna")
    gen_id = make_generation(anna.id, status="done", cost_micro_usd=42_000)
    for _ in range(2):
        with TestClient(app) as test_client:
            assert test_client.get("/api/health").status_code == 200
    with dbmod.session(data_dir / "app.db") as conn:
        assert conn.execute("SELECT username FROM users").fetchall()[0][0] == "anna"
        row = conn.execute("SELECT status, cost_micro_usd FROM generations WHERE id = ?", (gen_id,))
        assert tuple(row.fetchone()) == ("done", 42_000)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION


def test_1_newer_schema_is_refused(settings) -> None:
    dbmod.init_db(settings)
    with dbmod.session(settings.db_path) as conn:
        conn.execute(f"PRAGMA user_version = {dbmod.SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="новее"):
        dbmod.init_db(settings)


def test_1_schema_constraints(db, make_user, make_generation) -> None:
    anna = make_user("anna")
    with pytest.raises(sqlite3.IntegrityError):
        make_user("ANNA")  # логины уникальны без учёта регистра
    with pytest.raises(sqlite3.IntegrityError):
        make_generation(anna.id, status="unknown")
    with pytest.raises(sqlite3.IntegrityError):
        make_generation(999)  # нет такого пользователя

    parent = make_generation(anna.id)
    child = make_generation(anna.id, parent_id=parent)
    with db:
        db.execute(
            "INSERT INTO generation_inputs (generation_id, idx, path, source_generation_id)"
            " VALUES (?, 0, 'inputs/a.png', ?)",
            (child, parent),
        )
        db.execute("DELETE FROM generations WHERE id = ?", (parent,))
    row = db.execute("SELECT parent_id FROM generations WHERE id = ?", (child,)).fetchone()
    assert row["parent_id"] is None
    src = db.execute("SELECT source_generation_id FROM generation_inputs").fetchone()
    assert src[0] is None

    with db:
        db.execute("DELETE FROM generations WHERE id = ?", (child,))
    assert db.execute("SELECT COUNT(*) FROM generation_inputs").fetchone()[0] == 0


def test_1_defaults(db, make_user) -> None:
    anna = make_user("anna")
    with db:
        db.execute(
            "INSERT INTO generations (user_id, batch_id, model, quality, size, prompt)"
            " VALUES (?, 'b1', 'm', 'low', '1024x1024', 'p')",
            (anna.id,),
        )
    row = db.execute("SELECT * FROM generations").fetchone()
    assert row["status"] == "pending"
    assert row["shared"] == 1
    assert row["output_format"] == "jpeg"
    assert row["cost_micro_usd"] == 0
    assert row["created_at"].endswith("Z")
    user_row = db.execute("SELECT * FROM users").fetchone()
    assert user_row["is_active"] == 1 and user_row["daily_limit_micro_usd"] is None


# 2. WAL и внешние ключи.


def test_2_wal_and_foreign_keys(client: TestClient, settings) -> None:
    with dbmod.session() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_2_get_db_dependency(client: TestClient) -> None:
    gen = dbmod.get_db()
    conn = next(gen)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    gen.close()


# 3. /api/health: режим по ключу, degraded при свободном месте ниже 10%.


def test_3_health_mock_without_key(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" or body["disk_free_pct"] < 10
    assert body["mode"] == "mock"
    assert 0 <= body["disk_free_pct"] <= 100
    assert set(body) == {"status", "mode", "disk_free_pct"}


def test_3_health_openai_with_key(env, app) -> None:
    env.setenv("OPENAI_API_KEY", FAKE_KEY)
    reset_settings()
    with TestClient(app) as test_client:
        body = test_client.get("/api/health").json()
    assert body["mode"] == "openai"
    assert FAKE_KEY not in str(body)


@pytest.mark.parametrize(("free", "status"), [(5, "degraded"), (9.9, "degraded"), (10, "ok")])
def test_3_health_degraded_on_low_disk(client, monkeypatch, free, status) -> None:
    total = 1000
    usage = Usage(total=total, used=total - free * 10, free=free * 10)
    monkeypatch.setattr(health, "disk_usage", lambda _path: usage)
    body = client.get("/api/health").json()
    assert body["status"] == status
    assert body["disk_free_pct"] == pytest.approx(free)


def test_3_disk_free_for_missing_dir(tmp_path: Path) -> None:
    assert 0 <= health.disk_free_pct(tmp_path / "нет" / "такой" / "папки") <= 100


# 4. Прерванные задачи → error с пояснением и нулевой стоимостью.


def test_4_interrupted_jobs_become_error(app, settings, make_user, make_generation) -> None:
    anna = make_user("anna")
    pending = make_generation(anna.id, status="pending", variant_idx=0, batch_id="b")
    running = make_generation(
        anna.id, status="running", variant_idx=1, batch_id="b", cost_micro_usd=500
    )
    done = make_generation(anna.id, status="done", cost_micro_usd=1000)
    failed = make_generation(anna.id, status="error", error="модерация")

    with TestClient(app):
        pass

    with dbmod.session(settings.db_path) as conn:
        rows = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, status, error, cost_micro_usd, finished_at FROM generations"
            )
        }
    for gen_id in (pending, running):
        assert rows[gen_id]["status"] == "error"
        assert rows[gen_id]["error"] == "прервано перезапуском сервиса"
        assert rows[gen_id]["cost_micro_usd"] == 0
        assert rows[gen_id]["finished_at"]
    assert (rows[done]["status"], rows[done]["cost_micro_usd"]) == ("done", 1000)
    assert (rows[failed]["status"], rows[failed]["error"]) == ("error", "модерация")


def test_4_recover_returns_count(settings, make_user, make_generation) -> None:
    anna = make_user("anna")
    make_generation(anna.id, status="running")
    assert dbmod.init_db(settings) == 1
    assert dbmod.init_db(settings) == 0


# 5. Ключ не попадает в логи даже на DEBUG.


def test_5_key_not_in_logs(env, app, caplog: pytest.LogCaptureFixture) -> None:
    env.setenv("OPENAI_API_KEY", FAKE_KEY)
    env.setenv("ADMIN_PASSWORD", "admin-pass-123")
    env.setenv("LOG_LEVEL", "DEBUG")
    reset_settings()
    caplog.set_level(logging.DEBUG)

    with TestClient(app) as test_client:
        test_client.get("/api/health")
        settings = get_settings()
        logger = logging.getLogger("app.test")
        logger.debug("ключ: %s", FAKE_KEY)
        logger.debug(f"f-строка с ключом {FAKE_KEY} и паролем {settings.admin_password}")
        logger.info("настройки: %r", settings)
        logging.getLogger("openai._base_client").debug(
            "Request options: %s", {"headers": {"Authorization": f"Bearer {FAKE_KEY}"}}
        )
        try:
            raise RuntimeError(f"ошибка с ключом {FAKE_KEY}")
        except RuntimeError:
            logger.exception("упало")
        logger.debug("чужой ключ sk-abcdefghijklmnopqrstuvwxyz0123 из ответа")

    text = caplog.text + "".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    assert caplog.records, "логи должны писаться"
    assert FAKE_KEY not in text
    assert "admin-pass-123" not in text
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in text
    assert "***" in text
    assert "openai_api_key" not in repr(settings)


# Конфигурация.


def test_config_defaults_and_parsing() -> None:
    settings = load_settings(
        {
            "DATA_DIR": "/tmp/x",
            "SECRET_KEY": "s",
            "COOKIE_SECURE": "0",
            "MAX_PARALLEL": "2",
            "TRUSTED_PROXIES": "172.16.0.0/12, 10.0.0.1",
            "SPEND_CAP_DAILY_USD": "20.5",
        }
    )
    assert settings.mode == "mock"
    assert settings.db_path == Path("/tmp/x/app.db")
    assert settings.cookie_secure is False
    assert settings.max_parallel == 2
    assert [str(n) for n in settings.trusted_proxies] == ["172.16.0.0/12", "10.0.0.1/32"]
    assert settings.spend_cap_daily_micro_usd == 20_500_000

    defaults = load_settings({})
    assert defaults.cookie_secure is True
    assert defaults.max_parallel == 4
    assert defaults.spend_cap_daily_micro_usd is None
    assert defaults.secret_key  # временный ключ, если не задан
    assert defaults.admin_username == "admin"


@pytest.mark.parametrize(
    "env_vars",
    [
        {"MAX_PARALLEL": "0"},
        {"MAX_PARALLEL": "много"},
        {"COOKIE_SECURE": "maybe"},
        {"TRUSTED_PROXIES": "not-an-ip"},
        {"SPEND_CAP_DAILY_USD": "abc"},
        {"SPEND_CAP_DAILY_USD": "-1"},
    ],
)
def test_config_rejects_bad_values(env_vars: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        load_settings({"SECRET_KEY": "s", **env_vars})


def test_5_uvicorn_access_log_still_formats(settings) -> None:
    """Вычистка не ломает форматтеры, которые сами разбирают args (access-лог uvicorn)."""
    from uvicorn.logging import AccessFormatter

    from app.config import setup_logging

    setup_logging(settings)
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", f"/api/health?k={FAKE_KEY}", "1.1", 200),
        None,
    )
    line = AccessFormatter("%(client_addr)s %(request_line)s %(status_code)s").format(record)
    assert "GET /api/health" in line and "200" in line
    assert FAKE_KEY not in line


def test_connection_can_close_in_another_thread(settings) -> None:
    """Зависимость `get_db` открывает и закрывает подключение в разных потоках пула."""
    from concurrent.futures import ThreadPoolExecutor

    dbmod.init_db(settings)
    conn = dbmod.connect()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(conn.close).result()
