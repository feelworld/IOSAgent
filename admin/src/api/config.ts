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
  const { data } = await client.get<ConfigItem[]>('/configs', { params })
  return data
}

export async function updateConfigs(configs: ConfigItem[]): Promise<void> {
  await client.put('/configs', { configs })
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
