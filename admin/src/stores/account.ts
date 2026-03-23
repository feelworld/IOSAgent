import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export interface AccountItem {
  id: string
  email: string
  status: string
  bound_device_id: string | null
  bound_device_name: string | null
  bound_device_uid: string | null
  is_primary: boolean
  pool_group: string
  last_used_at: string | null
  banned_at: string | null
  created_at: string | null
}

export interface AccountStats {
  total: number
  active: number
  banned: number
  suspended: number
  assigned: number
  unassigned: number
}

export const useAccountStore = defineStore('account', () => {
  const accounts = ref<AccountItem[]>([])
  const total = ref(0)
  const loading = ref(false)
  const stats = ref<AccountStats>({
    total: 0,
    active: 0,
    banned: 0,
    suspended: 0,
    assigned: 0,
    unassigned: 0,
  })

  async function fetchAccounts(params: {
    status?: string
    pool_group?: string
    bound?: string
    page?: number
    size?: number
  } = {}) {
    loading.value = true
    try {
      const res = await client.get('/apple-accounts', { params })
      const data = res.data?.data || res.data
      accounts.value = data.items || []
      total.value = data.total || 0
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const res = await client.get('/apple-accounts/stats')
      const data = res.data?.data || res.data
      stats.value = data
    } catch {
      // ignore
    }
  }

  async function batchImport(accountsText: string, poolGroup: string) {
    const res = await client.post('/apple-accounts/batch-import', {
      accounts_text: accountsText,
      pool_group: poolGroup,
    })
    return res.data?.data || res.data
  }

  async function createAccount(email: string, password: string, poolGroup: string) {
    const res = await client.post('/apple-accounts', {
      email,
      password,
      pool_group: poolGroup,
    })
    return res.data
  }

  async function disableAccount(accountId: string) {
    const res = await client.post(`/apple-accounts/${accountId}/disable`)
    return res.data
  }

  async function enableAccount(accountId: string) {
    const res = await client.post(`/apple-accounts/${accountId}/enable`)
    return res.data
  }

  async function unbindAccount(accountId: string) {
    const res = await client.post(`/apple-accounts/${accountId}/unbind`)
    return res.data
  }

  async function fetchDeviceAccounts(deviceId: string): Promise<AccountItem[]> {
    const res = await client.get(`/apple-accounts/by-device/${deviceId}`)
    const data = res.data?.data || res.data
    return Array.isArray(data) ? data : []
  }

  async function unbindAndRefill(accountId: string) {
    const res = await client.post(`/apple-accounts/${accountId}/unbind-and-refill`)
    return res.data?.data || res.data
  }

  return {
    accounts,
    total,
    loading,
    stats,
    fetchAccounts,
    fetchStats,
    batchImport,
    createAccount,
    disableAccount,
    enableAccount,
    unbindAccount,
    fetchDeviceAccounts,
    unbindAndRefill,
  }
})
