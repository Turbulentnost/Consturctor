import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { delimiter, dirname, join, resolve } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'
import { app } from 'electron'

const CURSOR_ENV_KEYS = ['CURSOR_API_KEY', 'CURSOR_API_BASE_URL', 'CURSOR_SDK_MODEL'] as const

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
  const constructorDesktop = findConstructorDesktop(starts)
  if (constructorDesktop) push(constructorDesktop)
  for (const start of starts) {
    push(resolve(start, '..', 'desktop'))
    push(resolve(start, 'desktop'))
    push(resolve(start, '..', 'Consturctor', 'desktop'))
    push(resolve(start, '..', '..', 'Consturctor', 'desktop'))
  }
  return rows.filter((path) => isDesktopRoot(path))
}

function resolveDesktopRoot(starts: string[], fallback: string): string {
  const envDesktop = process.env.CONSTRUCTOR_DESKTOP_ROOT
  if (envDesktop && isDesktopRoot(envDesktop)) return envDesktop
  const found = collectDesktopCandidates(starts)
  return found.find((path) => hasCursorKey(path)) || found[0] || fallback
}

function cursorEnvFromDesktop(desktopRoot: string): Record<string, string> {
  const files = [
    join(desktopRoot, '.env'),
    ...walkParents(desktopRoot).map((root) => join(root, 'Consturctor', 'desktop', '.env')),
    ...walkParents(desktopRoot).map((root) => join(root, 'backend', '.env')),
    ...walkParents(desktopRoot).map((root) => join(root, 'Consturctor', 'backend', '.env'))
  ]
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

type EventSink = (message: AgentSidecarMessage) => void

const START_TYPES = new Set([
  'design',
  'readiness',
  'demo',
  'run',
  'check_trigger',
  'form_orchestrator',
  'calc_orchestrator'
])

function isStartCommand(command: AgentSidecarMessage): boolean {
  return START_TYPES.has(String(command.type || ''))
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
  private readonly runMeta = new Map<string, { workflowId: string; kind: string }>()

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
    return process.env.CONSTRUCTOR_PYTHON || (app.isPackaged && existsSync(bundled) ? bundled : 'python')
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
    if (!cursorEnv.CURSOR_API_KEY) {
      console.error('[agent-sidecar] CURSOR_API_KEY не найден в desktop/.env Constructor')
    } else {
      console.log(`[agent-sidecar] desktop root: ${desktopRoot}`)
    }
    return {
      ...process.env,
      ...cursorEnv,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      CONSTRUCTOR_SIDECAR: sidecar,
      CONSTRUCTOR_DESKTOP_ROOT: desktopRoot,
      CONSTRUCTOR_PYTHON: this.pythonCommand(),
      CONSTRUCTOR_NODE: node,
      PLAYWRIGHT_BROWSERS_PATH:
        process.env.PLAYWRIGHT_BROWSERS_PATH || (existsSync(browsersPath) ? browsersPath : ''),
      PATH: pathParts.join(delimiter),
      Path: pathParts.join(delimiter)
    }
  }

  start(): void {
    if (this.child) return
    const { sidecar, desktopRoot } = this.resolvePaths()
    if (!existsSync(sidecar)) {
      this.onEvent({
        type: 'error',
        message: `Agent sidecar not found at ${sidecar}`
      })
      return
    }
    const env = this.runtimeEnv(sidecar, desktopRoot)
    let child: ChildProcessWithoutNullStreams
    try {
      child = spawn(env.CONSTRUCTOR_PYTHON || this.pythonCommand(), ['-u', sidecar], {
        cwd: existsSync(desktopRoot) ? desktopRoot : undefined,
        env
      })
    } catch (err) {
      this.onEvent({
        type: 'error',
        message: `Failed to start agent sidecar: ${err instanceof Error ? err.message : String(err)}`
      })
      return
    }
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
    child.on('error', (err) => {
      this.onEvent({
        type: 'error',
        message: `Agent sidecar error: ${err instanceof Error ? err.message : String(err)}`
      })
    })
    child.on('exit', (code) => {
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
      kind: String(command.type || '')
    })
  }

  private stampRunMeta(message: AgentSidecarMessage): AgentSidecarMessage {
    const runId = String(message.runId || message.id || '')
    const meta = runId ? this.runMeta.get(runId) : undefined
    if (!meta) return message
    const next: AgentSidecarMessage = { ...message }
    if (!next.workflowId && meta.workflowId) next.workflowId = meta.workflowId
    if (!next.kind && meta.kind) {
      next.kind = meta.kind === 'check_trigger' ? 'trigger' : meta.kind
    }
    if (next.type === 'result' || next.type === 'error') {
      this.runMeta.delete(runId)
    }
    return next
  }

  send(command: AgentSidecarMessage): boolean {
    const type = String(command.type || '')
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
    if (!this.isReady || !this.child || !this.child.stdin.writable) {
      this.enqueue(command)
      return true
    }
    return this.write(command)
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
    if (!this.child || !this.child.stdin.writable) {
      this.enqueue(command)
      return true
    }
    try {
      this.child.stdin.write(JSON.stringify(command) + '\n')
      console.log(`[agent-sidecar] sent ${String(command.type || '')}`)
      return true
    } catch {
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

  configure(token: string | null, credentials?: { login?: string; password?: string }): void {
    this.lastToken = token ?? null
    if (credentials) {
      if (credentials.login !== undefined) this.lastLogin = String(credentials.login || '')
      if (credentials.password !== undefined) this.lastPassword = String(credentials.password || '')
    }
    this.send({
      type: 'configure',
      backendUrl: this.backendUrl,
      token: this.lastToken,
      login: this.lastLogin,
      password: this.lastPassword
    })
  }

  ready(token: string | null, credentials?: { login?: string; password?: string }): void {
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
