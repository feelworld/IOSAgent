import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import { wsClient } from '../ws/client'

export interface DashboardData {
  devices: { total: number; online: number; offline: number; busy: number; error: number }
  tasks_today: { total: number; success: number; failed: number; running: number }
  strategies: { active_explore: number; active_execute: number }
  downloads_today: number
  downloads_total: number
}

export const useDashboardStore = defineStore('dashboard', () => {
  const data = ref<DashboardData>({
    devices: { total: 0, online: 0, offline: 0, busy: 0, error: 0 },
    tasks_today: { total: 0, success: 0, failed: 0, running: 0 },
    strategies: { active_explore: 0, active_execute: 0 },
    downloads_today: 0,
    downloads_total: 0,
  })
  const loading = ref(false)

  async function fetchDashboard() {
    loading.value = true
    try {
      const res = await client.get('/dashboard')
      if (res.data.code === 0) {
        data.value = res.data.data
      }
    } finally {
      loading.value = false
    }
  }

  function setupWsHandlers() {
    wsClient.on('dashboard.stats', (payload: any) => {
      if (payload.devices) data.value.devices = payload.devices
      if (payload.tasks_today) data.value.tasks_today = payload.tasks_today
      if (payload.strategies) data.value.strategies = payload.strategies
      if (payload.downloads_today !== undefined) data.value.downloads_today = payload.downloads_today
      if (payload.downloads_total !== undefined) data.value.downloads_total = payload.downloads_total
    })
  }

  return { data, loading, fetchDashboard, setupWsHandlers }
})
