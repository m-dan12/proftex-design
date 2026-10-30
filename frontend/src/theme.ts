// Тема: светлая, тёмная или как в системе. Выбор хранится в браузере.
import { ref } from 'vue'

export type ThemeChoice = 'system' | 'light' | 'dark'
const KEY = 'theme'

export const theme = ref<ThemeChoice>('system')

function apply(choice: ThemeChoice): void {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
}

export function initTheme(): void {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') theme.value = saved
  } catch {
    // хранилище недоступно (приватный режим) — остаётся системная тема
  }
  apply(theme.value)
}

export function setTheme(choice: ThemeChoice): void {
  theme.value = choice
  apply(choice)
  try {
    if (choice === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, choice)
  } catch {
    // не страшно: тема просто не запомнится
  }
}

const ORDER: ThemeChoice[] = ['system', 'light', 'dark']

export function cycleTheme(): void {
  setTheme(ORDER[(ORDER.indexOf(theme.value) + 1) % ORDER.length]!)
}
