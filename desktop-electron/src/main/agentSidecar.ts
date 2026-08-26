import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { join, resolve } from 'node:path'
import { existsSync } from 'node:fs'
import { app } from 'electron'

export type AgentSidecarMessage = Record<string, unknown>

type EventSink = (message: AgentSidecarMessage) => void

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

  constructor(
    private readonly backendUrl: string,
    private readonly onEvent: EventSink
  ) {}

  private resolvePaths(): { sidecar: string; desktopRoot: string } {
    const envSidecar = process.env.CONSTRUCTOR_SIDECAR
    const envDesktop = process.env.CONSTRUCTOR_DESKTOP_ROOT
    const appPath = app.getAppPath()
    const candidates = [
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
    let desktopRoot = envDesktop || ''
    if (!desktopRoot) {
      for (const base of candidates) {
        const guess = resolve(base, '..', 'desktop')
        if (existsSync(join(guess, 'app', 'config.py'))) {
          desktopRoot = guess
          break
        }
      }
    }
    if (!desktopRoot) {
      desktopRoot = resolve(appPath, '..', 'desktop')
    }
    return { sidecar, desktopRoot }
  }

  private pythonCommand(): string {
    return process.env.CONSTRUCTOR_PYTHON || 'python'
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
    const env = { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' }
    let child: ChildProcessWithoutNullStreams
    try {
      child = spawn(this.pythonCommand(), ['-u', sidecar], {
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
      if (this.stopping) return
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
        if (message.type === 'ready') this.restarts = 0
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
        this.onEvent(message)
      }
      index = this.stdoutBuffer.indexOf('\n')
    }
  }

  send(command: AgentSidecarMessage): boolean {
    if (!this.child) {
      this.start()
    }
    if (!this.child || !this.child.stdin.writable) return false
    try {
      this.child.stdin.write(JSON.stringify(command) + '\n')
      return true
    } catch {
      return false
    }
  }

  configure(token: string | null): void {
    this.lastToken = token ?? null
    this.send({ type: 'configure', backendUrl: this.backendUrl, token: this.lastToken })
  }

  ready(token: string | null): void {
    this.lastToken = token ?? null
    this.start()
    this.configure(this.lastToken)
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
