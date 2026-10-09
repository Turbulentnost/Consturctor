import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { FileText, Printer, X } from 'lucide-react'
import {
  addDays,
  DAYS_SHORT,
  formatPeriod,
  isoWeekday,
  mondayOf,
  MONTHS_GEN,
  sameDay,
  type CalendarView
} from '../../utils/calendar'
import {
  isOutlookFolderOwner,
  meetingInstanceKey,
  parseMeetingTime,
  type MeetingEvent
} from '../../utils/outlookMeetings'
import { PrintSchedule, type PrintField } from './MeetingPrintSchedule'
import {
  conflictSegments,
  isTopSpan,
  meetingSpan,
  minutesLabel,
  spanConflictParts,
  type ConflictSegment,
  type MeetingSpan
} from '../../utils/meetingOverlap'
import { calendarPalette, type CalendarPalette } from '../../workplace/meetingCalendars'
import './meetingsCalendar.css'

/** Высота часа в сетке недели: от неё считается высота блока по длительности. */
const HOUR_H = 52
/** Ниже заголовок и время под ним уже не поместятся. */
const MIN_BLOCK_H = 46
/** Шаг строки заголовка, тот же что в CSS. */
const TITLE_LINE_H = 16
/** Рамки и отступы блока; время идёт сразу под заголовком. */
const BLOCK_CHROME_H = 10
const TIME_ROW_H = 16
/** Ниже времени уже не видно, остаётся только заголовок. */
const TIME_MIN_BLOCK_H = 42

/**
 * Сколько строк заголовка реально влезает в блок такой высоты. Без этого счёта
 * последняя строка обрезается пополам и наезжает на время.
 */
function titleLines(height: number, withTime: boolean): number {
  const free = height - BLOCK_CHROME_H - (withTime ? TIME_ROW_H : 0)
  return Math.max(1, Math.floor(free / TITLE_LINE_H))
}
const DEFAULT_FROM_HOUR = 6
const DEFAULT_TO_HOUR = 20

/** Строка режима дня — один календарь, как в «Расписании» Outlook. */
export type DayRowSpec = { key: string; label: string; palette?: CalendarPalette }

/**
 * Раскладываем совещания по дорожкам: каждое встаёт в первую дорожку, где ни с кем
 * не пересекается. Так внутри одного календаря блоки не залезают друг на друга.
 */
function packSubLanes(blocks: LaneBlock[]): LaneBlock[][] {
  const lanes: LaneBlock[][] = [[]]
  for (const block of [...blocks].sort((left, right) => left.span.from - right.span.from)) {
    const free = lanes.findIndex((lane) =>
      lane.every((item) => item.span.to <= block.span.from || block.span.to <= item.span.from)
    )
    if (free < 0) lanes.push([block])
    else lanes[free].push(block)
  }
  return lanes
}

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
  /** anchor — рамка блока на экране: от неё внешняя карточка считает своё место. */
  onSelectMeeting?: (meeting: MeetingEvent, anchor: DOMRect) => void
  showDetailsModal?: boolean
  /** meeting.id → протокол 1С, если для совещания он уже создан. */
  protocolMarks?: ReadonlyMap<string, { number: string }>
  /** Периодом и масштабом управляет внешняя панель. */
  hideHeader?: boolean
  /** Цвет блока встречи по владельцу календаря — тот же, что в легенде. */
  eventPalette?: (meeting: MeetingEvent) => CalendarPalette
  /** Приоритет календаря: меньше — это совещание видно поверх пересечения. */
  priorityOf?: (meeting: MeetingEvent) => number
  /** Режим дня: по строке на календарь. Порядок — тот же, что в левой панели. */
  dayRows?: DayRowSpec[]
  /** К какой строке относится совещание; вернуть ключ из dayRows. */
  rowKeyOf?: (meeting: MeetingEvent) => string
}

