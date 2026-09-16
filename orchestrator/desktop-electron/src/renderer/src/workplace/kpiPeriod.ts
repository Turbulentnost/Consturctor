import { addDays, mondayOf } from '../utils/calendar'
import { dayKeyFromDate, type KpiRangeShortcut } from '../pages/KpiRangePicker'

export function currentWeekRange(): { from: string; to: string } {
  const monday = mondayOf(new Date())
  return { from: dayKeyFromDate(monday), to: dayKeyFromDate(addDays(monday, 6)) }
}

export function rollingKpiRange(days: KpiRangeShortcut): { from: string; to: string } {
  const to = new Date()
  const from = addDays(to, -(Number(days) - 1))
  return { from: dayKeyFromDate(from), to: dayKeyFromDate(to) }
}
