import { addDays, mondayOf, sameDay, type CalendarView } from './calendar'

export function isOutlookFolderOwner(value: string | undefined): boolean {
  const text = String(value || '').trim().toLowerCase()
  return !text || text === 'календарь' || text === 'calendar' || text === 'календари' || text === 'calendars'
}

export function meetingFormatHint(location: string): string {
  const loc = (location || '').trim()
  if (!loc) return 'Формат не указан'
  const lower = loc.toLowerCase()
  if (
    lower.includes('teams') ||
    lower.includes('zoom') ||
    lower.includes('meet') ||
    lower.includes('онлайн') ||
    lower.includes('http')
  ) {
    return 'Онлайн'
  }
  return 'Очно / переговорная'
}

export function formatMeetingStamp(value: string): string {
  const parsed = parseMeetingTime(value)
  if (!parsed) return (value || '').trim() || '—'
  return parsed.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}

/** A meeting read from the user's Outlook calendar (normalized for the UI). */
export interface MeetingEvent {
  id: string
  subject: string
  start: string
  end: string
  location: string
  organizer: string
  attendees: string
  owner: string
  ownCalendar?: boolean
}

interface OutlookMeetingRaw {
  entry_id?: string
  subject?: string
  start?: string
  end?: string
  location?: string
  calendar_owner?: string
  own_calendar?: boolean
  organizer?: string
  required_attendees?: string
  optional_attendees?: string
}

const CACHE_KEY = 'orchOutlookMeetings:v6'
const REQUEST_TIMEOUT_MS = 180_000
const inflight = new Map<
  string,
  Promise<{ ok: boolean; meetings: MeetingEvent[]; error?: string; cached: boolean }>
>()

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function dayKey(day: Date): string {
  return `${day.getFullYear()}-${pad2(day.getMonth() + 1)}-${pad2(day.getDate())}`
}

/**
 * Parse an Outlook COM datetime string into a local Date.
 *
 * COM / pywintypes often stringify a *local* ReceivedTime as
 * "2026-09-03 14:00:00+00:00". `new Date` then treats +00:00 as UTC and the
 * tile shows a shifted clock. Read the wall-clock and ignore that fake offset.
 */
export function parseMeetingTime(raw: string): Date | null {
  const value = (raw || '').trim()
  if (!value) return null
  const com = value.match(
    /^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]00:00)?$/
  )
  if (com) {
    const stamp = new Date(
      Number(com[1]),
      Number(com[2]) - 1,
      Number(com[3]),
      Number(com[4]),
      Number(com[5]),
      Number(com[6] || 0)
    )
    if (!Number.isNaN(stamp.getTime())) return stamp
  }
  const direct = new Date(value)
  if (!Number.isNaN(direct.getTime())) return direct
  const iso = value.replace(' ', 'T')
  const parsed = new Date(iso)
  if (!Number.isNaN(parsed.getTime())) return parsed
  const ru = value.match(
    /^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2}))?)?/
  )
  if (ru) {
    const stamp = new Date(
      Number(ru[3]),
      Number(ru[2]) - 1,
      Number(ru[1]),
      Number(ru[4] || 0),
      Number(ru[5] || 0),
      Number(ru[6] || 0)
    )
    if (!Number.isNaN(stamp.getTime())) return stamp
  }
  return null
}

/** Keep meetings that belong to the logged-in system user (ФИО из 1С). */
export function meetingInvolvesPerson(meeting: MeetingEvent, person: string): boolean {
  if (meeting.ownCalendar || isOutlookFolderOwner(meeting.owner)) return true
  const name = (person || '').trim()
  if (!name) return true
  const hay = [meeting.organizer, meeting.attendees, meeting.subject, meeting.owner]
    .join(' ')
    .toLocaleLowerCase('ru')
  const parts = name.replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  const last = (parts[0] || '').toLocaleLowerCase('ru')
  if (last.length >= 4 && !hay.includes(last)) return false
  if (parts.length > 1) {
    const first = parts[1].toLocaleLowerCase('ru')
    if (hay.includes(first)) return true
    if (last && hay.includes(`${last} ${first[0]}`)) return true
    if (first.length >= 4 && hay.includes(first.slice(0, 4))) return true
    return hay.includes(last)
  }
  return last ? hay.includes(last) : false
}

