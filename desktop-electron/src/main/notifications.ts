import { BrowserWindow } from 'electron'

const PING_MS = 20_000
const RECONNECT_MS = 4_000
const POLL_MS = 15_000
const KICK_MESSAGE = 'Выполнен вход на другом устройстве. Этот сеанс завершён.'

function notifyWindows(channel: string, payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send(channel, payload)
  }
}

function websocketUrl(backendUrl: string, token: string): string {
  const url = new URL(backendUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = '/api/v1/notifications/ws'
  url.search = `token=${encodeURIComponent(token)}`
  return url.toString()
}

export type NotificationCommand = Record<string, unknown>

export class NotificationGuard {
  private socket: WebSocket | null = null
  private token = ''
  private kicked = false
  private generation = 0
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private pollTimer: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly backendUrl: string,
    private readonly onCommand?: (command: NotificationCommand) => void
  ) {}

  start(token: string): void {
    this.detach()
    this.token = token
    this.kicked = false
    this.connect()
    void this.pollPending()
    this.pollTimer = setInterval(() => {
      void this.pollPending()
    }, POLL_MS)
  }

  stop(): void {
    this.detach()
  }

  private detach(): void {
    this.generation += 1
    this.clearTimers()
    this.token = ''
    const socket = this.socket
    this.socket = null
    if (socket) {
      try {
        socket.close()
      } catch {
        /* ignore */
      }
    }
  }

  private isLive(generation: number, socket?: WebSocket | null): boolean {
    if (this.kicked || this.generation !== generation || !this.token) return false
    if (socket && this.socket !== socket) return false
    return true
  }

  private connect(): void {
    if (!this.token || this.kicked) return
    const generation = this.generation
    const socket = new WebSocket(websocketUrl(this.backendUrl, this.token))
    this.socket = socket

    socket.addEventListener('open', () => {
      if (!this.isLive(generation, socket)) return
      this.startPing()
      void this.pollPending()
    })

    socket.addEventListener('message', (event) => {
      if (!this.isLive(generation, socket)) return
      this.onMessage(String(event.data || ''))
    })

    socket.addEventListener('close', (event) => {
      if (this.generation !== generation) return
      if (this.socket === socket) this.socket = null
      this.clearPing()
      if (this.kicked) return
      // 4001 is sent both to the replaced remote session and to our own
      // previous socket after reconnect. Only a live session_replaced or a
      // 401 on the current token should log this window out.
      if (event.code === 4001) return
      this.scheduleReconnect()
    })

    socket.addEventListener('error', () => {
      /* close handler reconnects */
    })
  }

  private onMessage(text: string): void {
    if (text === 'pong' || text === 'ping') return
    let payload: Record<string, unknown>
    try {
      payload = JSON.parse(text) as Record<string, unknown>
    } catch {
      return
    }
    const kind = String(payload.type || '')
    if (kind === 'session_replaced') {
      this.kick(String(payload.message || KICK_MESSAGE))
      return
    }
    if (kind === 'evaluate_trigger' || kind === 'run_agent') {
      this.onCommand?.(payload)
      return
    }
    if (
      kind === 'chat_message' ||
      kind === 'thread_opened' ||
      kind === 'chat_receipt' ||
      kind === 'presence' ||
      kind === 'ticket_updated'
    ) {
      notifyWindows('chat:event', payload)
    }
  }

  private kick(message: string): void {
    if (this.kicked) return
    this.kicked = true
    const text = message.trim() || KICK_MESSAGE
    this.detach()
    notifyWindows('session:kicked', { message: text })
  }

  private async pollPending(): Promise<void> {
    const generation = this.generation
    const token = this.token
    if (!token || this.kicked) return
    try {
      const response = await fetch(`${this.backendUrl}/api/v1/notifications/pending`, {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/json'
        }
      })
      if (!this.isLive(generation) || this.token !== token) return
      if (response.status === 401) {
        this.kick(KICK_MESSAGE)
      }
    } catch {
      /* network blips are retried on the next poll */
    }
  }

  private startPing(): void {
    this.clearPing()
    this.pingTimer = setInterval(() => {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send('ping')
      }
    }, PING_MS)
  }

  private scheduleReconnect(): void {
    if (this.kicked || !this.token || this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, RECONNECT_MS)
  }

  private clearPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  private clearTimers(): void {
    this.clearPing()
    if (this.pollTimer) {
      clearInterval(this.pollTimer)
      this.pollTimer = null
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}
