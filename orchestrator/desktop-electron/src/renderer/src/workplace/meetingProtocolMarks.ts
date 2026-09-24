import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { addDays, mondayOf, type CalendarView } from '../utils/calendar'
import { parseMeetingTime, type MeetingEvent } from '../utils/outlookMeetings'

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

const STOP_WORDS = new Set([
  'совещание',
  'совещания',
  'еженедельное',
  'еженедельный',
  'протокол',
  'отчетное',
  'отчётное',
  'проект',
  'служба',
  'развития',
  'группа',
  'рабочая'
])

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

function dayOf(raw: string): string {
  const parsed = parseMeetingTime(raw)
  if (parsed) return isoDay(parsed)
  return (raw || '').slice(0, 10)
}

function clockMinutes(hhmm: string): number | null {
  const match = /^(\d{1,2}):(\d{2})/.exec((hhmm || '').trim())
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

function meetingMinutes(raw: string): number | null {
  const parsed = parseMeetingTime(raw)
  if (!parsed) return null
  return parsed.getHours() * 60 + parsed.getMinutes()
}

function words(text: string): Set<string> {
  const norm = text.toLowerCase().replace(/ё/g, 'е')
  return new Set(
    norm.split(/[^a-zа-я0-9]+/i).filter((word) => word.length >= 5 && !STOP_WORDS.has(word))
  )
}

function sharedWords(left: Set<string>, right: Set<string>): number {
  let count = 0
  for (const word of left) {
    if (right.has(word)) count += 1
  }
  return count
}

/** Outlook meeting ↔ Document_ТД_Протокол: explicit outlook id, or same day plus topic/time. */
export function protocolMatchesMeeting(meeting: MeetingEvent, row: OnecProtocolRow): boolean {
  const comment = String(row.comment || '')
  if (meeting.id && comment.includes(`outlook:${meeting.id}`)) return true
  const meetingDay = dayOf(meeting.start)
  const protocolDay = String(row.date || '').slice(0, 10)
  if (!meetingDay || meetingDay !== protocolDay) return false
  const shared = sharedWords(
    words(`${meeting.subject} ${meeting.location}`),
    words(`${row.meeting_topic || ''} ${row.brief || ''} ${comment}`)
  )
  const startMin = meetingMinutes(meeting.start)
  const protoMin = clockMinutes(String(row.time_start || ''))
  const timeClose = startMin != null && protoMin != null && Math.abs(startMin - protoMin) <= 20
  if (timeClose && shared >= 1) return true
  return shared >= 2
}

export function marksForMeetings(
  meetings: MeetingEvent[],
  protocols: OnecProtocolRow[],
  stored: Record<string, ProtocolMark>
): Map<string, ProtocolMark> {
  const marks = new Map<string, ProtocolMark>()
  for (const meeting of meetings) {
    const local = stored[meeting.id]
    if (local && local.refKey) {
      marks.set(meeting.id, local)
      continue
    }
    const hit = protocols.find((row) => protocolMatchesMeeting(meeting, row))
    if (!hit) {
      // local mark without Ref_Key (older record): still shows the number, edit stays disabled
      if (local && local.number) marks.set(meeting.id, local)
      continue
    }
    marks.set(meeting.id, {
      number: String(hit.number || '').trim() || local?.number || '',
      refKey: String(hit.ref_key || '').trim()
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
