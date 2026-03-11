<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ExploreStrategyResult } from '../stores/strategy'

use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  strategies: ExploreStrategyResult[]
  recommended: string[]
}>()

const chartOption = computed(() => {
  const labels = props.strategies.map(
    (s, i) => s.params?.keyword ? `#${i + 1} ${s.params.keyword}` : `策略 #${i + 1}`,
  )
  const scores = props.strategies.map(s => s.effectiveness_score)
  const rates = props.strategies.map(s => +(s.success_rate * 100).toFixed(1))

  return {
    tooltip: { trigger: 'axis' as const },
    legend: { data: ['效果评分', '成功率 (%)'] },
    xAxis: {
      type: 'category' as const,
      data: labels,
      axisLabel: { rotate: 30 },
    },
    yAxis: [
      { type: 'value' as const, name: '评分' },
      { type: 'value' as const, name: '成功率 (%)', max: 100 },
    ],
    series: [
      {
        name: '效果评分',
        type: 'bar' as const,
        data: scores,
        itemStyle: {
          color: (p: any) =>
            props.recommended.includes(props.strategies[p.dataIndex]?.id)
              ? '#67C23A'
              : '#409EFF',
        },
      },
      {
        name: '成功率 (%)',
        type: 'line' as const,
        yAxisIndex: 1,
        data: rates,
        smooth: true,
        lineStyle: { color: '#E6A23C' },
        itemStyle: { color: '#E6A23C' },
      },
    ],
  }
})
</script>

<template>
  <div class="explore-analysis-chart">
    <VChart :option="chartOption" autoresize style="height: 360px" />
  </div>
</template>

<style scoped>
.explore-analysis-chart {
  width: 100%;
}
</style>
