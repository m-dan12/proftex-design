/** Деньги в API — целые микродоллары. */
const NBSP = ' '

/** Порог, ниже которого сумма показывается с четырьмя знаками: 0,01 USD. */
const SMALL_MICRO = 10_000

function groupThousands(int: string): string {
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
}

/**
 * 12_340_000 → «12,34 USD», 4_200 → «0,0042 USD», 1_234_500_000 → «1 234,50 USD».
 * Считает целыми числами, чтобы не ловить ошибки округления float.
 */
export function formatMoney(microUsd: number): string {
  const micro = Math.max(0, Math.round(microUsd))
  const digits = micro > 0 && micro < SMALL_MICRO ? 4 : 2
  const scale = 10 ** (6 - digits)
  const units = Math.round(micro / scale)
  const div = 10 ** digits
  const int = Math.floor(units / div)
  const frac = String(units % div).padStart(digits, '0')
  return `${groupThousands(String(int))},${frac}${NBSP}USD`
}

/** ISO-время → «29.10.2026, 16:36» по часовому поясу браузера. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

/** Дата для параметров from/to: YYYY-MM-DD (сутки по Москве считает бэкенд). */
export function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
