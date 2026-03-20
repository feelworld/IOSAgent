import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export interface ScriptStep {
  action: string
  target?: string
  params?: Record<string, any>
  timeout?: number
}

export type ScriptType = 'steps' | 'python'

export interface ScriptItem {
  id: string
  name: string
  description: string | null
  script_type: ScriptType
  current_version: number
  status: string
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface ScriptVersionItem {
  id: string
  script_id: string
  version: number
  script_type: ScriptType
  steps: ScriptStep[]
  python_code?: string
  changelog: string | null
  published_at: string | null
  created_at: string
}

export const useScriptStore = defineStore('script', () => {
  const scripts = ref<ScriptItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const versions = ref<ScriptVersionItem[]>([])

  async function fetchScripts(params: {
    status?: string
    page?: number
    size?: number
  } = {}) {
    loading.value = true
    try {
      const { data } = await client.get('/scripts', { params })
      if (data.code === 0) {
        scripts.value = data.data.items
        total.value = data.data.total
      }
    } finally {
      loading.value = false
    }
  }

  async function createScript(payload: {
    name: string
    description?: string
    script_type?: ScriptType
    steps?: ScriptStep[]
    python_code?: string
  }) {
    const { data } = await client.post('/scripts', payload)
    return data
  }

  async function updateScript(id: string, payload: {
    script_type?: ScriptType
    steps?: ScriptStep[]
    python_code?: string
    changelog?: string
  }) {
    const { data } = await client.put(`/scripts/${id}`, payload)
    return data
  }

  async function publishScript(id: string) {
    const { data } = await client.post(`/scripts/${id}/publish`)
    return data
  }

  async function rollbackScript(id: string, version: number) {
    const { data } = await client.post(`/scripts/${id}/rollback`, { target_version: version })
    return data
  }

  async function fetchVersions(id: string) {
    const { data } = await client.get(`/scripts/${id}/versions`)
    if (data.code === 0) {
      versions.value = data.data
    }
    return data
  }

  async function grayRelease(id: string, deviceIds: string[]) {
    const { data } = await client.post(`/scripts/${id}/gray-release`, { device_ids: deviceIds })
    return data
  }

  return {
    scripts, total, loading, versions,
    fetchScripts, createScript, updateScript,
    publishScript, rollbackScript, fetchVersions, grayRelease,
  }
})
