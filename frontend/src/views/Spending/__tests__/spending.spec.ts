// Показатели 1, 2 и 4 карточки T13: итог, график и формат сумм на экране «Мои расходы».
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import type { DOMWrapper } from '@vue/test-utils'
import type { MySpending } from '@/api/client'
import { server } from '@/mocks/node'
import { MOCK_ACCOUNTS } from '@/mocks/db'
import { auth } from '@/stores/auth'
import { mountApp, settle } from '@/__tests__/helpers'
import { formatMoney, pluralWorks } from '../money'
import { customRangeError, fillDays, presetRange, shortDay, tickIndexes } from '../period'

const NOW = new Date('2026-10-30T12:00:00')

/** Ответ с несколькими днями и моделями; итог сходится с разбивками. */
const RICH: MySpending = {
  from: '2026-10-24',
  to: '2026-10-30',
  total_micro_usd: 12_345_678 + 4_200 + 500_000,
  count: 6,
  by_day: [
    { key: '2026-10-25', label: '2026-10-25', count: 3, cost_micro_usd: 12_345_678 },
    { key: '2026-10-27', label: '2026-10-27', count: 1, cost_micro_usd: 4_200 },
    { key: '2026-10-30', label: '2026-10-30', count: 2, cost_micro_usd: 500_000 },
  ],
  by_model: [
    { key: 'gpt-image-2.5-sunburst', label: 'GPT Image 2.5 Sunburst', count: 4, cost_micro_usd: 12_545_678 },
    { key: 'gpt-image-1-mini', label: 'GPT Image 1 Mini', count: 2, cost_micro_usd: 304_200 },
  ],
}

const EMPTY: MySpending = { from: '2026-10-30', to: '2026-10-30', total_micro_usd: 0, count: 0, by_day: [], by_model: [] }

/** Подменяет ответ GET /api/spending/me и запоминает параметры запросов. */
function serve(body: (url: URL) => MySpending) {
  const calls: URL[] = []
  server.use(
    http.get('*/api/spending/me', ({ request }) => {
      const url = new URL(request.url)
      calls.push(url)
      return HttpResponse.json(body(url))
    }),
  )
  return calls
}

async function openSpending() {
  await auth.login(MOCK_ACCOUNTS.designer.username, MOCK_ACCOUNTS.designer.password)
  return mountApp('/spending')
}

const sum = (xs: number[]) => xs.reduce((s, x) => s + x, 0)
const micro = (els: DOMWrapper<Element>[]) => els.map((e) => Number(e.attributes('data-micro')))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
})
afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('формат сумм (показатель 4)', () => {
  it('обычные суммы: два знака, запятая, USD', () => {
    expect(formatMoney(12_340_000)).toBe('12,34 USD')
    expect(formatMoney(10_000)).toBe('0,01 USD')
    expect(formatMoney(133_000)).toBe('0,13 USD')
    expect(formatMoney(0)).toBe('0,00 USD')
    expect(formatMoney(1_234_500_000)).toBe('1 234,50 USD')
    expect(formatMoney(12_345_678)).toBe('12,35 USD')
  })

  it('меньше 0,01 USD — четыре знака', () => {
    expect(formatMoney(4_200)).toBe('0,0042 USD')
    expect(formatMoney(9_000)).toBe('0,0090 USD')
    expect(formatMoney(100)).toBe('0,0001 USD')
  })

  it('склонение числа работ', () => {
    expect([1, 2, 5, 11, 12, 21, 22, 25, 111].map(pluralWorks)).toEqual([
      '1 работа',
      '2 работы',
      '5 работ',
      '11 работ',
      '12 работ',
      '21 работа',
      '22 работы',
      '25 работ',
      '111 работ',
    ])
  })

  it('на экране суммы в формате «12,35 USD» и «0,0042 USD»', async () => {
    serve(() => RICH)
    const { wrapper } = await openSpending()
    const cells = wrapper.findAll('[data-testid="model-cost"]').map((c) => c.text())
    expect(cells).toEqual(['12,55 USD', '0,30 USD'])
    const titles = wrapper.findAll('[data-testid="chart-bar"] title').map((t) => t.text())
    expect(titles).toContain('27.10.2026: 0,0042 USD, 1 работа')
  })
})

