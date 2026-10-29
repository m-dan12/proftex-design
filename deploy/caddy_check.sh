#!/usr/bin/env bash
# Готовит объединённый Caddyfile (существующий + design.caddy), проверяет его `caddy validate`
# и убеждается, что diff со старым файлом состоит только из добавленных строк,
# то есть блок ops.proftex.tech не изменён (NFR-12).
#
#   deploy/caddy_check.sh /etc/caddy/Caddyfile [выходной файл]
#
# Исходный файл не меняется. Результат пишется в <выход> (по умолчанию <Caddyfile>.new),
# рядом сохраняется копия старого: <Caddyfile>.bak-ГГГГММДД-ЧЧММСС.
# Чем проверять: CADDY_CMD (например "docker exec caddy caddy"), иначе caddy из PATH,
# иначе образ caddy:2 через docker run. Для Caddy в контейнере файл должен быть виден
# внутри контейнера по тому же пути (CADDY_VALIDATE_PATH — путь внутри контейнера).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="${1:?укажите путь к существующему Caddyfile}"
out="${2:-$src.new}"
block="${DESIGN_CADDY:-$here/design.caddy}"

[ -f "$src" ] || { echo "нет файла $src" >&2; exit 1; }
if grep -q 'design\.proftex\.tech' "$src"; then
	echo "в $src уже есть design.proftex.tech — объединять нечего" >&2
	exit 1
fi

backup="$src.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$src" "$backup"
{ cat "$src"; printf '\n'; cat "$block"; } > "$out"

# 1. Только добавления: в diff нет строк, начинающихся с "<" (удалённых или изменённых).
if diff "$src" "$out" | grep -q '^<'; then
	echo "ОШИБКА: объединение меняет существующие строки" >&2
	diff "$src" "$out" >&2 || true
	exit 1
fi
echo "diff: только добавленные строки ($(diff "$src" "$out" | grep -c '^>' || true))"

# 2. caddy validate.
validate() {
	local file="$1"
	if [ -n "${CADDY_CMD:-}" ]; then
		# shellcheck disable=SC2086
		$CADDY_CMD validate --adapter caddyfile --config "${CADDY_VALIDATE_PATH:-$file}"
	elif command -v caddy >/dev/null 2>&1; then
		caddy validate --adapter caddyfile --config "$file"
	else
		local dir
		dir="$(cd "$(dirname "$file")" && pwd)"
		docker run --rm --network none -v "$dir:/cfg:ro" caddy:2 \
			caddy validate --adapter caddyfile --config "/cfg/$(basename "$file")"
	fi
}
validate "$out"

echo "OK: $out готов, копия старого: $backup"
echo "Применить: cp $out $src && caddy reload --config $src (или docker exec caddy caddy reload ...)"
echo "Откат:     cp $backup $src && caddy reload --config $src"
