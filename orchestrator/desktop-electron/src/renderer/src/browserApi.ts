const BACKEND = String(import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:7812').replace(/\/+$/, '')

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

  const COM_SECRET_KEY = 'orchestrator.session.comSecret'
  const readComSecret = (): { login: string; password: string; nameMail: string } | null => {
    try {
      const raw = sessionStorage.getItem(COM_SECRET_KEY)
      if (!raw) return null
      const parsed = JSON.parse(raw) as { login?: string; password?: string; nameMail?: string }
      if (!parsed.password) return null
      return {
        login: parsed.login || '',
        password: parsed.password,
        nameMail: parsed.nameMail || ''
      }
    } catch {
      return null
    }
  }

  window.api = {
    getConfig: async () => ({ backendUrl: BACKEND, testUser: false }),
    setComSecret: async (payload) => {
      if (!payload?.password) {
        sessionStorage.removeItem(COM_SECRET_KEY)
        return { ok: true }
      }
      sessionStorage.setItem(
        COM_SECRET_KEY,
        JSON.stringify({
          login: payload.login || '',
          password: payload.password,
          nameMail: payload.nameMail || ''
        })
      )
      return { ok: true }
    },
    getComSecret: async () => readComSecret(),
    clearComSecret: async () => {
      sessionStorage.removeItem(COM_SECRET_KEY)
      return { ok: true }
    },
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
    fetchBinary: async (opts) => {
      const raw = String(opts.url || '').trim()
      if (!raw) return { ok: false, error: 'Нет ссылки на файл' }
      const url = raw.startsWith('http://') || raw.startsWith('https://') ? raw : `${BACKEND}${raw.startsWith('/') ? raw : `/${raw}`}`
      const headers: Record<string, string> = {}
      if (opts.token) headers.Authorization = `Bearer ${opts.token}`
      try {
        const res = await fetch(url, { headers })
        if (!res.ok) return { ok: false, error: `Ошибка загрузки (${res.status})` }
        const buffer = await res.arrayBuffer()
        const limit = typeof opts.maxBytes === 'number' && opts.maxBytes > 0 ? opts.maxBytes : 50 * 1024 * 1024
        if (buffer.byteLength > limit) return { ok: false, error: 'Файл слишком большой для просмотра' }
        const bytes = new Uint8Array(buffer)
        let binary = ''
        const chunk = 0x8000
        for (let i = 0; i < bytes.length; i += chunk) {
          binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
        }
        const contentType = (res.headers.get('content-type') || 'application/octet-stream').split(';')[0].trim().toLowerCase()
        return { ok: true, base64: btoa(binary), contentType, size: bytes.length }
      } catch {
        return { ok: false, error: 'Не удалось загрузить файл' }
      }
    },
    fetchFilePreview: async (opts) => {
      const raw = String(opts.url || '').trim()
      if (!raw) return { ok: false, error: 'Нет ссылки на файл' }
      const url = raw.startsWith('http://') || raw.startsWith('https://') ? raw : `${BACKEND}${raw.startsWith('/') ? raw : `/${raw}`}`
      const headers: Record<string, string> = {}
      if (opts.token) headers.Authorization = `Bearer ${opts.token}`
      try {
        const res = await fetch(url, { headers })
        if (!res.ok) return { ok: false, error: `Ошибка загрузки (${res.status})` }
        const buffer = await res.arrayBuffer()
        if (buffer.byteLength > 20 * 1024 * 1024) {
          return { ok: false, tooLarge: true, error: 'Файл слишком большой для предпросмотра' }
        }
        const name = String(opts.fileName || raw).toLowerCase()
        const headerMime = (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase()
        const bytes = new Uint8Array(buffer)
        const isPdf =
          bytes.length >= 4 &&
          bytes[0] === 0x25 &&
          bytes[1] === 0x50 &&
          bytes[2] === 0x44 &&
          bytes[3] === 0x46
        const isText =
          /\.(txt|md|csv|json|xml|html|htm|log)$/.test(name) || headerMime.startsWith('text/')
        const isEmbed =
          isPdf ||
          headerMime.startsWith('image/') ||
          headerMime === 'application/pdf' ||
          /\.(pdf|png|jpe?g|webp|gif)$/.test(name)
        if (isText) {
          return { ok: true, kind: 'text', text: new TextDecoder('utf-8').decode(buffer), mime: headerMime || 'text/plain' }
        }
        if (isEmbed) {
          const mime = isPdf ? 'application/pdf' : headerMime || 'application/octet-stream'
          const blob = new Blob([buffer], { type: mime })
          const dataUrl = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => resolve(String(reader.result || ''))
            reader.onerror = () => reject(new Error('read failed'))
            reader.readAsDataURL(blob)
          })
          return { ok: true, kind: 'embed', dataUrl, mime }
        }
        return {
          ok: true,
          kind: 'external',
          hint: 'Документ этого формата лучше открыть после скачивания',
          mime: headerMime || 'application/octet-stream'
        }
      } catch {
        return { ok: false, error: 'Не удалось загрузить файл' }
      }
    },
    download: async () => ({ ok: false, error: 'Только в Electron' }),
    createWorkflow: async () => ({ ok: false, status: 501, error: 'Только в Electron' }),
    stream: async () => ({ ok: false, status: 501, error: 'Только в Electron' }),
    onStreamEvent: noopUnsub,
    getPathForFile: () => '',
    openFile: async () => [],
    openPath: async () => ({ ok: false, error: 'Только в Electron' }),
    printToPdf: async () => ({ ok: false, error: 'Только в Electron' }),
    printPreview: async () => ({ ok: false, error: 'Только в Electron' }),
    printDialog: async () => ({ ok: false, error: 'Только в Electron' }),
    readLocalFilePreview: async () => ({ ok: false, error: 'Только в Electron' }),
    copyLocalFile: async () => ({ ok: false, error: 'Только в Electron' }),
    startNotifications: async () => ({ ok: true }),
    stopNotifications: async () => ({ ok: true }),
    showNotification: async () => ({ ok: true }),
    onNotificationOpen: noopUnsub,
    onNotificationStop: noopUnsub,
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
      error: '',
      source: '',
      devMode: true
    }),
    checkUpdate: async () => ({
      state: 'idle' as const,
      currentVersion: '',
      availableVersion: '',
      percent: 0,
      error: 'Проверка недоступна в dev',
      source: '',
      devMode: true
    }),
    installUpdate: async () => ({ ok: false, error: 'Только в Electron' }),
    onUpdateStatus: noopUnsub,
    loadOdataExternalEnv: async () => ({
      ok: false,
      path: '',
      missing: ['electron'],
      invokeArgs: {}
    }),
    fetchErpOdataTasks: async () => ({
      ok: false,
      status: 501,
      error: 'Только в Electron'
    })
  } as Window['api']

  const agentDefaults = {
    ready: async () => ({ ok: true }),
    start: async () => ({ ok: true }),
    answer: async () => ({ ok: true }),
    hitl: async () => ({ ok: true }),
    skip: async () => ({ ok: true }),
    cancel: async () => ({ ok: true }),
    readCalendar: async () => ({ ok: false }),
    searchOutlookMail: async () => ({ ok: false }),
    invokeAcTool: async () => ({ ok: false }),
    onEvent: noopUnsub
  } as Window['agent']

  if (!window.agent) {
    window.agent = agentDefaults
  } else {
    window.agent = { ...agentDefaults, ...window.agent }
    if (typeof window.agent.onEvent !== 'function') {
      window.agent.onEvent = noopUnsub
    }
  }
}

installBrowserApi()
