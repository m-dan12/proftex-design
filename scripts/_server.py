"""Общий запуск временного бэкенда для `load_check.py` и `security_probe.py`.

Если задан `BASE_URL`, скрипты работают с уже запущенным сервисом. Иначе поднимается свой
Uvicorn (один процесс, режим заглушки, временная база) и после работы останавливается.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "check-admin-pass")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def backend(
    extra_env: dict[str, str] | None = None,
) -> Iterator[tuple[str, subprocess.Popen | None]]:
    """Адрес сервиса и процесс (None, если сервис уже был запущен)."""
    if os.environ.get("BASE_URL"):
        yield os.environ["BASE_URL"].rstrip("/"), None
        return
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="design-check-") as data:
        env = {
            **os.environ,
            "DATA_DIR": data,
            "SECRET_KEY": "check-secret-key",
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": ADMIN_PASSWORD,
            "COOKIE_SECURE": "0",
            "OPENAI_API_KEY": "",
            **(extra_env or {}),
        }
        log = Path(data) / "server.log"
        with log.open("wb") as out:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--workers", "1",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT / "backend", env=env, stdout=out, stderr=subprocess.STDOUT,
            )  # fmt: skip
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    try:
                        urllib.request.urlopen(f"{base}/api/health", timeout=1)
                        break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise RuntimeError("сервис не поднялся")
                os.environ["SERVER_LOG"] = str(log)
                yield base, proc
            finally:
                proc.terminate()
                proc.wait(timeout=10)
        # лог читают до выхода из блока (`SERVER_LOG`), здесь он удаляется вместе с папкой
