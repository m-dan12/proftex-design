// Периоды экрана расходов и подготовка ряда для графика.
import type { SpendingBucket } from '@/api/client'
import { isoDate } from '@/utils/format'

export type PeriodKind = 'today' | '7d' | '30d' | 'custom'

export const PERIODS: { kind: PeriodKind; label: string }[] = [
  { kind: 'today', label: 'Сегодня' },
  { kind: '7d', label: '7 дней' },
  { kind: '30d', label: '30 дней' },
  { kind: 'custom', label: 'Свой' },
]

/** Самый длинный период, который график раскладывает по всем дням (дальше — только дни с расходами). */
export const MAX_FILLED_DAYS = 400

const DAY_MS = 86_400_000

function shift(d: Date, days: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + days)
  return r
}

/** Границы готового периода включительно, в формате YYYY-MM-DD. */
export function presetRange(kind: Exclude<PeriodKind, 'custom'>, today: Date): { from: string; to: string } {
  const back = kind === 'today' ? 0 : kind === '7d' ? 6 : 29
  return { from: isoDate(shift(today, -back)), to: isoDate(today) }
}

/** Проверка своего периода: текст ошибки или пустая строка. */
export function customRangeError(from: string, to: string): string {
  const re = /^\d{4}-\d{2}-\d{2}$/
  if (!re.test(from) || !re.test(to)) return 'Укажите обе даты'
  if (from > to) return 'Начало периода позже конца'
  return ''
}

function parseDay(day: string): number {
  const [y, m, d] = day.split('-').map(Number)
  return Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1)
}

/**
 * Ряд для графика: все дни периода по порядку, дни без расходов — нулями.
 * Если период длиннее MAX_FILLED_DAYS, остаются только дни из данных.
 */
export function fillDays(from: string, to: string, buckets: SpendingBucket[]): SpendingBucket[] {
  const sorted = [...buckets].sort((a, b) => a.key.localeCompare(b.key))
  const start = parseDay(from)
  const span = Math.round((parseDay(to) - start) / DAY_MS) + 1
  if (!(span > 0) || span > MAX_FILLED_DAYS) return sorted
  const known = new Map(sorted.map((b) => [b.key, b]))
  const out: SpendingBucket[] = []
  for (let i = 0; i < span; i++) {
    const key = new Date(start + i * DAY_MS).toISOString().slice(0, 10)
    out.push(known.get(key) ?? { key, label: key, count: 0, cost_micro_usd: 0 })
    known.delete(key)
  }
  // дни из данных вне периода не теряем, чтобы сумма графика совпадала с итогом
  out.push(...known.values())
  return out.sort((a, b) => a.key.localeCompare(b.key))
}

/** «2026-10-27» → «27.10». */
export function shortDay(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  return m ? `${m[3]}.${m[2]}` : day
}

/** «2026-10-27» → «27.10.2026». */
export function longDay(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  return m ? `${m[3]}.${m[2]}.${m[1]}` : day
}

/** Индексы подписей оси X: первая, последняя и равномерно между ними, не больше max. */
export function tickIndexes(n: number, max = 6): number[] {
  if (n <= 0) return []
  if (n <= max) return Array.from({ length: n }, (_, i) => i)
  const step = (n - 1) / (max - 1)
  return Array.from({ length: max }, (_, i) => Math.round(i * step))
}