type LaneBlock = {
  span: MeetingSpan
  /** Куски блока, накрытые другими совещаниями. */
  parts: ConflictSegment[]
  /** Этот блок остаётся видимым в пересечении. */
  top: boolean
}

type DayLane = {
  day: Date
  blocks: LaneBlock[]
}

type ConflictPick = { day: Date; segment: ConflictSegment }

/**
 * Рамка самого блока совещания на сетке. Список пересечений внизу страницы
 * карточки не открывает: она должна вылететь из совещания на его времени.
 */
function meetingBlockAnchor(meeting: MeetingEvent, fallback: DOMRect): DOMRect {
  const node = document.querySelector<HTMLElement>(
    `[data-meeting-key="${CSS.escape(meetingInstanceKey(meeting))}"]`
  )
  if (!node) return fallback
  const box = node.getBoundingClientRect()
  const frame = node.closest('.mcal-scroll')?.getBoundingClientRect()
  const offscreen =
    frame &&
    (box.bottom < frame.top + 4 ||
      box.top > frame.bottom - 4 ||
      box.right < frame.left + 4 ||
      box.left > frame.right - 4)
  if (offscreen) node.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
  return node.getBoundingClientRect()
}

function timeLabel(date: Date | null): string {
  if (!date) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function meetingRange(meeting: MeetingEvent): string {
  const start = parseMeetingTime(meeting.start)
  const end = parseMeetingTime(meeting.end)
  if (!start) return ''
  return end ? `${timeLabel(start)}–${timeLabel(end)}` : timeLabel(start)
}

function buildLanes(
  days: Date[],
  meetings: MeetingEvent[],
  priorityOf?: (meeting: MeetingEvent) => number,
  groupOf?: (meeting: MeetingEvent) => string
): DayLane[] {
  return days.map((day) => {
    const spans: MeetingSpan[] = []
    for (const meeting of meetings) {
      const start = parseMeetingTime(meeting.start)
      if (!start || !sameDay(start, day)) continue
      const span = meetingSpan(meeting, priorityOf?.(meeting) ?? 0)
      if (span) spans.push(span)
    }
    spans.sort((left, right) => left.from - right.from || left.priority - right.priority)

    // Пересечения ищем внутри группы. Без groupOf группа одна — все совещания дня
    // делят колонку, поэтому конфликтом считается любое наложение.
    const groups = new Map<string, MeetingSpan[]>()
    for (const span of spans) {
      const key = groupOf ? groupOf(span.meeting) : ''
      groups.set(key, [...(groups.get(key) || []), span])
    }
    const marks = new Map<string, Omit<LaneBlock, 'span'>>()
    for (const group of groups.values()) {
      const segments = conflictSegments(group)
      for (const span of group) {
        marks.set(meetingInstanceKey(span.meeting), {
          parts: spanConflictParts(span, segments),
          top: isTopSpan(span, group)
        })
      }
    }

    return {
      day,
      blocks: spans.map((span) => ({
        span,
        ...(marks.get(meetingInstanceKey(span.meeting)) || { parts: [], top: true })
      }))
    }
  })
}

/** Окно сетки всегда 06:00–20:00: всё, что помещается в него, видно без прокрутки. */
function hourWindow(_lanes: DayLane[]): { from: number; to: number } {
  return { from: DEFAULT_FROM_HOUR, to: DEFAULT_TO_HOUR }
}

/** Совещание уже закончилось: цвет человека сохраняем, блок просто приглушаем. */
function isPast(span: MeetingSpan, now: Date): boolean {
  const start = parseMeetingTime(span.meeting.start)
  const day = start || now
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, span.to).getTime() < now.getTime()
}

