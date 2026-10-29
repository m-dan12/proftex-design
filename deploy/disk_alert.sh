#!/usr/bin/env bash
# Cron-проверка свободного места (NFR-15): предупреждение, если disk_free_pct ниже порога.
#   */30 * * * * root /opt/design-studio/deploy/disk_alert.sh
#
# Источник — /api/health сервиса; если он не отвечает, процент считается через df по тому
# design-data (место кончается и тогда, когда сервис лежит).
# Предупреждение уходит в syslog (logger -t design-studio), в stderr (cron отправит письмо
# по MAILTO) и, если задан ALERT_WEBHOOK_URL, POST-запросом с текстом. Повтор не чаще раза
# в ALERT_REPEAT_HOURS часов (по умолчанию 6).
# Переменные: DISK_ALERT_PCT (порог, 10), HEALTH_URL, DESIGN_DATA_DIR, ALERT_WEBHOOK_URL.
set -euo pipefail

threshold="${DISK_ALERT_PCT:-10}"
health_url="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
stamp="${ALERT_STAMP:-/var/tmp/design-studio-disk-alert}"
repeat_s=$(( ${ALERT_REPEAT_HOURS:-6} * 3600 ))

pct=""
source="api"
if [ -z "${DISK_FREE_PCT:-}" ]; then
	body="$(curl -fsS --max-time 5 "$health_url" 2>/dev/null || true)"
	if [ -n "$body" ]; then
		pct="$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["disk_free_pct"])' 2>/dev/null || true)"
	fi
else
	pct="$DISK_FREE_PCT"  # для проверки скрипта
fi
if [ -z "$pct" ]; then
	source="df"
	dir="${DESIGN_DATA_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' design-data 2>/dev/null || echo /)}"
	used="$(df -P "$dir" | awk 'NR==2 {gsub("%", "", $5); print $5}')"
	pct=$(( 100 - used ))
fi

if python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)' "$pct" "$threshold"; then
	msg="design.proftex.tech: свободно ${pct}% диска (порог ${threshold}%, источник ${source}) на $(hostname)"
	now=$(date +%s)
	last=$(cat "$stamp" 2>/dev/null || echo 0)
	if [ $(( now - last )) -ge "$repeat_s" ]; then
		logger -t design-studio -p user.warning "$msg" 2>/dev/null || true
		echo "$msg" >&2
		if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
			curl -fsS --max-time 10 -X POST --data-urlencode "text=$msg" "$ALERT_WEBHOOK_URL" >/dev/null || true
		fi
		echo "$now" > "$stamp"
	fi
	exit 1
fi
rm -f "$stamp"
echo "свободно ${pct}% (источник ${source}), порог ${threshold}%"
