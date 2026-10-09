import type { ListResponse } from './types'

// Адрес локальной платформы агентов: Electron main запускает её на свободном порту.
let base = ''
let resolving: Promise<string> | null = null

export function backendUrl(): string {
  return base
}

export function platformUrl(): Promise<string> {
  if (base) return Promise.resolve(base)
  if (!resolving) {
    resolving = (async () => {
      if (!window.platform?.ensure) throw new Error('Платформа агентов доступна только в приложении Оркестратора')
      const status = await window.platform.ensure()
      if (!status.ok || !status.url) throw new Error(status.error || 'Платформа агентов не запустилась')
      base = status.url.replace(/\/+$/, '')
      return base
    })().finally(() => {
      resolving = null
    })
  }
  return resolving
}

function detailFrom(data: unknown, fallback: string): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

async function send<T>(url: string, method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${url}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  const text = await response.text()
  let data: unknown = undefined
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!response.ok) {
    throw new Error(detailFrom(data, text || `HTTP ${response.status}`))
  }
  return data as T
}

export async function apiRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  try {
    return await send<T>(await platformUrl(), method, path, body)
  } catch (error) {
    // fetch падает TypeError, когда сервис перезапущен на другом порту или ещё не поднят.
    if (!(error instanceof TypeError)) throw error
    base = ''
    return send<T>(await platformUrl(), method, path, body)
  }
}

export function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>('GET', path)
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>('POST', path, body)
}

export function apiList<T>(path: string): Promise<T[]> {
  return apiGet<ListResponse<T>>(path).then((body) => body.items)
}
