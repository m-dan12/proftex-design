/** 93000 → «$0.09». Деньги в API — целые микродоллары. */
export function formatUsd(microUsd: number, digits = 2): string {
  return `$${(microUsd / 1_000_000).toFixed(digits)}`
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
