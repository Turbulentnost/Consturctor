import { app, shell, BrowserWindow, ipcMain, dialog, type IpcMainInvokeEvent } from 'electron'
import { join, basename, dirname, extname } from 'node:path'

const DESKTOP_APP_NAME = 'Orchestrator'
app.setName(DESKTOP_APP_NAME)
app.setPath('userData', join(app.getPath('appData'), DESKTOP_APP_NAME))
if (process.platform === 'win32') {
  app.setAppUserModelId('com.orchestrator.desktop')
}
import { readFileSync, existsSync, mkdirSync, writeFileSync, statSync, copyFileSync, unlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { NotificationGuard, showToast, type ToastPayload } from './notifications'
import { AgentSidecar, type AgentSidecarMessage } from './agentSidecar'
import {
  LOCAL_BACKEND_DEFAULT,
  ensureDesktopBackend,
  ensureLocalBackend,
  isLoopback,
  pingBackendHealth
} from './ensureBackend'
import { loadExternalOdataEnv } from './odataExternalEnv'
import { getUpdateStatus, installAvailableUpdate, requestUpdateCheck, startUpdater, stopUpdater } from './updater'
import {
  clearComSessionSecret,
  getComSessionSecret,
  setComSessionSecret
} from './comSessionSecret'

interface RequestOptions {
  method?: string
  path: string
  body?: unknown
  params?: Record<string, string | number | boolean | undefined | null>
  token?: string | null
  timeoutMs?: number
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

const LOCAL_BACKEND = LOCAL_BACKEND_DEFAULT
const LAN_BACKEND = 'http://192.168.1.157:7812'

function preferLocalBackend(env: Record<string, string>): boolean {
  const flag = (
    process.env.ORCH_PREFER_LOCAL ||
    env.ORCH_PREFER_LOCAL ||
    process.env.VITE_ORCH_PREFER_LOCAL ||
    env.VITE_ORCH_PREFER_LOCAL ||
    ''
  )
    .trim()
    .toLowerCase()
  if (flag === '0' || flag === 'false' || flag === 'no') return false
  if (flag === '1' || flag === 'true' || flag === 'yes') return true
  // Dev: default to loopback so new API routes work before LAN gateway redeploy.
  return !app.isPackaged
}

/** Explicit BACKEND_URL wins — erp_pm login/search stay on gateway when configured. */
function resolveBackendUrl(env: Record<string, string>): string {
  const cwdEnvPath = join(process.cwd(), '.env')
  const cwdEnv =
    !app.isPackaged && existsSync(cwdEnvPath) ? parseEnvFile(cwdEnvPath) : ({} as Record<string, string>)

  const explicit = (
    process.env.BACKEND_URL ||
    env.BACKEND_URL ||
    cwdEnv.BACKEND_URL ||
    ''
  ).trim()
  if (explicit) return explicit.replace(/\/+$/, '')

  if (!app.isPackaged && preferLocalBackend({ ...env, ...cwdEnv })) {
    return LOCAL_BACKEND
  }

  return app.isPackaged ? LAN_BACKEND : LOCAL_BACKEND
}

function loadWorkspaceDevGateway(env: Record<string, string>): {
  fio: string
  nameMail: string
  password: string
} | null {
  if (app.isPackaged) return null
  const candidates = [
    join(process.cwd(), '..', '..', '..', '.env'),
    join(process.cwd(), '..', '..', '.env')
  ]
  let merged: Record<string, string> = { ...env }
  for (const path of candidates) {
    if (existsSync(path)) merged = { ...parseEnvFile(path), ...merged }
  }
  const password = (merged.MY_PASSWORD || merged.TURBOPROJECT_PASSWORD || '').trim()
  const nameMail = (merged.MY_NAME_MAIL || merged.NAME_MAIL || '').trim().toLowerCase()
  const fio = (merged.MY_NAME || merged.TURBOPROJECT_EMPLOYEE || '').trim()
  if (!password && !nameMail && !fio) return null
  return { fio, nameMail, password }
}

function loadConfig(): {
  backendUrl: string
  testUser: boolean
  updateOwner: string
  updateRepo: string
  updateToken: string
  devGateway: { fio: string; nameMail: string; password: string } | null
} {
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
    join(app.getAppPath(), '..', 'desktop', '.env'),
    join(process.cwd(), '..', '..', '..', 'Consturctor', 'desktop', '.env'),
    join(app.getAppPath(), '..', '..', '..', 'Consturctor', 'desktop', '.env')
  ]
  let env: Record<string, string> = {}
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      env = { ...parseEnvFile(candidate), ...env }
    }
  }
  if (!app.isPackaged) {
    const cwdEnvPath = join(process.cwd(), '.env')
    if (existsSync(cwdEnvPath)) {
      env = { ...env, ...parseEnvFile(cwdEnvPath) }
    }
    for (const [key, value] of Object.entries(process.env)) {
      if (value !== undefined && value !== '') env[key] = value
    }
  }
  const backendUrl = resolveBackendUrl(env)
  const flag = (process.env.CONSTRUCTOR_TEST_USER || env.CONSTRUCTOR_TEST_USER || '')
    .trim()
    .toLowerCase()
  const testUser = ['1', 'true', 'yes', 'on'].includes(flag)
  const updateOwner = (
    process.env.UPDATE_GITHUB_OWNER ||
    env.UPDATE_GITHUB_OWNER ||
    'Turbulentnost'
  ).trim()
  const updateRepo = (
    process.env.UPDATE_GITHUB_REPO ||
    env.UPDATE_GITHUB_REPO ||
    'Consturctor'
  ).trim()
  const updateToken = (
    process.env.UPDATE_GITHUB_TOKEN ||
    process.env.GH_TOKEN ||
    process.env.GITHUB_TOKEN ||
    env.UPDATE_GITHUB_TOKEN ||
    env.GH_TOKEN ||
    env.GITHUB_TOKEN ||
    ''
  ).trim()
  const devGateway = loadWorkspaceDevGateway(env)
  return { backendUrl, testUser, updateOwner, updateRepo, updateToken, devGateway }
}

