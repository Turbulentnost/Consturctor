import { Fragment } from 'react'
import {
  isOutlookFolderOwner,
  meetingFormatHint,
  meetingInstanceKey,
  parseMeetingTime,
  type MeetingEvent
} from '../../utils/outlookMeetings'
import { isoWeekday, WEEKDAYS } from '../../utils/calendar'

export type PrintField = 'subject' | 'time' | 'location' | 'format' | 'organizer' | 'attendees' | 'owner'

/** Высота области строк на листе A4 альбомный (мм), без заголовка и шкалы часов. */
const BODY_MM = 176
/** Высота заголовка дня (мм). */
const GROUP_MM = 6
/** Золотой угол: соседние совещания получают заметно разные оттенки. */
const GOLDEN_ANGLE = 137.508
/** Сколько участников показываем по именам в обычной плотности; остальные — числом. */
const NAMED_ATTENDEES = 2

type Density = 'normal' | 'dense' | 'compact'

type PrintBlock = {
  meeting: MeetingEvent
  from: number
  to: number
  start: Date | null
  end: Date | null
}

type PrintRow = PrintBlock & { key: string; solid: string; soft: string }

type PrintGroup = { day: Date; rows: PrintRow[] }

function timeLabel(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function printSpan(meeting: MeetingEvent): PrintBlock | null {
  const start = parseMeetingTime(meeting.start)
  if (!start) return null
  const end = parseMeetingTime(meeting.end)
  const from = start.getHours() * 60 + start.getMinutes()
  let to = end ? end.getHours() * 60 + end.getMinutes() : from + 30
  if (end && (end.getDate() !== start.getDate() || end.getMonth() !== start.getMonth())) to = 24 * 60
  if (to <= from) to = from + 30
  return { meeting, from, to, start, end }
}

function meetingColor(index: number): { solid: string; soft: string } {
  const hue = Math.round((index * GOLDEN_ANGLE) % 360)
  return { solid: `hsl(${hue} 58% 40%)`, soft: `hsl(${hue} 60% 96%)` }
}

function attendeesText(raw: string, density: Density): string {
  const attendees = (raw || '')
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)
  if (!attendees.length) return '—'
  if (density !== 'normal') return `${attendees.length} чел.`
  if (attendees.length <= NAMED_ATTENDEES) return attendees.join(', ')
  return `${attendees.slice(0, NAMED_ATTENDEES).join(', ')} и ещё ${attendees.length - NAMED_ATTENDEES}`
}

function calloutParts(
  row: PrintBlock,
  fields: Record<PrintField, boolean>,
  density: Density
): {
  title: string
  time: string
  meta: string[]
} {
  const { meeting, start, end } = row
  const owner =
    meeting.owner && !isOutlookFolderOwner(meeting.owner) ? meeting.owner : 'Мой календарь'
  return {
    title: fields.subject ? meeting.subject || '—' : '',
    time: fields.time
      ? start
        ? `${timeLabel(start)}${end ? `–${timeLabel(end)}` : ''}`
        : '—'
      : '',
    meta: [
      fields.location ? `Место: ${meeting.location || '—'}` : '',
      fields.format ? meetingFormatHint(meeting.location) : '',
      fields.organizer ? `Организатор: ${meeting.organizer || '—'}` : '',
      fields.attendees ? `Участники: ${attendeesText(meeting.attendees || '', density)}` : '',
      fields.owner ? `Владелец: ${owner}` : ''
    ].filter(Boolean)
  }
}

/**
 * Лист A4 альбомный: шкала времени сверху, по строке на совещание.
 * Цветная полоса показывает время, текст — в свободной части строки
 * (справа или слева от полосы, где больше места). Каждое совещание — свой цвет.
 */
