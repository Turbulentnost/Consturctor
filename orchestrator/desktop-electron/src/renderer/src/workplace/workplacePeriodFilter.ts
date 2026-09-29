import { dayKeyFromDate } from '../pages/KpiRangePicker'
import { parseIso } from '../utils/calendar'
import { parseTaskDueDate } from './tileFilters'

export function orderedWorkplaceDayKeys(from: string, to: string): { from: string; to: string } {
  if (!from || !to) return { from: from || to, to: to || from }
  return from <= to ? { from, to } : { from: to, to: from }
}

/** Если дату не удалось распознать — строку не отсекаем (открытые задачи без срока). */
export function isDayKeyInWorkplacePeriod(
  dayKey: string | null | undefined,
  from: string,
  to: string
): boolean {
  if (!dayKey) return true
  if (!from || !to) return true
  const range = orderedWorkplaceDayKeys(from, to)
  return dayKey >= range.from && dayKey <= range.to
}

export function dateLabelToDayKey(raw: string | undefined | null): string | null {
  const text = String(raw || '').trim()
  if (!text || text === '—') return null
  const fromDeadline = parseTaskDueDate(text)
  if (fromDeadline) return dayKeyFromDate(fromDeadline)
  const iso = parseIso(text) || parseIso(text.replace(' ', 'T'))
  if (iso) return dayKeyFromDate(iso)
  return null
}

export function deadlineInWorkplacePeriod(deadline: string | undefined, from: string, to: string): boolean {
  return isDayKeyInWorkplacePeriod(dateLabelToDayKey(deadline), from, to)
}

export function isoTimestampInWorkplacePeriod(iso: string | undefined, from: string, to: string): boolean {
  const text = String(iso || '').trim()
  if (!text) return true
  const stamp = parseIso(text)
  if (!stamp) return true
  return isDayKeyInWorkplacePeriod(dayKeyFromDate(stamp), from, to)
}
