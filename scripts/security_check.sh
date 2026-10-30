#!/usr/bin/env bash
# S-14 «Безопасность»: ключ не в образе, логах, ответах и git; загрузки и чужие файлы.
#   scripts/security_check.sh
# Проверки по HTTP запускают временный сервис в режиме заглушки (см. security_probe.py).
set -u
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
status=0
fail() { echo "  FAIL $1"; status=1; }
ok() { echo "  OK   $1"; }

echo "Ключ не в git и не в образе:"
if git grep -nIE 'sk-[A-Za-z0-9_-]{20,}' -- . ':!scripts/security_probe.py' ':!backend/tests' ':!frontend/node_modules' >/dev/null; then
  fail "в репозитории есть строка, похожая на ключ OpenAI"
else ok "в отслеживаемых файлах нет строк вида sk-…"; fi
if git ls-files --error-unmatch .env >/dev/null 2>&1; then fail ".env лежит в git"; else ok ".env не в git"; fi
git check-ignore -q .env && ok ".env в .gitignore" || fail ".env не в .gitignore"
if grep -nE '^\s*(ARG|ENV)\s+.*(OPENAI_API_KEY|SECRET_KEY|ADMIN_PASSWORD)\s*=\s*\S' deploy/Dockerfile; then
  fail "Dockerfile запекает секрет в образ"
else ok "Dockerfile не задаёт значения секретов"; fi
if grep -nE '^\s*COPY\s+.*\.env' deploy/Dockerfile; then fail "Dockerfile копирует .env"; else ok "Dockerfile не копирует .env"; fi

"$PY" scripts/security_probe.py all || status=1

echo "S-14:" "$([ "$status" -eq 0 ] && echo OK || echo FAIL)"
exit "$status"
