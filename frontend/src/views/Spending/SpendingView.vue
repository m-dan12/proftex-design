<!-- «Мои расходы» (FR-13): период, итог, график по дням и таблица по моделям. -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, ApiError, unwrap, type MySpending } from '@/api/client'
import DayChart from './DayChart.vue'
import { formatMoney } from '@/utils/format'
import { pluralWorks } from './money'
import { customRangeError, fillDays, longDay, PERIODS, presetRange, type PeriodKind } from './period'

const kind = ref<PeriodKind>('30d')
const range = ref(presetRange('30d', new Date()))
const customFrom = ref(range.value.from)
const customTo = ref(range.value.to)
const customError = ref('')

const data = ref<MySpending | null>(null)
const loading = ref(false)
const error = ref('')
let requestNo = 0

async function load(): Promise<void> {
  const no = ++requestNo
  loading.value = true
  error.value = ''
  try {
    const res = await unwrap(api.GET('/api/spending/me', { params: { query: { ...range.value } } }))
    if (no !== requestNo) return
    data.value = res
  } catch (e) {
    if (no !== requestNo) return
    data.value = null
    error.value = e instanceof ApiError ? e.detail : 'Сервер недоступен, попробуйте позже'
  } finally {
    if (no === requestNo) loading.value = false
  }
}

function choose(k: PeriodKind): void {
  kind.value = k
  customError.value = ''
  if (k === 'custom') {
    customFrom.value = range.value.from
    customTo.value = range.value.to
    return
  }
  range.value = presetRange(k, new Date())
  void load()
}

function applyCustom(): void {
  customError.value = customRangeError(customFrom.value, customTo.value)
  if (customError.value) return
  range.value = { from: customFrom.value, to: customTo.value }
  void load()
}

const days = computed(() => (data.value ? fillDays(data.value.from, data.value.to, data.value.by_day) : []))
const models = computed(() => [...(data.value?.by_model ?? [])].sort((a, b) => b.cost_micro_usd - a.cost_micro_usd))
const isEmpty = computed(() => !!data.value && data.value.count === 0 && data.value.by_day.length === 0)
const periodText = computed(() => {
  const r = data.value ?? range.value
  return r.from === r.to ? longDay(r.from) : `${longDay(r.from)} — ${longDay(r.to)}`
})

function share(micro: number): string {
  const total = data.value?.total_micro_usd ?? 0
  return total > 0 ? `${Math.round((micro / total) * 100)}%` : '—'
}

onMounted(load)
</script>

<template>
  <section class="page spending">
    <h1>Мои расходы</h1>

    <div class="periods" role="group" aria-label="Период">
      <button
        v-for="p in PERIODS"
        :key="p.kind"
        type="button"
        class="btn"
        :class="{ 'btn-primary': kind === p.kind }"
        :aria-pressed="kind === p.kind"
        :data-testid="`period-${p.kind}`"
        @click="choose(p.kind)"
      >
        {{ p.label }}
      </button>
    </div>

    <form v-if="kind === 'custom'" class="custom card" novalidate data-testid="custom-form" @submit.prevent="applyCustom">
      <div class="field">
        <label for="spending-from">С</label>
        <input id="spending-from" v-model="customFrom" class="input" type="date" data-testid="custom-from" />
      </div>
      <div class="field">
        <label for="spending-to">По</label>
        <input id="spending-to" v-model="customTo" class="input" type="date" data-testid="custom-to" />
      </div>
      <button type="submit" class="btn btn-primary">Показать</button>
      <p v-if="customError" class="error custom-error" role="alert" data-testid="custom-error">{{ customError }}</p>
    </form>

    <p v-if="error" class="error" role="alert" data-testid="spending-error">{{ error }}</p>

    <template v-if="data">
      <div class="card summary" :aria-busy="loading">
        <div class="muted">Итого за {{ periodText }}</div>
        <div class="total" data-testid="total">{{ formatMoney(data.total_micro_usd) }}</div>
        <div class="muted" data-testid="count">{{ pluralWorks(data.count) }}</div>
      </div>

      <div v-if="isEmpty" class="card empty" data-testid="spending-empty">
        <p>За этот период расходов нет.</p>
        <RouterLink :to="{ name: 'generate' }" class="btn btn-primary">Создать работу</RouterLink>
      </div>

      <template v-else>
        <div class="card">
          <h2>По дням</h2>
          <DayChart :days="days" />
        </div>

        <div class="card">
          <h2>По моделям</h2>
          <div class="table-wrap">
            <table class="models">
              <thead>
                <tr>
                  <th scope="col">Модель</th>
                  <th scope="col" class="num">Работ</th>
                  <th scope="col" class="num">Сумма</th>
                  <th scope="col" class="num">Доля</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in models" :key="m.key" data-testid="model-row" :data-micro="m.cost_micro_usd">
                  <td class="name">{{ m.label }}</td>
                  <td class="num">{{ m.count }}</td>
                  <td class="num" data-testid="model-cost">{{ formatMoney(m.cost_micro_usd) }}</td>
                  <td class="num muted">{{ share(m.cost_micro_usd) }}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Итого</th>
                  <td class="num">{{ data.count }}</td>
                  <td class="num" data-testid="models-total">{{ formatMoney(data.total_micro_usd) }}</td>
                  <td class="num muted"></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      </template>
    </template>
    <p v-else-if="loading" class="muted">Загружаем…</p>
  </section>
</template>

<style scoped>
.spending {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.spending h1,
.spending h2 {
  margin: 0;
}

.spending h2 {
  font-size: 17px;
  margin-bottom: 12px;
}

.periods {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.custom {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0 12px;
}

.custom .field {
  flex: 1 1 140px;
  min-width: 0;
}

.custom .btn {
  margin-bottom: 12px;
}

.custom-error {
  flex-basis: 100%;
  margin: 0;
}

.error {
  margin: 0;
}

.summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.total {
  font-size: 32px;
  font-weight: 600;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.empty p {
  margin: 0;
}

.table-wrap {
  overflow-x: auto;
}

.models {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.models th,
.models td {
  padding: 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}

.models thead th {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
}

.models tfoot th,
.models tfoot td {
  font-weight: 600;
  border-bottom: none;
}

.models .num {
  text-align: right;
  white-space: nowrap;
}

.models .name {
  overflow-wrap: anywhere;
}
</style>
