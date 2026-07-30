import axios from 'axios'
import { apiBasePath } from './basePath'

export const api = axios.create({
  baseURL: apiBasePath(),
  withCredentials: true,
  timeout: 30000,
})

export function csrfHeaders(csrfToken: string) {
  return { 'X-CSRF-Token': csrfToken }
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((item) => item.msg).join('；')
    return error.message
  }
  return error instanceof Error ? error.message : '请求失败'
}
