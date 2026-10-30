#!/usr/bin/env bash
# Проверки артефактов деплоя (критерии T07). Запуск из корня: deploy/tests/run.sh
# Части, которым нужен Docker (сборка, compose, caddy:2), пропускаются, если демона нет;
# SKIP_BUILD=1 пропускает долгую сборку образа (тогда 4a проверяется на готовом design-studio:current).
# ok/bad только печатают, поэтому `A && ok || bad` здесь безопасно.
# shellcheck disable=SC2015
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
fail=0
ok() { echo "PASS  $*"; }
bad() { echo "FAIL  $*"; fail=1; }
skip() { echo "SKIP  $*"; }
have_docker() { docker info >/dev/null 2>&1; }

# 6. Секретов нет: .env в .dockerignore, ключей вида sk-... нет в репозитории.
grep -qx '.env' .dockerignore && ok "6: .env в .dockerignore" || bad "6: .env нет в .dockerignore"
if grep -rnE "sk-[A-Za-z0-9_-]{20,}" --exclude-dir=.git --exclude-dir=node_modules . >/dev/null; then bad "6: в репозитории найден ключ sk-..."; else ok "6: ключей sk-... в репозитории нет"; fi

# 4. Бэкап: хук + verify на тестовой базе.
if deploy/backup/verify.sh --selftest >/tmp/design-verify.log 2>&1; then
	ok "4: verify.sh --selftest (копия, integrity ok, строки совпадают, файлы на месте)"
else
	bad "4: verify.sh --selftest"; cat /tmp/design-verify.log
fi

# 5. Откат в deploy.sh (сухой прогон).
out="$(DRY_RUN_HEALTH=fail deploy/deploy.sh --dry-run --no-pull 2>&1 || true)"
if grep -q "docker tag design-studio:previous design-studio:current" <<<"$out" \
	&& ! DRY_RUN_HEALTH=fail deploy/deploy.sh --dry-run --no-pull >/dev/null 2>&1; then
	ok "5: deploy.sh --dry-run при провале здоровья возвращает previous и выходит с ошибкой"
else
	bad "5: deploy.sh не откатывает"; echo "$out"
fi
if DRY_RUN_HEALTH=ok deploy/deploy.sh --dry-run --no-pull | grep -q "откат"; then
	bad "5: откат при здоровом запуске"
else
	ok "5: при здоровом запуске отката нет"
fi

# disk_alert.sh: порог 10%.
if DISK_FREE_PCT=5 ALERT_STAMP="$(mktemp -u)" deploy/disk_alert.sh >/dev/null 2>&1; then
	bad "disk_alert: 5% не вызвал предупреждение"
else
	ok "disk_alert: 5% → предупреждение"
fi
DISK_FREE_PCT=50 deploy/disk_alert.sh >/dev/null && ok "disk_alert: 50% → тихо" || bad "disk_alert: 50%"

if ! have_docker; then
	skip "1, 2, 3, 4a: нет Docker"
	exit "$fail"
fi

# 2. docker compose config.
if DESIGN_ENV_FILE=../.env.example docker compose -f deploy/docker-compose.yml config -q; then
	ok "2: docker compose config"
else
	bad "2: docker compose config"
fi
cmd="$(DESIGN_ENV_FILE=../.env.example docker compose -f deploy/docker-compose.yml config --format json \
	| python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["services"]["design-studio"]["command"]))')"
grep -q -- "--workers=1" <<<"$cmd" && ok "4a: в compose --workers=1" || bad "4a: в compose нет --workers=1"

# 3. caddy validate объединённого конфига, ops-блок не изменён.
tmp="$(mktemp -d)"
cp deploy/tests/ops.Caddyfile.sample "$tmp/Caddyfile"
if deploy/caddy_check.sh "$tmp/Caddyfile" >"$tmp/log" 2>&1 \
	&& diff <(sed -n '/^ops.proftex.tech/,/^}/p' "$tmp/Caddyfile") <(sed -n '/^ops.proftex.tech/,/^}/p' "$tmp/Caddyfile.new") >/dev/null \
	&& cmp -s deploy/tests/ops.Caddyfile.sample "$tmp/Caddyfile"; then
	ok "3: caddy validate (существующий + design.caddy), блок ops и исходный файл не изменены"
else
	bad "3: caddy_check.sh"; cat "$tmp/log"
fi
printf 'design.proftex.tech {\n\tnot_a_directive\n}\n' >"$tmp/broken.caddy"
cp deploy/tests/ops.Caddyfile.sample "$tmp/Caddyfile2"
if DESIGN_CADDY="$tmp/broken.caddy" deploy/caddy_check.sh "$tmp/Caddyfile2" >/dev/null 2>&1; then
	bad "3: сломанный блок прошёл validate"
else
	ok "3: сломанный блок отклонён"
fi
rm -rf "$tmp"

# 1. Сборка образа.
if [ "${SKIP_BUILD:-0}" != 1 ]; then
	if docker build -q -f deploy/Dockerfile -t design-studio:check . >/dev/null; then
		ok "1: docker build -f deploy/Dockerfile ."
		img=design-studio:check
	else
		bad "1: docker build"; img=""
	fi
else
	skip "1: сборка (SKIP_BUILD=1)"
	img=design-studio:current
fi

# 4a + 6: один процесс Uvicorn, не root, .env и ключей в образе нет.
if [ -n "${img:-}" ] && docker image inspect "$img" >/dev/null 2>&1; then
	name="design-check-$$"
	docker run -d --rm --name "$name" -e SECRET_KEY=check "$img" >/dev/null
	sleep 4
	procs="$(docker top "$name" -eo pid,user,args | grep -c '[u]vicorn' || true)"
	user="$(docker top "$name" -eo pid,user | awk 'NR > 1 {print $2}' | sort -u)"
	[ "$procs" = 1 ] && ok "4a: в контейнере ровно один процесс uvicorn" || bad "4a: процессов uvicorn: $procs"
	[ "$user" != root ] && [ "$user" != 0 ] && ok "образ: процесс не от root ($user)" || bad "образ: процесс от root"
	if docker exec "$name" sh -c 'test ! -e /app/.env && ! grep -rqsE "sk-[A-Za-z0-9_-]{20,}" /app'; then
		ok "6: в образе нет .env и ключей sk-..."
	else
		bad "6: в образе найден секрет"
	fi
	docker stop "$name" >/dev/null
fi

exit "$fail"