function meetingDedupeKey(meeting: MeetingEvent): string {
  const id = (meeting.id || '').trim()
  const start = (meeting.start || '').trim()
  if (id) return `${id}\0${start}`
  return `${start}\0${(meeting.subject || '').trim()}`
}

/** Outlook COM may return the same appointment twice (shared calendars / merged folders). */
export function dedupeMeetingEvents(meetings: MeetingEvent[]): MeetingEvent[] {
  const seen = new Set<string>()
  const out: MeetingEvent[] = []
  for (const meeting of meetings) {
    const key = meetingDedupeKey(meeting)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(meeting)
  }
  return out
}

function normalizeMeeting(raw: OutlookMeetingRaw, index: number): MeetingEvent {
  const attendees = [raw.required_attendees, raw.optional_attendees]
    .map((item) => (item || '').trim())
    .filter(Boolean)
    .join('; ')
  return {
    id: (raw.entry_id || '').trim() || `meeting-${index}`,
    subject: (raw.subject || '').trim() || 'Совещание',
    start: (raw.start || '').trim(),
    end: (raw.end || '').trim(),
    location: (raw.location || '').trim(),
    organizer: (raw.organizer || '').trim(),
    attendees,
    owner: (raw.calendar_owner || '').trim(),
    ownCalendar: Boolean(raw.own_calendar) || isOutlookFolderOwner(raw.calendar_owner)
  }
}

/** The date window (local) that a given calendar view/anchor needs to render. */
export function meetingWindow(view: CalendarView, anchor: Date): { from: Date; to: Date } {
  if (view === 'day') {
    const from = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
    return { from, to: addDays(from, 1) }
  }
  if (view === 'month') {
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    const from = mondayOf(first)
    return { from, to: addDays(from, 42) }
  }
  const from = mondayOf(anchor)
  return { from, to: addDays(from, 7) }
}

interface MeetingCache {
  day: string
  from: string
  to: string
  owner: string
  meetings: MeetingEvent[]
}

function readCache(): MeetingCache | null {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as MeetingCache
    if (!parsed || !Array.isArray(parsed.meetings)) return null
    return parsed
  } catch {
    return null
  }
}

function writeCache(cache: MeetingCache): void {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(cache))
  } catch {
    /* ignore quota / serialization issues */
  }
}

