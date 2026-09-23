import { type ChildProcessWithoutNullStreams } from 'node:child_process'
import { resolveWindowsPythonExe, spawnHidden } from './spawnHidden'
import { delimiter, dirname, join, resolve } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'
import { app } from 'electron'

const CURSOR_ENV_KEYS = [
  'CURSOR_API_KEY',
  'CURSOR_API_BASE_URL',
  'CURSOR_SDK_MODEL',
  'LM_STUDIO_BASE_URL',
  'LM_STUDIO_MODEL',
  'LM_STUDIO_OCR_MODEL'
] as const

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

function isDesktopRoot(path: string): boolean {
  return existsSync(join(path, 'app', 'config.py'))
}

function hasCursorKey(path: string): boolean {
  return Boolean(parseEnvFile(join(path, '.env')).CURSOR_API_KEY?.trim())
}

function walkParents(start: string, depth = 6): string[] {
  const rows: string[] = []
  let current = resolve(start)
  for (let i = 0; i < depth; i += 1) {
    rows.push(current)
    const parent = resolve(current, '..')
    if (parent === current) break
    current = parent
  }
  return rows
}

function findConstructorDesktop(starts: string[]): string {
  for (const start of starts) {
    for (const root of walkParents(start)) {
      const guess = join(root, 'Consturctor', 'desktop')
      if (isDesktopRoot(guess)) return guess
    }
  }
  return ''
}

function collectDesktopCandidates(starts: string[]): string[] {
  const rows: string[] = []
  const push = (value: string): void => {
    const path = resolve(value)
    if (!rows.includes(path)) rows.push(path)
  }
  for (const start of starts) {
    // Prefer in-repo orchestrator/desktop (desktop-electron is nested under orchestrator/).
    push(resolve(start, '..', 'desktop'))
    push(resolve(start, '..', '..', 'desktop'))
    push(resolve(start, 'desktop'))
  }
  const constructorDesktop = findConstructorDesktop(starts)
  if (constructorDesktop) push(constructorDesktop)
  for (const start of starts) {
    push(resolve(start, '..', 'Consturctor', 'desktop'))
    push(resolve(start, '..', '..', 'Consturctor', 'desktop'))
  }
  return rows.filter((path) => isDesktopRoot(path))
}

function isOrchestratorRepoDesktop(path: string): boolean {
  const normalized = path.replace(/\\/g, '/').toLowerCase()
  return (
    normalized.endsWith('/orchestrator/desktop') ||
    /\/orchestrator\/(?:orchestrator\/)?desktop$/i.test(normalized)
  )
}

function resolveDesktopRoot(starts: string[], fallback: string): string {
  const envDesktop = process.env.CONSTRUCTOR_DESKTOP_ROOT
  if (envDesktop) {
    const resolved = resolve(envDesktop)
    if (isDesktopRoot(resolved)) return resolved
  }
  const found = collectDesktopCandidates(starts)
  const local = found.find((path) => isOrchestratorRepoDesktop(path))
  if (local) return local
  return found.find((path) => hasCursorKey(path)) || found[0] || fallback
}

const ONEC_DESKTOP_ENV_KEYS = [
  'ONEC_COM_SERVER',
  'ONEC_COM_REF',
  'ONEC_COM_CONNECTION_STRING',
  'ONEC_ENTERPRISE_DB',
  'ONEC_COM_PROGID',
  'ONEC_DB_PATH',
  'BACKEND_URL'
] as const

function onecInfraEnvFromDesktop(desktopRoot: string): Record<string, string> {
  const parsed = parseEnvFile(join(desktopRoot, '.env'))
  const out: Record<string, string> = {}
  for (const key of ONEC_DESKTOP_ENV_KEYS) {
    const value = parsed[key]?.trim()
    if (value) out[key] = value
  }
  if (!out.ONEC_ENTERPRISE_DB && out.ONEC_COM_SERVER && out.ONEC_COM_REF) {
    out.ONEC_ENTERPRISE_DB = `/S${out.ONEC_COM_SERVER}\\${out.ONEC_COM_REF}`
  }
  return out
}

