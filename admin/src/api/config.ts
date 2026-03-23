import client from './client'

export interface ConfigItem {
  id?: string
  key: string
  value: string | number
  description: string
  scope: 'global' | 'device_group' | 'device'
  scope_id?: string
  updated_at?: string
}

export interface ConfigListParams {
  scope: string
  scope_id?: string
}

export async function getConfigs(params: ConfigListParams): Promise<ConfigItem[]> {
  const { data: resp } = await client.get('/configs', { params })
  const list = resp?.data ?? resp
  return Array.isArray(list) ? list : []
}

export async function updateConfigs(configs: ConfigItem[]): Promise<void> {
  for (const cfg of configs) {
    await client.put('/configs', {
      key: cfg.key,
      value: cfg.value,
      scope: cfg.scope,
      scope_id: cfg.scope_id || undefined,
    })
  }
}

export async function getDeviceGroups(): Promise<{ id: string; name: string }[]> {
  const { data } = await client.get<{ id: string; name: string }[]>('/device-groups')
  return data
}

export async function getDevices(): Promise<{ id: string; device_uid: string; name: string }[]> {
  const { data } = await client.get<{ id: string; device_uid: string; name: string }[]>('/devices', {
    params: { page: 1, size: 500 },
  })
  return data
}
