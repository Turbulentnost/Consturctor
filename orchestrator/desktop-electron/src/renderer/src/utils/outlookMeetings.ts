import { addDays, mondayOf, type CalendarView } from './calendar'

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
}

interface OutlookMeetingRaw {
  entry_id?: string
  subject?: string
  start?: string
  end?: string
  location?: string
  calendar_owner?: string
  organizer?: string
  required_attendees?: string
  optional_attendees?: string
}

const CACHE_KEY = 'orchOutlookMeetings:v4'
const REQUEST_TIMEOUT_MS = 180_000

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function dayKey(day: Date): string {
  return `${day.getFullYear()}-${pad2(day.getMonth() + 1)}-${pad2(day.getDate())}`
}

/**
 * Parse an Outlook COM datetime string into a local Date.
 *
 * COM returns values like "2026-09-03 14:00:00+00:00" (space separator) or a
 * plain "2026-09-03 14:00:00" (local, no offset). `new Date` is picky about the
 * space form, so we normalize it to the ISO "T" form and fall back gracefully.
 */
export function parseMeetingTime(raw: string): Date | null {
  const value = (raw || '').trim()
  if (!value) return null
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
    owner: (raw.calendar_owner || '').trim()
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
        finish({
          ok: true,
          meetings: raw
            .map(normalizeMeeting)
            .filter((item) => meetingInvolvesPerson(item, range.forUser || ''))
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

/**
 * Return the user's meetings for the window a view needs, hitting Outlook at most
 * once per day (the "first launch of the day" fetch) unless `force` is set or the
 * cached window does not cover what is requested. Subsequent same-day reads for a
 * covered window are served from localStorage without touching Outlook COM.
 */
export async function ensureOutlookMeetings(
  view: CalendarView,
  anchor: Date,
  options: { force?: boolean; owner?: string } = {}
): Promise<{ ok: boolean; meetings: MeetingEvent[]; error?: string; cached: boolean }> {
  const win = meetingWindow(view, anchor)
  const fromKey = dayKey(win.from)
  const toKey = dayKey(addDays(win.to, -1))
  const today = dayKey(new Date())
  const owner = (options.owner || '').trim()

  if (!options.force) {
    const cache = readCache()
    if (
      cache &&
      cache.day === today &&
      cache.owner === owner &&
      cache.from <= fromKey &&
      cache.to >= toKey
    ) {
      return {
        ok: true,
        meetings: cache.meetings.filter((item) => meetingInvolvesPerson(item, owner)),
        error: '',
        cached: true
      }
    }
  }

  const result = await requestOutlookMeetings({
    dateFrom: fromKey,
    dateTo: toKey,
    forUser: owner,
    allVisible: true
  })
  if (result.ok) {
    writeCache({ day: today, from: fromKey, to: toKey, owner, meetings: result.meetings })
  }
  return { ...result, cached: false }
}