const CONFIG = loadConfig()

function resolveAppIcon(): string {
  const candidates = [
    join(process.resourcesPath, 'icon.ico'),
    join(__dirname, '../../build/icon.ico'),
    join(process.cwd(), 'build/icon.ico'),
    join(process.cwd(), 'src/renderer/src/assets/logo.png')
  ]
  for (const item of candidates) {
    if (existsSync(item)) return item
  }
  return ''
}

const APP_ICON = resolveAppIcon()

function broadcastAgentEvent(message: AgentSidecarMessage): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send('agent:event', message)
  }
}

const agentSidecar = new AgentSidecar(CONFIG.backendUrl, broadcastAgentEvent)

const notifyGuard = new NotificationGuard(CONFIG.backendUrl, (command) => {
  const kind = String(command.type || '')
  const triggerId = String(command.trigger_id || command.id || '')
  const workflowId = String(command.workflow_id || '')
  const message = String(command.message || '')
  // Same scheduled-start path as Constructor: check_trigger, then run with source=trigger.
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
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.doc': 'application/msword',
  '.xls': 'application/vnd.ms-excel',
  '.ppt': 'application/vnd.ms-powerpoint',
  '.pdf': 'application/pdf',
  '.md': 'text/markdown',
  '.txt': 'text/plain',
  '.csv': 'text/csv',
  '.json': 'application/json',
  '.xml': 'application/xml',
  '.html': 'text/html',
  '.htm': 'text/html',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif'
}

const LOCAL_FILE_PREVIEW_MAX_BYTES = 20 * 1024 * 1024

const TEXT_PREVIEW_EXTS = new Set(['.txt', '.md', '.csv', '.json', '.xml', '.html', '.htm', '.log'])

const EXTERNAL_OFFICE_EXTS = new Set(['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'])

type LocalFilePreviewResult =
  | {
      ok: true
      path: string
      size: number
      mime: string
      kind: 'text'
      text: string
    }
  | {
      ok: true
      path: string
      size: number
      mime: string
      kind: 'embed'
      dataUrl: string
    }
  | {
      ok: true
      path: string
      size: number
      mime: string
      kind: 'external'
      hint: string
    }
  | { ok: false; error: string; tooLarge?: boolean; path?: string; size?: number }

function resolveSafeLocalFile(filePath: string): { ok: true; path: string } | { ok: false; error: string } {
  const target = String(filePath || '').trim()
  if (!target) return { ok: false, error: 'Пустой путь' }
  if (!existsSync(target)) return { ok: false, error: 'Файл не найден' }
  try {
    const st = statSync(target)
    if (!st.isFile()) return { ok: false, error: 'Не файл' }
    return { ok: true, path: target }
  } catch {
    return { ok: false, error: 'Нет доступа к файлу' }
  }
}

function localFilePreviewKind(ext: string, mime: string): 'text' | 'embed' | 'external' {
  if (TEXT_PREVIEW_EXTS.has(ext) || mime.startsWith('text/')) return 'text'
  if (EXTERNAL_OFFICE_EXTS.has(ext)) return 'external'
  if (mime.startsWith('image/') || ext === '.pdf') return 'embed'
  return 'external'
}

async function handleReadLocalFilePreview(_evt: unknown, filePath: string): Promise<LocalFilePreviewResult> {
  const resolved = resolveSafeLocalFile(filePath)
  if (!resolved.ok) return { ok: false, error: resolved.error }
  let size = 0
  try {
    size = statSync(resolved.path).size
  } catch {
    return { ok: false, error: 'Не удалось прочитать файл' }
  }
  if (size > LOCAL_FILE_PREVIEW_MAX_BYTES) {
    return {
      ok: false,
      tooLarge: true,
      path: resolved.path,
      size,
      error: 'Файл слишком большой для предпросмотра в приложении'
    }
  }
  const ext = extname(resolved.path).toLowerCase()
  const mime = MIME_BY_EXT[ext] || 'application/octet-stream'
  const kind = localFilePreviewKind(ext, mime)
  try {
    const buffer = readFileSync(resolved.path)
    if (kind === 'text') {
      return { ok: true, path: resolved.path, size, mime, kind: 'text', text: buffer.toString('utf-8') }
    }
    if (kind === 'embed') {
      return {
        ok: true,
        path: resolved.path,
        size,
        mime,
        kind: 'embed',
        dataUrl: `data:${mime};base64,${buffer.toString('base64')}`
      }
    }
    return {
      ok: true,
      path: resolved.path,
      size,
      mime,
      kind: 'external',
      hint: 'Документ откроется во внешнем приложении (Word, Excel…)'
    }
  } catch {
    return { ok: false, error: 'Не удалось прочитать файл' }
  }
}

async function handleCopyLocalFile(
  _evt: unknown,
  opts: { sourcePath: string; defaultName?: string }
): Promise<{ ok: boolean; canceled?: boolean; path?: string; error?: string }> {
  const resolved = resolveSafeLocalFile(opts.sourcePath)
  if (!resolved.ok) return { ok: false, error: resolved.error }
  const win = BrowserWindow.getFocusedWindow()
  const result = await dialog.showSaveDialog(win!, {
    defaultPath: opts.defaultName || basename(resolved.path)
  })
  if (result.canceled || !result.filePath) return { ok: false, canceled: true }
  try {
    copyFileSync(resolved.path, result.filePath)
    return { ok: true, path: result.filePath }
  } catch {
    return { ok: false, error: 'Не удалось сохранить файл' }
  }
}

function buildUrl(path: string, params?: RequestOptions['params'], baseUrl?: string): string {
  const root = (baseUrl || CONFIG.backendUrl).replace(/\/+$/, '')
  const base = `${root}${path}`
  if (!params) return base
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue
    usp.append(key, String(value))
  }
  const query = usp.toString()
  return query ? `${base}?${query}` : base
}

