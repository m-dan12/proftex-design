<!-- Модальный диалог админки: Esc и клик по фону закрывают, Tab не выходит за пределы, фокус возвращается. -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{ title: string }>()
const emit = defineEmits<{ close: [] }>()

const box = ref<HTMLElement | null>(null)
let returnFocus: HTMLElement | null = null

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'

function focusables(): HTMLElement[] {
  return box.value ? Array.from(box.value.querySelectorAll<HTMLElement>(FOCUSABLE)) : []
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
    return
  }
  if (e.key !== 'Tab') return
  const items = focusables()
  if (!items.length) return
  const first = items[0]!
  const last = items[items.length - 1]!
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

onMounted(async () => {
  returnFocus = document.activeElement as HTMLElement | null
  await nextTick()
  ;(focusables()[0] ?? box.value)?.focus()
})

onBeforeUnmount(() => {
  returnFocus?.focus?.()
})
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div
      ref="box"
      class="card dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-dialog-title"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <h2 id="admin-dialog-title">{{ title }}</h2>
      <slot />
      <div class="actions">
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--gap);
  background: rgb(0 0 0 / 45%);
}

.dialog {
  width: 100%;
  max-width: 420px;
  box-shadow: var(--shadow);
}

.dialog h2 {
  font-size: 18px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: var(--gap);
}
</style>
