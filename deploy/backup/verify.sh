#!/usr/bin/env bash
# Проверка бэкапа (S-13).
#
#   deploy/backup/verify.sh             проверить настоящий бэкап в BACKUP_DIR
#   deploy/backup/verify.sh --selftest  собрать тестовую базу и файлы, прогнать хук и проверку
#
# Что проверяется:
#   1. копия базы есть и PRAGMA integrity_check = ok;
#   2. восстановление в тестовую папку (sqlite backup) даёт ту же integrity и то же число строк
#      в каждой таблице;
#   3. в недельной копии картинок есть все файлы results/ и inputs/, на которые ссылается база.
#      Файл, появившийся в сервисе позже последней недельной синхронизации, — предупреждение,
#      а не ошибка (он попадёт в копию в ближайшее воскресенье).
# Переменные: BACKUP_DIR (по умолчанию /opt/backup/data/design-studio), DESIGN_DATA_DIR
# (для проверки «позже синхронизации», по умолчанию — том design-data, если он есть).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

verify() {
	local backup_dir="$1" data_dir="${2:-}"
	python3 - "$backup_dir" "$data_dir" <<'PY'
import os, shutil, sqlite3, sys, tempfile
from pathlib import Path

backup_dir, data_dir = Path(sys.argv[1]), sys.argv[2]
db = backup_dir / "app.db"
files = backup_dir / "files"
errors, warnings = [], []

def integrity(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        return c.execute("PRAGMA integrity_check").fetchone()[0]

def counts(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}

def rel(p):
    # В базе путь относительный (results/1.png) или от корня тома (/data/results/1.png).
    p = p.replace("\\", "/")
    for prefix in ("/data/", (data_dir.rstrip("/") + "/") if data_dir else None):
        if prefix and p.startswith(prefix):
            return p[len(prefix):]
    return p.lstrip("/")

if not db.is_file():
    print(f"FAIL: нет копии базы {db}")
    sys.exit(1)

ic = integrity(db)
print(f"integrity_check копии: {ic}")
if ic != "ok":
    errors.append("integrity_check копии не ok")

src_counts = counts(db)
with tempfile.TemporaryDirectory() as tmp:
    restored = Path(tmp) / "restored.db"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as s, sqlite3.connect(restored) as d:
        s.backup(d)
    ric = integrity(restored)
    rcounts = counts(restored)
print(f"восстановление: integrity_check = {ric}, строк: {rcounts}")
if ric != "ok":
    errors.append("integrity_check восстановленной базы не ok")
if rcounts != src_counts:
    errors.append(f"число строк после восстановления {rcounts} != {src_counts}")

with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
    tables = set(src_counts)
    refs = []
    if "generations" in tables:
        refs += [r[0] for r in c.execute(
            "SELECT result_path FROM generations WHERE result_path IS NOT NULL AND result_path != ''")]
    if "generation_inputs" in tables:
        refs += [r[0] for r in c.execute(
            "SELECT path FROM generation_inputs WHERE path IS NOT NULL AND path != ''")]

stamp = files / ".synced_at"
synced_at = stamp.stat().st_mtime if stamp.exists() else None
missing = 0
for r in refs:
    p = rel(r)
    if (files / p).is_file():
        continue
    live = Path(data_dir) / p if data_dir else None
    if live and live.is_file() and synced_at is not None and live.stat().st_mtime > synced_at:
        warnings.append(f"{p}: создан после недельной синхронизации")
    else:
        missing += 1
        errors.append(f"нет в недельной копии: {p}")
print(f"недельная копия: ссылок в базе {len(refs)}, отсутствует {missing}")

for w in warnings:
    print(f"WARN: {w}")
for e in errors:
    print(f"FAIL: {e}")
if errors:
    sys.exit(1)
print("OK: бэкап проверен")
PY
}

selftest() {
	# Глобальная: trap EXIT срабатывает уже после выхода из функции.
	work="$(mktemp -d)"
	trap 'rm -rf "$work"' EXIT
	local data="$work/data" backup="$work/backup"
	mkdir -p "$data/results" "$data/inputs/2" "$data/thumbs"

	# Схема по разделу 5 ТЗ (подмножество полей, достаточное для бэкапа).
	python3 - "$data" <<'PY'
import sqlite3, sys
from pathlib import Path
data = Path(sys.argv[1])
c = sqlite3.connect(data / "app.db")
c.execute("PRAGMA journal_mode=WAL")
c.executescript("""
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, daily_limit_micro_usd INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE generations (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  parent_id INTEGER, status TEXT NOT NULL, prompt TEXT, cost_micro_usd INTEGER NOT NULL DEFAULT 0,
  result_path TEXT, thumb_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE generation_inputs (id INTEGER PRIMARY KEY, generation_id INTEGER NOT NULL REFERENCES generations(id),
  idx INTEGER NOT NULL, path TEXT NOT NULL, source_generation_id INTEGER, filename TEXT);
""")
c.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('admin', 'scrypt$x', 1)")
c.execute("INSERT INTO generations (user_id, status, prompt, result_path, thumb_path) VALUES (1, 'done', 'a', 'results/1.png', 'thumbs/1.webp')")
c.execute("INSERT INTO generations (user_id, status, prompt, result_path, thumb_path, parent_id) VALUES (1, 'done', 'b', '/data/results/2.jpeg', 'thumbs/2.webp', 1)")
c.execute("INSERT INTO generations (user_id, status, prompt) VALUES (1, 'error', 'c')")
c.execute("INSERT INTO generation_inputs (generation_id, idx, path, filename) VALUES (2, 0, 'inputs/2/0.jpg', 'ref.jpg')")
c.execute("INSERT INTO generation_inputs (generation_id, idx, path, source_generation_id) VALUES (2, 1, 'inputs/2/1.png', 1)")
c.commit()
for p in ["results/1.png", "results/2.jpeg", "inputs/2/0.jpg", "inputs/2/1.png", "thumbs/1.webp"]:
    (data / p).write_bytes(b"x" * 64)
# Последнюю запись оставляем только в app.db-wal (выход без checkpoint), как у работающего
# сервиса: копия обязана её содержать.
c.execute("INSERT INTO users (username, password_hash) VALUES ('designer', 'scrypt$y')")
c.commit()
import os
os._exit(0)
PY

	echo "== хук бэкапа (WEEKLY=1)"
	DESIGN_DATA_DIR="$data" BACKUP_DIR="$backup" WEEKLY=1 "$here/design-studio.sh"

	echo "== проверка копии"
	verify "$backup" "$data"

	echo "== число строк копии совпадает с исходной базой"
	python3 - "$data/app.db" "$backup/app.db" <<'PY'
import sqlite3, sys
def counts(p):
    c = sqlite3.connect(p)
    return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
a, b = counts(sys.argv[1]), counts(sys.argv[2])
print(f"исходная {a}\nкопия    {b}")
assert a == b and a["users"] == 2, "число строк не совпадает"
PY
	[ ! -e "$backup/files/thumbs" ] || { echo "FAIL: thumbs/ не должны копироваться"; exit 1; }

	echo "== отрицательная проверка: удаляем файл из недельной копии — verify должен упасть"
	rm "$backup/files/inputs/2/1.png"
	if verify "$backup" "" >/dev/null; then
		echo "FAIL: verify не заметил пропавший файл"
		exit 1
	fi
	echo "OK: пропажа файла обнаружена"
	echo "SELFTEST OK"
}

if [ "${1:-}" = "--selftest" ]; then
	selftest
else
	data="${DESIGN_DATA_DIR:-}"
	if [ -z "$data" ] && command -v docker >/dev/null 2>&1; then
		data="$(docker volume inspect -f '{{.Mountpoint}}' design-data 2>/dev/null || true)"
	fi
	verify "${BACKUP_DIR:-/opt/backup/data/design-studio}" "$data"
fi