const ONEC_LOCAL_API_TOOLS = new Set(['onec.docflow_tasks'])

function parseInvokeToolName(body: unknown): string {
  if (body === undefined || body === null) return ''
  if (typeof body === 'object' && !Array.isArray(body)) {
    return String((body as Record<string, unknown>).tool ?? '').trim()
  }
  return ''
}

/** 1C docflow only — loopback has DOK_HTTP_*; auth/erp_pm stays on CONFIG.backendUrl. */
function pathPrefersLocalBackendFirst(opts: RequestOptions): boolean {
  if (!opts.path.includes('/api/v1/tools/invoke')) return false
  return ONEC_LOCAL_API_TOOLS.has(parseInvokeToolName(opts.body))
}

function resolveDocflowGatewayBase(): string {
  const fromEnv = (process.env.AUTH_ERP_GATEWAY_URL || '').trim().replace(/\/+$/, '')
  if (fromEnv && !isLoopback(fromEnv)) return fromEnv
  return LAN_BACKEND
}

function pathIsAuthApi(path: string): boolean {
  const p = path || ''
  if (!p.includes('/api/v1/auth/')) return false
  if (p.includes('/auth/me/activity')) return false
  return true
}

function pathIsAgentLibraryApi(path: string): boolean {
  return (path || '').includes('/api/v1/agents/library')
}

async function backendBasesForRequest(opts: RequestOptions): Promise<string[]> {
  const primary = CONFIG.backendUrl.replace(/\/+$/, '')
  // Login / FIO search always via configured backend (loopback); gateway proxy is in backend/.env.
  if (pathIsAuthApi(opts.path)) return [primary]
  if (!app.isPackaged && pathIsAgentLibraryApi(opts.path)) {
    await ensureLocalBackend(LOCAL_BACKEND)
    if (isLoopback(primary)) return [primary]
    return [LOCAL_BACKEND, primary]
  }
  if (!app.isPackaged && pathPrefersLocalBackendFirst(opts)) {
    const gateway = resolveDocflowGatewayBase()
    await ensureLocalBackend(LOCAL_BACKEND)
    const profileEnvPath = join(app.getPath('userData'), '.env')
    const profileEnv = existsSync(profileEnvPath) ? parseEnvFile(profileEnvPath) : {}
    const preferLocal = preferLocalBackend(profileEnv)
    const bases: string[] = []
    const push = (base: string) => {
      const normalized = (base || '').replace(/\/+$/, '')
      if (normalized && !bases.includes(normalized)) bases.push(normalized)
    }
    // Local backend carries DOK_HTTP_* to 229; LAN gateway often returns stub/empty without session SOAP.
    if (preferLocal || isLoopback(primary)) push(LOCAL_BACKEND)
    if (!isLoopback(primary)) push(primary)
    else if (gateway !== LOCAL_BACKEND) push(gateway)
    if (bases.length) return bases
    return [LOCAL_BACKEND]
  }
  return [primary]
}

