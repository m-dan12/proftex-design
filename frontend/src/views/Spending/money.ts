// Склонение для экранов расходов и профиля. Форматирование денег — в `@/utils/format`.

/** 1 работа, 2 работы, 5 работ. */
export function pluralWorks(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return `${n} работа`
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} работы`
  return `${n} работ`
}
