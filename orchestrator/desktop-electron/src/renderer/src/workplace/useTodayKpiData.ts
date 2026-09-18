import { useMemo } from 'react'
import type { UserProfile } from '../api/types'
import { sameDay } from '../utils/calendar'
import { countMeetingsOnDay } from '../utils/outlookMeetings'
import type { SpecSummaryTile } from './specV04Shell'
import { isTurboPinPlaceholder } from './orchestratorTaskSources'
import { summarizeDayLaunches } from './todayKpiLaunches'
import {
  isDocflowFromMe,
  isDocflowToMe,
  isTurboTaskAsManager,
  isTurboTaskToMe
} from './tileFilters'
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

function countText(loading: boolean, count: number): string {
  return dash(loading, count ? String(count) : '—')
}

/**
 * KPI «Сегодня»: факт/план за выбранный день + раздельно 1С и Turbo «мне / от меня / руководитель».
 */
export function buildTodayKpiTiles(data: SpecV04SourcesState, periodDay = new Date()): SpecSummaryTile[] {
  const loading = data.loading
  const launches = summarizeDayLaunches(data.boardEvents || [], data.boardAgents || [], periodDay)
  const erpFio = data.erpFio

  const onecToMe = data.erpTasks.filter((task) => isDocflowToMe(task)).length
  const onecFromMe = data.erpTasks.filter((task) => isDocflowFromMe(task, erpFio)).length
  const onecDone = data.erpTasks.filter((task) => task.status === 'Выполнена').length

  const turboMine = data.turboTasks.filter((task) => isTurboTaskToMe(task)).length
  const turboMgr = data.turboTasks.filter((task) => isTurboTaskAsManager(task)).length

  const dayTotal = data.erpTaskCount + launches.slotCount
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
      hint: loading ? 'загрузка…' : dayTotal ? '1С + регламент' : 'нет задач',
      tooltip: 'Сводка: выполненные задачи 1С и регламентные запуски агентов за выбранный день',
      tone: 'orange',
      progress: dayPct,
      ring: true
    },
    {
      id: 'onec',
      label: '1С мне',
      value: countText(loading, onecToMe),
      hint: loading ? '…' : 'исполнитель',
      tooltip: 'Задачи документооборота, где вы исполнитель. Клик — фильтр виджета «Задачи из 1С»',
      tone: 'blue',
      progress: loading ? undefined : pct(onecDone, onecToMe || data.erpTaskCount || 1),
      ring: true
    },
    {
      id: 'onec-from-me',
      label: '1С от меня',
      value: countText(loading, onecFromMe),
      hint: loading ? '…' : 'автор',
      tooltip: 'Поручения и задачи, где вы автор. Клик — переключатель «Задачи от меня»',
      tone: 'lilac'
    },
    {
      id: 'proj-mine',
      label: 'Turbo мне',
      value: countText(loading, turboMine),
      hint: loading ? '…' : 'исполнитель',
      tooltip: 'Открытые задачи TurboProject, назначенные на вас. Клик — виджет «Проектные задачи»',
      tone: 'purple'
    },
    {
      id: 'proj-mgr',
      label: 'Turbo РП',
      value: countText(loading, turboMgr),
      hint: loading ? '…' : 'руководитель',
      tooltip:
        'Задачи в проектах, где вы руководитель (сегодня и просроченные у команды). Клик — режим «как руководитель»',
      tone: 'purple'
    },
    {
      id: 'reg',
      label: 'Регламент',
      value: dash(loading, factPlan(regDone, regTotal)),
      hint: loading ? '…' : regTotal ? 'агенты' : 'Constructor',
      tooltip: 'Запуски регламентных агентов за день',
      tone: 'green',
      progress: loading ? undefined : pct(regDone, regTotal || 1),
      ring: true
    },
    {
      id: 'ev',
      label: 'События',
      value: countText(loading, meetToday),
      hint: loading ? '…' : periodIsToday ? 'Outlook' : 'календарь',
      tooltip: 'Совещания и встречи из Outlook на выбранный день',
      tone: 'yellow'
    }
  ]
}

export function useTodayKpiData(
  user: UserProfile | null,
  periodDay = new Date()
): { data: SpecV04SourcesState; tiles: SpecSummaryTile[] } {
  const data = useSpecV04Sources(user)
  const tiles = useMemo(() => buildTodayKpiTiles(data, periodDay), [data, periodDay])
  return { data, tiles }
}
