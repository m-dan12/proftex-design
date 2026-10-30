"""T08: вход, сессии, лимит попыток, администрирование пользователей."""

import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app import deps, manage
from app.config import reset_settings
from app.deps import CurrentUser, hash_password, verify_password
from app.routers.auth import client_ip, login_limiter

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))

PASSWORD = "designer-pass-1"
ADMIN_PASSWORD = "admin-pass-123"
PROXY = ("172.18.0.2", 40000)  # адрес из TRUSTED_PROXIES по умолчанию (172.16.0.0/12)


def assert_schema(data: Any, name: str) -> None:
    """Ответ соответствует схеме из `openapi.yaml`."""
    schema = {"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]}
    Draft202012Validator(schema).validate(data)


def assert_error(response: Any, status: int) -> None:
    assert response.status_code == status, response.text
    assert_schema(response.json(), "Error")
    assert isinstance(response.json()["detail"], str)


@pytest.fixture(autouse=True)
def clean_limiter() -> Iterator[None]:
    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.fixture
def designer(make_user: Callable[..., CurrentUser]) -> CurrentUser:
    return make_user("designer", password_hash=hash_password(PASSWORD))


@pytest.fixture
def boss(make_user: Callable[..., CurrentUser]) -> CurrentUser:
    return make_user("boss", is_admin=True, password_hash=hash_password(ADMIN_PASSWORD))


def login(client: TestClient, username: str, password: str, **kwargs: Any) -> Any:
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}, **kwargs
    )


@pytest.fixture
def new_client(app: Any) -> Iterator[Callable[..., TestClient]]:
    """Отдельные клиенты со своими cookie (разные браузеры)."""
    clients: list[TestClient] = []

    def factory(**kwargs: Any) -> TestClient:
        test_client = TestClient(app, **kwargs)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield factory
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def as_boss(client: TestClient, boss: CurrentUser) -> TestClient:
    assert login(client, "boss", ADMIN_PASSWORD).status_code == 200
    return client


# --- 1. Вход, cookie, лимит ----------------------------------------------------


def test_login_sets_secure_cookie(client: TestClient, designer: CurrentUser, env: Any) -> None:
    env.setenv("COOKIE_SECURE", "1")
    reset_settings()
    response = login(client, "designer", PASSWORD)
    assert response.status_code == 200, response.text
    assert_schema(response.json(), "User")
    assert response.json()["username"] == "designer"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("session=")
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered
    assert "max-age=2592000" in lowered


def test_login_then_me_and_logout(client: TestClient, designer: CurrentUser) -> None:
    assert login(client, "Designer", PASSWORD).status_code == 200  # логин без учёта регистра
    me = client.get("/api/me")
    assert me.status_code == 200
    assert_schema(me.json(), "User")
    assert me.json()["id"] == designer.id
    assert client.post("/api/auth/logout").status_code == 204
    assert_error(client.get("/api/me"), 401)
    assert_error(client.post("/api/auth/logout"), 401)


def test_wrong_password_and_unknown_user(client: TestClient, designer: CurrentUser) -> None:
    assert_error(login(client, "designer", "wrong-password"), 401)
    assert_error(login(client, "nobody", PASSWORD), 401)
    assert "set-cookie" not in login(client, "designer", "nope").headers


def test_sixth_attempt_is_429(client: TestClient, designer: CurrentUser) -> None:
    for _ in range(5):
        assert login(client, "designer", "wrong").status_code == 401
    # Даже верный пароль не принимается, пока окно не истекло.
    assert_error(login(client, "designer", PASSWORD), 429)


def test_limit_window_expires(
    client: TestClient, designer: CurrentUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.routers.auth.time.monotonic", lambda: now[0])
    for _ in range(5):
        login(client, "designer", "wrong")
    assert login(client, "designer", PASSWORD).status_code == 429
    now[0] += 61
    assert login(client, "designer", PASSWORD).status_code == 200


def test_login_validation_422_is_text(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "", "password": "x"})
    assert_error(response, 422)
    assert_error(client.post("/api/auth/login", json={}), 422)