describe('периоды', () => {
  it('готовые периоды считаются от сегодняшнего дня', () => {
    expect(presetRange('today', NOW)).toEqual({ from: '2026-10-30', to: '2026-10-30' })
    expect(presetRange('7d', NOW)).toEqual({ from: '2026-10-24', to: '2026-10-30' })
    expect(presetRange('30d', NOW)).toEqual({ from: '2026-10-01', to: '2026-10-30' })
  })

  it('свой период проверяется', () => {
    expect(customRangeError('2026-10-01', '2026-10-30')).toBe('')
    expect(customRangeError('2026-10-30', '2026-10-01')).toBe('Начало периода позже конца')
    expect(customRangeError('', '2026-10-01')).toBe('Укажите обе даты')
  })

  it('кнопки периодов отправляют from/to', async () => {
    const calls = serve(() => RICH)
    const { wrapper } = await openSpending()
    expect(calls.at(-1)?.searchParams.get('from')).toBe('2026-10-01')
    expect(calls.at(-1)?.searchParams.get('to')).toBe('2026-10-30')

    await wrapper.find('[data-testid="period-7d"]').trigger('click')
    await settle()
    expect(calls.at(-1)?.searchParams.get('from')).toBe('2026-10-24')

    await wrapper.find('[data-testid="period-today"]').trigger('click')
    await settle()
    expect(calls.at(-1)?.searchParams.get('from')).toBe('2026-10-30')
    expect(calls.at(-1)?.searchParams.get('to')).toBe('2026-10-30')
  })

  it('свой период: неверный порядок дат показывает ошибку и не ходит в API', async () => {
    const calls = serve(() => RICH)
    const { wrapper } = await openSpending()
    await wrapper.find('[data-testid="period-custom"]').trigger('click')
    await settle()
    const before = calls.length
    await wrapper.find('[data-testid="custom-from"]').setValue('2026-10-20')
    await wrapper.find('[data-testid="custom-to"]').setValue('2026-10-10')
    await wrapper.find('[data-testid="custom-form"]').trigger('submit')
    await settle()
    expect(wrapper.find('[data-testid="custom-error"]').text()).toBe('Начало периода позже конца')
    expect(calls.length).toBe(before)

    await wrapper.find('[data-testid="custom-to"]').setValue('2026-10-25')
    await wrapper.find('[data-testid="custom-form"]').trigger('submit')
    await settle()
    expect(wrapper.find('[data-testid="custom-error"]').exists()).toBe(false)
    expect(calls.at(-1)?.searchParams.get('from')).toBe('2026-10-20')
    expect(calls.at(-1)?.searchParams.get('to')).toBe('2026-10-25')
  })
})

describe('итог равен сумме по дням и по моделям (показатель 1)', () => {
  it('на стандартных мок-данных', async () => {
    const { wrapper } = await openSpending()
    const total = wrapper.find('[data-testid="total"]').text()
    const days = sum(micro(wrapper.findAll('[data-testid="chart-bar"]')))
    const models = sum(micro(wrapper.findAll('[data-testid="model-row"]')))
    expect(days).toBeGreaterThan(0)
    expect(total).toBe(formatMoney(days))
    expect(total).toBe(formatMoney(models))
    expect(wrapper.find('[data-testid="models-total"]').text()).toBe(total)
  })

  it('на ответе с несколькими днями и моделями', async () => {
    serve(() => RICH)
    const { wrapper } = await openSpending()
    const total = wrapper.find('[data-testid="total"]').text()
    expect(total).toBe(formatMoney(RICH.total_micro_usd))
    expect(sum(micro(wrapper.findAll('[data-testid="chart-bar"]')))).toBe(RICH.total_micro_usd)
    expect(sum(micro(wrapper.findAll('[data-testid="model-row"]')))).toBe(RICH.total_micro_usd)
    expect(wrapper.find('[data-testid="count"]').text()).toBe('6 работ')
  })
})

