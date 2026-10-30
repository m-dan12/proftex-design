<!-- График расходов по дням: обычный SVG, столбцы растягиваются по ширине, подписи — HTML, чтобы не мельчали. -->
<script setup lang="ts">
import { computed } from 'vue'
import type { SpendingBucket } from '@/api/client'
import { formatMoney } from '@/utils/format'
import { pluralWorks } from './money'
import { longDay, shortDay, tickIndexes } from './period'

const props = defineProps<{ days: SpendingBucket[] }>()

/** Ширина слота одного дня и высота области графика в единицах viewBox. */
const SLOT = 10
const BAR = 7
const H = 100
/** Самый маленький ненулевой столбец, чтобы копеечные дни были видны. */
const MIN_BAR = 1.5

const max = computed(() => Math.max(0, ...props.days.map((d) => d.cost_micro_usd)))
const width = computed(() => Math.max(1, props.days.length) * SLOT)

const bars = computed(() =>
  props.days.map((d, i) => {
    const raw = max.value > 0 ? (d.cost_micro_usd / max.value) * H : 0
    const h = d.cost_micro_usd > 0 ? Math.max(raw, MIN_BAR) : 0
    return {
      key: d.key,
      micro: d.cost_micro_usd,
      x: i * SLOT + (SLOT - BAR) / 2,
      slotX: i * SLOT,
      y: H - h,
      h,
      title: `${longDay(d.key)}: ${formatMoney(d.cost_micro_usd)}, ${pluralWorks(d.count)}`,
    }
  }),
)

const ticks = computed(() => {
  const n = props.days.length
  return tickIndexes(n).map((i) => {
    const day = props.days[i]!
    const style: Record<string, string> =
      n > 2 && i === 0
        ? { left: '0' }
        : n > 2 && i === n - 1
          ? { right: '0' }
          : { left: `${((i + 0.5) / n) * 100}%`, transform: 'translateX(-50%)' }
    return { key: day.key, label: shortDay(day.key), style }
  })
})
</script>

<template>
  <figure class="chart" data-testid="chart">
    <div class="ymax muted">
      <span class="sr-only">Максимум за день: </span>
      <span data-testid="chart-ymax">{{ formatMoney(max) }}</span>
    </div>
    <svg
      class="plot"
      :viewBox="`0 0 ${width} ${H}`"
      preserveAspectRatio="none"
      role="img"
      aria-label="Расходы по дням"
    >
      <line class="grid" x1="0" :x2="width" y1="0.5" y2="0.5" />
      <line class="grid" x1="0" :x2="width" :y1="H / 2" :y2="H / 2" />
      <g v-for="b in bars" :key="b.key" data-testid="chart-bar" :data-key="b.key" :data-micro="b.micro">
        <title>{{ b.title }}</title>
        <rect class="hit" :x="b.slotX" y="0" :width="SLOT" :height="H" />
        <rect class="bar" :x="b.x" :y="b.y" :width="BAR" :height="b.h" />
      </g>
      <line class="axis" x1="0" :x2="width" :y1="H" :y2="H" />
    </svg>
    <div class="xlabels muted">
      <span v-for="t in ticks" :key="t.key" class="xlabel" :style="t.style" data-testid="chart-xlabel">
        {{ t.label }}
      </span>
    </div>
  </figure>
</template>

<style scoped>
.chart {
  margin: 0;
  min-width: 0;
  overflow: hidden;
}

.ymax {
  font-size: 12px;
  margin-bottom: 4px;
}

.plot {
  display: block;
  width: 100%;
  height: 180px;
}

.grid {
  stroke: var(--border);
  stroke-dasharray: 4 4;
  vector-effect: non-scaling-stroke;
}

.axis {
  stroke: var(--text-muted);
  vector-effect: non-scaling-stroke;
}

.hit {
  fill: transparent;
}

.bar {
  fill: var(--accent);
}

g:hover .bar {
  opacity: 0.8;
}

g:hover .hit {
  fill: var(--accent-soft);
}

.xlabels {
  position: relative;
  height: 20px;
  margin-top: 4px;
  font-size: 12px;
}

.xlabel {
  position: absolute;
  top: 0;
  white-space: nowrap;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
