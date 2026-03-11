import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import { wsClient } from '../ws/client'

export interface StrategyItem {
  id: string
  name: string
  script_id: string
  script_version: number
  params: Record<string, any>
  phase: 'explore' | 'execute'
  status: 'active' | 'paused' | 'completed' | 'abandoned'
  effectiveness_score: number
  total_executions: number
  successful_executions: number
  total_downloads: number
  explore_session_id: string | null
  created_at: string
}

export interface ExploreStrategyResult {
  id: string
  params: Record<string, any>
  executions: number
  success_rate: number
  total_downloads: number
  effectiveness_score: number
}

export interface ExploreAnalysis {
  session_id: string
  total_executions: number
  strategies: ExploreStrategyResult[]
  recommended_strategies: string[]
}

export const useStrategyStore = defineStore('strategy', () => {
  const strategies = ref<StrategyItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const activeExploreSessionId = ref<string | null>(null)
  const analysis = ref<ExploreAnalysis | null>(null)
  const analysisLoading = ref(false)

  async function fetchStrategies(params: {
    phase?: string
    status?: string
    page?: number
    size?: number
  } = {}) {
    loading.value = true
    try {
      const { data } = await client.get('/strategies', { params })
      if (data.code === 0) {
        strategies.value = data.data.items
        total.value = data.data.total
      }
    } finally {
      loading.value = false
    }
  }

  async function startExplore(payload: {
    script_id: string
    script_version?: number
    device_count: number
    rounds: number
    param_variations: Record<string, any>[]
  }) {
    const { data } = await client.post('/strategies/explore/start', payload)
    if (data.code === 0) {
      activeExploreSessionId.value = data.data.session_id
    }
    return data
  }

  async function stopExplore(sessionId: string) {
    const { data } = await client.post(`/strategies/explore/${sessionId}/stop`)
    if (data.code === 0) {
      activeExploreSessionId.value = null
    }
    return data
  }

  async function getAnalysis(sessionId: string) {
    analysisLoading.value = true
    try {
      const { data } = await client.get(`/strategies/explore/${sessionId}/analysis`)
      if (data.code === 0) {
        analysis.value = data.data
      }
      return data
    } finally {
      analysisLoading.value = false
    }
  }

  async function startExecute(payload: {
    strategy_ids: string[]
    device_ids?: string[]
    all_devices?: boolean
  }) {
    const { data } = await client.post('/strategies/execute/start', payload)
    return data
  }

  function setupWsHandlers() {
    wsClient.on('strategy.effectiveness_changed', (payload: any) => {
      const idx = strategies.value.findIndex(s => s.id === payload.id)
      if (idx >= 0) {
        strategies.value[idx].effectiveness_score = payload.effectiveness_score
        if (payload.total_executions !== undefined) {
          strategies.value[idx].total_executions = payload.total_executions
        }
        if (payload.successful_executions !== undefined) {
          strategies.value[idx].successful_executions = payload.successful_executions
        }
        if (payload.total_downloads !== undefined) {
          strategies.value[idx].total_downloads = payload.total_downloads
        }
        if (payload.status !== undefined) {
          strategies.value[idx].status = payload.status
        }
      }
    })
  }

  return {
    strategies,
    total,
    loading,
    activeExploreSessionId,
    analysis,
    analysisLoading,
    fetchStrategies,
    startExplore,
    stopExplore,
    getAnalysis,
    startExecute,
    setupWsHandlers,
  }
})
