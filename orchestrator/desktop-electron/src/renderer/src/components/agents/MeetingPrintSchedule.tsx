import { useLayoutEffect, useRef, useState } from 'react'
import { meetingInstanceKey, parseMeetingTime, type MeetingEvent } from '../../utils/outlookMeetings'
import { DAYS_SHORT, isoWeekday, MONTHS_GEN } from '../../utils/calendar'
import { calendarPalette } from '../../workplace/meetingCalendars'

/** Окно как на дневной сетке: 7:00–20:00. */
const FROM_HOUR = 7
const TO_HOUR = 20
const SNAP_MINUTES = 15

type PrintBlock = {
  meeting: MeetingEvent
  key: string
  from: number
  to: number
  lane: number
}

export type PrintTool = 'insert' | 'delete' | null

/** Лист A4: горизонтальный — как сейчас, вертикальный — рамки на всю страницу. */
export type PrintSheet = 'landscape' | 'portrait'

type Drag = { day: Date; anchor: number; current: number }

const SPAN_MINUTES = (TO_HOUR - FROM_HOUR) * 60
const HOURS = Array.from({ length: TO_HOUR - FROM_HOUR + 1 }, (_, index) => FROM_HOUR + index)

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

function timeLabel(minutes: number): string {
  return `${pad2(Math.floor(minutes / 60))}:${pad2(minutes % 60)}`
}

function durationLabel(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours && rest) return `${hours} ч ${rest} мин`
  if (hours === 1) return '1 час'
  if (hours) return `${hours} ч`
  return `${rest} мин`
}

function longDate(day: Date): string {
  return `${day.getDate()} ${MONTHS_GEN[day.getMonth() + 1]} ${day.getFullYear()}`
}

/**
 * Время и кабинет по длине текста, тема — сколько нужно заголовку,
 * участники забирают всю оставшуюся ширину строки.
 */
function columnTracks(items: MeetingEvent[], width: number): string {
  if (width < 240) return '4.4rem minmax(0, 1.2fr) minmax(7rem, 18%) minmax(0, 2fr)'
  const time = 70
  let roomChars = 8
  let themeChars = 10
  for (const item of items) {
    roomChars = Math.max(roomChars, (item.location || '').trim().length)
    themeChars = Math.max(themeChars, (item.subject || '').trim().length || 10)
  }
  const room = Math.round(Math.min(Math.max(roomChars * 7.2, 96), width * 0.18))
  const rest = Math.max(160, width - time - room)
  const theme = Math.round(Math.min(Math.max(themeChars * 6.4, rest * 0.22), rest * 0.4))
  const people = Math.max(120, Math.round(width - time - room - theme))
  return `${time}px ${theme}px ${room}px ${people}px`
}

function percentOf(minutes: number): number {
  return ((minutes - FROM_HOUR * 60) / SPAN_MINUTES) * 100
}

function minutesAt(column: HTMLElement, clientY: number): number {
  const rect = column.getBoundingClientRect()
  const ratio = rect.height > 0 ? (clientY - rect.top) / rect.height : 0
  const raw = FROM_HOUR * 60 + Math.min(1, Math.max(0, ratio)) * SPAN_MINUTES
  return Math.round(raw / SNAP_MINUTES) * SNAP_MINUTES
}

function spanOf(meeting: MeetingEvent): { from: number; to: number } | null {
  const start = parseMeetingTime(meeting.start)
  if (!start) return null
  const end = parseMeetingTime(meeting.end)
  const from = start.getHours() * 60 + start.getMinutes()
  let to = end ? end.getHours() * 60 + end.getMinutes() : from + 60
  if (end && (end.getDate() !== start.getDate() || end.getMonth() !== start.getMonth())) to = 24 * 60
  if (to <= from) to = from + SNAP_MINUTES
  return { from, to }
}

