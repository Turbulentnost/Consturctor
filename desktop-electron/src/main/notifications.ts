import { BrowserWindow, Notification } from 'electron'

const PING_MS = 20_000
const RECONNECT_MS = 4_000
const POLL_MS = 15_000
const KICK_MESSAGE = 'Выполнен вход на другом устройстве. Этот сеанс завершён.'

function notifyWindows(channel: string, payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send(channel, payload)
  }
}

export interface ToastPayload {
  title: string
  body?: string
  workflowId?: string
  runId?: string
  requestId?: string
  draftId?: string
}

export interface HitlToastDecision {
  requestId: string
  approved: boolean
  workflowId: string
  runId: string
}

export interface ToastHooks {
  onOpen?: (payload: { workflowId: string; runId: string }) => void
  onHitl?: (decision: HitlToastDecision) => void
}

let toastHooks: ToastHooks = {}
const liveToasts = new Map<string, Notification>()
const handledActivations = new Set<string>()
let activationInstalled = false

export function setToastHooks(hooks: ToastHooks): void {
  toastHooks = hooks
}

function focusAppWindows(): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed()) continue
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  }
}

function openFromToast(payload: ToastPayload): void {
  focusAppWindows()
  const open = {
    workflowId: payload.workflowId || '',
    runId: payload.runId || '',
    draftId: payload.draftId || ''
  }
  toastHooks.onOpen?.(open)
  notifyWindows('notification:open', open)
}

function decideHitl(payload: ToastPayload, approved: boolean): void {
  const requestId = (payload.requestId || '').trim()
  if (!requestId) {
    openFromToast(payload)
    return
  }
  const key = `${requestId}:${approved ? '1' : '0'}`
  if (handledActivations.has(key)) return
  handledActivations.add(key)
  const toast = liveToasts.get(requestId)
  if (toast) {
    try {
      toast.close()
    } catch {
      /* already dismissed */
    }
    liveToasts.delete(requestId)
  }
  const decision: HitlToastDecision = {
    requestId,
    approved,
    workflowId: payload.workflowId || '',
    runId: payload.runId || ''
  }
  toastHooks.onHitl?.(decision)
  notifyWindows('notification:hitl', decision)
  openFromToast(payload)
}

