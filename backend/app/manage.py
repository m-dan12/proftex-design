"""Служебные команды и автосоздание администратора.

    python -m app.manage create-admin [--username ИМЯ]

Пароль берётся из `ADMIN_PASSWORD`, а если переменная пуста — спрашивается в терминале
(дважды, без эха). Пароль никогда не печатается. Если такой логин уже есть, пользователю
ставится новый пароль, права администратора и снимается блокировка: так восстанавливают
доступ, если пароль администратора потерян.
"""

import argparse
import getpass
import logging
import sys

from app.config import Settings, get_settings, setup_logging
from app.db import init_db, session
from app.deps import hash_password

log = logging.getLogger(__name__)

MIN_PASSWORD = 8


def ensure_admin(settings: Settings | None = None) -> bool:
    """При пустой базе создать администратора из `ADMIN_USERNAME`/`ADMIN_PASSWORD`.

    Ничего не делает, если пользователи уже есть или пароль не задан. Возвращает `True`,
    если администратор создан. Вызывается при старте сервиса (lifespan в `routers/auth.py`).
    """
    settings = get_settings() if settings is None else settings
    with session(settings.db_path) as conn:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return False
        if not settings.admin_password:
            log.warning(
                "Пользователей нет и ADMIN_PASSWORD пуст: создайте администратора"
                " командой python -m app.manage create-admin"
            )
            return False
        if len(settings.admin_password) < MIN_PASSWORD:
            log.error("ADMIN_PASSWORD короче %d символов: администратор не создан", MIN_PASSWORD)
            return False
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (settings.admin_username, hash_password(settings.admin_password)),
        )
    log.info("Создан администратор %s", settings.admin_username)
    return True


def create_admin(username: str, password: str, settings: Settings | None = None) -> str:
    """Создать администратора или вернуть доступ существующему; результат: «создан»/«обновлён»."""
    settings = get_settings() if settings is None else settings
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Пароль короче {MIN_PASSWORD} символов")
    init_db(settings)
    with session(settings.db_path) as conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ?, is_admin = 1, is_active = 1 WHERE username = ?",
            (hash_password(password), username),
        )
        if cursor.rowcount:
            return "обновлён"
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (username, hash_password(password)),
        )
    return "создан"


def _ask_password() -> str:
    first = getpass.getpass("Пароль администратора: ")
    if getpass.getpass("Ещё раз: ") != first:
        raise ValueError("Пароли не совпадают")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create-admin", help="создать администратора или сбросить ему пароль"
    )
    create.add_argument("--username", help="логин (по умолчанию ADMIN_USERNAME или admin)")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings)
    username = args.username or settings.admin_username
    try:
        password = settings.admin_password or _ask_password()
        result = create_admin(username, password, settings)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"Администратор {username} {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