function blocksOf(items: MeetingEvent[]): { blocks: PrintBlock[]; lanes: number } {
  const ordered = items
    .map((meeting) => {
      const span = spanOf(meeting)
      if (!span) return null
      const from = Math.max(span.from, FROM_HOUR * 60)
      const to = Math.min(span.to, TO_HOUR * 60)
      if (to <= from) return null
      return { meeting, key: meetingInstanceKey(meeting), from, to, lane: 0 }
    })
    .filter((block): block is PrintBlock => block != null)
    .sort((left, right) => left.from - right.from || right.to - right.from - (left.to - left.from))
  const lanes: PrintBlock[][] = []
  for (const block of ordered) {
    const free = lanes.findIndex((lane) => lane.every((item) => item.to <= block.from || block.to <= item.from))
    const index = free < 0 ? lanes.length : free
    if (free < 0) lanes.push([])
    block.lane = index
    lanes[index].push(block)
  }
  return { blocks: ordered, lanes: Math.max(1, lanes.length) }
}

function selectionRange(drag: Drag, column: HTMLElement | null, clientY: number): { from: number; to: number } {
  const current = column ? minutesAt(column, clientY) : drag.current
  let from = Math.min(drag.anchor, current)
  let to = Math.max(drag.anchor, current)
  from = Math.max(FROM_HOUR * 60, from)
  to = Math.min(TO_HOUR * 60, to)
  if (to - from < SNAP_MINUTES) to = Math.min(TO_HOUR * 60, from + SNAP_MINUTES)
  if (to - from < SNAP_MINUTES) {
    from = Math.max(FROM_HOUR * 60, to - SNAP_MINUTES)
  }
  return { from, to }
}

/**
 * Лист как дневная сетка: слева часы, карточки совещаний светлым тоном.
 * Вставить и Удалить — протяжка интервала, не перенос блока.
 */
