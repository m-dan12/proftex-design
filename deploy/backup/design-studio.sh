#!/usr/bin/env bash
# Хук для /opt/backup/pre.d/ (NFR-11): запускается перед ежедневным бэкапом VDS.
#   - каждый день: согласованная копия базы через `sqlite3 .backup` + PRAGMA integrity_check;
#   - по воскресеньям (или WEEKLY=1): rsync папок results/ и inputs/ в каталог бэкапа.
#     thumbs/ не копируются — превью пересоздаются из результатов.
#
# Переменные:
#   DESIGN_DATA_DIR  данные сервиса на хосте (по умолчанию — точка монтирования тома design-data)
#   BACKUP_DIR       куда класть копию (по умолчанию /opt/backup/data/design-studio)
#   WEEKLY=1         принудительно скопировать картинки сегодня
# Код возврата не 0 — копия не удалась, внешний бэкап должен это увидеть.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/backup/data/design-studio}"
if [ -z "${DESIGN_DATA_DIR:-}" ]; then
	DESIGN_DATA_DIR="$(docker volume inspect -f '{{.Mountpoint}}' design-data)"
fi
db="$DESIGN_DATA_DIR/app.db"
[ -f "$db" ] || { echo "design-studio backup: нет базы $db" >&2; exit 1; }

mkdir -p "$BACKUP_DIR/files"
chmod 700 "$BACKUP_DIR"

tmp="$BACKUP_DIR/app.db.tmp"
rm -f "$tmp"

# .backup даёт согласованный снимок даже при работающем сервисе (WAL).
if command -v sqlite3 >/dev/null 2>&1; then
	sqlite3 "$db" ".timeout 10000" ".backup '$tmp'"
	check="$(sqlite3 "$tmp" 'PRAGMA integrity_check;')"
else
	# Нет sqlite3 на хосте — тот же онлайн-бэкап через модуль sqlite3 из Python.
	python3 - "$db" "$tmp" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=10)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PY
	check="$(python3 -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0])' "$tmp")"
fi

if [ "$check" != "ok" ]; then
	echo "design-studio backup: integrity_check = $check" >&2
	rm -f "$tmp"
	exit 1
fi
mv -f "$tmp" "$BACKUP_DIR/app.db"
date -u +%Y-%m-%dT%H:%M:%SZ > "$BACKUP_DIR/app.db.created_at"
echo "design-studio backup: база скопирована, integrity_check = ok"

if [ "${WEEKLY:-0}" = "1" ] || [ "$(date +%u)" = "7" ]; then
	for sub in results inputs; do
		mkdir -p "$DESIGN_DATA_DIR/$sub" "$BACKUP_DIR/files/$sub"
		# Инкрементально и без --delete: удалённые в сервисе работы остаются в бэкапе.
		rsync -a "$DESIGN_DATA_DIR/$sub/" "$BACKUP_DIR/files/$sub/"
	done
	date -u +%Y-%m-%dT%H:%M:%SZ > "$BACKUP_DIR/files/.synced_at"
	echo "design-studio backup: results/ и inputs/ синхронизированы"
fi
