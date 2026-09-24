import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { addDays, mondayOf, type CalendarView } from '../utils/calendar'
import type { MeetingEvent } from '../utils/outlookMeetings'

export const PROTOCOL_CREATED_EVENT = 'orch-protocol-created'

export type ProtocolMark = {
  number: string
  refKey: string
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

export function rememberProtocolDocument(userId: string, meetingId: string, mark: ProtocolMark): void {
  const id = meetingId.trim()
  if (!id) return
  const bucket = readStored(userId)
  bucket[id] = { number: mark.number || '', refKey: mark.refKey || '' }
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

/** Outlook meeting ↔ Document_ТД_Протокол only by the outlook id written into the comment. */
export function protocolMatchesMeeting(meeting: MeetingEvent, row: OnecProtocolRow): boolean {
  const id = (meeting.id || '').trim()
  if (!id) return false
  return String(row.comment || '').includes(`outlook:${id}`)
}

function markFitsMeeting(
  meeting: MeetingEvent,
  mark: ProtocolMark | undefined,
  protocols: OnecProtocolRow[]
): boolean {
  if (!mark?.refKey) return Boolean(mark?.number)
  const row = protocols.find((item) => String(item.ref_key || '').trim() === mark.refKey)
  if (!row) return true
  const comment = String(row.comment || '')
  if (!comment.includes('outlook:')) return true
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
    const local = stored[meeting.id]
    if (local?.refKey && markFitsMeeting(meeting, local, protocols)) {
      marks.set(meeting.id, local)
      usedRefs.add(local.refKey)
    }
  }
  for (const meeting of meetings) {
    if (marks.has(meeting.id)) continue
    const hit = protocols.find((row) => {
      const ref = String(row.ref_key || '').trim()
      return Boolean(ref) && !usedRefs.has(ref) && protocolMatchesMeeting(meeting, row)
    })
    if (!hit) {
      const local = stored[meeting.id]
      if (local?.number && !local.refKey) marks.set(meeting.id, local)
      continue
    }
    const refKey = String(hit.ref_key || '').trim()
    usedRefs.add(refKey)
    marks.set(meeting.id, {
      number: String(hit.number || '').trim() || stored[meeting.id]?.number || '',
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