function cursorEnvFromDesktop(desktopRoot: string): Record<string, string> {
  const appData = process.env.APPDATA || ''
  const files = [
    appData ? join(appData, 'constructor-desktop-electron', '.env') : '',
    appData ? join(appData, 'Orchestrator', '.env') : '',
    join(process.cwd(), '.env'),
    join(desktopRoot, '.env'),
    ...walkParents(desktopRoot).map((root) => join(root, 'Consturctor', 'desktop', '.env')),
    ...walkParents(desktopRoot).map((root) => join(root, 'backend', '.env')),
    ...walkParents(desktopRoot).map((root) => join(root, 'Consturctor', 'backend', '.env'))
  ].filter(Boolean)
  const out: Record<string, string> = {}
  for (const file of files) {
    const parsed = parseEnvFile(file)
    for (const key of CURSOR_ENV_KEYS) {
      if (!out[key] && parsed[key]?.trim()) out[key] = parsed[key].trim()
    }
  }
  return out
}

export type AgentSidecarMessage = Record<string, unknown>

export type AgentSidecarSendResult = {
  ok: boolean
  queued?: boolean
  error?: string
  reason?: 'not_ready' | 'start_failed' | 'stopped' | 'write_failed'
}

export type AgentSidecarStatus = {
  ready: boolean
  starting: boolean
  queuedCommands: number
  error: string
  sidecarPath: string
  desktopRoot: string
  python: string
  cwd: string
}

type EventSink = (message: AgentSidecarMessage) => void

const START_TYPES = new Set([
  'design',
  'readiness',
  'demo',
  'run',
  'check_trigger',
  'form_orchestrator',
  'calc_orchestrator',
  'kpi_module'
])

function isStartCommand(command: AgentSidecarMessage): boolean {
  return START_TYPES.has(String(command.type || ''))
}

function isForceRestart(command: AgentSidecarMessage): boolean {
  const value = command.forceRestart ?? command.force_restart
  if (value === true) return true
  const text = String(value ?? '')
    .trim()
    .toLowerCase()
  return text === '1' || text === 'true' || text === 'yes'
}

/**
 * Manages the Python agent sidecar process that drives the local Cursor SDK.
 * It reuses the existing desktop code and speaks newline-delimited JSON on
 * stdin/stdout. See desktop-electron/pybridge/agent_sidecar.py.
 */
export class AgentSidecar {
  private child: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ''
  private restartTimer: NodeJS.Timeout | null = null
  private restarts = 0
  private stopping = false
  private lastToken: string | null = null
  private lastLogin = ''
  private lastPassword = ''
  private isReady = false
  private pending: AgentSidecarMessage[] = []
  private lastStart: AgentSidecarMessage | null = null
  private lastStartError = ''
  private lastPaths: { sidecar: string; desktopRoot: string; python: string; cwd: string } = {
    sidecar: '',
    desktopRoot: '',
    python: '',
    cwd: ''
  }
  private readonly runMeta = new Map<string, { workflowId: string; kind: string; source: string }>()

  constructor(
    private readonly backendUrl: string,
    private readonly onEvent: EventSink
  ) {}

  private resolvePaths(): { sidecar: string; desktopRoot: string } {
    const envSidecar = process.env.CONSTRUCTOR_SIDECAR
    const envDesktop = process.env.CONSTRUCTOR_DESKTOP_ROOT
    const appPath = app.getAppPath()
    const candidates = [
      process.resourcesPath,
      appPath,
      resolve(appPath, '..'),
      resolve(__dirname, '..', '..'),
      process.cwd()
    ]
    let sidecar = envSidecar || ''
    if (!sidecar) {
      for (const base of candidates) {
        const guess = join(base, 'pybridge', 'agent_sidecar.py')
        if (existsSync(guess)) {
          sidecar = guess
          break
        }
      }
    }
    if (!sidecar) {
      sidecar = join(appPath, 'pybridge', 'agent_sidecar.py')
    }
    const desktopRoot = resolveDesktopRoot(candidates, envDesktop || resolve(appPath, '..', 'desktop'))
    return { sidecar, desktopRoot }
  }

  private pythonCommand(): string {
    const bundled = join(process.resourcesPath, 'python', process.platform === 'win32' ? 'python.exe' : 'python')
    if (process.env.CONSTRUCTOR_PYTHON) return process.env.CONSTRUCTOR_PYTHON
    if (app.isPackaged && existsSync(bundled)) return bundled
    return resolveWindowsPythonExe()
  }

  private nodeCommand(): string {
    const bundled = join(process.resourcesPath, 'node', process.platform === 'win32' ? 'node.exe' : 'node')
    return process.env.CONSTRUCTOR_NODE || (app.isPackaged && existsSync(bundled) ? bundled : 'node')
  }