def test_blocked_user_cannot_login(client: TestClient, make_user: Callable[..., Any]) -> None:
    make_user("ghost", is_active=False, password_hash=hash_password(PASSWORD))
    assert_error(login(client, "ghost", PASSWORD), 403)


# --- 1a. IP за доверенным прокси ------------------------------------------------


def test_clients_behind_trusted_proxy_are_separate(
    new_client: Callable[..., TestClient], designer: CurrentUser
) -> None:
    proxy = new_client(client=PROXY)
    for _ in range(5):
        response = login(proxy, "designer", "wrong", headers={"X-Forwarded-For": "203.0.113.1"})
        assert response.status_code == 401
    first = login(proxy, "designer", PASSWORD, headers={"X-Forwarded-For": "203.0.113.1"})
    assert first.status_code == 429
    second = login(proxy, "designer", PASSWORD, headers={"X-Forwarded-For": "203.0.113.2"})
    assert second.status_code == 200


def test_forwarded_for_from_untrusted_peer_is_ignored(
    new_client: Callable[..., TestClient], designer: CurrentUser
) -> None:
    direct = new_client(client=("198.51.100.7", 40000))
    for i in range(5):
        headers = {"X-Forwarded-For": f"203.0.113.{i + 1}"}
        assert login(direct, "designer", "wrong", headers=headers).status_code == 401
    headers = {"X-Forwarded-For": "203.0.113.99"}
    assert login(direct, "designer", PASSWORD, headers=headers).status_code == 429


def test_client_ip_takes_rightmost_untrusted(settings: Any) -> None:
    class Req:
        def __init__(self, host: str, xff: str | None) -> None:
            self.client = type("C", (), {"host": host})()
            self.headers = _Headers({"x-forwarded-for": xff} if xff else {})

    class _Headers(dict):
        def getlist(self, key: str) -> list[str]:
            return [self[key]] if key in self else []

    # Клиент подставил свой X-Forwarded-For, Caddy дописал настоящий адрес справа.
    assert client_ip(Req("172.18.0.2", "6.6.6.6, 203.0.113.5"), settings) == "203.0.113.5"
    assert client_ip(Req("172.18.0.2", "203.0.113.5, 172.18.0.3"), settings) == "203.0.113.5"
    assert client_ip(Req("172.18.0.2", None), settings) == "172.18.0.2"
    assert client_ip(Req("8.8.8.8", "203.0.113.5"), settings) == "8.8.8.8"


def test_trusted_proxies_setting(
    new_client: Callable[..., TestClient], designer: CurrentUser, env: Any
) -> None:
    env.setenv("TRUSTED_PROXIES", "10.0.0.1")
    reset_settings()
    proxy = new_client(client=("172.18.0.2", 40000))  # больше не доверенный
    for i in range(5):
        login(proxy, "designer", "wrong", headers={"X-Forwarded-For": f"203.0.113.{i}"})
    headers = {"X-Forwarded-For": "203.0.113.50"}
    assert login(proxy, "designer", PASSWORD, headers=headers).status_code == 429


# --- 1b. Сброс пароля ----------------------------------------------------------


def test_reset_password(
    as_boss: TestClient, new_client: Callable[..., TestClient], designer: CurrentUser
) -> None:
    other = new_client()
    assert login(other, "designer", PASSWORD).status_code == 200

    response = as_boss.post(f"/api/admin/users/{designer.id}/reset-password")
    assert response.status_code == 200, response.text
    assert_schema(response.json(), "PasswordReset")
    new_password = response.json()["password"]
    assert len(new_password) == 12

    # Старая сессия пользователя и старый пароль больше не действуют.
    assert_error(other.get("/api/me"), 401)
    assert_error(login(other, "designer", PASSWORD), 401)
    assert login(other, "designer", new_password).status_code == 200

    listing = as_boss.get("/api/admin/users")
    assert new_password not in listing.text
    assert "password" not in listing.text
    assert "scrypt" not in listing.text


