import { app, shell, BrowserWindow, ipcMain, dialog, type IpcMainInvokeEvent } from 'electron'
import { join, basename, dirname, extname } from 'node:path'
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import {
  installToastActivation,
  NotificationGuard,
  setToastHooks,
  showToast,
  type ToastPayload
} from './notifications'
import { AgentSidecar, type AgentSidecarMessage } from './agentSidecar'

interface RequestOptions {
  method?: string
  path: string
  body?: unknown
  params?: Record<string, string | number | boolean | undefined | null>
  token?: string | null
  timeoutMs?: number
  filePaths?: string[]
  extraFields?: Record<string, string>
}

interface UploadOptions {
  endpoint: string
  filePath: string
  fieldName?: string
  token?: string | null
  extraFields?: Record<string, string>
  timeoutMs?: number
}

const DEFAULT_TIMEOUT = 600_000

function parseEnvFile(path: string): Record<string, string> {
  const out: Record<string, string> = {}
  if (!existsSync(path)) return out
  const text = readFileSync(path, 'utf-8')
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 0) continue
    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    out[key] = value
  }
  return out
}

function loadConfig(): { backendUrl: string; testUser: boolean } {
  const userEnv = join(app.getPath('userData'), '.env')
  const resourceEnv = join(process.resourcesPath, 'desktop', '.env')
  if (!existsSync(userEnv) && existsSync(resourceEnv)) {
    try {
      mkdirSync(dirname(userEnv), { recursive: true })
      writeFileSync(userEnv, readFileSync(resourceEnv))
    } catch {
      /* Keep resource .env as fallback. */
    }
  }
  const candidates = [
    userEnv,
    join(dirname(app.getPath('exe')), '.env'),
    resourceEnv,
    join(app.getAppPath(), '.env'),
    join(process.cwd(), '.env'),
    join(app.getAppPath(), '..', '.env'),
    join(process.cwd(), '..', 'desktop', '.env'),
    join(app.getAppPath(), '..', 'desktop', '.env')
  ]
  let env: Record<string, string> = {}
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      env = { ...parseEnvFile(candidate), ...env }
    }
  }
  const backendUrl = (
    process.env.BACKEND_URL ||
    env.BACKEND_URL ||
    'http://127.0.0.1:7812'
  ).replace(/\/+$/, '')
  const flag = (process.env.CONSTRUCTOR_TEST_USER || env.CONSTRUCTOR_TEST_USER || '')
    .trim()
    .toLowerCase()
  const testUser = ['1', 'true', 'yes', 'on'].includes(flag)
  return { backendUrl, testUser }
}

const CONFIG = loadConfig()

if (process.platform === 'win32') {
  app.setAppUserModelId('com.constructor.desktop')
}

function broadcastAgentEvent(message: AgentSidecarMessage): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send('agent:event', message)
  }
}

const agentSidecar = new AgentSidecar(CONFIG.backendUrl, broadcastAgentEvent)

setToastHooks({
  onHitl: (decision) => {
    agentSidecar.send({
      type: 'hitl',
      requestId: decision.requestId,
      approved: decision.approved
    })
  }
})

const notifyGuard = new NotificationGuard(CONFIG.backendUrl, (command) => {
  const kind = String(command.type || '')
  const triggerId = String(command.trigger_id || command.id || '')
  const workflowId = String(command.workflow_id || '')
  const message = String(command.message || '')
  if (kind === 'evaluate_trigger') {
    agentSidecar.send({
      type: 'check_trigger',
      id: `trg-${triggerId}-${Date.now()}`,
      triggerId,
      workflowId,
      message
    })
  } else if (kind === 'run_agent') {
    agentSidecar.send({
      type: 'run',
      id: `run-${Date.now()}`,
      workflowId,
      message,
      source: 'trigger',
      triggerId
    })
  } else if (kind === 'form_orchestrator') {
    agentSidecar.send({
      type: 'form_orchestrator',
      id: `orch-form-${Date.now()}`
    })
  } else if (kind === 'calc_orchestrator') {
    const tileIds = Array.isArray(command.tile_ids)
      ? command.tile_ids.map((item) => String(item))
      : []
    agentSidecar.send({
      type: 'calc_orchestrator',
      id: `orch-calc-${Date.now()}`,
      tileIds
    })
  }
})

