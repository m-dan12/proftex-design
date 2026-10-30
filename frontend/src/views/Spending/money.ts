// Форматирование денег для экранов расходов и профиля. В API деньги — целые микродоллары.

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

/** 1 работа, 2 работы, 5 работ. */
export function pluralWorks(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return `${n} работа`
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} работы`
  return `${n} работ`
}