export function PrintSchedule({
  days,
  fields,
  title
}: {
  days: { day: Date; items: MeetingEvent[] }[]
  fields: Record<PrintField, boolean>
  title: string
}): React.JSX.Element {
  const blocksByDay = days
    .map((group) => ({
      day: group.day,
      blocks: group.items
        .map((meeting) => printSpan(meeting))
        .filter((block): block is PrintBlock => block != null)
        .sort((left, right) => left.from - right.from)
    }))
    .filter((group) => group.blocks.length > 0)

  let colorIndex = 0
  const groups: PrintGroup[] = blocksByDay.map((group) => ({
    day: group.day,
    rows: group.blocks.map((block) => {
      const color = meetingColor(colorIndex)
      colorIndex += 1
      return { ...block, key: `${meetingInstanceKey(block.meeting)}-${colorIndex}`, ...color }
    })
  }))
  const allRows = groups.flatMap((group) => group.rows)

  let fromHour = 8
  let toHour = 19
  for (const row of allRows) {
    fromHour = Math.min(fromHour, Math.floor(row.from / 60))
    toHour = Math.max(toHour, Math.ceil(row.to / 60))
  }
  fromHour = Math.max(0, fromHour)
  toHour = Math.min(24, Math.max(toHour, fromHour + 1))
  const hours = Array.from({ length: toHour - fromHour + 1 }, (_, index) => fromHour + index)
  const spanMinutes = (toHour - fromHour) * 60
  const percentOf = (minutes: number): number => ((minutes - fromHour * 60) / spanMinutes) * 100

  const rowCount = Math.max(1, allRows.length)
  const rowMm = (BODY_MM - GROUP_MM * groups.length) / rowCount
  const density: Density = rowMm >= 12 ? 'normal' : rowMm >= 7 ? 'dense' : 'compact'

  return (
    <>
      <h3 className="mcal-print-date">{title}</h3>
      <div className={`mcp-sheet is-${density}`}>
        <div className="mcp-axis">
          {hours.map((hour) => (
            <span key={hour} className="mcp-hour" style={{ left: `${percentOf(hour * 60)}%` }}>
              {hour}:00
            </span>
          ))}
        </div>
        <div className="mcp-body">
          <div className="mcp-grid" aria-hidden>
            {hours.map((hour) => (
              <i key={hour} style={{ left: `${percentOf(hour * 60)}%` }} />
            ))}
          </div>
          {groups.map((group) => (
            <Fragment key={group.day.toISOString()}>
              <div className="mcp-group">{WEEKDAYS[isoWeekday(group.day)].toLocaleUpperCase('ru')}</div>
              {group.rows.map((row) => {
                const left = percentOf(row.from)
                const right = percentOf(row.to)
                const barWidth = Math.max(right - left, 0.5)
                const placeRight = 100 - right >= left
                const parts = calloutParts(row, fields, density)
                const empty = !parts.title && !parts.time && parts.meta.length === 0
                const calloutStyle = placeRight
                  ? { left: `calc(${right}% + 2mm)`, right: 0 }
                  : { left: 0, right: `calc(${100 - left}% + 2mm)` }
                return (
                  <div key={row.key} className="mcp-row">
                    <div
                      className="mcp-bar"
                      style={{ left: `${left}%`, width: `${barWidth}%`, background: row.solid }}
                    />
                    <div
                      className="mcp-callout"
                      style={{ ...calloutStyle, background: row.soft, borderLeftColor: row.solid }}
                    >
                      <CalloutText parts={parts} empty={empty} />
                    </div>
                  </div>
                )
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </>
  )
}

function CalloutText({
  parts,
  empty
}: {
  parts: { title: string; time: string; meta: string[] }
  empty: boolean
}): React.JSX.Element {
  if (empty) return <span>—</span>
  return (
    <>
      {parts.title ? <strong>{parts.title}</strong> : null}
      {parts.time ? <span className="mcp-time">{parts.time}</span> : null}
      {parts.meta.length ? <span className="mcp-meta">{parts.meta.join(' · ')}</span> : null}
    </>
  )
}