export function MeetingsCalendar(props: MeetingsCalendarProps): React.JSX.Element {
  const { view, anchor, meetings, loading, error, ownerName, showDetailsModal = true } = props
  const [details, setDetails] = useState<MeetingEvent | null>(null)
  const [conflict, setConflict] = useState<ConflictPick | null>(null)
  const [printOpen, setPrintOpen] = useState(false)

  const selectMeeting = (meeting: MeetingEvent, anchor: DOMRect): void => {
    props.onSelectMeeting?.(meeting, anchor)
    if (showDetailsModal) setDetails(meeting)
  }

  const days = useMemo(() => {
    if (view === 'day') return [new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())]
    if (view === 'month') return []
    const start = mondayOf(anchor)
    return Array.from({ length: 7 }, (_, index) => addDays(start, index))
  }, [view, anchor])

  const monthDays = useMemo(() => {
    if (view !== 'month') return []
    const start = mondayOf(new Date(anchor.getFullYear(), anchor.getMonth(), 1))
    return Array.from({ length: 42 }, (_, index) => addDays(start, index))
  }, [view, anchor])

  const lanes = useMemo(
    () =>
      buildLanes(
        view === 'month' ? monthDays : days,
        meetings,
        props.priorityOf,
        // В режиме дня у каждого календаря своя строка, и чужое совещание рядом ничего
        // не закрывает. Штриховкой отмечаем только накладки внутри одного календаря.
        view === 'day' ? props.rowKeyOf : undefined
      ),
    [view, monthDays, days, meetings, props.priorityOf, props.rowKeyOf]
  )

  useEffect(() => {
    setConflict(null)
  }, [view, anchor, meetings])

  const total = lanes.reduce((sum, lane) => sum + lane.blocks.length, 0)

  // Печать совпадает с открытым режимом: день, семь дней недели или выбранный месяц.
  const printDays = useMemo(() => {
    const visible =
      view === 'month' ? lanes.filter((lane) => lane.day.getMonth() === anchor.getMonth()) : lanes
    return visible
      .map((lane) => ({
        day: lane.day,
        items: lane.blocks.map((block) => block.span.meeting)
      }))
      .filter((group) => group.items.length > 0)
  }, [lanes, view, anchor])

  return (
    <div className="run-calendar meetings-calendar mcal-root">
      {props.hideHeader ? null : (
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
      )}

      <div className="cal-legend meetings-note">
        {error ? (
          <span className="meetings-error">{error}</span>
        ) : loading ? (
          <span>Читаем совещания из Outlook…</span>
        ) : (
          <span>
            Совещания {ownerName || 'текущего пользователя'} из Outlook · {total}
            {total ? '' : ' (пусто в этом периоде)'}
          </span>
        )}
        <button type="button" className="mcal-print-btn" onClick={() => setPrintOpen(true)}>
          <Printer size={14} aria-hidden />
          Печать
        </button>
      </div>

      {view === 'day' ? (
        <DayStrip
          lane={lanes[0]}
          rows={props.dayRows}
          rowKeyOf={props.rowKeyOf}
          onSelect={selectMeeting}
          onConflict={setConflict}
          selectedId={props.selectedId}
          protocolMarks={props.protocolMarks}
          eventPalette={props.eventPalette}
        />
      ) : view === 'month' ? (
        <MonthGrid
          anchor={anchor}
          lanes={lanes}
          onSelect={selectMeeting}
          onConflict={setConflict}
          selectedId={props.selectedId}
          protocolMarks={props.protocolMarks}
          eventPalette={props.eventPalette}
        />
      ) : (
        <WeekGrid
          lanes={lanes}
          onSelect={selectMeeting}
          onConflict={setConflict}
          selectedId={props.selectedId}
          protocolMarks={props.protocolMarks}
          eventPalette={props.eventPalette}
        />
      )}

      {conflict ? (
        <ConflictPanel
          pick={conflict}
          onClose={() => setConflict(null)}
          onSelect={selectMeeting}
          eventPalette={props.eventPalette}
          // В режиме дня накладка лежит в своих дорожках — видно оба совещания.
          markTop={view !== 'day'}
        />
      ) : null}

      {showDetailsModal && details ? (
        <MeetingDetails meeting={details} onClose={() => setDetails(null)} />
      ) : null}
      {printOpen ? (
        <MeetingPrintDialog
          days={printDays}
          periodLabel={formatPeriod(view, anchor)}
          onClose={() => setPrintOpen(false)}
        />
      ) : null}
    </div>
  )
}

