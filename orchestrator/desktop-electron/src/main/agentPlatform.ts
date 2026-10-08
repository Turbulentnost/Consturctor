import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { createServer } from 'node:net'
import { delimiter, dirname, join, resolve } from 'node:path'
import { app } from 'electron'
import { cursorEnvFromDesktop } from './agentSidecar'
import { resolveWindowsPythonExe, spawnHidden } from './spawnHidden'

const HOST = '127.0.0.1'
const START_TIMEOUT_MS = 90_000
const HEALTH_TIMEOUT_MS = 2_500
const STDERR_TAIL = 30

export type AgentPlatformUser = {
  fio: string
  password: string
  token: string
}

export type AgentPlatformStatus = {
  ok: boolean
  url: string
  starting: boolean
  error: string
  root: string
}

function delay(ms: number): Promise<void> {
  return new Promise((done) => setTimeout(done, ms))
}

async function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, HOST, () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => (port ? resolvePort(port) : reject(new Error('Нет свободного порта'))))
    })
  })
}

async function healthy(url: string): Promise<boolean> {
  try {
    const response = await fetch(`${url}/health`, { signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS) })
    return response.ok
  } catch {
    return false
  }
}

function killTree(child: ChildProcess): void {
  if (!child.pid || child.exitCode !== null) return
  if (process.platform === 'win32') {
    // Раннер Cursor SDK и MCP-сервер — дочерние процессы сервиса; без /T они переживут выход.
    spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }).on(
      'error',
      () => undefined
    )
  } else {
    child.kill()
  }
}

/**
 * Платформа ИИ-агентов TurboTester (конфигурация 2) как локальный сервис Оркестратора:
 * раннер Cursor SDK, MCP-инструменты, вопросы и разрешения. Работает под вошедшим пользователем.
 */
export class AgentPlatform {
  private child: ChildProcess | null = null
  private starting: Promise<AgentPlatformStatus> | null = null
  private port = 0
  private user: AgentPlatformUser = { fio: '', password: '', token: '' }
  private launchedFor = ''
  private lastError = ''
  private stderr: string[] = []
  private stopping = false

  constructor(
    private readonly backendUrl: string,
    private readonly desktopRoot: () => string
  ) {}

  private get url(): string {
    return this.port ? `http://${HOST}:${this.port}` : ''
  }

  // Токен в ключ не входит: его обновление не должно обрывать идущие запуски.
  private userKey(user: AgentPlatformUser): string {
    return `${user.fio}\n${user.password}`
  }

  root(): string {
    const appPath = app.getAppPath()
    const candidates = [
      process.env.ORCH_AGENT_PLATFORM_ROOT || '',
      join(process.resourcesPath, 'agent-platform'),
      resolve(appPath, '..', 'agent-platform'),
      resolve(appPath, '..', '..', 'agent-platform'),
      resolve(__dirname, '..', '..', '..', 'agent-platform')
    ].filter(Boolean)
    return (
      candidates.find((path) => existsSync(join(path, 'backend', 'run_platform.py'))) ||
      candidates[candidates.length - 1]
    )
  }

  private python(): string {
    const bundled = join(process.resourcesPath, 'python', process.platform === 'win32' ? 'python.exe' : 'python')
    if (process.env.CONSTRUCTOR_PYTHON) return process.env.CONSTRUCTOR_PYTHON
    if (app.isPackaged && existsSync(bundled)) return bundled
    return resolveWindowsPythonExe()
  }

  private node(): string {
    const bundled = join(process.resourcesPath, 'node', process.platform === 'win32' ? 'node.exe' : 'node')
    return process.env.CONSTRUCTOR_NODE || (app.isPackaged && existsSync(bundled) ? bundled : '')
  }

  private environment(port: number): NodeJS.ProcessEnv {
    const desktopRoot = this.desktopRoot()
    const localAppData = process.env.LOCALAPPDATA || app.getPath('appData')
    const dataDir = join(localAppData, 'Orchestrator', 'agent-platform')
    mkdirSync(dataDir, { recursive: true })
    const node = this.node()
    const pathParts = [node ? dirname(node) : '', process.env.PATH || process.env.Path || ''].filter(Boolean)
    const browsers = join(desktopRoot, 'ms-playwright')
    const { fio, password, token } = this.user
    return {
      ...process.env,
      ...cursorEnvFromDesktop(desktopRoot),
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
      API_HOST: HOST,
      API_PORT: String(port),
      PLATFORM_DATA_DIR: dataDir,
      TOOLS_WORKSPACES_ROOT:
        process.env.CONSTRUCTOR_AGENT_WORKSPACES_ROOT || join(localAppData, 'Orchestrator', 'agent_workspaces'),
      CONSTRUCTOR_API_URL: this.backendUrl,
      CONSTRUCTOR_DESKTOP_DIR: desktopRoot,
      CONSTRUCTOR_USER_FIO: fio,
      CONSTRUCTOR_USER_PASSWORD: password,
      CONSTRUCTOR_API_TOKEN: password ? '' : token,
      // Каталог агентов Constructor платформе Оркестратора не нужен: не опрашиваем базу каждую минуту.
      CONSTRUCTOR_SYNC_ENABLED: 'false',
      PLAYWRIGHT_BROWSERS_PATH: process.env.PLAYWRIGHT_BROWSERS_PATH || (existsSync(browsers) ? browsers : ''),
      PATH: pathParts.join(delimiter),
      Path: pathParts.join(delimiter)
    }
  }

