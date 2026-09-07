import { useMemo, useState } from 'react'
import type { AgentRunnerEvent } from '../../api/types'
import { DAYS_SHORT, MONTHS_GEN, isoWeekday, parseIso, STATUS_STYLE } from '../../utils/calendar'
import type { FeedItem } from './types'

export interface MiniMeeting {
  title: string
  start: string
  end: string
  mark: string
  reason: string
}

const MARK_ALIAS: Record<string, string> = {
  add: 'recommend_add',
  green: 'recommend_add',
  recommend_add: 'recommend_add',
  cancel: 'recommend_cancel',
  red: 'recommend_cancel',
  recommend_cancel: 'recommend_cancel',
  keep: 'meeting',
  stay: 'meeting',
  meeting: 'meeting'
}

function markKey(raw: string): string {
  const key = (raw || '').trim().toLowerCase().replace(/-/g, '_')
  return MARK_ALIAS[key] || 'meeting'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function normalizeMeetingList(raw: unknown): MiniMeeting[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      title: String(item.title ?? item.subject ?? item.name ?? ''),
      start: String(item.start ?? item.start_at ?? item.at ?? ''),
      end: String(item.end ?? item.end_at ?? ''),
      mark: String(item.mark ?? item.color ?? item.kind ?? 'keep'),
      reason: String(item.reason ?? item.note ?? item.subtitle ?? '')
    }))
    .filter((item) => item.title && item.start)
}

/** Extract meetings from a calendar.show_meetings payload (result or arguments). */
export function meetingsFromResult(result: unknown): MiniMeeting[] {
  const seen = new WeakSet<object>()
  const walk = (value: unknown, depth: number): MiniMeeting[] => {
    if (value == null || depth > 4) return []
    if (Array.isArray(value)) return normalizeMeetingList(value)
    const row = asRecord(value)
    if (!row || seen.has(row)) return []
    seen.add(row)
    for (const key of ['meetings', 'items', 'events']) {
      const found = normalizeMeetingList(row[key])
      if (found.length) return found
    }
    if (row.title && (row.start || row.start_at || row.at)) return normalizeMeetingList([row])
    for (const key of ['result', 'arguments', 'output', 'output_data', 'data']) {
      const found = walk(row[key], depth + 1)
      if (found.length) return found
    }
    return []
  }
  return walk(result, 0)
}

export function meetingsFromToolItem(item: { result?: unknown; arguments?: unknown }): MiniMeeting[] {
  const fromResult = meetingsFromResult(item.result)
  if (fromResult.length) return fromResult
  return meetingsFromResult(item.arguments)
}

export function meetingsFromFeed(items: FeedItem[]): MiniMeeting[] {
  let found: MiniMeeting[] = []
  for (const item of items) {
    if (item.kind !== 'tool' || item.tool !== 'calendar.show_meetings') continue
    const parsed = meetingsFromToolItem(item)
    if (parsed.length) found = parsed
  }
  return found
}

export function meetingsFromEvents(events: AgentRunnerEvent[]): MiniMeeting[] {
  let found: MiniMeeting[] = []
  for (const event of events) {
    if (String(event.tool || '') === 'calendar.show_meetings') {
      const parsed = meetingsFromToolItem({ result: event.result, arguments: event.arguments })
      if (parsed.length) found = parsed
      continue
    }
    const nested = meetingsFromResult(event.result).concat(meetingsFromResult(event.arguments))
    if (nested.length > 1) found = nested
  }
  return found
}

