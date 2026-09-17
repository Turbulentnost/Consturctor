import { useMemo } from 'react'
import type { UserProfile } from '../api/types'
import { sameDay } from '../utils/calendar'
import { countMeetingsOnDay } from '../utils/outlookMeetings'
import type { SpecSummaryTile } from './specV04Shell'
import type { SpecTaskRow } from './specV04DemoData'
import { compareTasksByUrgency, filterOnecTodayRows, isDocflowFromMe } from './tileFilters'
import { summarizeDayLaunches } from './todayKpiLaunches'
import type { TodayTileAlertFlags } from './todayTileAlerts'
import { type SpecV04SourcesState, useSpecV04Sources } from './useSpecV04Data'
import { isTodayOrOverdueProjectTask } from './useTodayProjectTasks'

function pct(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((done / total) * 100)
}

function dash(loading: boolean, text: string): string {
  return loading ? '—' : text
}

function factPlan(done: number, total: number): string {
  return total ? `${done} из ${total}` : '—'
}

/** Подпись плитки «Проекты»: источник или разбивка задач по проектам. */
export function todayProjectTaskHint(tasks: SpecTaskRow[]): string {
  const counts = new Map<string, number>()
  for (const task of tasks) {
    const name = (task.project || task.process || '').trim()
    if (!name || name === '—') continue
    counts.set(name, (counts.get(name) || 0) + 1)
  }
  const rows = [...counts.entries()].sort((left, right) => {
    if (right[1] !== left[1]) return right[1] - left[1]
    return left[0].localeCompare(right[0], 'ru')
  })
  if (!rows.length) return 'TurboProject'
  if (rows.length === 1) return rows[0][0]
  return rows
    .slice(0, 3)
    .map(([name, count]) => `${name}: ${count}`)
    .join(' · ')
}

/**
 * KPI «Сегодня»: факт/план за выбранный день.
 * День = фильтр «Период». Чат и lastRunStatus карточки не входят.
 */
export function buildTodayKpiTiles(
  data: SpecV04SourcesState,
  periodDay = new Date(),
  onecRows?: SpecTaskRow[],
  alerts: Partial<TodayTileAlertFlags> = {}
): SpecSummaryTile[] {
  const loading = data.loading
  const launches = summarizeDayLaunches(data.boardEvents || [], data.boardAgents || [], periodDay)

  const onecToday =
    onecRows ?? filterOnecTodayRows(data.erpTasks || [], periodDay, { actorFio: data.erpFio })
  const onecTotal = onecToday.length
  const onecDone = onecToday.filter((task) => task.status === 'Выполнена').length

  const dayTotal = onecTotal + launches.slotCount
  const dayDone = onecDone + launches.slotDone
  const dayPct = loading ? undefined : pct(dayDone, dayTotal || 1)

  const regTotal = launches.agentIds.length
  const regDone = launches.agentDoneIds.length

  const projTasks = (data.turboTasks || []).filter((task) =>
    isTodayOrOverdueProjectTask(task, periodDay)
  )
  const projTaskTotal = projTasks.length
  const projLoading = Boolean(data.turboLoading) && !projTaskTotal
  const meetToday = countMeetingsOnDay(data.meetings || [], periodDay)
  const meetingsLoading = Boolean(data.meetingsLoading) && !meetToday
  const periodIsToday = sameDay(periodDay, new Date())

  return [
    {
      id: 'day',
      label: 'Выполнение дня',
      value: dash(loading, factPlan(dayDone, dayTotal)),
      hint: loading
        ? 'загрузка…'
        : dayTotal
          ? '1С + запуски по расписанию'
          : 'нет задач на учёте',
      tone: 'orange',
      progress: dayPct,
      ring: true
    },
    {
      id: 'onec',
      label: 'Задачи из 1С',
      value: dash(loading, String(onecTotal)),
      hint: loading
        ? 'загрузка…'
        : onecTotal
          ? 'срок сегодня и просроченные'
          : 'нет срока сегодня и просроченных',
      tone: 'blue',
      progress: loading || !onecTotal ? undefined : pct(onecDone, onecTotal),
      ring: Boolean(onecTotal && onecDone)
    },
    {
      id: 'reg',
      label: 'Регламентные работы',
      value: dash(loading, factPlan(regDone, regTotal)),
      hint: loading
        ? 'загрузка…'
        : regTotal
          ? 'успешные / должны запуститься сегодня'
          : 'нет запусков по расписанию',
      tone: 'green',
      progress: loading ? undefined : pct(regDone, regTotal || 1),
      ring: true
    },
    {
      id: 'proj',
      label: 'Проекты',
      value: dash(projLoading, projTaskTotal ? String(projTaskTotal) : '—'),
      hint: projLoading ? 'загрузка…' : todayProjectTaskHint(projTasks),
      tone: 'purple'
    },
    {
      id: 'ev',
      label: 'События дня',
      value: dash(meetingsLoading, meetToday ? String(meetToday) : '—'),
      hint: meetingsLoading ? 'загрузка…' : periodIsToday ? 'Outlook, сегодня' : 'Outlook',
      tone: 'yellow',
      notify: Boolean(alerts.meet)
    }
  ]
}

export function useTodayKpiData(
  user: UserProfile | null,
  periodDay: Date = new Date(),
  alerts: Partial<TodayTileAlertFlags> = {}
): {
  data: SpecV04SourcesState
  tiles: SpecSummaryTile[]
  /** Same rows the «Задачи из 1С» tile counts — table must render this list. */
  onecTodayRows: SpecTaskRow[]
} {
  const data = useSpecV04Sources(user)
  const onecTodayRows = useMemo(
    () =>
      filterOnecTodayRows(data.erpTasks || [], periodDay, { actorFio: data.erpFio }).sort(
        compareTasksByUrgency
      ),
    [data.erpFio, data.erpTasks, periodDay]
  )
  const tiles = useMemo(
    () => buildTodayKpiTiles(data, periodDay, onecTodayRows, alerts),
    [alerts, data, onecTodayRows, periodDay]
  )
  return { data, tiles, onecTodayRows }
}

export function onecTodayRowsForTable(
  rows: SpecTaskRow[],
  fromMe: boolean,
  actorFio: string
): SpecTaskRow[] {
  if (!fromMe) return rows
  return rows.filter((row) => isDocflowFromMe(row, actorFio))
}
