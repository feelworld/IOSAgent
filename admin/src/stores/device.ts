import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '../api/client'
import { wsClient } from '../ws/client'

export interface DeviceItem {
  id: string
  device_uid: string
  name: string | null
  model: string
  ios_version: string
  status: string
  battery_level: number | null
  network_type: string | null
  wda_url: string
  companion_id: string
  current_apple_id: string | null
  current_task_id: string | null
  last_heartbeat: string | null
  registered_at: string | null
  udid: string | null
  serial_number: string | null
  imei: string | null
  meid: string | null
  wifi_mac: string | null
  bluetooth_mac: string | null
  cpu_architecture: string | null
  hardware_platform: string | null
  chip_id: number | null
  product_type: string | null
  jailbroken: boolean | null
  jailbreak_type: string | null
}

export interface DeviceStats {
  total: number
  online: number
  offline: number
  busy: number
  error: number
  online_rate: number
}

export const useDeviceStore = defineStore('device', () => {
  const devices = ref<DeviceItem[]>([])
  const total = ref(0)
  const stats = ref<DeviceStats>({ total: 0, online: 0, offline: 0, busy: 0, error: 0, online_rate: 0 })
  const loading = ref(false)

  async function fetchDevices(params: {
    status?: string
    group_id?: string
    page?: number
    size?: number
    sort?: string
  } = {}) {
    loading.value = true
    try {
      const { data } = await client.get('/devices', { params })
      if (data.code === 0) {
        devices.value = data.data.items
        total.value = data.data.total
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    const { data } = await client.get('/devices/stats')
    if (data.code === 0) {
      stats.value = data.data
    }
  }

  function setupWsHandlers() {
    wsClient.on('device.status_changed', (payload: any) => {
      const idx = devices.value.findIndex(d => d.device_uid === payload.device_uid)
      if (idx >= 0) {
        devices.value[idx].status = payload.new_status
        if (payload.battery_level !== undefined) {
          devices.value[idx].battery_level = payload.battery_level
        }
        if (payload.current_task_id !== undefined) {
          devices.value[idx].current_task_id = payload.current_task_id
        }
      }
    })

    wsClient.on('device.heartbeat', (payload: any) => {
      for (const dev of payload.devices || []) {
        const idx = devices.value.findIndex(d => d.device_uid === dev.device_uid)
        if (idx >= 0) {
          devices.value[idx].status = dev.status
          if (dev.battery_level !== undefined) {
            devices.value[idx].battery_level = dev.battery_level
          }
        }
      }
    })
  }

  return { devices, total, stats, loading, fetchDevices, fetchStats, setupWsHandlers }
})
