// Фокус не выходит из диалога: Tab и Shift+Tab ходят по кругу внутри него.
import { onBeforeUnmount, onMounted, type Ref } from 'vue'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function focusableIn(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)]
}

export function useFocusTrap(root: Ref<HTMLElement | null>): void {
  function onKeydown(e: KeyboardEvent): void {
    const el = root.value
    if (e.key !== 'Tab' || !el) return
    const list = focusableIn(el)
    if (!list.length) {
      e.preventDefault()
      el.focus()
      return
    }
    const first = list[0]!
    const last = list[list.length - 1]!
    const active = document.activeElement
    const inside = active instanceof Node && el.contains(active)
    if (e.shiftKey && (active === first || active === el || !inside)) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && (active === last || !inside)) {
      e.preventDefault()
      first.focus()
    }
  }

  // Фокус, ушедший из диалога не с клавиатуры, возвращается в него.
  function onFocusIn(e: FocusEvent): void {
    const el = root.value
    if (el && e.target instanceof Node && !el.contains(e.target)) el.focus()
  }

  onMounted(() => {
    document.addEventListener('keydown', onKeydown, true)
    document.addEventListener('focusin', onFocusIn)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown, true)
    document.removeEventListener('focusin', onFocusIn)
  })
}
