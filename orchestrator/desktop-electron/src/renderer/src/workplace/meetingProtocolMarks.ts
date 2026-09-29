import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { addDays, mondayOf, type CalendarView } from '../utils/calendar'
import {
  meetingInstanceKey,
  meetingOutlookMarker,
  parseMeetingTime,
  type MeetingEvent
} from '../utils/outlookMeetings'
import { meetingProtocolKey } from './meetingProtocolStore'

export const PROTOCOL_CREATED_EVENT = 'orch-protocol-created'

export type ProtocolMark = {
  number: string
  refKey: string
  /** Picked by the user from 1С: trusted even without the outlook: marker in the comment. */
  manual?: boolean
}

export type OnecProtocolRow = {
  ref_key?: string
  number?: string
  date?: string
  time_start?: string
  time_end?: string
  meeting_topic?: string
  comment?: string
  brief?: string
}

const STORAGE_PREFIX = 'orch-meeting-protocol-doc-v1:'

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${(userId || '').trim() || 'default'}`
}

function readStored(userId: string): Record<string, ProtocolMark> {
  try {
    const raw = localStorage.getItem(storageKey(userId))
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, ProtocolMark>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function rememberProtocolDocument(
  userId: string,
  meeting: MeetingEvent,
  mark: ProtocolMark
): void {
  const key = meetingInstanceKey(meeting)
  if (!key) return
  const bucket = readStored(userId)
  const previous = bucket[key]
  const manual = mark.manual ?? (previous?.manual && previous.refKey === mark.refKey)
  bucket[key] = { number: mark.number || '', refKey: mark.refKey || '', ...(manual ? { manual: true } : {}) }
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(bucket))
  } catch {
    /* quota */
  }
  window.dispatchEvent(new CustomEvent(PROTOCOL_CREATED_EVENT))
}

function isoDay(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

export function calendarQueryRange(view: CalendarView, anchor: Date): { from: string; to: string } {
  if (view === 'day') {
    const day = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
    return { from: isoDay(day), to: isoDay(day) }
  }
  if (view === 'week') {
    const start = mondayOf(anchor)
    return { from: isoDay(start), to: isoDay(addDays(start, 6)) }
  }
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)
  return { from: isoDay(addDays(first, -7)), to: isoDay(addDays(last, 7)) }
}

function protocolMeetingDay(row: OnecProtocolRow): string {
  const fromDate = String(row.date || '').trim().slice(0, 10)
  if (fromDate) return fromDate
  const comment = String(row.comment || '')
  const match = comment.match(/outlook:[^\s|]+\|(\d{4}-\d{2}-\d{2})/)
  return match?.[1] || ''
}

/** Outlook meeting ↔ Document_ТД_Протокол by outlook marker (id + day) or legacy id + same day as protocol. */
export function protocolMatchesMeeting(meeting: MeetingEvent, row: OnecProtocolRow): boolean {
  const id = (meeting.id || '').trim()
  const comment = String(row.comment || '')
  if (!id || !comment.includes('outlook:')) return false
  const marker = meetingOutlookMarker(meeting)
  if (marker && comment.includes(marker)) return true
  const legacy = `outlook:${id}`
  if (!comment.includes(legacy)) return false
  const meetingDay = parseMeetingTime(meeting.start)
  const protocolDay = protocolMeetingDay(row)
  if (!protocolDay || !meetingDay) return false
  return isoDay(meetingDay) === protocolDay
}

function storedMarkForMeeting(
  meeting: MeetingEvent,
  stored: Record<string, ProtocolMark>
): ProtocolMark | undefined {
  const key = meetingInstanceKey(meeting)
  return stored[key] || stored[meetingProtocolKey(meeting)] || stored[(meeting.id || '').trim()]
}

function markFitsMeeting(
  meeting: MeetingEvent,
  mark: ProtocolMark | undefined,
  protocols: OnecProtocolRow[]
): boolean {
  if (!mark?.refKey) return Boolean(mark?.number)
  if (mark.manual) return true
  const row = protocols.find((item) => String(item.ref_key || '').trim() === mark.refKey)
  if (!row) return true
  const comment = String(row.comment || '')
  if (!comment.includes('outlook:')) return false
  return protocolMatchesMeeting(meeting, row)
}

export function marksForMeetings(
  meetings: MeetingEvent[],
  protocols: OnecProtocolRow[],
  stored: Record<string, ProtocolMark>
): Map<string, ProtocolMark> {
  const marks = new Map<string, ProtocolMark>()
  const usedRefs = new Set<string>()
  for (const meeting of meetings) {
    const instanceKey = meetingInstanceKey(meeting)
    const local = storedMarkForMeeting(meeting, stored)
    if (local?.refKey && markFitsMeeting(meeting, local, protocols)) {
      marks.set(instanceKey, local)
      usedRefs.add(local.refKey)
    }
  }
  for (const meeting of meetings) {
    const instanceKey = meetingInstanceKey(meeting)
    if (marks.has(instanceKey)) continue
    const hit = protocols.find((row) => {
      const ref = String(row.ref_key || '').trim()
      return Boolean(ref) && !usedRefs.has(ref) && protocolMatchesMeeting(meeting, row)
    })
    if (!hit) {
      const local = storedMarkForMeeting(meeting, stored)
      if (local?.number && !local.refKey && markFitsMeeting(meeting, local, protocols)) {
        marks.set(instanceKey, local)
      }
      continue
    }
    const refKey = String(hit.ref_key || '').trim()
    usedRefs.add(refKey)
    const local = storedMarkForMeeting(meeting, stored)
    marks.set(instanceKey, {
      number: String(hit.number || '').trim() || local?.number || '',
      refKey
    })
  }
  return marks
}

export function useProtocolMarks(
  userId: string,
  meetings: MeetingEvent[],
  view: CalendarView,
  anchor: Date
): Map<string, ProtocolMark> {
  const range = calendarQueryRange(view, anchor)
  const [protocols, setProtocols] = useState<OnecProtocolRow[]>([])
  const [stored, setStored] = useState<Record<string, ProtocolMark>>(() => readStored(userId))
  const [tick, setTick] = useState(0)

  useEffect(() => {
    setStored(readStored(userId))
  }, [userId, tick])

  useEffect(() => {
    const refresh = (): void => setTick((value) => value + 1)
    window.addEventListener(PROTOCOL_CREATED_EVENT, refresh)
    return () => window.removeEventListener(PROTOCOL_CREATED_EVENT, refresh)
  }, [])

  useEffect(() => {
    let cancelled = false
    void api
      .invokeServerTool(
        'onec.meeting_protocols',
        {
          meeting_kind: 'any',
          date_from: range.from,
          date_to: range.to,
          review_only: false,
          include_closed: true,
          max_results: 200
        },
        60_000
      )
      .then((res) => {
        if (cancelled || !res.ok || !res.result || typeof res.result !== 'object') return
        const rows = (res.result as { protocols?: OnecProtocolRow[] }).protocols
        setProtocols(Array.isArray(rows) ? rows : [])
      })
    return () => {
      cancelled = true
    }
  }, [range.from, range.to, tick])

  return useMemo(
    () => marksForMeetings(meetings, protocols, stored),
    [meetings, protocols, stored]
  )
}
