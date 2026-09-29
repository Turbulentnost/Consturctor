import type { AssignmentRegistryRow } from './assignmentRegistryTypes'
import { parseRegistryDay } from './assignmentRegistryMappers'

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

export function isBusinessDay(date: Date): boolean {
  const day = date.getDay()
  return day >= 1 && day <= 5
}

/** Понедельник текущей календарной недели. */
export function startOfCalendarWeek(date: Date): Date {
  const d = startOfDay(date)
  const weekday = d.getDay()
  const diff = weekday === 0 ? -6 : 1 - weekday
  d.setDate(d.getDate() + diff)
  return d
}

export function endOfCalendarWeek(date: Date): Date {
  const end = startOfCalendarWeek(date)
  end.setDate(end.getDate() + 6)
  return end
}

/** Последний день окна из N рабочих дней, начиная с today (включительно). */
export function endOfBusinessDaysWindow(today: Date, businessDays: number): Date {
  let cursor = startOfDay(today)
  let left = businessDays
  while (left > 0) {
    if (isBusinessDay(cursor)) left -= 1
    if (left > 0) cursor.setDate(cursor.getDate() + 1)
  }
  return cursor
}

export function isDueWithinBusinessDays(
  row: AssignmentRegistryRow,
  businessDays: number,
  today = new Date()
): boolean {
  if (!row.open || row.overdue) return false
  const due = parseRegistryDay(row.fullRemediationDue)
  if (!due) return false
  const start = startOfDay(today)
  const end = endOfBusinessDaysWindow(today, businessDays)
  return due >= start && due <= end
}

export function isClosedThisWeek(row: AssignmentRegistryRow, today = new Date()): boolean {
  if (row.open) return false
  const closed =
    parseRegistryDay(row.finalReportDate) ||
    parseRegistryDay(row.weeklyReportDate) ||
    parseRegistryDay(row.date)
  if (!closed) return false
  const weekStart = startOfCalendarWeek(today)
  const weekEnd = endOfCalendarWeek(today)
  return closed >= weekStart && closed <= weekEnd
}

export function isReportOverdue(row: AssignmentRegistryRow): boolean {
  return row.open && row.overdue
}

/** Строки для печати/PDF: просроченные, закрытые за неделю, срок в 3 рабочих дня. */
export function selectRegistryReportRows(
  rows: AssignmentRegistryRow[],
  today = new Date()
): {
  overdue: AssignmentRegistryRow[]
  closedThisWeek: AssignmentRegistryRow[]
  dueSoon: AssignmentRegistryRow[]
  all: AssignmentRegistryRow[]
} {
  const overdue = rows.filter(isReportOverdue)
  const closedThisWeek = rows.filter((row) => isClosedThisWeek(row, today))
  const dueSoon = rows.filter((row) => isDueWithinBusinessDays(row, 3, today))

  const seen = new Set<string>()
  const all: AssignmentRegistryRow[] = []
  for (const row of [...overdue, ...closedThisWeek, ...dueSoon]) {
    if (seen.has(row.id)) continue
    seen.add(row.id)
    all.push(row)
  }
  return { overdue, closedThisWeek, dueSoon, all }
}