  private runtimeEnv(sidecar: string, desktopRoot: string): NodeJS.ProcessEnv {
    const node = this.nodeCommand()
    const nodeDir = existsSync(node) ? dirname(node) : ''
    const pathParts = [nodeDir, process.env.PATH || process.env.Path || ''].filter(Boolean)
    const browsersPath = join(desktopRoot, 'ms-playwright')
    const cursorEnv = cursorEnvFromDesktop(desktopRoot)
    const onecEnv = onecInfraEnvFromDesktop(desktopRoot)
    const pythonPathParts = [desktopRoot, process.env.PYTHONPATH].filter(Boolean)
    const localAppData = process.env.LOCALAPPDATA || process.env.APPDATA || ''
    const orchestratorWorkspacesRoot = localAppData
      ? join(localAppData, 'Orchestrator', 'agent_workspaces')
      : ''
    if (!cursorEnv.CURSOR_API_KEY) {
      console.error('[agent-sidecar] CURSOR_API_KEY не найден в desktop/.env Constructor')
    } else {
      console.log(`[agent-sidecar] desktop root: ${desktopRoot}`)
    }
    return {
      ...process.env,
      ...onecEnv,
      ...cursorEnv,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONPATH: pythonPathParts.join(delimiter),
      CONSTRUCTOR_SIDECAR: sidecar,
      CONSTRUCTOR_DESKTOP_ROOT: desktopRoot,
      CONSTRUCTOR_INSTANCE: process.env.CONSTRUCTOR_INSTANCE || 'orchestrator',
      CONSTRUCTOR_AGENT_WORKSPACES_ROOT:
        process.env.CONSTRUCTOR_AGENT_WORKSPACES_ROOT || orchestratorWorkspacesRoot,
      CONSTRUCTOR_PYTHON: this.pythonCommand(),
      CONSTRUCTOR_NODE: node,
      PLAYWRIGHT_BROWSERS_PATH:
        process.env.PLAYWRIGHT_BROWSERS_PATH || (existsSync(browsersPath) ? browsersPath : ''),
      PATH: pathParts.join(delimiter),
      Path: pathParts.join(delimiter)
    }
  }

  /** Start the Python sidecar as early as possible (before renderer IPC). */
  warmup(): void {
    this.start()
    this.configure(this.lastToken)
  }

  sessionCredentials(): { login: string; password: string } {
    return { login: this.lastLogin, password: this.lastPassword }
  }

  setSessionCredentials(credentials?: { login?: string; password?: string }): void {
    if (!credentials) return
    if (credentials.login !== undefined) this.lastLogin = String(credentials.login || '')
    if (credentials.password !== undefined) this.lastPassword = String(credentials.password || '')
  }

  status(): AgentSidecarStatus {
    const { sidecar, desktopRoot } = this.resolvePaths()
    const python = this.lastPaths.python || this.pythonCommand()
    const cwd =
      this.lastPaths.cwd ||
      (existsSync(desktopRoot) ? desktopRoot : existsSync(sidecar) ? dirname(sidecar) : '')
    return {
      ready: this.isReady,
      starting: Boolean(this.child) && !this.isReady,
      queuedCommands: this.pending.length,
      error: this.lastStartError,
      sidecarPath: this.lastPaths.sidecar || sidecar,
      desktopRoot: this.lastPaths.desktopRoot || desktopRoot,
      python,
      cwd
    }
  }

  start(): void {
    if (this.child) return
    const { sidecar, desktopRoot } = this.resolvePaths()
    const python = process.env.CONSTRUCTOR_PYTHON || this.pythonCommand()
    const cwd = existsSync(desktopRoot) ? desktopRoot : dirname(sidecar)
    this.lastPaths = { sidecar, desktopRoot, python, cwd }
    if (!existsSync(sidecar)) {
      this.lastStartError = `Файл sidecar не найден: ${sidecar}`
      this.onEvent({
        type: 'error',
        message: this.lastStartError
      })
      return
    }
    this.lastStartError = ''
    const env = this.runtimeEnv(sidecar, desktopRoot)
    let child: ChildProcessWithoutNullStreams
    try {
      child = spawnHidden(env.CONSTRUCTOR_PYTHON || python, ['-u', sidecar], {
        cwd: existsSync(cwd) ? cwd : undefined,
        env
      }) as ChildProcessWithoutNullStreams
    } catch (err) {
      this.lastStartError = `Не удалось запустить sidecar: ${err instanceof Error ? err.message : String(err)}`
      this.onEvent({
        type: 'error',
        message: this.lastStartError
      })
      return
    }
    console.log(
      `[agent-sidecar] spawn python=${python} sidecar=${sidecar} cwd=${cwd} desktop=${desktopRoot}`
    )
    this.child = child
    this.isReady = false
    this.stdoutBuffer = ''
    child.stdout.setEncoding('utf-8')
    child.stdout.on('data', (chunk: string) => this.onStdout(chunk))
    child.stderr.setEncoding('utf-8')
    child.stderr.on('data', (chunk: string) => {
      const text = String(chunk).trim()
      if (text) console.error(`[agent-sidecar] ${text}`)
    })
    const ignorePipeError = (err: Error): void => {
      console.error(`[agent-sidecar] pipe: ${err.message}`)
    }
    child.stdin.on('error', ignorePipeError)
    child.stdout.on('error', ignorePipeError)
    child.stderr.on('error', ignorePipeError)
    child.on('error', (err) => {
      this.lastStartError = `Sidecar process error: ${err instanceof Error ? err.message : String(err)}`
      this.onEvent({
        type: 'error',
        message: this.lastStartError
      })
    })
    child.on('exit', (code) => {
      try {
        if (!child.stdin.destroyed) child.stdin.destroy()
      } catch {
        /* already closed */
      }
      this.child = null
      this.isReady = false
      if (this.stopping) return
      this.pending = this.lastStart ? [this.lastStart] : []
      this.onEvent({
        type: 'sidecar_exit',
        code: code ?? -1
      })
      this.scheduleRestart()
    })
    // Configure right away so the ApiClient has backend URL + token.
    this.configure(this.lastToken)
  }

