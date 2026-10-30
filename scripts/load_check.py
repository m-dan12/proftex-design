"""S-07 «Параллельность»: 6 запусков подряд.

Одновременно `running` не больше 4, все 6 заканчиваются `done`, `/api/health` отвечает
быстрее 300 мс всё время. Без `BASE_URL` поднимает собственный сервис в режиме заглушки.

    python scripts/load_check.py
"""

from __future__ import annotations

import sys
import time

import httpx
from _server import ADMIN_PASSWORD, backend

RUNS = 6
MAX_RUNNING = 4
HEALTH_LIMIT_S = 0.3
TIMEOUT_S = 90


def main() -> int:
    with backend() as (base, _), httpx.Client(base_url=base, timeout=10) as client:
        login = client.post(
            "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
        )
        login.raise_for_status()

        ids: list[int] = []
        for i in range(RUNS):
            response = client.post(
                "/api/generations",
                data={"prompt": f"нагрузка {i}", "model": "gpt-image-1-mini",
                      "quality": "low", "size": "1024x1024"},
            )  # fmt: skip
            response.raise_for_status()
            ids.extend(response.json()["ids"])

        peak = 0
        slowest = 0.0
        deadline = time.monotonic() + TIMEOUT_S
        statuses: dict[int, str] = {}
        while time.monotonic() < deadline:
            started = time.monotonic()
            health = client.get("/api/health")
            slowest = max(slowest, time.monotonic() - started)
            health.raise_for_status()
            listing = client.get("/api/generations", params={"scope": "mine", "limit": 50}).json()
            statuses = {g["id"]: g["status"] for g in listing["items"] if g["id"] in ids}
            peak = max(peak, sum(s == "running" for s in statuses.values()))
            if len(statuses) == len(ids) and all(s in ("done", "error") for s in statuses.values()):
                break
            time.sleep(0.15)

        done = sum(s == "done" for s in statuses.values())
        print(f"запусков: {len(ids)}, done: {done}, пик running: {peak}, "
              f"самый медленный /api/health: {slowest * 1000:.0f} мс")  # fmt: skip
        problems = []
        if len(ids) != RUNS or done != RUNS:
            problems.append(f"не все запуски закончились done: {statuses}")
        if peak > MAX_RUNNING:
            problems.append(f"одновременно running {peak} > {MAX_RUNNING}")
        if slowest >= HEALTH_LIMIT_S:
            problems.append(f"/api/health ответил за {slowest * 1000:.0f} мс (порог 300)")
        for p in problems:
            print("FAIL:", p, file=sys.stderr)
        print("S-07:", "FAIL" if problems else "OK")
        return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