export function PrintSchedule({
  days,
  tool,
  sheet,
  selectedKey,
  onSelect,
  onRange
}: {
  days: { day: Date; items: MeetingEvent[] }[]
  tool: PrintTool
  sheet: PrintSheet
  selectedKey: string | null
  onSelect: (key: string) => void
  onRange: (day: Date, from: number, to: number) => void
}): React.JSX.Element {
  const [drag, setDrag] = useState<Drag | null>(null)
  const [colWidth, setColWidth] = useState(0)
  const boardRef = useRef<HTMLDivElement>(null)
  const columnRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<Drag | null>(null)
  const single = days.length === 1
  const day = single ? days[0].day : null

  useLayoutEffect(() => {
    const node = boardRef.current
    if (!node) return
    const measure = (): void => {
      const cols = Math.max(1, days.length)
      setColWidth(Math.max(0, (node.clientWidth - 42) / cols))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [days.length])

  return (
    <div
      ref={boardRef}
      className={`mcal-day-v mcp-board${tool ? ' is-tool' : ''}${sheet === 'portrait' ? ' is-portrait' : ' is-landscape'}`}
      style={{ ['--mcal-cols' as string]: String(Math.max(1, days.length)) }}
    >
      <div className="mcal-day-v-head">
        <div className={`mcal-day-v-corner${day && sameToday(day) ? ' is-today' : ''}`}>
          {day ? (
            <>
              <span className="mcal-head-dow">{DAYS_SHORT[isoWeekday(day)]}</span>
              <span className="mcal-head-date">{day.getDate()}</span>
            </>
          ) : null}
        </div>
        {days.map((group) => (
          <div key={group.day.toISOString()} className="mcal-day-v-name mcp-colhead">
            <span className="mcal-day-label">{single ? longDate(group.day) : `${DAYS_SHORT[isoWeekday(group.day)]}, ${longDate(group.day)}`}</span>
            <div
              className="mcp-cols mcp-cols-head"
              style={{ gridTemplateColumns: columnTracks(group.items, colWidth) }}
            >
              <span>Время</span>
              <span>Тема</span>
              <span>Кабинет</span>
              <span>Участники</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mcal-day-v-body mcp-body">
        <div className="mcal-gutter" aria-hidden>
          {HOURS.map((hour, index) => (
            <span
              key={hour}
              className={`mcal-hour${index === 0 ? ' is-first' : ''}${index === HOURS.length - 1 ? ' is-last' : ''}`}
              style={{ top: `${percentOf(hour * 60)}%` }}
            >
              {pad2(hour)}:00
            </span>
          ))}
        </div>
        {days.map((group) => (
          <DayColumn
            key={group.day.toISOString()}
            day={group.day}
            items={group.items}
            columns={columnTracks(group.items, colWidth)}
            sheet={sheet}
            tool={tool}
            drag={drag}
            selectedKey={selectedKey}
            onSelect={onSelect}
            onDragStart={(anchor, node) => {
              columnRef.current = node
              const next = { day: group.day, anchor, current: anchor }
              dragRef.current = next
              setDrag(next)
            }}
            onDragMove={(clientY) => {
              const column = columnRef.current
              const current = dragRef.current
              if (!column || !current) return
              const next = { ...current, current: minutesAt(column, clientY) }
              dragRef.current = next
              setDrag(next)
            }}
            onDragEnd={(clientY) => {
              const column = columnRef.current
              const current = dragRef.current
              columnRef.current = null
              dragRef.current = null
              setDrag(null)
              if (!current || !column || current.day.getTime() !== group.day.getTime()) return
              const range = selectionRange(current, column, clientY)
              onRange(group.day, range.from, range.to)
            }}
          />
        ))}
      </div>
    </div>
  )
}

function sameToday(day: Date): boolean {
  const now = new Date()
  return day.getFullYear() === now.getFullYear() && day.getMonth() === now.getMonth() && day.getDate() === now.getDate()
}

function DayColumn({
  day,
  items,
  columns,
  sheet,
  tool,
  drag,
  selectedKey,
  onSelect,
  onDragStart,
  onDragMove,
  onDragEnd
}: {
  day: Date
  items: MeetingEvent[]
  columns: string
  sheet: PrintSheet
  tool: PrintTool
  drag: Drag | null
  selectedKey: string | null
  onSelect: (key: string) => void
  onDragStart: (anchor: number, node: HTMLDivElement) => void
  onDragMove: (clientY: number) => void
  onDragEnd: (clientY: number) => void
}): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  const [colHeight, setColHeight] = useState(0)
  const { blocks } = blocksOf(items)
  const pxPerMin = colHeight > 0 ? colHeight / SPAN_MINUTES : 0
  const bands = layoutBands(blocks, pxPerMin, sheet === 'portrait')
  const range = drag && drag.day.getTime() === day.getTime() ? ordered(drag) : null

  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    const measure = (): void => setColHeight(node.clientHeight)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  const now = new Date()
  const nowMinutes = now.getHours() * 60 + now.getMinutes()
  const showNow = sameToday(day) && nowMinutes >= FROM_HOUR * 60 && nowMinutes <= TO_HOUR * 60

  return (
    <div
      ref={ref}
      className={`mcal-day-v-col${sameToday(day) ? ' is-today' : ''}`}
      style={{ ['--mcp-col-template' as string]: columns }}
      onPointerDown={(event) => {
        if (!tool || !ref.current || event.button !== 0) return
        event.preventDefault()
        ref.current.setPointerCapture(event.pointerId)
        onDragStart(minutesAt(ref.current, event.clientY), ref.current)
      }}
      onPointerMove={(event) => {
        if (!tool || !ref.current?.hasPointerCapture(event.pointerId)) return
        onDragMove(event.clientY)
      }}
      onPointerUp={(event) => {
        if (!tool || !ref.current?.hasPointerCapture(event.pointerId)) return
        ref.current.releasePointerCapture(event.pointerId)
        onDragEnd(event.clientY)
      }}
    >
      {HOURS.map((hour) => (
        <div key={hour} className="mcal-line" style={{ top: `${percentOf(hour * 60)}%` }} />
      ))}
      {showNow ? <div className="mcal-now" style={{ top: `${percentOf(nowMinutes)}%` }} /> : null}
      {blocks.map((block, index) => {
        const colors = calendarPalette(colorIndex(block.key))
        const band = bands.get(block.key) ?? { from: block.from, to: block.to, textTo: block.to }
        const boxSpan = Math.max(1, band.to - band.from)
        const textSpan = Math.max(1, Math.min(band.textTo, band.to) - band.from)
        const realSpan = Math.max(1, block.to - block.from)
        const top = percentOf(band.from)
        const height = Math.min(100 - top, percentOf(band.to) - top)
        const slotPct = Math.min(100, (realSpan / boxSpan) * 100)
        const textPct = Math.min(100, (textSpan / boxSpan) * 100)
        const textPx = textSpan * pxPerMin
        const slotPx = realSpan * pxPerMin
        const density = rowDensity(textPx, textSpan, pxPerMin)
        const themeLines = Math.max(1, Math.floor((textPx - 6) / 16))
        const people = peopleOf(block.meeting.attendees)
        const subject = block.meeting.subject.trim() || 'Без темы'
        const room = block.meeting.location.trim()
        const peopleText = people.join('; ')
        const tone = {
          ['--mcp-fill' as string]: colors.fill,
          ['--mcp-border' as string]: colors.border,
          ['--mcp-dot' as string]: colors.dot,
          ['--mcp-ink' as string]: colors.text
        }
        return (
          <article
            key={block.key}
            className={`mcal-event mcp-row${density === 'full' ? '' : ` is-${density}`}${realSpan <= SNAP_MINUTES ? ' is-q15' : ''}${selectedKey === block.key ? ' is-selected' : ''}`}
            title={[subject, room, peopleText].filter(Boolean).join('\n')}
            style={{
              ...tone,
              top: `${top}%`,
              height: `${height}%`,
              left: 0,
              right: 0,
              width: '100%',
              zIndex: 2 + index,
              color: colors.text
            }}
            onClick={(event) => {
              if (tool) return
              event.stopPropagation()
              onSelect(block.key)
            }}
          >
            <div className="mcp-cols mcp-sheet" style={{ gridTemplateColumns: columns }}>
            <div className="mcp-track">
              <div className="mcp-time" style={{ height: `${slotPct}%` }} title={`${timeLabel(block.from)}–${timeLabel(block.to)}`}>
                {slotPx >= 26 ? (
                  <>
                    <span>{timeLabel(block.from)}</span>
                    <span>{timeLabel(block.to)}</span>
                  </>
                ) : (
                  <span className="mcp-time-range">
                    {timeLabel(block.from)}–{timeLabel(block.to)}
                  </span>
                )}
              </div>
            </div>
            <div className="mcp-track mcp-fill" style={{ height: `${textPct}%` }}>
              <div className="mcp-theme">
                <span className="mcp-theme-text" style={density === 'full' ? { WebkitLineClamp: themeLines } : undefined}>
                  {subject}
                </span>
              </div>
            </div>
            <div className="mcp-track mcp-fill" style={{ height: `${textPct}%` }}>
              <div className="mcp-room">{room}</div>
            </div>
            <div className="mcp-track mcp-fill" style={{ height: `${textPct}%` }}>
              <div className="mcp-people">{peopleText}</div>
            </div>
            </div>
          </article>
        )
      })}
      {range && tool ? (
        <div
          className={`mcp-range is-${tool}`}
          style={{ top: `${percentOf(range.from)}%`, height: `${Math.max(percentOf(range.to) - percentOf(range.from), 0.4)}%` }}
        >
          <strong>
            {timeLabel(range.from)}–{timeLabel(range.to)}
          </strong>
          <span>{durationLabel(range.to - range.from)}</span>
        </div>
      ) : null}
    </div>
  )
}

type Band = { from: number; to: number; textTo: number }

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value))
}

function nextStart(sorted: PrintBlock[], index: number): number {
  const from = sorted[index].from
  for (let later = index + 1; later < sorted.length; later += 1) {
    if (sorted[later].from > from) return sorted[later].from
  }
  return TO_HOUR * 60
}

/**
 * Одиночный короткий слот по-прежнему растягивает текст в свободное место.
 * Несколько коротких подряд делят место до следующего совещания поровну,
 * чтобы у каждого хватило высоты хотя бы на строку. На следующее не заходят.
 */
function layoutBands(blocks: PrintBlock[], pxPerMin: number, fillSheet: boolean): Map<string, Band> {
  const sorted = [...blocks].sort((left, right) => left.from - right.from || right.to - left.to)
  const readableMin = pxPerMin > 0 ? clamp(44 / pxPerMin, 20, 75) : 44
  const maxBandMin = pxPerMin > 0 ? clamp(72 / pxPerMin, readableMin, 100) : 72
  const bands = new Map<string, Band>()
  if (fillSheet) {
    sorted.forEach((block, itemIndex) => {
      const limit = itemIndex + 1 < sorted.length ? nextStart(sorted, itemIndex) : TO_HOUR * 60
      bands.set(block.key, soloBand(block, limit, true))
    })
    return bands
  }
  let index = 0
  while (index < sorted.length) {
    const block = sorted[index]
    const duration = block.to - block.from
    if (duration >= readableMin) {
      bands.set(block.key, soloBand(block, nextStart(sorted, index), false))
      index += 1
      continue
    }
    const cluster: PrintBlock[] = [block]
    index += 1
    while (index < sorted.length) {
      const next = sorted[index]
      if (next.to - next.from >= readableMin) break
      const prev = cluster[cluster.length - 1]
      if (next.from >= prev.from + readableMin && next.from >= prev.to) break
      cluster.push(next)
      index += 1
    }
    if (cluster.length === 1) {
      bands.set(block.key, soloBand(block, nextStart(sorted, index - 1), false))
      continue
    }
    const first = cluster[0]
    const last = cluster[cluster.length - 1]
    const following = sorted[index]
    const limit = Math.min(following ? following.from : TO_HOUR * 60, TO_HOUR * 60)
    let windowEnd = Math.min(limit, first.from + maxBandMin * cluster.length)
    windowEnd = Math.max(windowEnd, Math.min(limit, last.to))
    if (windowEnd - first.from < cluster.length) windowEnd = Math.min(TO_HOUR * 60, first.from + cluster.length)
    const share = (windowEnd - first.from) / cluster.length
    cluster.forEach((item, itemIndex) => {
      const from = first.from + share * itemIndex
      const to = itemIndex === cluster.length - 1 ? windowEnd : first.from + share * (itemIndex + 1)
      const end = Math.max(to, from + 0.5)
      bands.set(item.key, { from, to: end, textTo: end })
    })
  }
  return bands
}

function soloBand(block: PrintBlock, limit: number, fillSheet: boolean): Band {
  const duration = block.to - block.from
  const grow = fillSheet ? Math.max(duration, limit - block.from) : duration < 90 ? 90 : duration
  const textTo = Math.min(Math.max(block.to, block.from + grow), limit, TO_HOUR * 60)
  return { from: block.from, to: Math.max(block.to, textTo), textTo }
}

/** Узкая полоса показывает одну строку с многоточием, а не обрезки нескольких. */
function rowDensity(textPx: number, textMin: number, pxPerMin: number): 'tight' | 'brief' | 'full' {
  if (pxPerMin > 0) {
    if (textPx < 22) return 'tight'
    if (textPx < 40) return 'brief'
    return 'full'
  }
  if (textMin < 16) return 'tight'
  if (textMin < 32) return 'brief'
  return 'full'
}

function peopleOf(raw: string): string[] {
  return (raw || '')
    .split(/[,;\n]/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function ordered(drag: Drag): { from: number; to: number } {
  let from = Math.min(drag.anchor, drag.current)
  let to = Math.max(drag.anchor, drag.current)
  from = Math.max(FROM_HOUR * 60, Math.min(from, TO_HOUR * 60))
  to = Math.max(FROM_HOUR * 60, Math.min(to, TO_HOUR * 60))
  if (to - from < SNAP_MINUTES) to = Math.min(TO_HOUR * 60, from + SNAP_MINUTES)
  if (to - from < SNAP_MINUTES) from = Math.max(FROM_HOUR * 60, to - SNAP_MINUTES)
  return { from, to }
}

function colorIndex(key: string): number {
  let hash = 0
  for (const char of key) hash = (hash * 33 + char.charCodeAt(0)) >>> 0
  return hash
}

export function printStamp(day: Date, minutes: number): string {
  return `${day.getFullYear()}-${pad2(day.getMonth() + 1)}-${pad2(day.getDate())} ${timeLabel(minutes)}:00`
}

export const PRINT_DAY_START = FROM_HOUR * 60
export const PRINT_DAY_END = TO_HOUR * 60
export const PRINT_SNAP = SNAP_MINUTES