def test_reset_password_404_and_403(
    as_boss: TestClient, new_client: Callable[..., TestClient], designer: CurrentUser
) -> None:
    assert_error(as_boss.post("/api/admin/users/9999/reset-password"), 404)
    plain = new_client()
    login(plain, "designer", PASSWORD)
    assert_error(plain.post(f"/api/admin/users/{designer.id}/reset-password"), 403)


def test_generated_passwords_differ() -> None:
    passwords = {deps.generate_password() for _ in range(50)}
    assert len(passwords) == 50
    assert all(len(p) == 12 for p in passwords)


# --- 2. Хеши -------------------------------------------------------------------


def test_password_stored_as_scrypt(as_boss: TestClient, db: sqlite3.Connection) -> None:
    secret = "plain-text-pass"
    response = as_boss.post("/api/admin/users", json={"username": "newbie", "password": secret})
    assert response.status_code == 201
    stored = db.execute("SELECT password_hash FROM users WHERE username = 'newbie'").fetchone()[0]
    assert stored != secret
    assert secret not in stored
    assert stored.startswith("scrypt$")
    assert verify_password(secret, stored)
    assert not verify_password("other-pass", stored)
    rows = db.execute("SELECT password_hash FROM users").fetchall()
    assert all(row[0].startswith("scrypt$") for row in rows)


def test_verify_password_rejects_garbage() -> None:
    assert not verify_password("x", None)
    assert not verify_password("x", "plain")
    assert not verify_password("x", "bcrypt$1$2$3$4$5")
    assert not verify_password("x", "scrypt$a$b$c$d$e")


# --- 3. Блокировка действует сразу ----------------------------------------------


