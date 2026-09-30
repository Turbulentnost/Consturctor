import { useMemo, useRef, useState } from 'react'
import { FileText } from 'lucide-react'
import {
  addDays,
  clip,
  DAYS_SHORT,
  formatPeriod,
  isoWeekday,
  mondayOf,
  sameDay,
  STATUS_STYLE,
  type CalendarView
} from '../../utils/calendar'
import {
  isOutlookFolderOwner,
  meetingInstanceKey,
  parseMeetingTime,
  type MeetingEvent
} from '../../utils/outlookMeetings'

const HEADER = 40
const HOUR_H = 56
const CARD_H = 48
const CARD_GAP = 4
const GUTTER = 52
const COL_MIN = 168

interface MeetingsCalendarProps {
  view: CalendarView
  anchor: Date
  meetings: MeetingEvent[]
  loading: boolean
  error: string
  ownerName?: string
  onView: (view: CalendarView) => void
  onShift: (step: number) => void
  onToday: () => void
  onRefresh: () => void
  selectedId?: string
  onSelectMeeting?: (meeting: MeetingEvent) => void
  showDetailsModal?: boolean
  /** meeting.id → протокол 1С, если для совещания он уже создан. */
  protocolMarks?: ReadonlyMap<string, { number: string }>
}

interface Positioned {
  meeting: MeetingEvent
  start: Date
  end: Date | null
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function timeLabel(date: Date | null): string {
  if (!date) return ''
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

function positioned(meetings: MeetingEvent[]): Positioned[] {
  const rows: Positioned[] = []
  for (const meeting of meetings) {
    const start = parseMeetingTime(meeting.start)
    if (!start) continue
    rows.push({ meeting, start, end: parseMeetingTime(meeting.end) })
  }
  rows.sort((a, b) => a.start.getTime() - b.start.getTime())
  return rows
}

export function MeetingsCalendar(props: MeetingsCalendarProps): React.JSX.Element {
  const { view, anchor, meetings, loading, error, ownerName, showDetailsModal = true } = props
  const [selected, setSelected] = useState<MeetingEvent | null>(null)
  const selectMeeting = (meeting: MeetingEvent): void => {
    props.onSelectMeeting?.(meeting)
    if (showDetailsModal) setSelected(meeting)
  }
  const scrollRef = useRef<HTMLDivElement>(null)

  const items = useMemo(() => positioned(meetings), [meetings])

  const days = useMemo(() => {
    if (view === 'day')
      return [new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())]
    if (view === 'month') return []
    const start = mondayOf(anchor)
    return Array.from({ length: 7 }, (_, i) => addDays(start, i))
  }, [view, anchor])

  return (
    <div className="run-calendar meetings-calendar">
      <div className="cal-head">
        <div className="cal-heading">
          <div className="cal-title">Календарь совещаний</div>
          <div className="cal-period">{formatPeriod(view, anchor)}</div>
        </div>
        <div className="cal-controls">
          <button className="cal-btn cal-btn-arrow" onClick={() => props.onShift(-1)}>
            &lt;
          </button>
          <button className="cal-btn" onClick={props.onToday}>
            Сегодня
          </button>
          <button className="cal-btn cal-btn-arrow" onClick={() => props.onShift(1)}>
            &gt;
          </button>
          <button
            className={view === 'day' ? 'cal-btn active' : 'cal-btn'}
            onClick={() => props.onView('day')}
          >
            День
          </button>
          <button
            className={view === 'week' ? 'cal-btn active' : 'cal-btn'}
            onClick={() => props.onView('week')}
          >
            Неделя
          </button>
          <button
            className={view === 'month' ? 'cal-btn active' : 'cal-btn'}
            onClick={() => props.onView('month')}
          >
            Месяц
          </button>
          <button className="cal-btn primary" onClick={props.onRefresh} disabled={loading}>
            {loading ? 'Обновление…' : 'Обновить из Outlook'}
          </button>
        </div>
      </div>

      <div className="cal-legend meetings-note">
        {error ? (
          <span className="meetings-error">{error}</span>
        ) : loading ? (
          <span>Читаем совещания из Outlook…</span>
        ) : (
          <span>
            Совещания {ownerName || 'текущего пользователя'} из Outlook · {items.length}
            {items.length ? '' : ' (пусто в этом периоде)'}
          </span>
        )}
      </div>

      {view === 'month' ? (
        <MonthGrid
          anchor={anchor}
          items={items}
          onSelect={selectMeeting}
          protocolMarks={props.protocolMarks}
        />
      ) : (
        <div className="cal-scroll" ref={scrollRef}>
          <WeekGrid
            days={days}
            items={items}
            onSelect={selectMeeting}
            protocolMarks={props.protocolMarks}
          />
        </div>
      )}

      {showDetailsModal && selected ? (
        <MeetingDetails meeting={selected} onClose={() => setSelected(null)} />
      ) : null}
    </div>
  )
}

interface GridProps {
  days: Date[]
  items: Positioned[]
  onSelect: (meeting: MeetingEvent) => void
  protocolMarks?: ReadonlyMap<string, { number: string }>
}

/** Hour rows [from, to) the card covers on its start day: at least one, up to the hour the meeting ends in. */
function hourSpan(item: Positioned): { from: number; to: number } {
  const from = item.start.getHours()
  let to = from + 1
  const end = item.end
  if (end && end.getTime() > item.start.getTime()) {
    to = sameDay(end, item.start)
      ? end.getHours() + (end.getMinutes() || end.getSeconds() ? 1 : 0)
      : 24
  }
  return { from, to: Math.min(24, Math.max(from + 1, to)) }
}

interface Placed {
  item: Positioned
  dayIndex: number
  from: number
  to: number
  lane: number
  lanes: number
  stack: number
}

/**
 * Cards starting in the same hour stack vertically; a multi-hour card goes last in its stack
 * and stretches down, so anything else overlapping it gets a separate lane.
 */
function layoutDay(dayItems: Positioned[], dayIndex: number): Placed[] {
  const rows = dayItems
    .map((item) => ({ item, ...hourSpan(item) }))
    .sort(
      (a, b) =>
        a.from - b.from || a.to - a.from - (b.to - b.from) || a.item.start.getTime() - b.item.start.getTime()
    )
  const placed: Placed[] = []
  let cluster: Placed[] = []
  let lanes: { from: number; to: number }[][] = []
  let clusterEnd = -1
  const flush = (): void => {
    for (const p of cluster) p.lanes = lanes.length
    placed.push(...cluster)
    cluster = []
    lanes = []
  }
  for (const row of rows) {
    if (row.from >= clusterEnd) flush()
    const multi = row.to - row.from > 1
    let lane = lanes.findIndex((occupants) =>
      occupants.every(
        (x) => x.to <= row.from || row.to <= x.from || (x.from === row.from && x.to - x.from === 1)
      )
    )
    if (lane < 0) {
      lane = lanes.length
      lanes.push([])
    }
    const stack = lanes[lane].filter((x) => x.from === row.from).length
    lanes[lane].push({ from: row.from, to: row.to })
    cluster.push({ item: row.item, dayIndex, from: row.from, to: row.to, lane, lanes: 1, stack })
    clusterEnd = Math.max(clusterEnd, multi ? row.to : row.from + 1)
  }
  flush()
  return placed
}

function WeekGrid({ days, items, onSelect, protocolMarks }: GridProps): React.JSX.Element {
  const placed = days.flatMap((day, dayIndex) =>
    layoutDay(
      items.filter((item) => sameDay(item.start, day)),
      dayIndex
    )
  )
  const startHour = Math.min(8, ...(placed.length ? placed.map((p) => p.from) : [8]))
  let endHour = Math.max(20, ...(placed.length ? placed.map((p) => p.to) : [20]))
  endHour = Math.min(24, Math.max(endHour, startHour + 1))
  const hourList = Array.from({ length: Math.max(1, endHour - startHour) }, (_, i) => startHour + i)
  const hourHeight = hourList.map((hour) => {
    let max = 1
    for (const p of placed) if (p.from === hour && p.stack + 1 > max) max = p.stack + 1
    return Math.max(HOUR_H, max * (CARD_H + CARD_GAP) + 6)
  })
  const hourTop = hourHeight.reduce<number[]>((acc, h, i) => {
    acc.push(i === 0 ? HEADER : acc[i - 1] + hourHeight[i - 1])
    return acc
  }, [])
  const width = GUTTER + days.length * COL_MIN
  const height = HEADER + hourHeight.reduce((sum, h) => sum + h, 0)
  const rowTop = (index: number): number => (index >= hourList.length ? height : hourTop[index])
  const today = new Date()

  const hourLines: React.JSX.Element[] = []
  hourList.forEach((hour, index) => {
    const y = hourTop[index]
    hourLines.push(
      <div
        key={`line-${hour}`}
        className="cal-hour-line"
        style={{ top: y, left: GUTTER, width: days.length * COL_MIN }}
      />
    )
    hourLines.push(
      <div key={`hlabel-${hour}`} className="cal-hour-label" style={{ top: y - 8, width: GUTTER - 6 }}>
        {String(hour).padStart(2, '0')}:00
      </div>
    )
  })

  return (
    <div className="cal-week" style={{ width, height }}>
      {days.map((day, index) => {
        const x = GUTTER + index * COL_MIN
        const isToday = sameDay(day, today)
        const count = items.filter((item) => sameDay(item.start, day)).length
        return (
          <div key={`col-${index}`}>
            {isToday && <div className="cal-today-col" style={{ left: x, width: COL_MIN, height }} />}
            <div className="cal-col-sep" style={{ left: x, height }} />
            <div className="cal-day-head" style={{ left: x, width: COL_MIN }}>
              {isToday ? (
                <span className="cal-day-pill">
                  {DAYS_SHORT[isoWeekday(day)]} {day.getDate()}
                </span>
              ) : (
                <span className="cal-day-label">
                  {DAYS_SHORT[isoWeekday(day)]} {day.getDate()}
                </span>
              )}
              {count > 0 && (
                <span className={isToday ? 'cal-day-count today' : 'cal-day-count'}>{count}</span>
              )}
            </div>
          </div>
        )
      })}
      {hourLines}
      {placed.map((p, index) => {
        const hourIndex = p.from - startHour
        if (hourIndex < 0 || hourIndex >= hourList.length) return null
        const laneW = (COL_MIN - 10) / p.lanes
        const top = hourTop[hourIndex] + 4 + p.stack * (CARD_H + CARD_GAP)
        const multi = p.to - p.from > 1
        const bottom = rowTop(p.to - startHour) - 4
        return (
          <MeetingBlock
            key={`${p.item.meeting.id}-${p.item.start.toISOString()}-${index}`}
            item={p.item}
            style={{
              left: GUTTER + p.dayIndex * COL_MIN + 4 + p.lane * laneW,
              top,
              width: p.lanes > 1 ? laneW - 2 : laneW,
              height: multi ? Math.max(CARD_H, bottom - top) : CARD_H
            }}
            showEnd={multi}
            onClick={onSelect}
            protocolNumber={protocolMarks?.get(meetingInstanceKey(p.item.meeting))?.number}
          />
        )
      })}
    </div>
  )
}

interface MonthGridProps {
  anchor: Date
  items: Positioned[]
  onSelect: (meeting: MeetingEvent) => void
  protocolMarks?: ReadonlyMap<string, { number: string }>
}

function MonthGrid({ anchor, items, onSelect, protocolMarks }: MonthGridProps): React.JSX.Element {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const start = mondayOf(first)
  const today = new Date()
  const cells = Array.from({ length: 42 }, (_, i) => addDays(start, i))

  return (
    <div className="cal-month">
      <div className="cal-month-head">
        {DAYS_SHORT.map((name) => (
          <div key={name} className="cal-month-weekday">
            {name}
          </div>
        ))}
      </div>
      <div className="cal-month-grid">
        {cells.map((day, index) => {
          const inMonth = day.getMonth() === anchor.getMonth()
          const isToday = sameDay(day, today)
          const dayItems = items.filter((item) => sameDay(item.start, day))
          const shown = dayItems.slice(0, 3)
          const leftover = dayItems.length - shown.length
          return (
            <div key={index} className={isToday ? 'cal-month-cell today' : 'cal-month-cell'}>
              <div
                className="cal-month-day"
                style={{ color: isToday ? '#1565C0' : inMonth ? '#10141A' : '#9BB4D0' }}
              >
                {day.getDate()}
              </div>
              {shown.map((item, gi) => (
                <MeetingBlock
                  key={`${item.meeting.id}-${gi}`}
                  item={item}
                  style={{ position: 'relative' }}
                  onClick={onSelect}
                  compact
                  protocolNumber={protocolMarks?.get(meetingInstanceKey(item.meeting))?.number}
                />
              ))}
              {leftover > 0 && <div className="cal-month-more">+{leftover}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

interface MeetingBlockProps {
  item: Positioned
  style: React.CSSProperties
  onClick: (meeting: MeetingEvent) => void
  compact?: boolean
  showEnd?: boolean
  protocolNumber?: string
}

function meetingBlockColors(item: Positioned, now = new Date()): { bg: string; border: string } {
  const end = item.end || item.start
  if (end.getTime() < now.getTime()) return { bg: '#E8F6EE', border: '#1B7F4A' }
  if (sameDay(item.start, now)) return { bg: '#FFF6D8', border: '#C9A227' }
  return { bg: STATUS_STYLE.meeting.bg, border: STATUS_STYLE.meeting.border }
}

function MeetingBlock({ item, style, onClick, compact, showEnd, protocolNumber }: MeetingBlockProps): React.JSX.Element {
  const meta = meetingBlockColors(item)
  const tip = [
    item.meeting.subject,
    `${timeLabel(item.start)}${item.end ? `–${timeLabel(item.end)}` : ''}`,
    item.meeting.location,
    item.meeting.organizer
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <div
      className={
        protocolNumber != null
          ? compact
            ? 'cal-event compact has-protocol'
            : 'cal-event has-protocol'
          : compact
            ? 'cal-event compact'
            : 'cal-event'
      }
      style={{ ...style, background: meta.bg, borderColor: meta.border }}
      title={tip}
      onClick={(e) => {
        e.stopPropagation()
        onClick(item.meeting)
      }}
    >
      <div className="cal-event-title">
        {timeLabel(item.start)}
        {showEnd && item.end ? `–${timeLabel(item.end)}` : ''}&nbsp;&nbsp;{item.meeting.subject}
      </div>
      {!compact && (
        <div className="cal-event-sub">{clip(item.meeting.location || item.meeting.organizer || 'Совещание', 42)}</div>
      )}
      {protocolNumber != null ? (
        <span
          className="cal-event-doc"
          title={protocolNumber ? `Протокол ${protocolNumber}` : 'Протокол создан в 1С'}
        >
          <FileText size={12} aria-hidden />
        </span>
      ) : null}
    </div>
  )
}

interface MeetingDetailsProps {
  meeting: MeetingEvent
  onClose: () => void
}

function MeetingDetails({ meeting, onClose }: MeetingDetailsProps): React.JSX.Element {
  const start = parseMeetingTime(meeting.start)
  const end = parseMeetingTime(meeting.end)
  const when = start
    ? `${start.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}, ${timeLabel(start)}${
        end ? `–${timeLabel(end)}` : ''
      }`
    : ''
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card meeting-details" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">{meeting.subject}</div>
        {when && <p className="meeting-details-row">🕑 {when}</p>}
        {meeting.location && <p className="meeting-details-row">📍 {meeting.location}</p>}
        {meeting.organizer && <p className="meeting-details-row">Организатор: {meeting.organizer}</p>}
        {meeting.attendees && <p className="meeting-details-row">Участники: {meeting.attendees}</p>}
        {meeting.owner && !isOutlookFolderOwner(meeting.owner) ? (
          <p className="meeting-details-row muted">Календарь: {meeting.owner}</p>
        ) : null}
        <div className="modal-actions">
          <button className="btn-light" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  )
}
