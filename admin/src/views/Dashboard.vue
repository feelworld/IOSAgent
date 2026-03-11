<script setup lang="ts">
import { onMounted, computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useDashboardStore } from '../stores/dashboard'

use([PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const store = useDashboardStore()

const devicePieOption = computed(() => ({
  tooltip: { trigger: 'item' as const },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie' as const,
      radius: ['40%', '70%'],
      avoidLabelOverlap: true,
      label: { show: true, formatter: '{b}: {c}' },
      data: [
        { name: '在线', value: store.data.devices.online, itemStyle: { color: '#67C23A' } },
        { name: '离线', value: store.data.devices.offline, itemStyle: { color: '#909399' } },
        { name: '忙碌', value: store.data.devices.busy, itemStyle: { color: '#E6A23C' } },
        { name: '错误', value: store.data.devices.error, itemStyle: { color: '#F56C6C' } },
      ],
    },
  ],
}))

const taskPieOption = computed(() => ({
  tooltip: { trigger: 'item' as const },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie' as const,
      radius: ['40%', '70%'],
      avoidLabelOverlap: true,
      label: { show: true, formatter: '{b}: {c}' },
      data: [
        { name: '成功', value: store.data.tasks_today.success, itemStyle: { color: '#67C23A' } },
        { name: '失败', value: store.data.tasks_today.failed, itemStyle: { color: '#F56C6C' } },
        { name: '运行中', value: store.data.tasks_today.running, itemStyle: { color: '#409EFF' } },
      ],
    },
  ],
}))

const onlineRate = computed(() => {
  const { total, online } = store.data.devices
  return total > 0 ? `${((online / total) * 100).toFixed(1)}%` : '0%'
})

onMounted(() => {
  store.fetchDashboard()
  store.setupWsHandlers()
})
</script>

<template>
  <div class="dashboard" v-loading="store.loading">
    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="总设备" :value="store.data.devices.total" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="在线率" :value="onlineRate" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="今日任务" :value="store.data.tasks_today.total" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="今日下载" :value="store.data.downloads_today" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span>设备状态分布</span></template>
          <VChart :option="devicePieOption" autoresize style="height: 320px" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span>今日任务状态</span></template>
          <VChart :option="taskPieOption" autoresize style="height: 320px" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 策略信息 + 概览 -->
    <el-row :gutter="16" class="info-row">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span>策略概况</span></template>
          <el-descriptions :column="2" border size="default">
            <el-descriptions-item label="活跃探索">
              <el-tag type="warning">{{ store.data.strategies.active_explore }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="活跃实施">
              <el-tag type="success">{{ store.data.strategies.active_execute }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="今日下载">
              {{ store.data.downloads_today }}
            </el-descriptions-item>
            <el-descriptions-item label="累计下载">
              {{ store.data.downloads_total }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span>系统提醒</span></template>
          <el-alert
            v-if="store.data.devices.error > 0"
            :title="`${store.data.devices.error} 台设备处于错误状态`"
            type="error"
            show-icon
            :closable="false"
            style="margin-bottom: 8px"
          />
          <el-alert
            v-if="store.data.devices.offline > 0"
            :title="`${store.data.devices.offline} 台设备离线`"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 8px"
          />
          <el-alert
            v-if="store.data.tasks_today.failed > 0"
            :title="`今日 ${store.data.tasks_today.failed} 个任务失败`"
            type="error"
            show-icon
            :closable="false"
            style="margin-bottom: 8px"
          />
          <el-alert
            v-if="store.data.devices.error === 0 && store.data.devices.offline === 0 && store.data.tasks_today.failed === 0"
            title="系统运行正常"
            type="success"
            show-icon
            :closable="false"
          />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 0;
}
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
}
.chart-row {
  margin-bottom: 16px;
}
.info-row {
  margin-bottom: 16px;
}
</style>
