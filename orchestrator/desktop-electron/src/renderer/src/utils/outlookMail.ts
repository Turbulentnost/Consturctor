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

const MAIL_FETCH_MAX_DAYS = 90
const MAIL_CACHE_KEY = 'orchOutlookMail:v1'

interface OutlookMailCache {
  day: string
  mailbox: string
  dateFrom: string
  dateTo: string
  folder: string
  messages: Record<string, unknown>[]
}

function readMailCache(): OutlookMailCache | null {
  try {
    const raw = window.localStorage.getItem(MAIL_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as OutlookMailCache
    if (!parsed || !Array.isArray(parsed.messages)) return null
    return parsed
  } catch {
    return null
  }
}

function writeMailCache(cache: OutlookMailCache): void {
  try {
    window.localStorage.setItem(MAIL_CACHE_KEY, JSON.stringify(cache))
  } catch {
    /* ignore */
  }
}

/**
 * Письма за период — не чаще одного COM-запроса в день на тот же диапазон
 * (как ensureOutlookMeetings для календаря).
 */
export async function ensureOutlookMailRange(
  mailbox: string,
  dateFrom: string,
  dateTo: string,
  options: { force?: boolean; folder?: string; maxResults?: number } = {}
): Promise<{
  ok: boolean
  messages: Record<string, unknown>[]
  error?: string
  cached: boolean
}> {
  const fromKey = (dateFrom || '').trim()
  const toKey = (dateTo || '').trim()
  const today = dayKeyLocal(new Date())
  const folder = options.folder || 'All'
  const box = (mailbox || '').trim().toLowerCase()

  if (!options.force && fromKey && toKey) {
    const cache = readMailCache()
    if (
      cache &&
      cache.day === today &&
      cache.mailbox === box &&
      cache.dateFrom === fromKey &&
      cache.dateTo === toKey &&
      cache.folder === folder
    ) {
      return { ok: true, messages: cache.messages, cached: true }
    }
  }

  const result = await requestOutlookMail({
    dateFrom: fromKey,
    dateTo: toKey,
    folder,
    maxResults: options.maxResults ?? 120
  })
  if (result.ok && fromKey && toKey) {
    writeMailCache({
      day: today,
      mailbox: box,
      dateFrom: fromKey,
      dateTo: toKey,
      folder,
      messages: result.messages
    })
  }
  return { ...result, cached: false }
}

function parseDayKey(key: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key.trim())
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(d.getTime()) ? null : d
}

/** Диапазон для outlook.search_mail / IMAP: из UI-периода, не больше MAIL_FETCH_MAX_DAYS. */
export function resolveOutlookMailFetchRange(
  from: string,
  to: string,
  fallback = outlookMailWeekRange()
): { dateFrom: string; dateTo: string } {
  const startKey = (from || '').trim()
  const endKey = (to || '').trim()
  if (!startKey || !endKey) return fallback
  const lo = startKey <= endKey ? startKey : endKey
  const hi = startKey <= endKey ? endKey : startKey
  const end = parseDayKey(hi)
  const start = parseDayKey(lo)
  if (!end || !start) return fallback
  const spanDays = Math.floor((end.getTime() - start.getTime()) / 86400000) + 1
  if (spanDays <= MAIL_FETCH_MAX_DAYS) {
    return { dateFrom: lo, dateTo: hi }
  }
  const clampStart = new Date(end)
  clampStart.setDate(clampStart.getDate() - (MAIL_FETCH_MAX_DAYS - 1))
  return { dateFrom: dayKeyLocal(clampStart), dateTo: hi }
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

/** Уже отформатировано как dd.mm.yy hh:mm */
const MAIL_TIME_DISPLAY_RE = /^(\d{2})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2})$/
/** Legacy: hh:mm dd.mm.yy */
const MAIL_TIME_DISPLAY_LEGACY_RE = /^(\d{2}):(\d{2}) (\d{2})\.(\d{2})\.(\d{2})$/

function formatMailTimeFromDate(parsed: Date): string {
  const h = String(parsed.getHours()).padStart(2, '0')
  const m = String(parsed.getMinutes()).padStart(2, '0')
  const d = String(parsed.getDate()).padStart(2, '0')
  const mo = String(parsed.getMonth() + 1).padStart(2, '0')
  const y = String(parsed.getFullYear() % 100).padStart(2, '0')
  return `${d}.${mo}.${y} ${h}:${m}`
}

/** Отображение даты/времени письма: dd.mm.yy hh:mm (локальные часы). */
export function formatMailTime(raw: string): string {
  const value = (raw || '').trim()
  if (!value) return '—'
  if (MAIL_TIME_DISPLAY_RE.test(value)) return value
  const legacy = MAIL_TIME_DISPLAY_LEGACY_RE.exec(value)
  if (legacy) {
    return `${legacy[3]}.${legacy[4]}.${legacy[5]} ${legacy[1]}:${legacy[2]}`
  }
  const parsed = parseMeetingTime(value)
  if (!parsed) return value
  return formatMailTimeFromDate(parsed)
}

/** Для параметра формы 1С (ДатаПисьма). */
export function formatMailTimeRawForOneC(raw: string): string {
  const label = formatMailTime(raw)
  return label === '—' ? '' : label
}

export function formatMailReceivedLabel(raw: string): string {
  return formatMailTime(raw)
}
