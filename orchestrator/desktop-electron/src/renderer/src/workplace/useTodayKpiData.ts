import { useMemo } from 'react'
import type { UserProfile } from '../api/types'
import { sameDay } from '../utils/calendar'
import { countMeetingsOnDay } from '../utils/outlookMeetings'
import type { SpecSummaryTile } from './specV04Shell'
import { isTurboPinPlaceholder } from './orchestratorTaskSources'
import { summarizeDayLaunches } from './todayKpiLaunches'
import { type SpecV04SourcesState, useSpecV04Sources } from './useSpecV04Data'

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

/**
 * KPI «Сегодня»: факт/план за выбранный день.
 * День = фильтр «Период». Чат и lastRunStatus карточки не входят.
 */
export function buildTodayKpiTiles(data: SpecV04SourcesState, periodDay = new Date()): SpecSummaryTile[] {
  const loading = data.loading
  const launches = summarizeDayLaunches(data.boardEvents || [], data.boardAgents || [], periodDay)

  const onecTotal = data.erpTaskCount
  const onecDone = data.erpTasks.filter((task) => task.status === 'Выполнена').length

  const dayTotal = onecTotal + launches.slotCount
  const dayDone = onecDone + launches.slotDone
  const dayPct = loading ? undefined : pct(dayDone, dayTotal || 1)

  const regTotal = launches.agentIds.length
  const regDone = launches.agentDoneIds.length

  const projects = (data.projects || []).filter((project) => !isTurboPinPlaceholder(project))
  const projTotal = projects.length
  const meetToday = countMeetingsOnDay(data.meetings || [], periodDay)
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
      value: dash(loading, factPlan(onecDone, onecTotal)),
      hint: loading ? 'загрузка…' : onecTotal ? 'срок дня и просроченные' : 'сегодня и просроченные',
      tone: 'blue',
      progress: loading ? undefined : pct(onecDone, onecTotal || 1),
      ring: true
    },
    {
      id: 'reg',
      label: 'Регламентные работы',
      value: dash(loading, factPlan(regDone, regTotal)),
      hint: loading
        ? 'загрузка…'
        : regTotal
          ? 'агенты с запуском за день'
          : 'агенты Constructor',
      tone: 'green',
      progress: loading ? undefined : pct(regDone, regTotal || 1),
      ring: true
    },
    {
      id: 'proj',
      label: 'Проекты',
      value: dash(loading, projTotal ? String(projTotal) : '—'),
      hint: loading ? 'загрузка…' : 'TurboProject',
      tone: 'purple'
    },
    {
      id: 'ev',
      label: 'События дня',
      value: dash(loading, meetToday ? String(meetToday) : '—'),
      hint: loading ? 'загрузка…' : periodIsToday ? 'Outlook, сегодня' : 'Outlook',
      tone: 'yellow'
    }
  ]
}

export function useTodayKpiData(
  user: UserProfile | null,
  periodDay: Date = new Date()
): {
  data: SpecV04SourcesState
  tiles: SpecSummaryTile[]
} {
  const data = useSpecV04Sources(user)
  const tiles = useMemo(() => buildTodayKpiTiles(data, periodDay), [data, periodDay])
  return { data, tiles }
}