const MIME_BY_EXT: Record<string, string> = {
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.doc': 'application/msword',
  '.pdf': 'application/pdf',
  '.md': 'text/markdown',
  '.txt': 'text/plain',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif'
}

function appendLocalFiles(form: FormData, filePaths: string[]): number {
  let count = 0
  for (const filePath of filePaths) {
    if (!filePath || !existsSync(filePath)) continue
    const buffer = readFileSync(filePath)
    const name = basename(filePath)
    const mime = MIME_BY_EXT[extname(filePath).toLowerCase()] || 'application/octet-stream'
    const bytes = new Uint8Array(buffer)
    if (typeof File === 'function') {
      form.append('files', new File([bytes], name, { type: mime }))
    } else {
      form.append('files', new Blob([bytes], { type: mime }), name)
    }
    count += 1
  }
  return count
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const base = `${CONFIG.backendUrl}${path}`
  if (!params) return base
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue
    usp.append(key, String(value))
  }
  const query = usp.toString()
  return query ? `${base}?${query}` : base
}

function extractDetail(status: number, data: unknown): string {
  if (data && typeof data === 'object') {
    const detail = (data as Record<string, unknown>).detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as Record<string, unknown>
      if (first && typeof first.msg === 'string') return first.msg
    }
    const message = (data as Record<string, unknown>).message
    if (typeof message === 'string' && message.trim()) return message
  }
  if (typeof data === 'string' && data.trim()) return data
  return `Ошибка backend (${status})`
}

async function handleRequest(_evt: unknown, opts: RequestOptions) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT)
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  let bodyInit: string | FormData | undefined
  const filePaths = Array.isArray(opts.filePaths) ? opts.filePaths : []
  if (filePaths.length > 0) {
    const form = new FormData()
    for (const [key, value] of Object.entries(opts.extraFields || {})) {
      form.append(key, value)
    }
    if (opts.body && typeof opts.body === 'object' && !Array.isArray(opts.body)) {
      for (const [key, value] of Object.entries(opts.body as Record<string, unknown>)) {
        if (value != null) form.append(key, String(value))
      }
    }
    const attached = appendLocalFiles(form, filePaths)
    if (attached === 0) {
      clearTimeout(timer)
      return { ok: false, status: 0, error: 'Файлы не найдены на диске' }
    }
    bodyInit = form
  } else if (opts.body !== undefined && opts.body !== null) {
    headers['Content-Type'] = 'application/json'
    bodyInit = JSON.stringify(opts.body)
  }
  try {
    const response = await fetch(buildUrl(opts.path, opts.params), {
      method: opts.method || 'GET',
      headers,
      body: bodyInit,
      signal: controller.signal
    })
    const text = await response.text()
    let data: unknown = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = text
      }
    }
    if (!response.ok) {
      return { ok: false, status: response.status, error: extractDetail(response.status, data) }
    }
    return { ok: true, status: response.status, data }
  } catch (err) {
    const message =
      err instanceof Error && err.name === 'AbortError'
        ? 'Превышено время ожидания ответа backend'
        : `Не удалось подключиться к backend (${CONFIG.backendUrl})`
    return { ok: false, status: 0, error: message }
  } finally {
    clearTimeout(timer)
  }
}

