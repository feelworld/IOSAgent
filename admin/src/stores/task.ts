import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import { wsClient } from '../ws/client'

export interface TaskItem {
  id: string
  task_uid: string
  device_id: string
  script_id: string
  script_version: number
  status: string
  params: Record<string, any> | null
  result: {
    stdout?: string
    stderr?: string
    screenshots?: string[]
    download_count?: number
    duration_seconds?: number
  } | null
  error_message: string | null
  source: string
  dispatched_at: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface TaskStats {
  total: number
  pending: number
  running: number
  success: number
  failed: number
  timeout: number
  success_rate: number
}

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<TaskItem[]>([])
  const total = ref(0)
  const stats = ref<TaskStats>({
    total: 0,
    pending: 0,
    running: 0,
    success: 0,
    failed: 0,
    timeout: 0,
    success_rate: 0,
  })
  const loading = ref(false)

  async function fetchTasks(params: {
    status?: string
    source?: string
    page?: number
    size?: number
  } = {}) {
    loading.value = true
    try {
      const { data } = await client.get('/tasks', { params })
      if (data.code === 0) {
        tasks.value = data.data.items
        total.value = data.data.total
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    const { data } = await client.get('/tasks/stats')
    if (data.code === 0) {
      stats.value = data.data
    }
  }

  async function dispatchTask(payload: {
    device_ids: string[]
    action?: string
    app_name?: string
    script_id?: string
    script_version?: number
    params?: Record<string, any>
    timeout_seconds?: number
  }) {
    const { data } = await client.post('/tasks/dispatch', payload)
    return data
  }

  async function cancelTask(taskId: string) {
    const { data } = await client.post(`/tasks/${taskId}/cancel`)
    return data
  }

  function setupWsHandlers() {
    wsClient.on('task.updated', (payload: any) => {
      const idx = tasks.value.findIndex(t => t.id === payload.id)
      if (idx >= 0) {
        Object.assign(tasks.value[idx], payload)
      }
    })

    wsClient.on('task.completed', (payload: any) => {
      const idx = tasks.value.findIndex(t => t.id === payload.id)
      if (idx >= 0) {
        Object.assign(tasks.value[idx], payload)
      }
      fetchStats()
    })
  }

  return { tasks, total, stats, loading, fetchTasks, fetchStats, dispatchTask, cancelTask, setupWsHandlers }
})
