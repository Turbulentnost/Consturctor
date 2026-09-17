import { useMemo } from 'react'
import type { SpecPillTone, SpecTaskRow } from './specV04DemoData'
import type { SpecV04SourcesState } from './useSpecV04Data'

export type TodayProjectTaskRow = {
  id: string
  title: string
  deadline: string
  status: string
  statusTone: SpecPillTone
  assignee: string
  assigneeTone: SpecPillTone
  turboScope?: 'mine' | 'managed' | 'both'
}

function dayStamp(day: Date): string {
  const dd = String(day.getDate()).padStart(2, '0')
  const mm = String(day.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}`
}

function isSameCalendarDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

/** Задачи на выбранный день и просроченные: мне + проекты, где я руководитель. */
export function isTodayOrOverdueProjectTask(row: SpecTaskRow, day: Date): boolean {
  if (row.urgent) return true
  const deadline = (row.deadline || '').trim()
  if (!deadline || deadline === '—') return false
  const stamp = dayStamp(day)
  if (deadline === stamp || deadline.startsWith(`${stamp} `)) return true
  if (deadline.toLowerCase().startsWith('сегодня')) return isSameCalendarDay(day, new Date())
  return false
}

function specTaskToTodayRow(row: SpecTaskRow): TodayProjectTaskRow {
  const assignee = (row.who || row.executor || '—').trim() || '—'
  const assigneeTone: SpecPillTone = /^(ии|ai|агент)/i.test(assignee)
    ? 'purple'
    : assignee === '—'
      ? 'gray'
      : 'blue'
  return {
    id: row.id,
    title: row.title,
    deadline: row.deadline,
    status: row.status,
    statusTone: row.statusTone,
    assignee,
    assigneeTone,
    turboScope: row.turboScope
  }
}

export interface TodayProjectTasksState {
  loading: boolean
  noSession: boolean
  error: string
  rows: TodayProjectTaskRow[]
}

export function useTodayProjectTasks(
  periodDay: Date,
  spec: Pick<
    SpecV04SourcesState,
    'sourcesLoading' | 'turboLoading' | 'turboNoSession' | 'turboTasks' | 'turboError'
  >
): TodayProjectTasksState {
  const rows = useMemo(() => {
    if (spec.turboNoSession) return []
    return spec.turboTasks
      .filter((row) => isTodayOrOverdueProjectTask(row, periodDay))
      .map(specTaskToTodayRow)
  }, [periodDay, spec.turboNoSession, spec.turboTasks])

  const waiting = (spec.turboLoading || spec.sourcesLoading) && spec.turboTasks.length === 0
  return {
    loading: waiting && !spec.turboNoSession,
    noSession: spec.turboNoSession,
    error: rows.length ? '' : spec.turboError,
    rows
  }
}
