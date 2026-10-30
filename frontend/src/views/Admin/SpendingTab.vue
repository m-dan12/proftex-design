<!-- Вкладка «Расходы»: период, группировка, таблица с итогом и выгрузка CSV с теми же параметрами. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, ApiError, unwrap, type AdminSpending } from '@/api/client'
import { formatUsd, isoDate } from '@/utils/format'

type Preset = 'today' | '7' | '30' | 'custom'
type Group = AdminSpending['group']

const PRESETS: { id: Preset; label: string }[] = [
  { id: 'today', label: 'Сегодня' },
  { id: '7', label: '7 дней' },
  { id: '30', label: '30 дней' },
  { id: 'custom', label: 'Свой' },
]

const GROUP_TITLES: Record<Group, string> = {
  user: 'Пользователь',
  model: 'Модель',
  day: 'День',
}

function daysBack(days: number): { from: string; to: string } {
  const to = new Date()
  const from = new Date(to)
  from.setDate(from.getDate() - (days - 1))
  return { from: isoDate(from), to: isoDate(to) }
}

const preset = ref<Preset>('30')
const initial = daysBack(30)
const from = ref(initial.from)
const to = ref(initial.to)
const group = ref<Group>('user')

function choose(p: Preset): void {
  preset.value = p
  if (p === 'custom') return
  const range = daysBack(p === 'today' ? 1 : Number(p))
  from.value = range.from
  to.value = range.to
}

const periodError = computed(() => {
  if (!from.value || !to.value) return 'Укажите обе даты'
  if (from.value > to.value) return 'Начало периода позже конца'
  return ''
})

const query = computed(() => ({ from: from.value, to: to.value, group: group.value }))
const csvHref = computed(() => `/api/admin/spending.csv?${new URLSearchParams(query.value)}`)

const data = ref<AdminSpending | null>(null)
const loading = ref(false)
const error = ref('')
let seq = 0

async function load(): Promise<void> {
  if (periodError.value) return
  const my = ++seq
  loading.value = true
  error.value = ''
  try {
    const res = await unwrap(api.GET('/api/admin/spending', { params: { query: { ...query.value } } }))
    if (my === seq) data.value = res
  } catch (e) {
    if (my === seq) error.value = e instanceof ApiError ? e.detail : 'Сервер недоступен, попробуйте позже'
  } finally {
    if (my === seq) loading.value = false
  }
}

watch(query, load, { immediate: true })

/** Маленькие суммы с четырьмя знаками, чтобы не превращались в $0.00. */
const usd = (micro: number) => formatUsd(micro, micro > 0 && micro < 10_000 ? 4 : 2)
</script>

<template>
  <div class="spending">
    <div class="card filters">
      <div class="presets" role="group" aria-label="Период">
        <button
          v-for="p in PRESETS"
          :key="p.id"
          type="button"
          :class="['btn', preset === p.id ? 'btn-primary' : '']"
          :aria-pressed="preset === p.id"
          :data-testid="`period-${p.id}`"
          @click="choose(p.id)"
        >
          {{ p.label }}
        </button>
      </div>
      <div class="controls">
        <div v-if="preset === 'custom'" class="field">
          <label for="spend-from">С</label>
          <input id="spend-from" v-model="from" class="input" type="date" :max="to || undefined" />
        </div>
        <div v-if="preset === 'custom'" class="field">
          <label for="spend-to">По</label>
          <input id="spend-to" v-model="to" class="input" type="date" :min="from || undefined" />
        </div>
        <div class="field">
          <label for="spend-group">Группировка</label>
          <select id="spend-group" v-model="group" class="select">
            <option value="user">По пользователям</option>
            <option value="model">По моделям</option>
            <option value="day">По дням</option>
          </select>
        </div>
      </div>
      <p v-if="periodError" class="error" role="alert">{{ periodError }}</p>
      <div class="summary">
        <p class="total" data-testid="spend-total" :data-micro="data?.total_micro_usd ?? 0">
          Итого: <b>{{ usd(data?.total_micro_usd ?? 0) }}</b>
          <span class="muted"> · генераций: {{ data?.count ?? 0 }}</span>
        </p>
        <a
          class="btn"
          data-testid="csv-link"
          :href="csvHref"
          :download="`spending-${from}-${to}.csv`"
          :aria-disabled="!!periodError"
          :class="{ disabled: !!periodError }"
        >
          Скачать CSV
        </a>
      </div>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !data" class="muted">Загружаем расходы…</p>
    <p v-else-if="data && data.rows.length === 0" class="card empty muted" data-testid="spend-empty">
      За этот период расходов нет
    </p>
    <div v-else-if="data" class="table-wrap" :aria-busy="loading">
      <table class="table" data-testid="spend-table">
        <thead>
          <tr>
            <th scope="col">{{ GROUP_TITLES[data.group] }}</th>
            <th scope="col" class="num">Генераций</th>
            <th scope="col" class="num">Сумма</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data.rows" :key="r.key" data-testid="spend-row" :data-micro="r.cost_micro_usd">
            <td>{{ r.label }}</td>
            <td class="num">{{ r.count }}</td>
            <td class="num">{{ usd(r.cost_micro_usd) }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Итого</th>
            <td class="num">{{ data.count }}</td>
            <td class="num">
              <b>{{ usd(data.total_micro_usd) }}</b>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
</template>

<style scoped>
.spending {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
  gap: 0 var(--gap);
}

.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.total {
  margin: 0;
  font-size: 17px;
}

a.disabled {
  pointer-events: none;
  opacity: 0.6;
}

.empty {
  text-align: center;
}

.table-wrap {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.table thead th {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--surface-2);
}

.table tfoot th,
.table tfoot td {
  border-bottom: none;
  border-top: 2px solid var(--border);
}

.table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
