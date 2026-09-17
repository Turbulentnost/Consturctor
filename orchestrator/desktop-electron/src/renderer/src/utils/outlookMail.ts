import { parseMeetingTime } from './outlookMeetings'

/** Список писем — дольше, но не блокирует UI (async sidecar); 90s вместо 180s. */
const REQUEST_TIMEOUT_MS = 90_000

export function dayKeyLocal(day: Date): string {
  const y = day.getFullYear()
  const m = String(day.getMonth() + 1).padStart(2, '0')
  const d = String(day.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function skipOutlookCom(): boolean {
  const flag = String(import.meta.env.VITE_SKIP_OUTLOOK_COM || '').trim().toLowerCase()
  return flag === '1' || flag === 'true' || flag === 'yes'
}

function requestOutlookMail(range: {
  date?: string
  dateFrom?: string
  dateTo?: string
  folder?: string
  maxResults?: number
  query?: string
}): Promise<{
  ok: boolean
  messages: Record<string, unknown>[]
  error?: string
  source?: string
}> {
  return new Promise((resolve) => {
    const requestId = `mail-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    let settled = false
    const finish = (result: {
      ok: boolean
      messages: Record<string, unknown>[]
      error?: string
      source?: string
    }): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      unsubscribe()
      resolve(result)
    }
    const timer = setTimeout(
      () => finish({ ok: false, messages: [], error: 'Outlook не ответил вовремя' }),
      REQUEST_TIMEOUT_MS
    )
    const unsubscribe = window.agent.onEvent((payload) => {
      if (String(payload.type || '') !== 'mail_result') return
      if (String(payload.requestId || '') !== requestId) return
      if (payload.ok) {
        const raw = Array.isArray(payload.messages) ? payload.messages : []
        finish({
          ok: true,
          messages: raw.filter(
            (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object'
          ),
          source: String(payload.source || 'outlook_com')
        })
      } else {
        finish({
          ok: false,
          messages: [],
          error: String(payload.error || 'Не удалось прочитать почту Outlook')
        })
      }
    })
    void window.agent.searchOutlookMail({
      requestId,
      date: range.date,
      dateFrom: range.dateFrom,
      dateTo: range.dateTo,
      folder: range.folder || 'Inbox',
      maxResults: range.maxResults ?? 50,
      query: range.query
    })
  })
}

/** Диапазон текущей недели (пн…вс, локальный календарь) для outlook.search_mail. */
export function outlookMailWeekRange(anchor = new Date()): { dateFrom: string; dateTo: string } {
  const day = anchor.getDay()
  const diff = day === 0 ? -6 : 1 - day
  const monday = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + diff)
  const sunday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 6)
  return { dateFrom: dayKeyLocal(monday), dateTo: dayKeyLocal(sunday) }
}

export async function fetchOutlookMailForRange(
  dateFrom: string,
  dateTo: string,
  options: { folder?: string; maxResults?: number; query?: string } = {}
): Promise<{
  ok: boolean
  messages: Record<string, unknown>[]
  error?: string
  source?: string
}> {
  return requestOutlookMail({
    dateFrom,
    dateTo,
    folder: options.folder,
    maxResults: options.maxResults,
    query: options.query
  })
}

/** Inbox messages for one local calendar day (Outlook COM / MAPI). */
export async function fetchOutlookMailForDay(
  day: Date,
  options: { folder?: string; maxResults?: number; query?: string } = {}
): Promise<{
  ok: boolean
  messages: Record<string, unknown>[]
  error?: string
  source?: string
}> {
  return requestOutlookMail({
    date: dayKeyLocal(day),
    folder: options.folder,
    maxResults: options.maxResults,
    query: options.query
  })
}

export function formatMailTime(raw: string): string {
  const parsed = parseMeetingTime(raw)
  if (!parsed) return raw || '—'
  return parsed.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export function formatMailReceivedLabel(raw: string): string {
  const parsed = parseMeetingTime(raw)
  if (!parsed) return raw || '—'
  return parsed.toLocaleString('ru-RU', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}