function escapeXml(value: string): string {
  return (value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function parseHitlActivation(raw: string): { kind: 'open' | 'accept' | 'reject'; payload: ToastPayload } | null {
  const text = (raw || '').trim()
  if (!text.startsWith('constructor-hitl:')) return null
  const rest = text.slice('constructor-hitl:'.length)
  const q = rest.indexOf('?')
  const kind = (q >= 0 ? rest.slice(0, q) : rest).trim()
  const query = q >= 0 ? rest.slice(q + 1) : ''
  const params = new URLSearchParams(query)
  const payload: ToastPayload = {
    title: '',
    workflowId: params.get('wid') || '',
    runId: params.get('rid') || '',
    requestId: params.get('qid') || ''
  }
  if (kind === 'accept' || kind === 'reject' || kind === 'open') {
    return { kind, payload }
  }
  return null
}

function hitlToastXml(title: string, body: string, payload: ToastPayload): string {
  const qid = escapeXml(payload.requestId || '')
  const wid = escapeXml(payload.workflowId || '')
  const rid = escapeXml(payload.runId || '')
  return (
    `<toast launch="constructor-hitl:open?wid=${wid}&amp;rid=${rid}&amp;qid=${qid}" ` +
    `activationType="foreground" duration="long" scenario="reminder">` +
    `<visual><binding template="ToastGeneric">` +
    `<text>${escapeXml(title)}</text>` +
    `<text>${escapeXml(body)}</text>` +
    `</binding></visual>` +
    `<actions>` +
    `<action content="Принять" arguments="constructor-hitl:accept?qid=${qid}&amp;wid=${wid}&amp;rid=${rid}" activationType="foreground"/>` +
    `<action content="Отклонить" arguments="constructor-hitl:reject?qid=${qid}&amp;wid=${wid}&amp;rid=${rid}" activationType="foreground"/>` +
    `</actions></toast>`
  )
}

export function installToastActivation(): void {
  if (activationInstalled) return
  const handle = (
    Notification as typeof Notification & {
      handleActivation?: (callback: (details: {
        type?: string
        arguments?: string
        actionIndex?: number
      }) => void) => void
    }
  ).handleActivation
  if (typeof handle !== 'function') return
  activationInstalled = true
  handle((details) => {
    const parsed = parseHitlActivation(String(details?.arguments || ''))
    if (!parsed) return
    if (parsed.kind === 'accept') {
      decideHitl(parsed.payload, true)
      return
    }
    if (parsed.kind === 'reject') {
      decideHitl(parsed.payload, false)
      return
    }
    openFromToast(parsed.payload)
  })
}

/**
 * Show a native OS toast and, on click, focus the app window and ask the
 * renderer to open the related agent. HITL toasts also get Accept / Reject.
 */
export function showToast(payload: ToastPayload): void {
  const title = (payload.title || '').trim() || 'Уведомление'
  const body = (payload.body || '').trim()
  const requestId = (payload.requestId || '').trim()
  if (!Notification.isSupported()) {
    notifyWindows('notification:open', payload)
    return
  }
  const options: Electron.NotificationConstructorOptions = {
    title,
    body,
    timeoutType: requestId ? 'never' : 'default',
    urgency: requestId ? 'critical' : 'normal'
  }
  if (requestId) {
    options.id = requestId
    options.actions = [
      { type: 'button', text: 'Принять' },
      { type: 'button', text: 'Отклонить' }
    ]
    if (process.platform === 'win32') {
      options.toastXml = hitlToastXml(title, body, payload)
    }
  }
  const toast = new Notification(options)
  if (requestId) liveToasts.set(requestId, toast)
  toast.on('click', () => openFromToast(payload))
  toast.on('action', (event: Electron.Event & { actionIndex?: number }, index?: number) => {
    const actionIndex = typeof event?.actionIndex === 'number' ? event.actionIndex : (index ?? 0)
    decideHitl(payload, actionIndex === 0)
  })
  toast.on('close', () => {
    if (requestId) liveToasts.delete(requestId)
  })
  toast.show()
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
  // Ids already toasted, so WS pushes and /pending polls do not double-notify.
  private readonly shownIds = new Set<string>()

  constructor(
    private readonly backendUrl: string,
    private readonly onCommand?: (command: NotificationCommand) => void
  ) {}

  start(token: string): void {
    this.detach()
    this.token = token
    this.kicked = false
    this.shownIds.clear()
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
    if (
      kind === 'evaluate_trigger' ||
      kind === 'run_agent' ||
      kind === 'form_orchestrator' ||
      kind === 'calc_orchestrator'
    ) {
      this.onCommand?.(payload)
      return
    }
    if (kind === 'notification') {
      this.handleNotification(payload)
      return
    }
    if (kind === 'board_updated') {
      notifyWindows('board:updated', payload)
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

  private handleNotification(payload: Record<string, unknown>): void {
    const id = String(payload.id || '')
    if (id && this.shownIds.has(id)) return
    if (id) this.shownIds.add(id)
    showToast({
      title: String(payload.title || ''),
      body: String(payload.body || ''),
      workflowId: String(payload.workflow_id || payload.workflowId || ''),
      runId: String(payload.run_id || payload.runId || '')
    })
    notifyWindows('inbox:changed', { id })
    if (id) void this.ack(id)
  }

  private async ack(id: string): Promise<void> {
    const token = this.token
    if (!token || this.kicked) return
    try {
      await fetch(
        `${this.backendUrl}/api/v1/notifications/${encodeURIComponent(id)}/ack`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'application/json'
          }
        }
      )
    } catch {
      /* the next poll re-delivers if ack did not land */
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
        return
      }
      if (!response.ok) return
      const items = (await response.json()) as unknown
      if (!this.isLive(generation) || this.token !== token) return
      if (!Array.isArray(items)) return
      for (const item of items) {
        if (item && typeof item === 'object') {
          this.handleNotification(item as Record<string, unknown>)
        }
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