function isLanBackendHost(url: string): boolean {
  if (/127\.0\.0\.1|localhost/i.test(url)) return false
  return /:\/\/192\.168\.|:\/\/10\.|:\/\/172\.(1[6-9]|2\d|3[01])\./.test(url)
}

function backendUnreachableMessage(attemptedBase?: string): string {
  const profileHint = join(app.getPath('userData'), '.env')
  const base = (attemptedBase || CONFIG.backendUrl).replace(/\/+$/, '')
  const networkHint = isLanBackendHost(base)
    ? `Проверьте LAN до gateway ${base} (constructor-gateway на :7812). VPN на ПК для 1С не нужен — SQL выполняется на сервере gateway.`
    : `Проверьте VPN до erp_pm (локальный backend) или переключите BACKEND_URL на LAN gateway (например http://192.168.1.157:7812).`
  return (
    `Не удалось подключиться к backend (${base}). ${networkHint} ` +
    `BACKEND_URL: ${profileHint} или .env рядом с exe.`
  )
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

/** Routes that may exist on local backend before LAN gateway is redeployed. */
function pathUsesLocalBackendFallback(path: string, opts?: RequestOptions): boolean {
  const p = path || ''
  if (p.includes('/api/v1/admin/') || p.includes('/api/v1/workplace/kpi')) return true
  if (p.includes('/api/v1/agents/library')) return true
  if (pathPrefersLocalBackendFirst(opts || { path })) return true
  return false
}

function localBackendFallbackFailureMessage(path: string, localUp: boolean): string {
  if (!localUp) {
    return 'Не удалось подключиться к локальному backend. Проверьте orchestrator\\backend (run_dev.bat) и порт 7812.'
  }
  if ((path || '').includes('/api/v1/workplace/kpi')) {
    return 'Не удалось загрузить KPI рабочего места. Перелогиньтесь или обновите вкладку.'
  }
  if ((path || '').includes('/api/v1/agents/library')) {
    return (
      'Библиотека агентов недоступна на gateway. Запустите локальный backend (orchestrator\\backend, run_dev.bat) ' +
      'или обновите сервер с маршрутом GET /api/v1/agents/library.'
    )
  }
  return 'Не удалось загрузить админ-данные. Перелогиньтесь или обновите страницу.'
}

async function tryLocalBackendFallback(
  opts: RequestOptions,
  headers: Record<string, string>,
  bodyInit: string | undefined,
  signal: AbortSignal
): Promise<{ ok: true; status: number; data: unknown } | { ok: false; status: number; error: string } | null> {
  await ensureLocalBackend(LOCAL_BACKEND)
  try {
    const localPath = `${LOCAL_BACKEND}${opts.path}`
    const usp = new URLSearchParams()
    for (const [key, value] of Object.entries(opts.params || {})) {
      if (value === undefined || value === null) continue
      usp.append(key, String(value))
    }
    const query = usp.toString()
    const localResponse = await fetch(query ? `${localPath}?${query}` : localPath, {
      method: opts.method || 'GET',
      headers,
      body: bodyInit,
      signal
    })
    const localText = await localResponse.text()
    let localData: unknown = null
    if (localText) {
      try {
        localData = JSON.parse(localText)
      } catch {
        localData = localText
      }
    }
    if (localResponse.ok) {
      console.log(
        `Backend API fallback: ${opts.path} — ${CONFIG.backendUrl} → ${LOCAL_BACKEND}`
      )
      return { ok: true, status: localResponse.status, data: localData }
    }
    if (localResponse.status !== 404 && localResponse.status !== 405) {
      return {
        ok: false,
        status: localResponse.status,
        error: extractDetail(localResponse.status, localData)
      }
    }
  } catch {
    // keep original error from CONFIG.backendUrl
  }
  const localUp = await pingBackendHealth(LOCAL_BACKEND)
  return {
    ok: false,
    status: 404,
    error: localBackendFallbackFailureMessage(opts.path, localUp)
  }
}

async function handleRequest(_evt: unknown, opts: RequestOptions) {
  const totalTimeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  let bodyInit: string | undefined
  if (opts.body !== undefined && opts.body !== null) {
    headers['Content-Type'] = 'application/json'
    bodyInit = JSON.stringify(opts.body)
  }
  const primaryBase = CONFIG.backendUrl.replace(/\/+$/, '')
  const bases = await backendBasesForRequest(opts)
  const attemptTimeoutMs =
    bases.length > 1 ? Math.max(90_000, totalTimeoutMs) : totalTimeoutMs
  let lastError = { status: 0, error: backendUnreachableMessage(primaryBase) }

  for (let index = 0; index < bases.length; index += 1) {
    const base = bases[index]
    const hasNext = index < bases.length - 1
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), attemptTimeoutMs)
    try {
      const response = await fetch(buildUrl(opts.path, opts.params, base), {
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
      if (response.ok) {
        if (base !== primaryBase) {
          console.log(`Backend API routed: ${opts.path} via ${base}`)
        }
        return { ok: true, status: response.status, data }
      }
      lastError = {
        status: response.status,
        error: extractDetail(response.status, data)
      }
      const routeMissing = response.status === 404 || response.status === 405
      const docflowAuthRejected =
        pathPrefersLocalBackendFirst(opts) &&
        (response.status === 401 || response.status === 403)
      if (docflowAuthRejected && hasNext) {
        console.log(
          `Backend API retry: ${opts.path} — ${base} (docflow auth ${response.status}) → ${bases[index + 1]}`
        )
        continue
      }
      if (docflowAuthRejected) {
        return { ok: false, status: lastError.status, error: lastError.error }
      }
      if (hasNext) {
        console.log(
          `Backend API retry: ${opts.path} — ${base} (${response.status}) → ${bases[index + 1]}`
        )
        continue
      }
      const usingLan = primaryBase !== LOCAL_BACKEND
      if (
        pathUsesLocalBackendFallback(opts.path, opts) &&
        routeMissing &&
        (usingLan || isLoopback(primaryBase)) &&
        base === primaryBase
      ) {
        const fallback = await tryLocalBackendFallback(opts, headers, bodyInit, controller.signal)
        if (fallback) {
          if (fallback.ok) return fallback
          return { ok: false, status: fallback.status, error: fallback.error }
        }
      }
      return { ok: false, status: lastError.status, error: lastError.error }
    } catch (err) {
      lastError = {
        status: 0,
        error:
          err instanceof Error && err.name === 'AbortError'
            ? `Превышено время ожидания ответа backend (${base})`
            : backendUnreachableMessage(base)
      }
      if (hasNext) {
        console.log(`Backend API retry: ${opts.path} — ${base} (${lastError.error}) → ${bases[index + 1]}`)
        continue
      }
      if (
        pathUsesLocalBackendFallback(opts.path, opts) &&
        base === primaryBase &&
        primaryBase !== LOCAL_BACKEND
      ) {
        const fallback = await tryLocalBackendFallback(opts, headers, bodyInit, controller.signal)
        if (fallback?.ok) return fallback
        if (fallback && !fallback.ok) {
          return { ok: false, status: fallback.status, error: fallback.error }
        }
      }
      return { ok: false, status: lastError.status, error: lastError.error }
    } finally {
      clearTimeout(timer)
    }
  }
  return { ok: false, status: lastError.status, error: lastError.error }
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
        : backendUnreachableMessage()
    return { ok: false, status: 0, error: message }
  } finally {
    clearTimeout(timer)
  }
}

