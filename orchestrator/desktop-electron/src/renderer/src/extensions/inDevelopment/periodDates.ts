export interface DayRange {
  from: string
  to: string
}

export const MONTHS = [
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

const MONTHS_OF = [
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

const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export function isoDay(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

export function parts(day: string): { year: number; month: number; date: number } {
  const [year, month, date] = day.split('-').map(Number)
  return { year, month: month - 1, date }
}

export function todayIso(): string {
  const now = new Date()
  return isoDay(now.getFullYear(), now.getMonth(), now.getDate())
}

export function spanDays(a: string, b: string): DayRange {
  return a <= b ? { from: a, to: b } : { from: b, to: a }
}

export function rangeLabel(range: DayRange): string {
  const start = parts(range.from)
  const end = parts(range.to)
  if (range.from === range.to) return `${start.date} ${MONTHS_OF[start.month]} ${start.year}`
  if (start.year === end.year && start.month === end.month) {
    return `${start.date}–${end.date} ${MONTHS_OF[start.month]} ${start.year}`
  }
  if (start.year === end.year) {
    return `${start.date} ${MONTHS_OF[start.month]} — ${end.date} ${MONTHS_OF[end.month]} ${start.year}`
  }
  return `${start.date} ${MONTHS_OF[start.month]} ${start.year} — ${end.date} ${MONTHS_OF[end.month]} ${end.year}`
}

export function monthCells(year: number, month: number): Array<string | null> {
  const offset = (new Date(year, month, 1).getDay() + 6) % 7
  const count = new Date(year, month + 1, 0).getDate()
  const cells: Array<string | null> = Array.from({ length: offset }, () => null)
  for (let day = 1; day <= count; day += 1) cells.push(isoDay(year, month, day))
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
}

export function eachDay(range: DayRange): string[] {
  const days: string[] = []
  const cursor = new Date(parts(range.from).year, parts(range.from).month, parts(range.from).date)
  const end = range.to
  while (isoDay(cursor.getFullYear(), cursor.getMonth(), cursor.getDate()) <= end) {
    days.push(isoDay(cursor.getFullYear(), cursor.getMonth(), cursor.getDate()))
    cursor.setDate(cursor.getDate() + 1)
  }
  return days
}

export function defaultPeriod(): DayRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const to = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return {
    from: isoDay(from.getFullYear(), from.getMonth(), from.getDate()),
    to: isoDay(to.getFullYear(), to.getMonth(), to.getDate())
  }
}

export function monthKey(day: string): string {
  return day.slice(0, 7)
}

export function monthTitle(key: string): string {
  const [year, month] = key.split('-').map(Number)
  return `${MONTHS[month - 1]} ${year}`
}

function mondayOf(day: string): string {
  const { year, month, date } = parts(day)
  const cursor = new Date(year, month, date)
  cursor.setDate(cursor.getDate() - ((cursor.getDay() + 6) % 7))
  return isoDay(cursor.getFullYear(), cursor.getMonth(), cursor.getDate())
}

export function weekKey(day: string): string {
  return `${monthKey(day)}:${mondayOf(day)}`
}

export function weekTitle(days: string[]): string {
  const start = parts(days[0])
  const end = parts(days[days.length - 1])
  if (days.length === 1) return `нед. ${start.date} ${MONTHS_SHORT[start.month]}`
  if (start.month === end.month) return `нед. ${start.date}–${end.date} ${MONTHS_SHORT[start.month]}`
  return `нед. ${start.date} ${MONTHS_SHORT[start.month]}–${end.date} ${MONTHS_SHORT[end.month]}`
}

export function dayHeading(day: string): { num: string; weekday: string } {
  const { year, month, date } = parts(day)
  const weekday = WEEKDAYS[(new Date(year, month, date).getDay() + 6) % 7]
  return { num: String(date), weekday }
}

export type PeriodColumn =
  | { id: string; kind: 'month'; title: string; days: string[]; month: string }
  | { id: string; kind: 'week'; title: string; days: string[]; week: string }
  | { id: string; kind: 'day'; title: string; weekday: string; days: string[] }

export interface PeriodGroup {
  id: string
  title: string
  month: string
  open: boolean
  columns: PeriodColumn[]
}

export function buildPeriodColumns(days: string[], openMonth: string, openWeek: string): PeriodGroup[] {
  const months: string[] = []
  for (const day of days) {
    const key = monthKey(day)
    if (months[months.length - 1] !== key) months.push(key)
  }
  return months.map((month) => {
    const monthDays = days.filter((day) => monthKey(day) === month)
    if (month !== openMonth) {
      return {
        id: month,
        title: monthTitle(month),
        month,
        open: false,
        columns: [
          {
            id: `month:${month}`,
            kind: 'month' as const,
            title: monthTitle(month),
            days: monthDays,
            month
          }
        ]
      }
    }
    const weeks: Array<{ key: string; days: string[] }> = []
    for (const day of monthDays) {
      const key = weekKey(day)
      const last = weeks[weeks.length - 1]
      if (last?.key === key) last.days.push(day)
      else weeks.push({ key, days: [day] })
    }
    const columns: PeriodColumn[] = []
    for (const week of weeks) {
      if (week.key !== openWeek) {
        columns.push({
          id: `week:${week.key}`,
          kind: 'week',
          title: weekTitle(week.days),
          days: week.days,
          week: week.key
        })
      } else {
        for (const day of week.days) {
          const heading = dayHeading(day)
          columns.push({
            id: `day:${day}`,
            kind: 'day',
            title: heading.num,
            weekday: heading.weekday,
            days: [day]
          })
        }
      }
    }
    return { id: month, title: monthTitle(month), month, open: true, columns }
  })
}

export function firstWeekInMonth(days: string[], month: string): string {
  const day = days.find((item) => monthKey(item) === month) ?? days[0]
  return weekKey(day)
}

export function initialOpen(days: string[]): { month: string; week: string } {
  const today = todayIso()
  const focus = days.includes(today) ? today : days[0]
  const month = monthKey(focus)
  return { month, week: weekKey(focus) }
}