/** Low-level: ask the local Outlook (via the agent sidecar) for meetings. */
function requestOutlookMeetings(range: {
  dateFrom: string
  dateTo: string
  people?: string[]
  forUser?: string
  allVisible?: boolean
}): Promise<{ ok: boolean; meetings: MeetingEvent[]; error?: string }> {
  return new Promise((resolve) => {
    const requestId = `cal-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    let settled = false
    const finish = (result: { ok: boolean; meetings: MeetingEvent[]; error?: string }): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      unsubscribe()
      resolve(result)
    }
    const timer = setTimeout(
      () => finish({ ok: false, meetings: [], error: 'Outlook не ответил вовремя' }),
      REQUEST_TIMEOUT_MS
    )
    const unsubscribe = window.agent.onEvent((payload) => {
      if (String(payload.type || '') !== 'calendar_result') return
      if (String(payload.requestId || '') !== requestId) return
      if (payload.ok) {
        const raw = Array.isArray(payload.events) ? (payload.events as OutlookMeetingRaw[]) : []
        const meetings = dedupeMeetingEvents(
          raw
            .map((item, index) => normalizeMeeting(item, index))
            .filter((item) => meetingInvolvesPerson(item, range.forUser || ''))
        )
        finish({
          ok: true,
          meetings
        })
      } else {
        finish({
          ok: false,
          meetings: [],
          error: String(payload.error || 'Не удалось прочитать календарь Outlook')
        })
      }
    })
    void window.agent.readCalendar({
      requestId,
      dateFrom: range.dateFrom,
      dateTo: range.dateTo,
      people: range.people,
      forUser: range.forUser,
      allVisible: range.allVisible
    })
  })
}

export function countMeetingsOnDay(meetings: MeetingEvent[], anchor = new Date()): number {
  return meetings.filter((item) => meetingOverlapsLocalDay(item, anchor)).length
}

/** Meeting starts, ends or spans the local calendar day. */
export function meetingOverlapsLocalDay(meeting: MeetingEvent, day: Date): boolean {
  const start = parseMeetingTime(meeting.start)
  if (!start) return false
  if (sameDay(start, day)) return true
  const end = parseMeetingTime(meeting.end)
  if (end && sameDay(end, day)) return true
  if (!end || end <= start) return false
  const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate())
  const dayEnd = addDays(dayStart, 1)
  return start < dayEnd && end > dayStart
}

/**
 * «Предстоящие события» = те же совещания, что колонка выбранного дня
 * на вкладке «Совещания» и плитка «События дня». Не подмешивать остаток недели.
 */
export function selectUpcomingEventMeetings(
  meetings: MeetingEvent[],
  periodDay: Date
): MeetingEvent[] {
  return meetings
    .filter((meeting) => meetingOverlapsLocalDay(meeting, periodDay))
    .sort((left, right) => left.start.localeCompare(right.start))
}

function meetingsFromCache(
  cache: MeetingCache,
  owner: string,
  allVisible: boolean
): MeetingEvent[] {
  const list = dedupeMeetingEvents(cache.meetings)
  if (!allVisible) return list
  return list.filter((item) => meetingInvolvesPerson(item, owner))
}

function cacheCoversWindow(cache: MeetingCache, fromKey: string, toKey: string): boolean {
  if (cache.from > fromKey || cache.to < toKey) return false
  return cache.meetings.length > 0 || (cache.from === fromKey && cache.to === toKey)
}

export async function ensureOutlookMeetings(
  view: CalendarView,
  anchor: Date,
  options: { force?: boolean; owner?: string; allVisible?: boolean } = {}
): Promise<{ ok: boolean; meetings: MeetingEvent[]; error?: string; cached: boolean }> {
  const win = meetingWindow(view, anchor)
  const fromKey = dayKey(win.from)
  const toKey = dayKey(addDays(win.to, -1))
  const today = dayKey(new Date())
  const owner = (options.owner || '').trim()
  const allVisible = Boolean(options.allVisible)
  const inflightKey = `${fromKey}|${toKey}|${owner}|${Number(allVisible)}`

  if (!options.force) {
    const cache = readCache()
    if (cache && cache.day === today && cache.owner === owner && cacheCoversWindow(cache, fromKey, toKey)) {
      return {
        ok: true,
        meetings: meetingsFromCache(cache, owner, allVisible),
        error: '',
        cached: true
      }
    }
    const pending = inflight.get(inflightKey)
    if (pending) return pending
  }

  const run = (async () => {
    const result = await requestOutlookMeetings({
      dateFrom: fromKey,
      dateTo: toKey,
      forUser: allVisible ? owner : undefined,
      allVisible
    })
    if (result.ok) {
      const prev = readCache()
      if (
        result.meetings.length === 0 &&
        prev &&
        prev.day === today &&
        prev.owner === owner &&
        prev.meetings.length > 0 &&
        cacheCoversWindow(prev, fromKey, toKey)
      ) {
        return {
          ok: true,
          meetings: meetingsFromCache(prev, owner, allVisible),
          error: '',
          cached: true
        }
      }
      writeCache({ day: today, from: fromKey, to: toKey, owner, meetings: result.meetings })
    }
    return { ...result, cached: false }
  })()

  if (!options.force) {
    inflight.set(inflightKey, run)
    void run.finally(() => {
      if (inflight.get(inflightKey) === run) inflight.delete(inflightKey)
    })
  }
  return run
}
