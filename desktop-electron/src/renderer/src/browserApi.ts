const BACKEND = String(import.meta.env.VITE_BACKEND_URL || 'http://192.168.1.157:7812').replace(/\/+$/, '')

function errorText(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback
  const detail = (data as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail[0] && typeof detail[0] === 'object') {
    const msg = (detail[0] as { msg?: unknown }).msg
    if (typeof msg === 'string' && msg.trim()) return msg
  }
  const message = (data as { message?: unknown }).message
  if (typeof message === 'string' && message.trim()) return message
  return fallback
}

function installBrowserApi(): void {
  if (typeof window === 'undefined' || window.api?.request) return

  const noopUnsub = (): (() => void) => () => undefined

  window.api = {
    getConfig: async () => ({ backendUrl: BACKEND, testUser: false }),
    request: async (opts) => {
      const url = new URL(opts.path, `${BACKEND}/`)
      if (opts.params) {
        for (const [key, value] of Object.entries(opts.params)) {
          if (value === undefined || value === null || value === '') continue
          url.searchParams.set(key, String(value))
        }
      }
      const headers: Record<string, string> = {}
      if (opts.token) headers.Authorization = `Bearer ${opts.token}`
      if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
      const ctrl = new AbortController()
      const timer = window.setTimeout(() => ctrl.abort(), opts.timeoutMs || 120_000)
      try {
        const res = await fetch(url.toString(), {
          method: opts.method || 'GET',
          headers,
          body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
          signal: ctrl.signal
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, status: res.status, error: errorText(data, res.statusText || 'Ошибка backend') }
        }
        return { ok: true, status: res.status, data }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Нет связи с backend'
        return { ok: false, status: 0, error: `${message} (${BACKEND})` }
      } finally {
        window.clearTimeout(timer)
      }
    },
    upload: async () => ({ ok: false, status: 501, error: 'Загрузка файлов только в Electron' }),
    fetchDataUrl: async () => ({ ok: false, error: 'Только в Electron' }),
    download: async () => ({ ok: false, error: 'Только в Electron' }),
    createWorkflow: async () => ({ ok: false, status: 501, error: 'Только в Electron' }),
    stream: async () => ({ ok: false, status: 501, error: 'Только в Electron' }),
    onStreamEvent: noopUnsub,
    getPathForFile: () => '',
    openFile: async () => [],
    startNotifications: async () => ({ ok: true }),
    stopNotifications: async () => ({ ok: true }),
    showNotification: async () => ({ ok: true }),
    onNotificationOpen: noopUnsub,
    onNotificationHitl: noopUnsub,
    onInboxChanged: noopUnsub,
    onBoardUpdated: noopUnsub,
    onSessionKicked: noopUnsub,
    onChatEvent: noopUnsub,
    getUpdateStatus: async () => ({
      state: 'idle' as const,
      currentVersion: '',
      availableVersion: '',
      percent: 0,
      error: ''
    }),
    installUpdate: async () => ({ ok: false, error: 'Только в Electron' }),
    onUpdateStatus: noopUnsub
  } as Window['api']

  if (!window.agent) {
    window.agent = {
      ready: async () => ({ ok: true }),
      start: async () => ({ ok: true }),
      answer: async () => ({ ok: true }),
      hitl: async () => ({ ok: true }),
      skip: async () => ({ ok: true }),
      cancel: async () => ({ ok: true }),
      onEvent: noopUnsub
    } as Window['agent']
  }
}

installBrowserApi()