describe('график (показатель 2)', () => {
  it('столбцы, подписи и максимум берутся из данных', async () => {
    serve(() => RICH)
    const { wrapper } = await openSpending()
    const bars = wrapper.findAll('[data-testid="chart-bar"]')
    // все 7 дней периода из ответа, дни без расходов — нулевые
    expect(bars.map((b) => b.attributes('data-key'))).toEqual(fillDays(RICH.from, RICH.to, RICH.by_day).map((d) => d.key))
    expect(bars).toHaveLength(7)
    expect(micro(bars)).toEqual([0, 12_345_678, 0, 4_200, 0, 0, 500_000])
    // высота столбца пропорциональна сумме
    const heights = bars.map((b) => Number(b.find('rect.bar').attributes('height')))
    expect(heights[1]).toBeGreaterThan(heights[6]!)
    expect(heights[6]).toBeGreaterThan(heights[3]!)
    expect(heights[0]).toBe(0)
    // подписи осей
    expect(wrapper.find('[data-testid="chart-ymax"]').text()).toBe(formatMoney(12_345_678))
    const xs = wrapper.findAll('[data-testid="chart-xlabel"]').map((x) => x.text())
    expect(xs).toEqual(['24.10', '25.10', '26.10', '27.10', '28.10', '29.10', '30.10'].filter((_, i) => tickIndexes(7).includes(i)))
    expect(xs[0]).toBe(shortDay(RICH.from))
    expect(xs.at(-1)).toBe(shortDay(RICH.to))
  })

  it('другие данные — другие подписи (ничего не зашито)', async () => {
    serve(() => ({
      from: '2026-09-01',
      to: '2026-09-02',
      total_micro_usd: 3_000_000,
      count: 1,
      by_day: [{ key: '2026-09-02', label: '2026-09-02', count: 1, cost_micro_usd: 3_000_000 }],
      by_model: [{ key: 'x', label: 'Модель X', count: 1, cost_micro_usd: 3_000_000 }],
    }))
    const { wrapper } = await openSpending()
    expect(wrapper.findAll('[data-testid="chart-xlabel"]').map((x) => x.text())).toEqual(['01.09', '02.09'])
    expect(wrapper.find('[data-testid="chart-ymax"]').text()).toBe('3,00 USD')
    expect(wrapper.find('[data-testid="model-row"]').text()).toContain('Модель X')
  })

  it('пустой период показывает пустое состояние без графика и таблицы', async () => {
    serve(() => EMPTY)
    const { wrapper } = await openSpending()
    expect(wrapper.find('[data-testid="spending-empty"]').text()).toContain('За этот период расходов нет')
    expect(wrapper.find('[data-testid="chart"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="model-row"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="total"]').text()).toBe('0,00 USD')
  })

  it('ошибка API показывает текст', async () => {
    server.use(http.get('*/api/spending/me', () => HttpResponse.json({ detail: 'Неверный период' }, { status: 422 })))
    const { wrapper } = await openSpending()
    expect(wrapper.find('[data-testid="spending-error"]').text()).toBe('Неверный период')
  })

  it('fillDays не теряет дни вне периода и не раздувает длинные периоды', () => {
    const b = [{ key: '2020-01-05', label: '', count: 1, cost_micro_usd: 7 }]
    expect(fillDays('2020-01-01', '2022-01-01', b)).toEqual(b)
    expect(fillDays('2020-01-01', '2020-01-02', b).map((d) => d.key)).toEqual(['2020-01-01', '2020-01-02', '2020-01-05'])
  })
})