  private scheduleRestart(): void {
    if (this.stopping) return
    if (this.restarts >= 5) return
    this.restarts += 1
    const delay = Math.min(1000 * this.restarts, 5000)
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null
      this.start()
    }, delay)
  }

  private onStdout(chunk: string): void {
    this.stdoutBuffer += chunk
    let index = this.stdoutBuffer.indexOf('\n')
    while (index >= 0) {
      const line = this.stdoutBuffer.slice(0, index).trim()
      this.stdoutBuffer = this.stdoutBuffer.slice(index + 1)
      if (line) {
        let message: AgentSidecarMessage
        try {
          message = JSON.parse(line) as AgentSidecarMessage
        } catch {
          message = { type: 'log', text: line }
        }
        if (message.type === 'ready') {
          this.restarts = 0
          this.isReady = true
          this.lastStartError = ''
          this.flushPending()
        }
        // Opt-in diagnostics (set AGENT_SIDECAR_DEBUG=1) to confirm that runner
        // events (thinking/tool_call/tool_result) actually reach the main process.
        if (process.env.AGENT_SIDECAR_DEBUG) {
          const mtype = String(message.type || '')
          if (mtype === 'event') {
            const payload = message.payload as { type?: string } | undefined
            console.log('[agent-sidecar] event', payload?.type)
          } else {
            console.log('[agent-sidecar]', mtype)
          }
        }
        this.onEvent(this.stampRunMeta(message))
      }
      index = this.stdoutBuffer.indexOf('\n')
    }
  }

  private rememberRunMeta(command: AgentSidecarMessage): void {
    const runId = String(command.id || '')
    if (!runId) return
    this.runMeta.set(runId, {
      workflowId: String(command.workflowId || ''),
      kind: String(command.type || ''),
      source: String(command.source || '')
    })
  }

  private stampRunMeta(message: AgentSidecarMessage): AgentSidecarMessage {
    if (message.type === 'run_adopted') {
      const requested = String(message.runId || '')
      const linked = String(message.linkedRunId || '')
      if (requested && linked) {
        const meta = this.runMeta.get(requested)
        if (meta) this.runMeta.set(linked, meta)
      }
    }
    const runId = String(message.runId || message.id || '')
    const meta = runId ? this.runMeta.get(runId) : undefined
    if (!meta) return message
    const next: AgentSidecarMessage = { ...message }
    if (!next.workflowId && meta.workflowId) next.workflowId = meta.workflowId
    if (!next.kind && meta.kind) {
      next.kind = meta.kind === 'check_trigger' ? 'trigger' : meta.kind
    }
    if (!next.source && meta.source) next.source = meta.source
    if (next.type === 'result' || next.type === 'error') {
      this.runMeta.delete(runId)
    }
    return next
  }

  /** Kill the Python sidecar so stale in-memory runs cannot block a fresh launch. */
  private hardRestartSidecar(reason: string): void {
    console.log(`[agent-sidecar] hard restart: ${reason}`)
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    this.isReady = false
    this.runMeta.clear()
    const child = this.child
    this.child = null
    if (!child) return
    try {
      if (child.stdin.writable) {
        child.stdin.write(JSON.stringify({ type: 'shutdown' }) + '\n')
      }
    } catch {
      /* ignore */
    }
    try {
      child.kill('SIGTERM')
    } catch {
      /* ignore */
    }
  }

  private sendForceRun(command: AgentSidecarMessage): AgentSidecarSendResult {
    this.hardRestartSidecar('forceRestart run')
    this.pending = []
    this.enqueue(command)
    this.start()
    return { ok: true, queued: true, reason: 'not_ready' }
  }

  private stdinOpen(): boolean {
    const stdin = this.child?.stdin
    return Boolean(stdin && stdin.writable && !stdin.destroyed && !stdin.writableEnded)
  }

  send(command: AgentSidecarMessage): AgentSidecarSendResult {
    if (this.stopping) {
      return { ok: false, error: 'Sidecar останавливается', reason: 'stopped' }
    }
    const type = String(command.type || '')
    if (type === 'run' && isForceRestart(command)) {
      this.lastStart = command
      this.rememberRunMeta(command)
      return this.sendForceRun(command)
    }
    if (isStartCommand(command)) {
      this.lastStart = command
      this.rememberRunMeta(command)
    }
    if (type === 'cancel') {
      this.lastStart = null
    }
    if (!this.child) {
      this.start()
    }
    if (this.lastStartError && !this.child) {
      return { ok: false, error: this.lastStartError, reason: 'start_failed' }
    }
    if (!this.isReady || !this.stdinOpen()) {
      this.enqueue(command)
      return { ok: true, queued: true, reason: 'not_ready' }
    }
    return this.write(command) ? { ok: true } : { ok: false, error: 'Не удалось записать в sidecar', reason: 'write_failed' }
  }

  private enqueue(command: AgentSidecarMessage): void {
    const type = String(command.type || '')
    if (type === 'configure') {
      this.pending = this.pending.filter((item) => String(item.type || '') !== 'configure')
      this.pending.unshift(command)
      return
    }
    if (isStartCommand(command)) {
      this.pending = this.pending.filter((item) => !isStartCommand(item))
    }
    this.pending.push(command)
  }

  private write(command: AgentSidecarMessage): boolean {
    if (!this.stdinOpen()) {
      this.enqueue(command)
      return true
    }
    try {
      const stdin = this.child!.stdin
      const line = JSON.stringify(command) + '\n'
      stdin.write(line, (err) => {
        if (err) console.error(`[agent-sidecar] stdin write failed: ${err.message}`)
      })
      console.log(`[agent-sidecar] sent ${String(command.type || '')}`)
      return true
    } catch (err) {
      console.error(
        `[agent-sidecar] stdin write failed: ${err instanceof Error ? err.message : String(err)}`
      )
      this.enqueue(command)
      return false
    }
  }

  private flushPending(): void {
    const queued = this.pending
    this.pending = []
    for (const command of queued) {
      this.write(command)
    }
  }

  configure(
    token: string | null,
    credentials?: {
      login?: string
      password?: string
      onecComUsr?: string
      nameMail?: string
      userId?: string
      onecCatalogRefKey?: string
      [key: string]: unknown
    }
  ): void {
    this.lastToken = token ?? null
    if (credentials) {
      if (credentials.login !== undefined) this.lastLogin = String(credentials.login || '')
      if (credentials.password !== undefined) this.lastPassword = String(credentials.password || '')
    }
    const payload: Record<string, unknown> = {
      type: 'configure',
      backendUrl: this.backendUrl,
      token: this.lastToken,
      login: this.lastLogin,
      fio: this.lastLogin,
      erp_login: this.lastLogin,
      password: this.lastPassword
    }
    if (credentials) {
      for (const [key, value] of Object.entries(credentials)) {
        if (value === undefined || value === null) continue
        const text = String(value).trim()
        if (!text) continue
        payload[key] = text
      }
    }
    this.send(payload)
  }

  ready(
    token: string | null,
    credentials?: {
      login?: string
      password?: string
      onecComUsr?: string
      nameMail?: string
      userId?: string
      onecCatalogRefKey?: string
      [key: string]: unknown
    }
  ): void {
    this.lastToken = token ?? null
    this.start()
    this.configure(this.lastToken, credentials)
  }

  stop(): void {
    this.stopping = true
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    if (this.child) {
      try {
        this.child.stdin.write(JSON.stringify({ type: 'shutdown' }) + '\n')
      } catch {
        /* ignore */
      }
      const child = this.child
      this.child = null
      setTimeout(() => {
        if (!child.killed) child.kill()
      }, 500)
    }
  }
}
