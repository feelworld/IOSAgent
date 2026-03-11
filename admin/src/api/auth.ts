import client from './client'

interface LoginResponse {
  access_token: string
  token_type: string
}

interface UserInfo {
  username: string
  role: string
}

export async function login(username: string, password: string): Promise<void> {
  const { data: resp } = await client.post('/auth/login', {
    username,
    password,
  })
  const token = resp.access_token || resp.data?.access_token
  if (!token) throw new Error('No access_token in response')
  localStorage.setItem('token', token)
}

export async function getMe(): Promise<UserInfo> {
  const { data } = await client.get<UserInfo>('/auth/me')
  return data
}

export function logout(): void {
  localStorage.removeItem('token')
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem('token')
}