function absoluteBackendUrl(pathOrUrl: string): string {
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
  const url = absoluteBackendUrl(opts.url)
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

async function handleDownload(
  _evt: unknown,
  opts: { url: string; defaultName?: string; token?: string | null }
) {
  const win = BrowserWindow.getFocusedWindow()
  const result = await dialog.showSaveDialog(win!, { defaultPath: opts.defaultName || 'file' })
  if (result.canceled || !result.filePath) return { ok: false, canceled: true }
  const url = absoluteBackendUrl(opts.url)
  const headers: Record<string, string> = {}
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  try {
    const response = await fetch(url, { headers })
    if (!response.ok) return { ok: false, error: `Ошибка загрузки (${response.status})` }
    const arrayBuffer = await response.arrayBuffer()
    writeFileSync(result.filePath, Buffer.from(arrayBuffer))
    return { ok: true, path: result.filePath }
  } catch {
    return { ok: false, error: 'Не удалось скачать файл' }
  }
}

async function handleSaveLocalFile(
  _evt: unknown,
  opts: {
    defaultName?: string
    text?: string
    base64?: string
    filters?: { name: string; extensions: string[] }[]
  }
) {
  const win = BrowserWindow.getFocusedWindow()
  const result = await dialog.showSaveDialog(win!, {
    defaultPath: opts.defaultName || 'file',
    filters: opts.filters
  })
  if (result.canceled || !result.filePath) return { ok: false, canceled: true }
  try {
    const data = opts.base64
      ? Buffer.from(opts.base64, 'base64')
      : Buffer.from(opts.text || '', 'utf8')
    writeFileSync(result.filePath, data)
    return { ok: true, path: result.filePath }
  } catch {
    return { ok: false, error: 'Не удалось сохранить файл' }
  }
}

async function handleExportPdf(
  _evt: unknown,
  opts: { html: string; defaultName?: string }
) {
  const win = BrowserWindow.getFocusedWindow()
  const result = await dialog.showSaveDialog(win!, {
    defaultPath: opts.defaultName || 'report.pdf',
    filters: [{ name: 'PDF', extensions: ['pdf'] }]
  })
  if (result.canceled || !result.filePath) return { ok: false, canceled: true }

  const pdfWin = new BrowserWindow({
    show: false,
    width: 1024,
    height: 768,
    webPreferences: { sandbox: true, contextIsolation: true }
  })
  try {
    await pdfWin.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(opts.html || '')}`)
    const pdf = await pdfWin.webContents.printToPDF({
      printBackground: true,
      pageSize: 'A4'
    })
    writeFileSync(result.filePath, pdf)
    return { ok: true, path: result.filePath }
  } catch {
    return { ok: false, error: 'Не удалось сформировать PDF' }
  } finally {
    if (!pdfWin.isDestroyed()) pdfWin.destroy()
  }
}

type PrintHtmlOptions = {
  html?: string
  landscape?: boolean
  openAfter?: boolean
  defaultName?: string
}

/** Загружает автономный HTML во временный файл и скрытое окно (data:-URL ограничен по длине). */
async function loadHiddenPrintWindow(
  html: string
): Promise<{ win: BrowserWindow; cleanup: () => void }> {
  const tmpHtmlPath = join(
    tmpdir(),
    `orch-print-${Date.now()}-${Math.random().toString(36).slice(2)}.html`
  )
  writeFileSync(tmpHtmlPath, html, 'utf8')
  const win = new BrowserWindow({
    show: false,
    width: 1024,
    height: 768,
    webPreferences: { sandbox: true, contextIsolation: true }
  })
  const cleanup = (): void => {
    if (!win.isDestroyed()) win.destroy()
    try {
      unlinkSync(tmpHtmlPath)
    } catch {
      /* ignore */
    }
  }
  try {
    await win.loadFile(tmpHtmlPath)
  } catch (err) {
    cleanup()
    throw err
  }
  return { win, cleanup }
}

async function renderHtmlToPdf(html: string, landscape: boolean): Promise<Buffer> {
  const { win, cleanup } = await loadHiddenPrintWindow(html)
  try {
    return await win.webContents.printToPDF({
      landscape,
      printBackground: true,
      pageSize: 'A4'
    })
  } finally {
    cleanup()
  }
}

async function handlePrintToPdf(
  _evt: unknown,
  opts: PrintHtmlOptions
): Promise<{ ok: boolean; canceled?: boolean; path?: string; error?: string }> {
  const html = String(opts?.html || '').trim()
  if (!html) return { ok: false, error: 'Нет содержимого для сохранения в PDF' }
  const win = BrowserWindow.getFocusedWindow()
  const stamp = new Date().toISOString().slice(0, 10)
  const result = await dialog.showSaveDialog(win!, {
    defaultPath: opts?.defaultName || `реестр-поручений-${stamp}.pdf`,
    filters: [{ name: 'PDF', extensions: ['pdf'] }]
  })
  if (result.canceled || !result.filePath) return { ok: false, canceled: true }
  try {
    const pdf = await renderHtmlToPdf(html, Boolean(opts?.landscape))
    writeFileSync(result.filePath, pdf)
    if (opts?.openAfter) await shell.openPath(result.filePath)
    return { ok: true, path: result.filePath }
  } catch {
    return { ok: false, error: 'Не удалось сформировать PDF' }
  }
}

/** «Предварительный просмотр»: PDF во временный файл и открытие системным просмотрщиком. */
async function handlePrintPreview(
  _evt: unknown,
  opts: PrintHtmlOptions
): Promise<{ ok: boolean; path?: string; error?: string }> {
  const html = String(opts?.html || '').trim()
  if (!html) return { ok: false, error: 'Нет содержимого для предпросмотра' }
  try {
    const pdf = await renderHtmlToPdf(html, Boolean(opts?.landscape))
    const pdfPath = join(tmpdir(), `orch-print-preview-${Date.now()}.pdf`)
    writeFileSync(pdfPath, pdf)
    const openErr = await shell.openPath(pdfPath)
    if (openErr) return { ok: false, path: pdfPath, error: openErr }
    return { ok: true, path: pdfPath }
  } catch {
    return { ok: false, error: 'Не удалось сформировать PDF для предпросмотра' }
  }
}

async function handlePrintDialog(
  _evt: unknown,
  opts: PrintHtmlOptions
): Promise<{ ok: boolean; canceled?: boolean; error?: string }> {
  const html = String(opts?.html || '').trim()
  if (!html) return { ok: false, error: 'Нет содержимого для печати' }
  let loaded: { win: BrowserWindow; cleanup: () => void } | null = null
  try {
    loaded = await loadHiddenPrintWindow(html)
    const win = loaded.win
    return await new Promise((resolve) => {
      win.webContents.print(
        { silent: false, printBackground: true, landscape: Boolean(opts?.landscape) },
        (success, failureReason) => {
          if (success) {
            resolve({ ok: true })
          } else if ((failureReason || '').toLowerCase().includes('cancel')) {
            resolve({ ok: false, canceled: true })
          } else {
            resolve({ ok: false, error: failureReason || 'Печать не выполнена' })
          }
        }
      )
    })
  } catch {
    return { ok: false, error: 'Не удалось открыть диалог печати' }
  } finally {
    loaded?.cleanup()
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
    return { ok: false, status: 0, error: backendUnreachableMessage() }
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
    for (const filePath of opts.filePaths) {
      if (!existsSync(filePath)) continue
      const buffer = readFileSync(filePath)
      const name = basename(filePath)
      const mime = MIME_BY_EXT[extname(filePath).toLowerCase()] || 'application/octet-stream'
      const blob = new Blob([new Uint8Array(buffer)], { type: mime })
      form.append('files', blob, name)
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
    return { ok: false, status: 0, error: backendUnreachableMessage() }
  }
}

type IpcHandler = (...args: Parameters<Parameters<typeof ipcMain.handle>[1]>) => unknown

/** Re-register safely on electron-vite main HMR (avoid partial handler sets). */
function ipcHandle(channel: string, handler: IpcHandler): void {
  ipcMain.removeHandler(channel)
  ipcMain.handle(channel, handler)
}

function registerMainIpcHandlers(): void {
  ipcHandle(
    'session:setComSecret',
    (
      _evt,
      payload: { login?: string; password?: string; nameMail?: string; persist?: boolean }
    ) => {
      setComSessionSecret(
        {
          login: payload?.login,
          password: payload?.password,
          nameMail: payload?.nameMail
        },
        Boolean(payload?.persist)
      )
      return { ok: true }
    }
  )
  ipcHandle('session:getComSecret', () => getComSessionSecret())
  ipcHandle('session:clearComSecret', () => {
    clearComSessionSecret()
    return { ok: true }
  })
  ipcHandle('app:getConfig', () => ({
    backendUrl: CONFIG.backendUrl,
    testUser: CONFIG.testUser,
    devGateway: CONFIG.devGateway
      ? {
          fio: CONFIG.devGateway.fio,
          nameMail: CONFIG.devGateway.nameMail,
          hasPassword: Boolean(CONFIG.devGateway.password)
        }
      : null,
    devGatewaySecrets: CONFIG.devGateway
  }))
  ipcHandle('api:request', handleRequest)
  ipcHandle('api:upload', handleUpload)
  ipcHandle('api:fetchDataUrl', handleFetchDataUrl)
  ipcHandle('api:download', handleDownload)
  ipcHandle('api:saveLocalFile', handleSaveLocalFile)
  ipcHandle('api:exportPdf', handleExportPdf)
  ipcHandle('print:to-pdf', handlePrintToPdf)
  ipcHandle('print:preview', handlePrintPreview)
  ipcHandle('print:dialog', handlePrintDialog)
  ipcHandle('api:createWorkflow', handleCreateWorkflow)
  ipcHandle('api:stream', handleStream)
  ipcHandle(
    'agent:ready',
    (
      _evt,
      token: string | null,
      credentials?: { login?: string; password?: string; onecComUsr?: string }
    ) => {
      agentSidecar.ready(token ?? null, credentials)
      return { ok: true }
    }
  )
  ipcHandle('agent:status', () => agentSidecar.status())
  ipcHandle('agent:start', (_evt, command: AgentSidecarMessage) => agentSidecar.send(command))
  ipcHandle('agent:answer', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'answer' })
  )
  ipcHandle('agent:hitl', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'hitl' })
  )
  ipcHandle('agent:skip', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'skip' })
  )
  ipcHandle('agent:cancel', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'cancel' })
  )
  ipcHandle('agent:read-calendar', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'read_calendar' })
  )
  ipcHandle('agent:search-mail', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'search_mail' })
  )
  ipcHandle('agent:invoke-ac-tool', (_evt, command: AgentSidecarMessage) =>
    agentSidecar.send({ ...command, type: 'invoke_ac_tool' })
  )
  ipcHandle('notifications:start', (_evt, token: string) => {
    if (typeof token === 'string' && token.trim()) {
      notifyGuard.start(token.trim())
    }
    return { ok: true }
  })
  ipcHandle('notifications:stop', () => {
    notifyGuard.stop()
    return { ok: true }
  })
  ipcHandle('notify:show', (_evt, payload: ToastPayload) => {
    showToast(payload || { title: '' })
    return { ok: true }
  })
  ipcHandle('dialog:openFile', async (_evt, options: Electron.OpenDialogOptions) => {
    const win = BrowserWindow.getFocusedWindow()
    const result = await dialog.showOpenDialog(win!, options)
    return result.canceled ? [] : result.filePaths
  })
  ipcHandle('shell:openPath', async (_evt, filePath: string) => {
    const target = String(filePath || '').trim()
    if (!target) return { ok: false, error: 'Пустой путь' }
    const err = await shell.openPath(target)
    return err ? { ok: false, error: err } : { ok: true }
  })
  ipcHandle('fs:readLocalFilePreview', handleReadLocalFilePreview)
  ipcHandle('fs:copyLocalFile', handleCopyLocalFile)
  ipcHandle('updater:getStatus', () => getUpdateStatus())
  ipcHandle('updater:check', () => requestUpdateCheck())
  ipcHandle('updater:install', () => installAvailableUpdate())
  ipcHandle('orch:load-odata-external-env', () => {
    const loaded = loadExternalOdataEnv()
    return {
      ok: loaded.ok,
      path: loaded.path,
      missing: loaded.missing,
      invokeArgs: loaded.invokeArgs
    }
  })
  ipcHandle(
    'orch:fetch-erp-odata-tasks',
    async (
      _evt,
      opts: { token?: string | null; fio?: string; limit?: number; fallbackSql?: boolean }
    ) => {
      const loaded = loadExternalOdataEnv()
      const body = {
        tool: 'onec.erp_tasks_odata',
        arguments: {
          limit: opts?.limit ?? 80,
          fallback_sql: opts?.fallbackSql ?? true,
          ...(opts?.fio ? { fio: opts.fio } : {}),
          ...loaded.invokeArgs
        }
      }
      return handleRequest(_evt, {
        method: 'POST',
        path: '/api/v1/tools/invoke',
        body,
        token: opts?.token ?? null,
        timeoutMs: 120_000
      })
    }
  )
}

// Register before app.whenReady and on every electron-vite main HMR reload (whenReady does not re-run).
registerMainIpcHandlers()

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1120,
    minHeight: 720,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#0D3B73',
    title: 'Оркестратор',
    icon: APP_ICON || undefined,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true
    }
  })

  if (process.platform === 'win32' && APP_ICON) {
    mainWindow.setAppDetails({
      appId: 'com.orchestrator.desktop',
      appIconPath: APP_ICON,
      relaunchDisplayName: 'Оркестратор'
    })
  }

  mainWindow.on('ready-to-show', () => mainWindow.show())
  mainWindow.webContents.on('did-fail-load', (_event, code, desc, url) => {
    console.error(`Renderer failed to load: ${code} ${desc} ${url}`)
  })
  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level < 2) return
    console.log(`[renderer:error] ${message} (${sourceId}:${line})`)
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

app.whenReady().then(async () => {
  registerMainIpcHandlers()
  agentSidecar.warmup()
  const ready = await ensureDesktopBackend(CONFIG.backendUrl)
  const remoteUp =
    CONFIG.backendUrl.replace(/\/+$/, '') === LOCAL_BACKEND
      ? ready
      : await pingBackendHealth(CONFIG.backendUrl)
  const localUp = await pingBackendHealth(LOCAL_BACKEND)
  console.log(
    `Orchestrator backend: ${CONFIG.backendUrl}${remoteUp ? '' : ' (недоступен)'}` +
      (localUp ? `; local ${LOCAL_BACKEND} up` : `; local ${LOCAL_BACKEND} down`)
  )
  if (!ready) {
    console.warn('Backend auto-start did not complete — admin/workplace may fail until backend is up.')
  }
  startUpdater({
    owner: CONFIG.updateOwner,
    repo: CONFIG.updateRepo,
    token: CONFIG.updateToken
  })

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  notifyGuard.stop()
  agentSidecar.stop()
  stopUpdater()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