  status(): AgentPlatformStatus {
    return {
      ok: Boolean(this.child && this.url && !this.starting),
      url: this.url,
      starting: Boolean(this.starting),
      error: this.lastError,
      root: this.root()
    }
  }

  /** Пользователь Оркестратора сменился — сервис перезапускается под ним при следующем обращении. */
  setUser(user: Partial<AgentPlatformUser>): void {
    const next: AgentPlatformUser = {
      fio: String(user.fio ?? this.user.fio ?? '').trim(),
      password: String(user.password ?? this.user.password ?? ''),
      token: String(user.token ?? this.user.token ?? '')
    }
    this.user = next
    if (!this.child || this.userKey(next) === this.launchedFor) return
    console.log('[agent-platform] пользователь сменился — сервис будет перезапущен')
    this.shutdown()
  }

  async ensure(): Promise<AgentPlatformStatus> {
    if (this.starting) return this.starting
    if (this.child && this.url && (await healthy(this.url))) return this.status()
    if (!this.user.fio) {
      this.lastError = 'Войдите в Оркестратор: агенты запускаются под вашей учётной записью'
      return { ...this.status(), ok: false }
    }
    this.starting = this.launch().finally(() => {
      this.starting = null
    })
    return this.starting
  }

  private async launch(): Promise<AgentPlatformStatus> {
    this.shutdown()
    this.stopping = false
    const root = this.root()
    const script = join(root, 'backend', 'run_platform.py')
    if (!existsSync(script)) {
      this.lastError = `Не найдена платформа агентов: ${script}`
      return { ...this.status(), ok: false, error: this.lastError }
    }
    const port = await freePort()
    const python = this.python()
    let child: ChildProcess
    try {
      child = spawnHidden(python, ['-u', script], {
        cwd: join(root, 'backend'),
        env: this.environment(port),
        stdio: ['ignore', 'pipe', 'pipe']
      })
    } catch (error) {
      this.lastError = `Не удалось запустить платформу агентов: ${error instanceof Error ? error.message : String(error)}`
      return { ...this.status(), ok: false, error: this.lastError }
    }
    this.child = child
    this.port = port
    this.launchedFor = this.userKey(this.user)
    this.stderr = []
    const remember = (chunk: Buffer | string): void => {
      for (const line of String(chunk).split(/\r?\n/)) {
        const text = line.trim()
        if (!text) continue
        this.stderr.push(text)
        if (this.stderr.length > STDERR_TAIL) this.stderr.shift()
        console.log(`[agent-platform] ${text}`)
      }
    }
    child.stdout?.on('data', remember)
    child.stderr?.on('data', remember)
    child.on('exit', (code) => {
      if (this.child !== child) return
      this.child = null
      this.port = 0
      if (!this.stopping) {
        this.lastError = `Платформа агентов остановилась (код ${code ?? '?'}): ${this.stderr.slice(-3).join(' · ')}`
        console.error(`[agent-platform] ${this.lastError}`)
      }
    })
    console.log(`[agent-platform] spawn python=${python} root=${root} port=${port}`)
    const deadline = Date.now() + START_TIMEOUT_MS
    while (Date.now() < deadline) {
      if (this.child !== child) break
      if (await healthy(`http://${HOST}:${port}`)) {
        this.lastError = ''
        return { ok: true, url: `http://${HOST}:${port}`, starting: false, error: '', root }
      }
      await delay(400)
    }
    if (this.child === child) {
      this.lastError = `Платформа агентов не ответила за ${START_TIMEOUT_MS / 1000} с: ${this.stderr.slice(-3).join(' · ')}`
      this.shutdown()
    }
    return { ok: false, url: '', starting: false, error: this.lastError, root }
  }

  private shutdown(): void {
    const child = this.child
    this.child = null
    this.port = 0
    this.launchedFor = ''
    if (child) {
      this.stopping = true
      killTree(child)
    }
  }

  stop(): void {
    this.stopping = true
    this.shutdown()
  }
}
