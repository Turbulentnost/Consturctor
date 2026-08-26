import type { CalendarEvent } from '../api/types'

export type CalendarView = 'day' | 'week' | 'month'

export const MONTHS_GEN = [
  '',
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря'
]

export const MONTH_TITLE = [
  '',
  'январь',
  'февраль',
  'март',
  'апрель',
  'май',
  'июнь',
  'июль',
  'август',
  'сентябрь',
  'октябрь',
  'ноябрь',
  'декабрь'
]

export const DAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
export const WEEKDAYS = [
  'Понедельник',
  'Вторник',
  'Среда',
  'Четверг',
  'Пятница',
  'Суббота',
  'Воскресенье'
]

export interface StatusStyle {
  bg: string
  border: string
  label: string
}

export const STATUS_STYLE: Record<string, StatusStyle> = {
  scheduled: { bg: '#E8F6F1', border: '#08745F', label: 'Запланирован' },
  running: { bg: '#E8F1FB', border: '#2F6FED', label: 'Выполняется' },
  ok: { bg: '#F7FBF9', border: '#5B8F7E', label: 'Выполнен' },
  missed: { bg: '#F7F3EA', border: '#B0893A', label: 'Не запущен' },
  error: { bg: '#FDECEC', border: '#D64545', label: 'Ошибка' },
  paused: { bg: '#F2F4F3', border: '#8A9692', label: 'Приостановлен' }
}

export const SOURCE_LABEL: Record<string, string> = {
  schedule: 'по расписанию',
  manual: 'вручную',
  event: 'по событию'
}

/** Parse an ISO timestamp (UTC or offset) into a local Date, or null. */
export function parseIso(value: string): Date | null {
  const raw = (value || '').trim()
  if (!raw) return null
  const stamp = new Date(raw)
  if (Number.isNaN(stamp.getTime())) return null
  return stamp
}

/** Monday (weekday index 0) of the week containing `day`. */
export function mondayOf(day: Date): Date {
  const copy = new Date(day.getFullYear(), day.getMonth(), day.getDate())
  const weekday = (copy.getDay() + 6) % 7
  copy.setDate(copy.getDate() - weekday)
  return copy
}

export function isoWeekday(day: Date): number {
  return (day.getDay() + 6) % 7
}

export function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export function addDays(day: Date, count: number): Date {
  const copy = new Date(day.getFullYear(), day.getMonth(), day.getDate())
  copy.setDate(copy.getDate() + count)
  return copy
}

export function formatPeriod(view: CalendarView, anchor: Date): string {
  if (view === 'day') {
    return `${anchor.getDate()} ${MONTHS_GEN[anchor.getMonth() + 1]} ${anchor.getFullYear()}`
  }
  if (view === 'month') {
    return `${MONTH_TITLE[anchor.getMonth() + 1]} ${anchor.getFullYear()}`
  }
  const start = mondayOf(anchor)
  const end = addDays(start, 6)
  if (start.getMonth() === end.getMonth()) {
    return `${start.getDate()}-${end.getDate()} ${MONTHS_GEN[start.getMonth() + 1]} ${start.getFullYear()}`
  }
  return `${start.getDate()} ${MONTHS_GEN[start.getMonth() + 1]} - ${end.getDate()} ${MONTHS_GEN[end.getMonth() + 1]} ${end.getFullYear()}`
}

/** UTC ISO window [start, end) for the given view/anchor (local boundaries). */
export function windowFor(view: CalendarView, anchor: Date): { from: string; to: string } {
  let start: Date
  let end: Date
  if (view === 'day') {
    start = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
    end = addDays(start, 1)
  } else if (view === 'month') {
    start = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)
  } else {
    start = mondayOf(anchor)
    end = addDays(start, 7)
  }
  return { from: start.toISOString(), to: end.toISOString() }
}

export function shiftAnchor(view: CalendarView, anchor: Date, step: number): Date {
  if (view === 'day') return addDays(anchor, step)
  if (view === 'month') return new Date(anchor.getFullYear(), anchor.getMonth() + step, 1)
  return addDays(anchor, 7 * step)
}

export function ruPlural(n: number, one: string, few: string, many: string): string {
  const value = Math.abs(Math.trunc(n))
  if (value % 10 === 1 && value % 100 !== 11) return one
  if ([2, 3, 4].includes(value % 10) && ![12, 13, 14].includes(value % 100)) return few
  return many
}

export function agentsWord(n: number): string {
  return ruPlural(n, 'агент', 'агента', 'агентов')
}

export function activeWord(n: number): string {
  return ruPlural(n, 'активен', 'активны', 'активны')
}

export function runsWord(n: number): string {
  return ruPlural(n, 'запуск', 'запуска', 'запусков')
}

