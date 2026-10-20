import { meetingInstanceKey, parseMeetingTime, type MeetingEvent } from './outlookMeetings'

/** Очень короткая или «нулевая» встреча всё равно должна быть видна в сетке. */
const MIN_MINUTES = 15
const DAY_MINUTES = 24 * 60

export type MeetingSpan = {
  meeting: MeetingEvent
  /** Минуты от начала суток. */
  from: number
  to: number
  /** Позиция календаря в списке приоритетов: меньше — показывается поверх. */
  priority: number
}

export type ConflictSegment = {
  from: number
  to: number
  /** Пересекающиеся совещания, первое — то, что остаётся видимым. */
  meetings: MeetingEvent[]
}

export function meetingMinutes(meeting: MeetingEvent): { from: number; to: number } | null {
  const start = parseMeetingTime(meeting.start)
  if (!start) return null
  const end = parseMeetingTime(meeting.end)
  const from = start.getHours() * 60 + start.getMinutes()
  const length = end ? Math.round((end.getTime() - start.getTime()) / 60_000) : 60
  return { from, to: Math.min(DAY_MINUTES, from + Math.max(MIN_MINUTES, length)) }
}

export function meetingSpan(meeting: MeetingEvent, priority = 0): MeetingSpan | null {
  const minutes = meetingMinutes(meeting)
  if (!minutes) return null
  return { meeting, priority, ...minutes }
}

function sameSet(left: MeetingEvent[], right: MeetingEvent[]): boolean {
  if (left.length !== right.length) return false
  return left.every((item, index) => meetingInstanceKey(item) === meetingInstanceKey(right[index]))
}

/**
 * Участки, где совещания накладываются друг на друга. Режем сутки по границам всех
 * интервалов и оставляем те куски, которые накрыты больше одного раза; соседние
 * куски с тем же составом склеиваем, чтобы штриховка была одним блоком.
 */
export function conflictSegments(spans: MeetingSpan[]): ConflictSegment[] {
  if (spans.length < 2) return []
  const edges = [...new Set(spans.flatMap((span) => [span.from, span.to]))].sort((a, b) => a - b)
  const out: ConflictSegment[] = []
  for (let index = 0; index + 1 < edges.length; index += 1) {
    const from = edges[index]
    const to = edges[index + 1]
    const inside = spans.filter((span) => span.from < to && span.to > from)
    if (inside.length < 2) continue
    const meetings = [...inside]
      .sort((left, right) => left.priority - right.priority || left.from - right.from)
      .map((span) => span.meeting)
    const last = out[out.length - 1]
    if (last && last.to === from && sameSet(last.meetings, meetings)) {
      last.to = to
      continue
    }
    out.push({ from, to, meetings })
  }
  return out
}

/**
 * Участки самого блока, которые накрыты другими совещаниями. Штрихуем именно их,
 * а не всю колонку: иначе штриховка легла бы поверх заголовка верхнего блока.
 */
export function spanConflictParts(span: MeetingSpan, segments: ConflictSegment[]): ConflictSegment[] {
  const key = meetingInstanceKey(span.meeting)
  const parts: ConflictSegment[] = []
  for (const segment of segments) {
    if (!segment.meetings.some((meeting) => meetingInstanceKey(meeting) === key)) continue
    const from = Math.max(segment.from, span.from)
    const to = Math.min(segment.to, span.to)
    if (to > from) parts.push({ from, to, meetings: segment.meetings })
  }
  return parts
}

/** Верхний блок пересечения: никто из пересекающихся календарей не стоит выше по приоритету. */
export function isTopSpan(span: MeetingSpan, spans: MeetingSpan[]): boolean {
  const key = meetingInstanceKey(span.meeting)
  return !spans.some(
    (other) =>
      meetingInstanceKey(other.meeting) !== key &&
      other.priority < span.priority &&
      other.from < span.to &&
      span.from < other.to
  )
}

/**
 * Ключи встреч, которые накладываются на другую встречу в тот же день, — ровно те,
 * что сетка рисует штриховкой. Фильтр «Без конфликтов» обязан считать их так же,
 * иначе он оставляет заштрихованные блоки на месте.
 */
export function overlappingMeetingKeys(meetings: MeetingEvent[]): Set<string> {
  const byDay = new Map<number, MeetingSpan[]>()
  for (const meeting of meetings) {
    const start = parseMeetingTime(meeting.start)
    const span = meetingSpan(meeting)
    if (!start || !span) continue
    const day = new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime()
    const list = byDay.get(day) || []
    list.push(span)
    byDay.set(day, list)
  }
  const keys = new Set<string>()
  for (const spans of byDay.values()) {
    for (let left = 0; left < spans.length; left += 1) {
      for (let right = left + 1; right < spans.length; right += 1) {
        if (spans[left].from < spans[right].to && spans[right].from < spans[left].to) {
          keys.add(meetingInstanceKey(spans[left].meeting))
          keys.add(meetingInstanceKey(spans[right].meeting))
        }
      }
    }
  }
  return keys
}

export function minutesLabel(minutes: number): string {
  const hours = Math.floor(minutes / 60) % 24
  const rest = minutes % 60
  return `${String(hours).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}
