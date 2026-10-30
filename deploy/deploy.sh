#!/usr/bin/env bash
# Обновление сервиса на VDS: git pull → сборка → запуск → проверка здоровья → откат при провале.
#
#   deploy/deploy.sh [--dry-run] [--no-pull]
#
# Образы: design-studio:current — то, что запущено; design-studio:previous — прошлая версия.
# Если после запуска /api/health не ответил 200 за HEALTH_TIMEOUT секунд (по умолчанию 90),
# current возвращается на previous, контейнер перезапускается, код возврата 1.
#
# --dry-run печатает команды, ничего не меняя. Исход проверки здоровья в сухом прогоне
# задаёт DRY_RUN_HEALTH=ok|fail (по умолчанию ok) — так проверяется ветка отката;
# прошлая версия в сухом прогоне считается здоровой.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
compose=(docker compose -f "$root/deploy/docker-compose.yml")
image=design-studio
health_url="${HEALTH_URL:-http://127.0.0.1:${DESIGN_PORT:-8000}/api/health}"
health_timeout="${HEALTH_TIMEOUT:-90}"

dry=0
pull=1
for arg in "$@"; do
	case "$arg" in
		--dry-run) dry=1 ;;
		--no-pull) pull=0 ;;
		*) echo "неизвестный аргумент: $arg" >&2; exit 2 ;;
	esac
done

log() { echo "[deploy] $*"; }
run() {
	if [ "$dry" = 1 ]; then
		echo "+ $*"
	else
		"$@"
	fi
}

healthy() {
	if [ "$dry" = 1 ]; then
		echo "+ ждать 200 от $health_url до ${health_timeout} с (сухой прогон: $1)"
		[ "$1" = ok ]
		return
	fi
	local deadline=$(( $(date +%s) + health_timeout ))
	while [ "$(date +%s)" -lt "$deadline" ]; do
		if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$health_url")" = 200 ]; then
			return 0
		fi
		sleep 3
	done
	return 1
}

[ -f "$root/.env" ] || [ "$dry" = 1 ] || { echo "нет $root/.env (см. .env.example)" >&2; exit 1; }

if [ "$pull" = 1 ] && [ -d "$root/.git" ]; then
	log "обновление кода"
	run git -C "$root" pull --ff-only
fi

rev="$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo nogit)"
log "сборка $image:$rev"
run docker build -f "$root/deploy/Dockerfile" -t "$image:$rev" "$root"

had_current=0
if docker image inspect "$image:current" >/dev/null 2>&1; then
	had_current=1
fi
if [ "$had_current" = 1 ] || [ "$dry" = 1 ]; then
	log "сохраняю текущий образ как $image:previous"
	run docker tag "$image:current" "$image:previous"
fi

log "запуск $image:$rev"
run docker tag "$image:$rev" "$image:current"
run "${compose[@]}" up -d --no-build design-studio

if healthy "${DRY_RUN_HEALTH:-ok}"; then
	log "OK: $image:$rev работает, /api/health = 200"
	exit 0
fi

log "ПРОВАЛ: /api/health не ответил 200 за ${health_timeout} с"
run docker logs --tail 50 design-studio || true
if [ "$had_current" = 1 ] || [ "$dry" = 1 ]; then
	log "откат на $image:previous"
	run docker tag "$image:previous" "$image:current"
	run "${compose[@]}" up -d --no-build --force-recreate design-studio
	if healthy ok; then
		log "откат выполнен, работает прошлая версия"
	else
		log "ВНИМАНИЕ: и прошлая версия не отвечает — смотрите docker logs design-studio"
	fi
else
	log "прошлой версии нет (первый деплой) — откатывать некуда"
fi
exit 1