export function errorsWord(n: number): string {
  return ruPlural(n, 'ошибка', 'ошибки', 'ошибок')
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function hhmm(stamp: Date): string {
  return `${pad2(stamp.getHours())}:${pad2(stamp.getMinutes())}`
}

export function nextRunTile(value: string): string {
  const stamp = parseIso(value)
  if (stamp === null) return 'Ближайший - нет'
  const now = new Date()
  if (stamp <= now) return 'Ближайший - сейчас'
  if (sameDay(stamp, now)) return `Ближайший - ${hhmm(stamp)}`
  if (sameDay(stamp, addDays(now, 1))) return `Ближайший - завтра, ${hhmm(stamp)}`
  return `Ближайший - ${pad2(stamp.getDate())}.${pad2(stamp.getMonth() + 1)}, ${hhmm(stamp)}`
}

export function humanWhen(stamp: Date): string {
  const now = new Date()
  if (sameDay(stamp, now)) return `сегодня, ${hhmm(stamp)}`
  if (sameDay(stamp, addDays(now, 1))) return `завтра, ${hhmm(stamp)}`
  return `${pad2(stamp.getDate())}.${pad2(stamp.getMonth() + 1)}.${stamp.getFullYear()}, ${hhmm(stamp)}`
}

export function runLine(prefix: string, value: string): string {
  const stamp = parseIso(value)
  if (stamp === null) return `${prefix}: не было`
  return `${prefix}: ${humanWhen(stamp)}`
}

export function clip(text: string, limit: number): string {
  const value = (text || '').split(/\s+/).filter(Boolean).join(' ')
  if (value.length <= limit) return value
  return value.slice(0, limit - 1).trimEnd() + '…'
}

export function slotKey(event: CalendarEvent): string {
  const stamp = parseIso(event.startAt)
  if (stamp === null) return `none:${event.id}`
  return `${stamp.getFullYear()}-${stamp.getMonth()}-${stamp.getDate()}:${stamp.getHours()}`
}

/** Group events by (day, hour) slot, keeping first-seen order, each bucket sorted by start. */
export function groupBySlot(events: CalendarEvent[]): CalendarEvent[][] {
  const buckets = new Map<string, CalendarEvent[]>()
  const order: string[] = []
  for (const item of events) {
    const key = slotKey(item)
    if (!buckets.has(key)) {
      buckets.set(key, [])
      order.push(key)
    }
    buckets.get(key)!.push(item)
  }
  return order.map((key) =>
    [...buckets.get(key)!].sort((a, b) => a.startAt.localeCompare(b.startAt))
  )
}

export function groupHeading(events: CalendarEvent[]): string {
  const stamp = events.length ? parseIso(events[0].startAt) : null
  if (stamp === null) return 'Запуски'
  return `${WEEKDAYS[isoWeekday(stamp)]}, ${stamp.getDate()} ${MONTHS_GEN[stamp.getMonth() + 1]}  ·  ${pad2(stamp.getHours())}:00`
}

export function groupSummary(events: CalendarEvent[]): { title: string; subtitle: string; color: string } {
  const n = events.length
  const stamp = n ? parseIso(events[0].startAt) : null
  const timeText = stamp ? `${pad2(stamp.getHours())}:00` : ''
  const title = `${timeText}  ·  ${n} ${runsWord(n)}`
  const errors = events.filter((item) => item.status === 'error').length
  const running = events.filter((item) => item.status === 'running').length
  const sameAgent = new Set(events.map((item) => item.workflowId)).size === 1
  if (errors) return { title, subtitle: `${errors} ${errorsWord(errors)}`, color: '#D64545' }
  if (running) return { title, subtitle: `Выполняются ${running} из ${n}`, color: '#2F6FED' }
  if (events.every((item) => item.status === 'missed'))
    return { title, subtitle: 'Не запущены', color: '#B0893A' }
  if (events.every((item) => item.status === 'scheduled'))
    return { title, subtitle: 'Запланировано', color: '#08745F' }
  if (sameAgent) return { title, subtitle: 'История', color: '#6B7773' }
  if (events.every((item) => item.status === 'ok'))
    return { title, subtitle: 'Выполнено', color: '#5B8F7E' }
  const fallback = STATUS_STYLE[events[0]?.status] ?? STATUS_STYLE.scheduled
  return { title, subtitle: fallback.label, color: '#6B7773' }
}

export function timeText(value: string): string {
  const stamp = parseIso(value)
  return stamp ? hhmm(stamp) : ''
}

/** For local datetime-local input value -> ISO string with local timezone offset. */
export function localInputToIso(value: string): string {
  if (!value) return ''
  const stamp = new Date(value)
  if (Number.isNaN(stamp.getTime())) return ''
  return stamp.toISOString()
}

/** Current local time formatted for a datetime-local input (yyyy-MM-ddThh:mm). */
export function nowForInput(): string {
  const now = new Date()
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}T${pad2(now.getHours())}:${pad2(now.getMinutes())}`
}