interface GridProps {
  lanes: DayLane[]
  onSelect: (meeting: MeetingEvent, anchor: DOMRect) => void
  onConflict: (pick: ConflictPick) => void
  selectedId?: string
  protocolMarks?: ReadonlyMap<string, { number: string }>
  eventPalette?: (meeting: MeetingEvent) => CalendarPalette
}

function WeekGrid({
  lanes,
  onSelect,
  onConflict,
  selectedId,
  protocolMarks,
  eventPalette
}: GridProps): React.JSX.Element {
  const bounds = hourWindow(lanes)
  const hours = Array.from({ length: bounds.to - bounds.from }, (_, index) => bounds.from + index)
  const height = hours.length * HOUR_H
  const now = new Date()
  const perMinute = HOUR_H / 60
  const offset = (minutes: number): number => (minutes - bounds.from * 60) * perMinute

  return (
    <div className="cal-scroll mcal-scroll">
      <div className="mcal-head">
        <div className="mcal-gutter-cell" />
        {lanes.map((lane) => {
          const today = sameDay(lane.day, now)
          return (
            <div key={lane.day.toISOString()} className={`mcal-head-day${today ? ' is-today' : ''}`}>
              <span className="mcal-head-dow">{DAYS_SHORT[isoWeekday(lane.day)]}</span>
              <span className="mcal-head-date">{lane.day.getDate()}</span>
              {lane.blocks.length ? (
                <span className="mcal-head-count">{lane.blocks.length}</span>
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="mcal-body" style={{ height }}>
          <div className="mcal-gutter">
            {hours.map((hour) => (
              // Верхнюю метку не даём уехать за край: она центрируется по своей линии.
              <span key={hour} className="mcal-hour" style={{ top: Math.max(7, offset(hour * 60)) }}>
                {String(hour).padStart(2, '0')}:00
              </span>
            ))}
          </div>
          {lanes.map((lane) => (
            <div
              key={lane.day.toISOString()}
              className={`mcal-col${sameDay(lane.day, now) ? ' is-today' : ''}`}
            >
              {hours.map((hour) => (
                <div key={hour} className="mcal-line" style={{ top: offset(hour * 60) }} />
              ))}
              {sameDay(lane.day, now) ? (
                <div
                  className="mcal-now"
                  style={{ top: offset(now.getHours() * 60 + now.getMinutes()) }}
                />
              ) : null}
              {lane.blocks.map((block) => {
                const key = meetingInstanceKey(block.span.meeting)
                const blockHeight = Math.max(MIN_BLOCK_H, (block.span.to - block.span.from) * perMinute)
                return (
                  <MeetingBlock
                    key={key}
                    block={block}
                    now={now}
                    style={{ top: offset(block.span.from) }}
                    height={blockHeight}
                    selected={selectedId === key}
                    onClick={onSelect}
                    onConflict={(segment) => onConflict({ day: lane.day, segment })}
                    protocolNumber={protocolMarks?.get(key)?.number}
                    palette={eventPalette?.(block.span.meeting)}
                  />
                )
              })}
            </div>
          ))}
      </div>
    </div>
  )
}

function DayStrip({
  lane,
  rows,
  rowKeyOf,
  onSelect,
  onConflict,
  selectedId,
  protocolMarks,
  eventPalette
}: Omit<GridProps, 'lanes'> & {
  lane?: DayLane
  rows?: DayRowSpec[]
  rowKeyOf?: (meeting: MeetingEvent) => string
}): React.JSX.Element {
  if (!lane) return <div className="mcal-empty">Нет данных за день</div>
  const bounds = hourWindow([lane])
  const hours = Array.from({ length: bounds.to - bounds.from }, (_, index) => bounds.from + index)
  const height = hours.length * HOUR_H
  const now = new Date()
  const isToday = sameDay(lane.day, now)
  const perMinute = HOUR_H / 60
  const offset = (minutes: number): number => (minutes - bounds.from * 60) * perMinute

  const board = (rows?.length ? rows : [{ key: '', label: 'Календарь', palette: undefined }]).map(
    (row) => {
      const blocks = row.key
        ? lane.blocks.filter((block) => rowKeyOf?.(block.span.meeting) === row.key)
        : lane.blocks
      return { row, subLanes: packSubLanes(blocks) }
    }
  )

  return (
    <div className="cal-scroll mcal-scroll">
      <div className="mcal-day-v" style={{ ['--mcal-cols' as string]: board.length }}>
        <div className="mcal-day-v-head">
          <div className={`mcal-day-v-corner${isToday ? ' is-today' : ''}`}>
            <span className="mcal-head-dow">{DAYS_SHORT[isoWeekday(lane.day)]}</span>
            <span className="mcal-head-date">{lane.day.getDate()}</span>
          </div>
          {board.map(({ row }) => (
            <div key={row.key || 'self'} className="mcal-day-v-name" title={row.key || row.label}>
              <span
                className="mcal-day-dot"
                style={{ background: row.palette?.dot || '#2F6BD8' }}
                aria-hidden
              />
              <span className="mcal-day-label">{row.label}</span>
            </div>
          ))}
        </div>
        <div className="mcal-day-v-body" style={{ height }}>
          <div className="mcal-gutter">
            {hours.map((hour) => (
              <span key={hour} className="mcal-hour" style={{ top: Math.max(7, offset(hour * 60)) }}>
                {String(hour).padStart(2, '0')}:00
              </span>
            ))}
          </div>
          {board.map(({ row, subLanes }) => {
            const laneCount = Math.max(1, subLanes.length)
            const empty = subLanes.length === 1 && !subLanes[0].length
            return (
              <div key={row.key || 'self'} className={`mcal-day-v-col${isToday ? ' is-today' : ''}`}>
                {hours.map((hour) => (
                  <div key={hour} className="mcal-line" style={{ top: offset(hour * 60) }} />
                ))}
                {isToday ? (
                  <div
                    className="mcal-now"
                    style={{ top: offset(now.getHours() * 60 + now.getMinutes()) }}
                  />
                ) : null}
                {empty ? <span className="mcal-day-free">Свободно</span> : null}
                {subLanes.map((subLane, index) =>
                  subLane.map((block) => {
                    const key = meetingInstanceKey(block.span.meeting)
                    const share = 100 / laneCount
                    return (
                      <MeetingBlock
                        key={key}
                        block={block}
                        now={now}
                        style={{
                          top: offset(block.span.from),
                          left: `calc(${index * share}% + 2px)`,
                          width: `calc(${share}% - 6px)`,
                          right: 'auto'
                        }}
                        height={Math.max(MIN_BLOCK_H, (block.span.to - block.span.from) * perMinute)}
                        selected={selectedId === key}
                        onClick={onSelect}
                        onConflict={(segment) => onConflict({ day: lane.day, segment })}
                        protocolNumber={protocolMarks?.get(key)?.number}
                        palette={eventPalette?.(block.span.meeting)}
                      />
                    )
                  })
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/** «3 совещания»: слово согласуем с числом. */
function meetingsCountLabel(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  const word =
    mod10 === 1 && mod100 !== 11
      ? 'совещание'
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? 'совещания'
        : 'совещаний'
  return `${count} ${word}`
}

function MonthGrid({
  anchor,
  lanes,
  eventPalette
}: GridProps & { anchor: Date }): React.JSX.Element {
  const now = new Date()
  // Самый приоритетный — тот, кто в списке календарей стоит выше всех и вообще
  // есть в этом месяце. В ячейке дня показываем только его число совещаний.
  const topPriority = lanes.reduce((best, lane) => {
    for (const block of lane.blocks) best = Math.min(best, block.span.priority)
    return best
  }, Number.POSITIVE_INFINITY)
  return (
    <div className="cal-scroll mcal-scroll">
      <div className="mcal-month">
        <div className="mcal-month-head">
          {DAYS_SHORT.map((name) => (
            <span key={name}>{name}</span>
          ))}
        </div>
        <div className="mcal-month-grid">
          {lanes.map((lane) => {
            const inMonth = lane.day.getMonth() === anchor.getMonth()
            const today = sameDay(lane.day, now)
            const top = lane.blocks.filter((block) => block.span.priority === topPriority)
            const palette = top[0] ? eventPalette?.(top[0].span.meeting) : undefined
            return (
              <div
                key={lane.day.toISOString()}
                className={[
                  'mcal-month-cell',
                  inMonth ? '' : 'is-out',
                  today ? 'is-today' : ''
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <span className="mcal-month-day">{lane.day.getDate()}</span>
                {top.length ? (
                  <span
                    className="mcal-month-count"
                    style={{
                      background: palette?.fill || '#E7EFFC',
                      borderColor: palette?.border || '#A8C3F2',
                      color: palette?.text || '#17325F'
                    }}
                    title={meetingsCountLabel(top.length)}
                  >
                    {top.length}
                  </span>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function MeetingBlock({
  block,
  now,
  style,
  height,
  onClick,
  onConflict,
  selected,
  compact,
  horizontal,
  protocolNumber,
  palette
}: {
  block: LaneBlock
  now: Date
  style: React.CSSProperties
  /** Высота блока: от неё зависит и вёрстка, и число строк заголовка. */
  height: number
  onClick: (meeting: MeetingEvent, anchor: DOMRect) => void
  onConflict: (segment: ConflictSegment) => void
  selected?: boolean
  compact?: boolean
  horizontal?: boolean
  protocolNumber?: string
  palette?: CalendarPalette
}): React.JSX.Element {
  const { span, parts, top } = block
  const withTime = height >= TIME_MIN_BLOCK_H
  const lines = titleLines(height, withTime)
  const colors = palette || calendarPalette(0)
  const range = `${minutesLabel(span.from)}–${minutesLabel(span.to)}`
  const overlaps = new Set(
    parts.flatMap((part) => part.meetings.map(meetingInstanceKey))
  )
  overlaps.delete(meetingInstanceKey(span.meeting))
  // Карточка открывается только по явному клику: отпускание после прокрутки/протяжки не считаем кликом.
  const pressRef = useRef<{ x: number; y: number } | null>(null)
  const minutes = Math.max(1, span.to - span.from)
  const share = (value: number): string => `${((value / minutes) * 100).toFixed(2)}%`
  const tip = [
    span.meeting.subject,
    range,
    span.meeting.location,
    span.meeting.organizer,
    overlaps.size ? `Пересекается с ${overlaps.size} · нажмите на штриховку` : ''
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <div
      data-meeting-key={meetingInstanceKey(span.meeting)}
      className={[
        'mcal-event',
        compact ? 'is-compact' : '',
        horizontal ? 'is-horizontal' : '',
        selected ? 'is-selected' : '',
        parts.length ? (top ? 'has-conflict is-top' : 'has-conflict is-under') : '',
        isPast(span, now) ? 'is-past' : '',
        protocolNumber != null ? 'has-protocol' : ''
      ]
        .filter(Boolean)
        .join(' ')}
      style={{
        ...style,
        height,
        background: colors.fill,
        borderColor: colors.border,
        borderLeftColor: colors.dot,
        color: colors.text,
        // Приоритет календаря решает, чей блок останется сверху в наложении.
        zIndex: 4 + Math.max(0, 40 - span.priority * 2)
      }}
      title={tip}
      onPointerDown={(event) => {
        pressRef.current = { x: event.clientX, y: event.clientY }
      }}
      onClick={(event) => {
        event.stopPropagation()
        const press = pressRef.current
        pressRef.current = null
        if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 4) return
        onClick(span.meeting, event.currentTarget.getBoundingClientRect())
      }}
    >
      {/* maxHeight — гарантия от обрезанной пополам строки, line-clamp добавляет многоточие. */}
      <span className="mcal-event-title" style={{ maxHeight: lines * TITLE_LINE_H }}>
        <span className="mcal-event-title-text" style={{ WebkitLineClamp: lines }}>
          {span.meeting.subject}
        </span>
      </span>
      {withTime ? <span className="mcal-event-time">{range}</span> : null}
      {parts.map((part) =>
        compact ? null : (
          <button
            key={`${part.from}-${part.to}`}
            type="button"
            className="mcal-hatch"
            style={
              horizontal
                ? { left: share(part.from - span.from), width: share(part.to - part.from) }
                : { top: share(part.from - span.from), height: share(part.to - part.from) }
            }
            aria-label="Показать пересечения"
            title={`Пересечение ${minutesLabel(part.from)}–${minutesLabel(part.to)}: ${part.meetings.length} совещания`}
            onClick={(event) => {
              event.stopPropagation()
              onConflict(part)
            }}
          />
        )
      )}
      {protocolNumber != null ? (
        <span
          className="mcal-event-doc"
          title={protocolNumber ? `Протокол ${protocolNumber}` : 'Протокол создан в 1С'}
        >
          <FileText size={11} aria-hidden />
        </span>
      ) : null}
      {compact && parts.length ? (
        <button
          type="button"
          className="mcal-event-hatch"
          aria-label="Показать пересечения"
          title={`Пересекается с ${overlaps.size} — показать список`}
          onClick={(event) => {
            event.stopPropagation()
            onConflict(parts[0])
          }}
        />
      ) : null}
    </div>
  )
}

function ConflictPanel({
  pick,
  onClose,
  onSelect,
  eventPalette,
  markTop
}: {
  pick: ConflictPick
  onClose: () => void
  onSelect: (meeting: MeetingEvent, anchor: DOMRect) => void
  eventPalette?: (meeting: MeetingEvent) => CalendarPalette
  /** Отметить первое совещание как то, что осталось видимым в сетке. */
  markTop?: boolean
}): React.JSX.Element {
  const { segment, day } = pick
  return (
    <section className="mcal-conflict">
      <header className="mcal-conflict-head">
        <span>
          Пересечение {minutesLabel(segment.from)}–{minutesLabel(segment.to)},{' '}
          {day.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} ·{' '}
          {segment.meetings.length} совещания
        </span>
        <button type="button" className="mcal-conflict-close" aria-label="Закрыть" onClick={onClose}>
          <X size={14} aria-hidden />
        </button>
      </header>
      <ul className="mcal-conflict-list">
        {segment.meetings.map((meeting, index) => (
          <li key={meetingInstanceKey(meeting)}>
            <button
              type="button"
              className="mcal-conflict-item"
              onClick={(event) =>
                onSelect(meeting, meetingBlockAnchor(meeting, event.currentTarget.getBoundingClientRect()))
              }
            >
              <span
                className="mcal-conflict-dot"
                style={{ background: (eventPalette?.(meeting) || calendarPalette(0)).dot }}
                aria-hidden
              />
              <span className="mcal-conflict-title">{meeting.subject}</span>
              <span className="mcal-conflict-time">{meetingRange(meeting)}</span>
              {markTop && index === 0 ? (
                <span className="mcal-conflict-tag">видно в сетке</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function MeetingDetails({
  meeting,
  onClose
}: {
  meeting: MeetingEvent
  onClose: () => void
}): React.JSX.Element {
  const start = parseMeetingTime(meeting.start)
  const end = parseMeetingTime(meeting.end)
  const when = start
    ? `${start.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}, ${timeLabel(start)}${
        end ? `–${timeLabel(end)}` : ''
      }`
    : ''
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card is-resizable meeting-details" onClick={(event) => event.stopPropagation()}>
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

const PRINT_FIELDS_KEY = 'orch.meetings.print-fields'

const PRINT_FIELD_LIST: { id: PrintField; label: string }[] = [
  { id: 'subject', label: 'Тема' },
  { id: 'time', label: 'Дата / время' },
  { id: 'location', label: 'Место' },
  { id: 'format', label: 'Формат' },
  { id: 'organizer', label: 'Организатор' },
  { id: 'attendees', label: 'Участники' },
  { id: 'owner', label: 'Владелец' }
]

function readPrintFields(): Record<PrintField, boolean> {
  const base: Record<PrintField, boolean> = {
    subject: true,
    time: true,
    location: true,
    format: true,
    organizer: true,
    attendees: true,
    owner: true
  }
  try {
    const raw = window.localStorage.getItem(PRINT_FIELDS_KEY)
    if (!raw) return base
    return { ...base, ...(JSON.parse(raw) as Partial<Record<PrintField, boolean>>) }
  } catch {
    return base
  }
}

function printDayLabel(day: Date): string {
  return `${String(day.getDate()).padStart(2, '0')} ${MONTHS_GEN[day.getMonth() + 1]} ${day.getFullYear()}`
}

function MeetingPrintDialog({
  days,
  periodLabel,
  onClose
}: {
  days: { day: Date; items: MeetingEvent[] }[]
  periodLabel: string
  onClose: () => void
}): React.JSX.Element {
  const [fields, setFields] = useState(readPrintFields)
  const [previewScale, setPreviewScale] = useState(1)
  const [pageBox, setPageBox] = useState({ w: 1123, h: 794 })
  const pageRef = useRef<HTMLDivElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.localStorage.setItem(PRINT_FIELDS_KEY, JSON.stringify(fields))
  }, [fields])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useLayoutEffect(() => {
    const preview = previewRef.current
    const page = pageRef.current
    if (!preview || !page) return
    const fit = (): void => {
      const pad = 32
      const width = page.offsetWidth || 1
      const height = page.offsetHeight || 1
      const availW = Math.max(1, preview.clientWidth - pad)
      const availH = Math.max(1, preview.clientHeight - pad)
      const next = Math.min(availW / width, availH / height)
      setPageBox({ w: width, h: height })
      setPreviewScale(Number.isFinite(next) && next > 0 ? Math.min(1, next) : 1)
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(preview)
    return () => observer.disconnect()
  }, [days, fields])

  return createPortal(
    <div className="mcal-print-backdrop" role="dialog" aria-label="Печать совещаний">
      <aside className="mcal-print-settings">
        <h3>На печати</h3>
        <p className="mcal-print-period">{periodLabel}</p>
        {PRINT_FIELD_LIST.map((item) => (
          <label key={item.id}>
            <input
              type="checkbox"
              checked={fields[item.id]}
              onChange={(event) =>
                setFields((current) => ({ ...current, [item.id]: event.target.checked }))
              }
            />
            <span>{item.label}</span>
          </label>
        ))}
        <div className="mcal-print-actions">
          <button type="button" className="is-primary" onClick={() => window.print()}>
            Печать
          </button>
          <button type="button" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </aside>
      <div className="mcal-print-preview" ref={previewRef}>
        <div
          className="mcal-print-scale"
          style={{ width: pageBox.w * previewScale, height: pageBox.h * previewScale }}
        >
        <div
          className="mcal-print-page"
          ref={pageRef}
          style={{ transform: `scale(${previewScale})`, transformOrigin: 'top left' }}
        >
          <div className="mcal-print-fit">
            {days.length ? (
              <PrintSchedule
                days={days}
                fields={fields}
                title={days.length === 1 ? printDayLabel(days[0].day) : periodLabel}
              />
            ) : (
              <p className="mcal-print-empty">В этом периоде нет совещаний</p>
            )}
          </div>
        </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