async function handleUpload(_evt: unknown, opts: UploadOptions) {
  if (!existsSync(opts.filePath)) {
    return { ok: false, status: 0, error: 'Файл не найден' }
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT)
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  try {
    const buffer = readFileSync(opts.filePath)
    const name = basename(opts.filePath)
    const mime = MIME_BY_EXT[extname(opts.filePath).toLowerCase()] || 'application/octet-stream'
    const form = new FormData()
    const blob = new Blob([new Uint8Array(buffer)], { type: mime })
    form.append(opts.fieldName || 'file', blob, name)
    for (const [key, value] of Object.entries(opts.extraFields || {})) {
      form.append(key, value)
    }
    const response = await fetch(`${CONFIG.backendUrl}${opts.endpoint}`, {
      method: 'POST',
      headers,
      body: form,
      signal: controller.signal
    })
    const text = await response.text()
    let data: unknown = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = text
      }
    }
    if (!response.ok) {
      return { ok: false, status: response.status, error: extractDetail(response.status, data) }
    }
    return { ok: true, status: response.status, data }
  } catch (err) {
    const message =
      err instanceof Error && err.name === 'AbortError'
        ? 'Превышено время ожидания ответа backend'
        : `Не удалось подключиться к backend (${CONFIG.backendUrl})`
    return { ok: false, status: 0, error: message }
  } finally {
    clearTimeout(timer)
  }
}

function resolveBackendUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith('http://') || pathOrUrl.startsWith('https://')) {
    return pathOrUrl
  }
  const path = pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`
  return `${CONFIG.backendUrl}${path}`
}

function sniffImageMime(buffer: Buffer, headerType: string): string | null {
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) {
    return 'image/jpeg'
  }
  if (
    buffer.length >= 8 &&
    buffer[0] === 0x89 &&
    buffer[1] === 0x50 &&
    buffer[2] === 0x4e &&
    buffer[3] === 0x47
  ) {
    return 'image/png'
  }
  if (buffer.length >= 6) {
    const sig = buffer.subarray(0, 6).toString('ascii')
    if (sig === 'GIF87a' || sig === 'GIF89a') return 'image/gif'
  }
  if (
    buffer.length >= 12 &&
    buffer.subarray(0, 4).toString('ascii') === 'RIFF' &&
    buffer.subarray(8, 12).toString('ascii') === 'WEBP'
  ) {
    return 'image/webp'
  }
  const clean = headerType.split(';')[0].trim().toLowerCase()
  return clean.startsWith('image/') ? clean : null
}

async function handleFetchDataUrl(
  _evt: unknown,
  opts: { url: string; token?: string | null }
) {
  const url = resolveBackendUrl(opts.url)
  const headers: Record<string, string> = {}
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  try {
    const response = await fetch(url, { headers })
    if (!response.ok) return { ok: false, error: `Ошибка загрузки (${response.status})` }
    const buffer = Buffer.from(await response.arrayBuffer())
    const mime = sniffImageMime(buffer, response.headers.get('content-type') || '')
    if (!mime) return { ok: false, error: 'Ответ backend не является изображением' }
    return { ok: true, dataUrl: `data:${mime};base64,${buffer.toString('base64')}` }
  } catch {
    return { ok: false, error: 'Не удалось загрузить изображение' }
  }
}

function ensureDocxPath(filePath: string): string {
  const dir = dirname(filePath)
  let name = basename(filePath)
    .replace(/[<>:"/\\|?*]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[. ]+$/g, '')
  if (!name) name = 'Reglament'
  if (extname(name).toLowerCase() !== '.docx') name = `${name}.docx`
  return join(dir, name)
}

async function handleDownload(
  evt: IpcMainInvokeEvent,
  opts: { url: string; defaultName?: string; token?: string | null }
) {
  const win = BrowserWindow.fromWebContents(evt.sender) || BrowserWindow.getFocusedWindow()
  const suggested = ensureDocxPath(join(app.getPath('downloads'), opts.defaultName || 'Reglament.docx'))
  const result = await dialog.showSaveDialog(win ?? undefined, {
    defaultPath: suggested,
    filters: [{ name: 'Word', extensions: ['docx'] }]
  })
  if (result.canceled || !result.filePath) return { ok: false, canceled: true }
  const target = ensureDocxPath(result.filePath)
  const url = resolveBackendUrl(opts.url)
  const headers: Record<string, string> = {}
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  try {
    const response = await fetch(url, { headers })
    if (!response.ok) {
      let detail = `Ошибка загрузки (${response.status})`
      try {
        const payload = JSON.parse(await response.text()) as { detail?: unknown }
        if (typeof payload.detail === 'string' && payload.detail.trim()) {
          detail = payload.detail
        }
      } catch {
        /* keep status text */
      }
      return { ok: false, error: detail }
    }
    const buffer = Buffer.from(await response.arrayBuffer())
    if (buffer.length < 4 || buffer[0] !== 0x50 || buffer[1] !== 0x4b) {
      return { ok: false, error: 'Сервер вернул не документ Word' }
    }
    mkdirSync(dirname(target), { recursive: true })
    writeFileSync(target, buffer)
    if (!existsSync(target)) {
      return { ok: false, error: 'Файл не записался на диск' }
    }
    shell.showItemInFolder(target)
    return { ok: true, path: target }
  } catch (err) {
    const reason = err instanceof Error ? err.message : 'Не удалось скачать файл'
    return { ok: false, error: reason }
  }
}

async function handleCreateWorkflow(
  _evt: unknown,
  opts: { notes: string; draftId?: string; token?: string | null }
) {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  try {
    const form = new FormData()
    const notes = opts.notes || ''
    form.append('notes', notes)
    if (opts.draftId) form.append('draftId', opts.draftId)
    const blob = new Blob([notes], { type: 'text/plain' })
    form.append('files', blob, 'notes.txt')
    const response = await fetch(`${CONFIG.backendUrl}/api/v1/workflows`, {
      method: 'POST',
      headers,
      body: form
    })
    const text = await response.text()
    let data: unknown = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = text
      }
    }
    if (!response.ok) {
      return { ok: false, status: response.status, error: extractDetail(response.status, data) }
    }
    return { ok: true, status: response.status, data }
  } catch {
    return { ok: false, status: 0, error: `Не удалось подключиться к backend (${CONFIG.backendUrl})` }
  }
}

async function handleStream(
  event: Electron.IpcMainInvokeEvent,
  opts: {
    method?: string
    path: string
    body?: unknown
    token?: string | null
    filePaths?: string[]
    extraFields?: Record<string, string>
  }
) {
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  let bodyInit: string | FormData | undefined
  if (Array.isArray(opts.filePaths) && opts.filePaths.length > 0) {
    const form = new FormData()
    for (const [key, value] of Object.entries(opts.extraFields || {})) {
      form.append(key, value)
    }
    if (appendLocalFiles(form, opts.filePaths) === 0) {
      return { ok: false, status: 0, error: 'Файлы не найдены на диске' }
    }
    bodyInit = form
  } else if (opts.body !== undefined && opts.body !== null) {
    headers['Content-Type'] = 'application/json'
    bodyInit = JSON.stringify(opts.body)
  }
  try {
    const response = await fetch(buildUrl(opts.path), {
      method: opts.method || 'POST',
      headers,
      body: bodyInit
    })
    if (!response.ok) {
      const text = await response.text()
      let data: unknown = text
      try {
        data = JSON.parse(text)
      } catch {
        /* keep text */
      }
      return { ok: false, status: response.status, error: extractDetail(response.status, data) }
    }
    if (!response.body) {
      return { ok: false, status: response.status, error: 'Backend не вернул поток' }
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let eventName = 'message'
    let dataLines: string[] = []
    let finalPayload: unknown = null

    const flush = (): void => {
      if (!dataLines.length) return
      const raw = dataLines.join('\n')
      dataLines = []
      let payload: Record<string, unknown> = {}
      try {
        payload = JSON.parse(raw) as Record<string, unknown>
      } catch {
        payload = { type: eventName, text: raw }
      }
      const payloadType = String(payload.type || eventName)
      event.sender.send('api:stream-event', payload)
      if (payloadType === 'workflow' && payload.workflow && typeof payload.workflow === 'object') {
        finalPayload = payload.workflow
      }
      if (payloadType === 'session' && payload.session && typeof payload.session === 'object') {
        finalPayload = payload.session
      }
      eventName = 'message'
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line === '') {
          flush()
          continue
        }
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim())
        }
      }
    }
    if (dataLines.length) flush()
    if (!finalPayload) {
      return { ok: false, status: 0, error: 'Backend не вернул итоговый результат потока' }
    }
    return { ok: true, status: 200, data: finalPayload }
  } catch {
    return { ok: false, status: 0, error: `Не удалось подключиться к backend (${CONFIG.backendUrl})` }
  }
}

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1120,
    minHeight: 720,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#06483D',
    title: 'Constructor',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow.show())
  mainWindow.webContents.on('did-fail-load', (_event, code, desc, url) => {
    console.error(`Renderer failed to load: ${code} ${desc} ${url}`)
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (devUrl) {
    mainWindow.loadURL(devUrl)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  installToastActivation()
  console.log(`Constructor backend: ${CONFIG.backendUrl}`)
  ipcMain.handle('app:getConfig', () => ({
    backendUrl: CONFIG.backendUrl,
    testUser: CONFIG.testUser
  }))
  ipcMain.handle('api:request', handleRequest)
  ipcMain.handle('api:upload', handleUpload)
  ipcMain.handle('api:fetchDataUrl', handleFetchDataUrl)
  ipcMain.handle('api:download', handleDownload)
  ipcMain.handle('api:createWorkflow', handleCreateWorkflow)
  ipcMain.handle('api:stream', handleStream)
  ipcMain.handle(
    'agent:ready',
    (_evt, token: string | null, credentials?: { login?: string; password?: string }) => {
      agentSidecar.ready(token ?? null, credentials)
      return { ok: true }
    }
  )
  ipcMain.handle('agent:start', (_evt, command: AgentSidecarMessage) => {
    const ok = agentSidecar.send(command)
    return { ok }
  })
  ipcMain.handle('agent:answer', (_evt, command: AgentSidecarMessage) => {
    return { ok: agentSidecar.send({ ...command, type: 'answer' }) }
  })
  ipcMain.handle('agent:hitl', (_evt, command: AgentSidecarMessage) => {
    return { ok: agentSidecar.send({ ...command, type: 'hitl' }) }
  })
  ipcMain.handle('agent:skip', (_evt, command: AgentSidecarMessage) => {
    return { ok: agentSidecar.send({ ...command, type: 'skip' }) }
  })
  ipcMain.handle('agent:cancel', (_evt, command: AgentSidecarMessage) => {
    return { ok: agentSidecar.send({ ...command, type: 'cancel' }) }
  })
  ipcMain.handle('notifications:start', (_evt, token: string) => {
    if (typeof token === 'string' && token.trim()) {
      notifyGuard.start(token.trim())
    }
    return { ok: true }
  })
  ipcMain.handle('notifications:stop', () => {
    notifyGuard.stop()
    return { ok: true }
  })
  ipcMain.handle('notify:show', (_evt, payload: ToastPayload) => {
    showToast(payload || { title: '' })
    return { ok: true }
  })
  ipcMain.handle('dialog:openFile', async (_evt, options: Electron.OpenDialogOptions) => {
    const win = BrowserWindow.getFocusedWindow()
    const result = await dialog.showOpenDialog(win!, options)
    return result.canceled ? [] : result.filePaths
  })

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  notifyGuard.stop()
  agentSidecar.stop()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
