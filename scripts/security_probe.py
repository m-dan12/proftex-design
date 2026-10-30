"""S-14, проверки по HTTP (запускает `security_check.sh`).

Режим `leak`: сервис стартует с поддельным ключом OpenAI; ключ не должен попасть ни в
ответы API, ни в лог. Режим `uploads`: подделка под PNG, файл больше 20 МБ, «бомба»
20000×20000, чужая приватная картинка и путь `../`.
"""

from __future__ import annotations

import struct
import sys
import time
import zlib
from pathlib import Path

import httpx
from _server import ADMIN_PASSWORD, backend

FAKE_KEY = "sk-securitycheck-0123456789abcdef0123456789"
MEMORY_LIMIT_KB = 1024 * 1024  # 1 ГБ

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}{': ' + detail if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def bomb_png(side: int) -> bytes:
    """Серый PNG side×side: сжимается до сотен килобайт, а в памяти — сотни мегабайт."""
    header = b"\x89PNG\r\n\x1a\n" + png_chunk(
        b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0)
    )
    packer = zlib.compressobj(9)
    row = b"\x00" * (side + 1)
    body = b"".join(packer.compress(row) for _ in range(side)) + packer.flush()
    return header + png_chunk(b"IDAT", body) + png_chunk(b"IEND", b"")


def peak_memory_kb(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    return 0


def login(client: httpx.Client, username: str, password: str) -> None:
    client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).raise_for_status()


def probe_leak() -> None:
    print("Ключ не попадает в ответы и лог:")
    with backend({"OPENAI_API_KEY": FAKE_KEY}) as (base, _), httpx.Client(base_url=base) as client:
        login(client, "admin", ADMIN_PASSWORD)
        bodies = [
            client.get(p).text
            for p in ("/api/health", "/api/me", "/api/models", "/api/generations?scope=mine")
        ]
        bodies.append(
            client.post(
                "/api/generations", data={"prompt": "", "model": "x", "quality": "x", "size": "x"}
            ).text
        )
        bodies.append(client.get("/").text)
        check("ответы API без ключа", not any(FAKE_KEY in b for b in bodies))
        time.sleep(0.3)
        import os

        log = Path(os.environ["SERVER_LOG"]).read_text(errors="replace")
        check("лог без ключа", FAKE_KEY not in log)
        check(
            "режим openai включился (проверка осмысленна)",
            client.get("/api/health").json()["mode"] == "openai",
        )


def probe_uploads() -> None:
    print("Загрузки и доступ к файлам:")
    with backend() as (base, proc), httpx.Client(base_url=base, timeout=120) as admin:
        login(admin, "admin", ADMIN_PASSWORD)
        for name in ("alice-sec", "bob-sec"):
            admin.post(
                "/api/admin/users", json={"username": name, "password": f"pass-{name}"}
            ).raise_for_status()
        alice = httpx.Client(base_url=base, timeout=120)
        bob = httpx.Client(base_url=base, timeout=120)
        login(alice, "alice-sec", "pass-alice-sec")
        login(bob, "bob-sec", "pass-bob-sec")

        fields = {
            "prompt": "проверка",
            "model": "gpt-image-1-mini",
            "quality": "low",
            "size": "1024x1024",
        }

        r = alice.post(
            "/api/generations",
            data=fields,
            files=[("files", ("evil.png", b"MZ\x90\x00" + b"\x00" * 500, "image/png"))],
        )
        check(
            "файл .exe под видом .png → 422",
            r.status_code == 422,
            f"{r.status_code} {r.text[:120]}",
        )

        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (20 * 1024 * 1024 + 1024)
        r = alice.post(
            "/api/generations", data=fields, files=[("files", ("big.png", big, "image/png"))]
        )
        check("файл больше 20 МБ → 413", r.status_code == 413, f"{r.status_code} {r.text[:120]}")

        r = alice.post(
            "/api/generations",
            data=fields,
            files=[("files", ("bomb.png", bomb_png(20000), "image/png"))],
        )
        check("картинка 20000×20000 → 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")
        if proc is not None:
            peak = peak_memory_kb(proc.pid)
            check(
                "память сервиса после «бомбы» ≤ 1 ГБ", peak <= MEMORY_LIMIT_KB, f"{peak // 1024} МБ"
            )

        r = alice.post("/api/generations", data={**fields, "shared": "false"})
        r.raise_for_status()
        gid = r.json()["ids"][0]
        for _ in range(60):
            if alice.get(f"/api/generations/{gid}").json()["status"] == "done":
                break
            time.sleep(0.5)
        check(
            "своя приватная картинка открывается",
            alice.get(f"/api/generations/{gid}/image?kind=result").status_code == 200,
        )
        check(
            "чужая приватная картинка → 404",
            bob.get(f"/api/generations/{gid}/image?kind=result").status_code == 404,
        )
        check("чужая приватная работа → 404", bob.get(f"/api/generations/{gid}").status_code == 404)

        for path in (
            "/api/generations/..%2f..%2f..%2fetc%2fpasswd/image?kind=result",
            "/assets/..%2f..%2f..%2fetc%2fpasswd",
            "/..%2f..%2fetc%2fpasswd",
        ):
            r = alice.get(path)
            check(
                f"путь {path[:40]}… → 404",
                r.status_code == 404 and "root:" not in r.text,
                str(r.status_code),
            )


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("leak", "all"):
        probe_leak()
    if mode in ("uploads", "all"):
        probe_uploads()
    print("S-14 (HTTP):", "FAIL" if failures else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
