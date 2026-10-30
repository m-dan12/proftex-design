"""Настройки сервиса из переменных окружения и логирование без секретов.

Список переменных — в `.env.example`. Режим работы определяется ключом:
есть `OPENAI_API_KEY` — `openai`, нет — `mock` (тестовые картинки, фиктивные токены).
Настройки читаются один раз и кешируются; в тестах кеш сбрасывает `reset_settings()`.
"""

import ipaddress
import logging
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Literal

Mode = Literal["mock", "openai"]
Network = ipaddress.IPv4Network | ipaddress.IPv6Network

log = logging.getLogger(__name__)

DEFAULT_DATA_DIR = "/data"
DEFAULT_TRUSTED_PROXIES = "172.16.0.0/12"


@dataclass(frozen=True)
class Settings:
    # Секреты не попадают в repr, чтобы случайный log.debug(settings) их не напечатал.
    openai_api_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    admin_password: str = field(default="", repr=False)
    admin_username: str = "admin"
    data_dir: Path = Path(DEFAULT_DATA_DIR)
    cookie_secure: bool = True
    max_parallel: int = 4
    trusted_proxies: tuple[Network, ...] = ()
    spend_cap_daily_micro_usd: int | None = None
    log_level: str = "INFO"

    @property
    def mode(self) -> Mode:
        return "openai" if self.openai_api_key else "mock"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    def secrets(self) -> tuple[str, ...]:
        """Значения, которые нельзя печатать в логи."""
        return tuple(s for s in (self.openai_api_key, self.secret_key, self.admin_password) if s)


def _bool(raw: str, name: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name}: ожидается 1 или 0, получено {raw!r}")


def _positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name}: ожидается целое число, получено {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name}: должно быть не меньше 1")
    return value


def _networks(raw: str) -> tuple[Network, ...]:
    try:
        return tuple(
            ipaddress.ip_network(part.strip(), strict=False)
            for part in raw.split(",")
            if part.strip()
        )
    except ValueError as exc:
        raise ValueError(f"TRUSTED_PROXIES: {exc}") from None


def _micro_usd(raw: str) -> int | None:
    if not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        raise ValueError(f"SPEND_CAP_DAILY_USD: ожидается число, получено {raw!r}") from None
    if value < 0:
        raise ValueError("SPEND_CAP_DAILY_USD: не может быть отрицательным")
    return int(value * 1_000_000)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Собрать настройки из окружения; неверное значение — ошибка при старте, а не в работе."""
    env = os.environ if env is None else env

    def get(name: str, default: str = "") -> str:
        return env.get(name, default).strip()

    secret_key = get("SECRET_KEY")
    if not secret_key:
        # Без постоянного ключа сессии живут до перезапуска; для прода ключ обязателен.
        log.warning("SECRET_KEY не задан: сгенерирован временный, сессии сбросятся при перезапуске")
        secret_key = secrets.token_urlsafe(48)

    return Settings(
        openai_api_key=get("OPENAI_API_KEY"),
        secret_key=secret_key,
        admin_password=get("ADMIN_PASSWORD"),
        admin_username=get("ADMIN_USERNAME", "admin") or "admin",
        data_dir=Path(get("DATA_DIR", DEFAULT_DATA_DIR) or DEFAULT_DATA_DIR),
        cookie_secure=_bool(get("COOKIE_SECURE", "1") or "1", "COOKIE_SECURE"),
        max_parallel=_positive_int(get("MAX_PARALLEL", "4") or "4", "MAX_PARALLEL"),
        trusted_proxies=_networks(get("TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES)),
        spend_cap_daily_micro_usd=_micro_usd(get("SPEND_CAP_DAILY_USD")),
        log_level=(get("LOG_LEVEL", "INFO") or "INFO").upper(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings() -> None:
    """Сбросить кеш настроек (тесты меняют окружение между запусками)."""
    get_settings.cache_clear()


# --- Логирование без секретов -------------------------------------------------

REDACTED = "***"
# Всё, что похоже на ключ OpenAI, даже если его нет в настройках (например, ключ из ответа ошибки).
_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_secrets: tuple[str, ...] = ()
_base_factory = logging.getLogRecordFactory()
_installed = False


def redact(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, REDACTED)
    return _KEY_PATTERN.sub(REDACTED, text)


def _clean(value: object) -> object:
    """Аргумент записи без секретов; тип сохраняется, если секрета в нём нет (%d, %r и т. п.)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, int | float | bool | None):
        return value
    text = str(value)
    cleaned = redact(text)
    return value if cleaned == text and redact(repr(value)) == repr(value) else cleaned


def _record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    """Чистит каждую запись в момент создания, поэтому секрет не увидит ни один обработчик.

    Форма `args` сохраняется: форматтеры вроде access-лога uvicorn разбирают её сами.
    """
    record = _base_factory(*args, **kwargs)
    if isinstance(record.msg, str):
        record.msg = redact(record.msg)
    else:
        record.msg = _clean(record.msg)
    if isinstance(record.args, tuple):
        record.args = tuple(_clean(arg) for arg in record.args)
    elif isinstance(record.args, Mapping):
        record.args = {key: _clean(arg) for key, arg in record.args.items()}
    if record.exc_info and not record.exc_text:
        record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
    if record.stack_info:
        record.stack_info = redact(record.stack_info)
    return record


def setup_logging(settings: Settings) -> None:
    """Включить вычистку секретов и задать уровень логов. Повторный вызов безопасен."""
    global _secrets, _installed
    _secrets = tuple(sorted(settings.secrets(), key=len, reverse=True))
    if not _installed:
        logging.setLogRecordFactory(_record_factory)
        _installed = True
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.setLevel(settings.log_level)