def test_blocked_user_with_live_cookie_gets_401(
    as_boss: TestClient, new_client: Callable[..., TestClient], designer: CurrentUser
) -> None:
    victim = new_client()
    assert login(victim, "designer", PASSWORD).status_code == 200
    assert victim.get("/api/me").status_code == 200
    response = as_boss.patch(f"/api/admin/users/{designer.id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert_error(victim.get("/api/me"), 401)
    # Разблокировка возвращает доступ без нового входа.
    as_boss.patch(f"/api/admin/users/{designer.id}", json={"is_active": True})
    assert victim.get("/api/me").status_code == 200


def test_tampered_and_expired_cookie(
    client: TestClient, designer: CurrentUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert login(client, "designer", PASSWORD).status_code == 200
    token = client.cookies["session"]
    body, _, signature = token.partition(".")
    client.cookies.clear()
    client.cookies.set("session", body + "x." + signature)
    assert_error(client.get("/api/me"), 401)
    client.cookies.set("session", "garbage")
    assert_error(client.get("/api/me"), 401)
    client.cookies.set("session", token)
    assert client.get("/api/me").status_code == 200
    real_time = time.time
    monkeypatch.setattr("app.deps.time.time", lambda: real_time() + deps.SESSION_MAX_AGE + 1)
    assert_error(client.get("/api/me"), 401)


def test_cookie_signed_with_other_key_rejected(
    client: TestClient, designer: CurrentUser, env: Any
) -> None:
    assert login(client, "designer", PASSWORD).status_code == 200
    env.setenv("SECRET_KEY", "another-secret")
    reset_settings()
    assert_error(client.get("/api/me"), 401)


# --- 4. Права администратора и создание ------------------------------------------


def test_admin_endpoints_need_admin(
    client: TestClient, designer: CurrentUser, boss: CurrentUser
) -> None:
    assert_error(client.get("/api/admin/users"), 401)
    login(client, "designer", PASSWORD)
    assert_error(client.get("/api/admin/users"), 403)
    assert_error(
        client.post("/api/admin/users", json={"username": "x1x", "password": "12345678"}), 403
    )
    assert_error(client.patch(f"/api/admin/users/{boss.id}", json={"is_active": False}), 403)


def test_admin_creates_user_and_duplicate_409(
    as_boss: TestClient, new_client: Callable[..., TestClient]
) -> None:
    response = as_boss.post(
        "/api/admin/users", json={"username": "anna.k", "password": "anna-pass-1"}
    )
    assert response.status_code == 201, response.text
    assert_schema(response.json(), "User")
    assert response.json()["is_admin"] is False
    assert response.json()["is_active"] is True
    assert response.json()["daily_limit_micro_usd"] is None
    assert_error(
        as_boss.post("/api/admin/users", json={"username": "anna.k", "password": "other-pass"}),
        409,
    )
    assert_error(
        as_boss.post("/api/admin/users", json={"username": "ANNA.K", "password": "other-pass"}),
        409,
    )
    listing = as_boss.get("/api/admin/users")
    assert listing.status_code == 200
    assert_schema(listing.json(), "UserList")
    assert [u["username"] for u in listing.json()["items"]] == ["boss", "anna.k"]
    anna = new_client()
    assert login(anna, "anna.k", "anna-pass-1").status_code == 200


def test_create_user_validation(as_boss: TestClient) -> None:
    for body in (
        {"username": "ab", "password": "12345678"},
        {"username": "имя", "password": "12345678"},
        {"username": "okname", "password": "short"},
        {"username": "okname"},
    ):
        assert_error(as_boss.post("/api/admin/users", json=body), 422)


def test_create_admin_user(as_boss: TestClient) -> None:
    response = as_boss.post(
        "/api/admin/users", json={"username": "boss2", "password": "12345678", "is_admin": True}
    )
    assert response.status_code == 201
    assert response.json()["is_admin"] is True


# --- PATCH: роль, лимит, последний администратор ---------------------------------


def test_patch_user_fields(as_boss: TestClient, designer: CurrentUser) -> None:
    url = f"/api/admin/users/{designer.id}"
    response = as_boss.patch(url, json={"daily_limit_micro_usd": 5_000_000})
    assert response.status_code == 200
    assert_schema(response.json(), "User")
    assert response.json()["daily_limit_micro_usd"] == 5_000_000
    assert response.json()["is_active"] is True
    response = as_boss.patch(url, json={"is_admin": True})
    assert response.json()["is_admin"] is True
    assert response.json()["daily_limit_micro_usd"] == 5_000_000
    response = as_boss.patch(url, json={"daily_limit_micro_usd": None})
    assert response.json()["daily_limit_micro_usd"] is None
    assert response.json()["is_admin"] is True


def test_patch_validation_and_404(as_boss: TestClient, designer: CurrentUser) -> None:
    url = f"/api/admin/users/{designer.id}"
    assert_error(as_boss.patch(url, json={}), 422)
    assert_error(as_boss.patch(url, json={"daily_limit_micro_usd": -1}), 422)
    assert_error(as_boss.patch(url, json={"is_active": None}), 422)
    assert_error(as_boss.patch("/api/admin/users/9999", json={"is_active": False}), 404)


def test_last_active_admin_is_protected(as_boss: TestClient, boss: CurrentUser) -> None:
    url = f"/api/admin/users/{boss.id}"
    assert_error(as_boss.patch(url, json={"is_active": False}), 409)
    assert_error(as_boss.patch(url, json={"is_admin": False}), 409)
    # Лимит менять можно.
    assert as_boss.patch(url, json={"daily_limit_micro_usd": 1}).status_code == 200


def test_admin_can_be_removed_when_another_exists(
    as_boss: TestClient, make_user: Callable[..., CurrentUser], boss: CurrentUser
) -> None:
    second = make_user("second", is_admin=True)
    blocked_admin = make_user("old", is_admin=True, is_active=False)
    assert (
        as_boss.patch(f"/api/admin/users/{second.id}", json={"is_admin": False}).status_code == 200
    )
    # Заблокированный администратор не считается: boss снова последний.
    assert blocked_admin.is_admin
    assert_error(as_boss.patch(f"/api/admin/users/{boss.id}", json={"is_active": False}), 409)
    as_boss.patch(f"/api/admin/users/{second.id}", json={"is_admin": True})
    response = as_boss.patch(f"/api/admin/users/{boss.id}", json={"is_admin": False})
    assert response.status_code == 200
    # Права сняты — сразу 403.
    assert_error(as_boss.get("/api/admin/users"), 403)


# --- 5. Смена своего пароля ------------------------------------------------------


def test_change_password(
    client: TestClient, new_client: Callable[..., TestClient], designer: CurrentUser
) -> None:
    other = new_client()
    login(other, "designer", PASSWORD)
    login(client, "designer", PASSWORD)
    url = "/api/me/password"
    assert_error(
        client.post(url, json={"old_password": "wrong", "new_password": "new-pass-1"}), 422
    )
    assert_error(client.post(url, json={"old_password": PASSWORD, "new_password": "short"}), 422)
    assert_error(client.post(url, json={"new_password": "new-pass-1"}), 422)
    response = client.post(url, json={"old_password": PASSWORD, "new_password": "new-pass-1"})
    assert response.status_code == 204
    # Текущая сессия продлена новой cookie, другие сессии завершены.
    assert client.get("/api/me").status_code == 200
    assert_error(other.get("/api/me"), 401)
    assert_error(login(other, "designer", PASSWORD), 401)
    assert login(other, "designer", "new-pass-1").status_code == 200


def test_change_password_needs_session(client: TestClient) -> None:
    body = {"old_password": "a", "new_password": "12345678"}
    assert_error(client.post("/api/me/password", json=body), 401)


# --- Автосоздание администратора и команда create-admin ---------------------------


def test_admin_autocreated_on_empty_db(app: Any, env: Any, db: sqlite3.Connection) -> None:
    env.setenv("ADMIN_USERNAME", "chief")
    env.setenv("ADMIN_PASSWORD", "chief-pass-1")
    reset_settings()
    with TestClient(app) as test_client:
        response = login(test_client, "chief", "chief-pass-1")
        assert response.status_code == 200
        assert response.json()["is_admin"] is True
    with TestClient(app):
        pass
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_admin_not_created_when_users_exist(
    app: Any, env: Any, designer: CurrentUser, db: sqlite3.Connection
) -> None:
    env.setenv("ADMIN_PASSWORD", "chief-pass-1")
    reset_settings()
    with TestClient(app):
        pass
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_admin_not_created_without_password(client: TestClient, db: sqlite3.Connection) -> None:
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert manage.ensure_admin() is False


def test_manage_create_admin(
    env: Any, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    env.setenv("ADMIN_PASSWORD", "cli-pass-123")
    reset_settings()
    assert manage.main(["create-admin", "--username", "root"]) == 0
    out = capsys.readouterr()
    assert "создан" in out.out
    assert "cli-pass-123" not in out.out + out.err
    row = db.execute("SELECT * FROM users WHERE username = 'root'").fetchone()
    assert row["is_admin"] == 1
    assert verify_password("cli-pass-123", row["password_hash"])
    # Повторный запуск восстанавливает доступ: снимает блокировку и ставит пароль.
    with db:
        db.execute("UPDATE users SET is_active = 0, is_admin = 0 WHERE username = 'root'")
    env.setenv("ADMIN_PASSWORD", "cli-pass-456")
    reset_settings()
    assert manage.main(["create-admin", "--username", "root"]) == 0
    assert "обновлён" in capsys.readouterr().out
    row = db.execute("SELECT * FROM users WHERE username = 'root'").fetchone()
    assert (row["is_admin"], row["is_active"]) == (1, 1)
    assert verify_password("cli-pass-456", row["password_hash"])


def test_manage_rejects_short_password(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": "short")
    assert manage.main(["create-admin"]) == 1
    answers = iter(["long-enough-1", "different-22"])
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": next(answers))
    assert manage.main(["create-admin"]) == 1