export function meetingsForHistoryRun(
  events: AgentRunnerEvent[],
  stored?: Array<{ title: string; start: string; end?: string; mark?: string; reason?: string }> | null
): MiniMeeting[] {
  const fromEvents = meetingsFromEvents(events)
  if (fromEvents.length) return fromEvents
  return normalizeMeetingList(stored || [])
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function hhmm(stamp: Date): string {
  return `${pad2(stamp.getHours())}:${pad2(stamp.getMinutes())}`
}

function timeRange(start: string, end: string): string {
  const a = parseIso(start)
  if (!a) return ''
  const b = parseIso(end)
  return b ? `${hhmm(a)}–${hhmm(b)}` : hhmm(a)
}

function dayLabel(stamp: Date): string {
  return `${DAYS_SHORT[isoWeekday(stamp)]}, ${stamp.getDate()} ${MONTHS_GEN[stamp.getMonth() + 1]}`
}

interface NormMeeting extends MiniMeeting {
  key: string
  stamp: Date | null
  endStamp: Date | null
}

interface DayColumn {
  id: string
  label: string
  order: number
  items: NormMeeting[]
}

function normalize(meetings: MiniMeeting[]): { columns: DayColumn[]; loose: NormMeeting[] } {
  const map = new Map<string, DayColumn>()
  const loose: NormMeeting[] = []
  for (const raw of meetings) {
    const stamp = parseIso(raw.start)
    const endStamp = parseIso(raw.end)
    const item: NormMeeting = { ...raw, key: markKey(raw.mark), stamp, endStamp }
    if (!stamp) {
      loose.push(item)
      continue
    }
    const id = `${stamp.getFullYear()}-${pad2(stamp.getMonth() + 1)}-${pad2(stamp.getDate())}`
    let column = map.get(id)
    if (!column) {
      column = { id, label: dayLabel(stamp), order: stamp.getTime(), items: [] }
      map.set(id, column)
    }
    column.items.push(item)
  }
  const columns = Array.from(map.values()).sort((l, r) => l.order - r.order)
  for (const column of columns) {
    column.items.sort((l, r) => (l.stamp?.getTime() ?? 0) - (r.stamp?.getTime() ?? 0))
  }
  return { columns, loose }
}

function minutesOf(stamp: Date): number {
  return stamp.getHours() * 60 + stamp.getMinutes()
}

/** Hour range [start, end] covering all meetings, padded and clamped to a sane window. */
function hourBounds(columns: DayColumn[]): { start: number; end: number } {
  let min = 9 * 60
  let max = 18 * 60
  let seen = false
  for (const column of columns) {
    for (const item of column.items) {
      if (!item.stamp) continue
      const startM = minutesOf(item.stamp)
      const endM = item.endStamp ? minutesOf(item.endStamp) : startM + 60
      min = seen ? Math.min(min, startM) : startM
      max = seen ? Math.max(max, endM) : endM
      seen = true
    }
  }
  const startHour = Math.max(0, Math.floor(min / 60) - (seen ? 0 : 0))
  const endHour = Math.min(24, Math.ceil(max / 60))
  return { start: Math.max(0, startHour), end: Math.max(startHour + 1, endHour) }
}

function Chip({ mark }: { mark: string }): React.JSX.Element {
  const style = STATUS_STYLE[mark] ?? STATUS_STYLE.meeting
  return (
    <span
      className="mini-cal-chip"
      style={{ background: style.bg, borderColor: style.border, color: style.border }}
    >
      {style.label}
    </span>
  )
}

function CalendarGrid({
  columns,
  rowHeight
}: {
  columns: DayColumn[]
  rowHeight: number
}): React.JSX.Element {
  const { start, end } = useMemo(() => hourBounds(columns), [columns])
  const hours: number[] = []
  for (let h = start; h < end; h += 1) hours.push(h)
  const bodyHeight = (end - start) * rowHeight

  return (
    <div
      className="mini-cal-grid"
      style={{ gridTemplateColumns: `48px repeat(${columns.length}, minmax(112px, 1fr))` }}
    >
      <div className="mini-cal-grid-corner" />
      {columns.map((column) => (
        <div key={column.id} className="mini-cal-grid-dayhead">
          {column.label}
        </div>
      ))}

      <div className="mini-cal-grid-axis" style={{ height: bodyHeight }}>
        {hours.map((h) => (
          <div key={h} className="mini-cal-grid-hour" style={{ height: rowHeight }}>
            <span>{pad2(h)}:00</span>
          </div>
        ))}
      </div>

      {columns.map((column) => (
        <div key={column.id} className="mini-cal-grid-col" style={{ height: bodyHeight }}>
          {hours.map((h) => (
            <div key={h} className="mini-cal-grid-cell" style={{ height: rowHeight }} />
          ))}
          {column.items.map((item, index) => {
            if (!item.stamp) return null
            const startM = minutesOf(item.stamp)
            const endM = item.endStamp ? minutesOf(item.endStamp) : startM + 60
            const top = ((startM - start * 60) / 60) * rowHeight
            const height = Math.max(22, ((Math.max(endM, startM + 20) - startM) / 60) * rowHeight - 2)
            const style = STATUS_STYLE[item.key] ?? STATUS_STYLE.meeting
            return (
              <div
                key={`${item.title}-${index}`}
                className="mini-cal-event"
                style={{
                  top,
                  height,
                  background: style.bg,
                  borderColor: style.border
                }}
                title={`${timeRange(item.start, item.end)} · ${item.title}${
                  item.reason ? `\n${item.reason}` : ''
                }`}
              >
                <span className="mini-cal-event-time">{timeRange(item.start, item.end)}</span>
                <span className="mini-cal-event-title">{item.title}</span>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function LooseList({ items }: { items: NormMeeting[] }): React.JSX.Element {
  return (
    <div className="mini-cal-loose">
      <div className="mini-cal-day-label">Без даты</div>
      {items.map((item, index) => (
        <div key={`${item.title}-${index}`} className="mini-cal-row">
          <span className="mini-cal-time">{timeRange(item.start, item.end) || '—'}</span>
          <span className="mini-cal-body">
            <span className="mini-cal-row-head">
              <span className="mini-cal-title" title={item.title}>
                {item.title}
              </span>
              <Chip mark={item.key} />
            </span>
            {item.reason && <span className="mini-cal-reason">{item.reason}</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

export function MiniCalendar({ meetings }: { meetings: MiniMeeting[] }): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  const { columns, loose } = useMemo(() => normalize(meetings), [meetings])

  const counts = useMemo(() => {
    let add = 0
    let cancel = 0
    let keep = 0
    for (const item of meetings) {
      const key = markKey(item.mark)
      if (key === 'recommend_add') add += 1
      else if (key === 'recommend_cancel') cancel += 1
      else keep += 1
    }
    return { add, cancel, keep }
  }, [meetings])

  if (columns.length === 0 && loose.length === 0) return null

  const summary = [
    counts.add > 0 ? `поставить ${counts.add}` : '',
    counts.cancel > 0 ? `отменить ${counts.cancel}` : '',
    counts.keep > 0 ? `оставить ${counts.keep}` : ''
  ]
    .filter(Boolean)
    .join(' · ')

  const legend = (
    <div className="mini-cal-legend">
      <span style={{ color: STATUS_STYLE.recommend_add.border }}>● Поставить</span>
      <span style={{ color: STATUS_STYLE.recommend_cancel.border }}>● Отменить</span>
      <span style={{ color: STATUS_STYLE.meeting.border }}>● Уже стоит</span>
    </div>
  )

  return (
    <div className="mini-cal">
      <div className="mini-cal-head">
        <div className="mini-cal-headings">
          <span className="mini-cal-name">План совещаний</span>
          {summary && <span className="mini-cal-summary">{summary}</span>}
        </div>
        <button type="button" className="mini-cal-expand" onClick={() => setOpen(true)}>
          Развернуть
        </button>
      </div>
      <div className="mini-cal-scroll">
        {columns.length > 0 && <CalendarGrid columns={columns} rowHeight={30} />}
        {loose.length > 0 && <LooseList items={loose} />}
      </div>
      {legend}

      {open && (
        <div className="modal-overlay" onClick={() => setOpen(false)}>
          <div className="modal-card mini-cal-modal" onClick={(e) => e.stopPropagation()}>
            <div className="mini-cal-modal-head">
              <div className="modal-title">План совещаний</div>
              <button type="button" className="mini-cal-close" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>
            {summary && <div className="mini-cal-modal-summary">{summary}</div>}
            <div className="mini-cal-modal-body">
              {columns.length > 0 && <CalendarGrid columns={columns} rowHeight={52} />}
              {loose.length > 0 && <LooseList items={loose} />}
            </div>
            {legend}
          </div>
        </div>
      )}
    </div>
  )
}
