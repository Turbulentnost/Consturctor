import { useMemo } from 'react'
import type { UserProfile } from '../api/types'
import { sameDay } from '../utils/calendar'
import { countMeetingsOnDay } from '../utils/outlookMeetings'
import type { SpecSummaryTile } from './specV04Shell'
import { isTurboPinPlaceholder } from './orchestratorTaskSources'
import { summarizeDayLaunches } from './todayKpiLaunches'
import type { SpecTaskRow } from './specV04DemoData'
import {
  buildTaskCatalog,
  filterTaskRows,
  isTurboTaskAsManager,
  isTurboTaskToMe,
  type TaskSourceFilter
} from './tileFilters'
import { taskDueOnSelectedDay } from './workplacePeriodFilter'
import { type SpecV04SourcesState, useSpecV04Sources } from './useSpecV04Data'

/** Те же строки, что вкладка «Задачи», но только со сроком в выбранный день. */
export function tasksMatchingTasksPage(
  data: SpecV04SourcesState,
  day: Date,
  source: TaskSourceFilter = 'all'
): SpecTaskRow[] {
  const catalog = buildTaskCatalog(
    data.erpTasks,
    data.turboTasks,
    data.processRows,
    data.platformTasks
  )
  return filterTaskRows(
    catalog.rows,
    { source, overdueOnly: false },
    catalog.erpIds,
    catalog.turboIds
  ).filter((row) => taskDueOnSelectedDay(row.deadline, day))
}

function pct(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((done / total) * 100)
}

function factPlan(done: number, total: number): string {
  return total ? `${done} из ${total}` : '—'
}

function countText(count: number): string {
  return count ? String(count) : '—'
}

/**
 * KPI «Сегодня»: факт/план за выбранный день + раздельно 1С и Turbo «мне / от меня / руководитель».
 */
export function buildTodayKpiTiles(data: SpecV04SourcesState, periodDay = new Date()): SpecSummaryTile[] {
  const onecLoading = data.erpLoading
  const turboLoading = data.turboLoading
  const regLoading = data.tableLoading
  const meetingsLoading = data.meetingsLoading
  const dayLoading = onecLoading || regLoading
  const launches = summarizeDayLaunches(data.boardEvents || [], data.boardAgents || [], periodDay)

  const onecMine = tasksMatchingTasksPage(data, periodDay, 'onec')
  const onecToMe = onecMine.length
  const onecFromMe = tasksMatchingTasksPage(data, periodDay, 'onec-from-me').length
  const onecDone = onecMine.filter((task) => task.status === 'Выполнена').length

  const turboMine = data.turboTasks.filter((task) => isTurboTaskToMe(task)).length
  const turboMgr = data.turboTasks.filter((task) => isTurboTaskAsManager(task)).length

  // Задачи только «мне». Регламент — один процесс за день, не каждый повторный запуск.
  const dayTotal = onecToMe + launches.agentIds.length
  const dayDone = onecDone + launches.agentDoneIds.length
  const dayPct = dayLoading ? undefined : pct(dayDone, dayTotal || 1)

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
      value: dayLoading ? '' : factPlan(dayDone, dayTotal),
      loading: dayLoading,
      hint: !dayLoading && !dayTotal ? 'нет задач' : 'мне + регламент',
      tooltip:
        'Задачи 1С на выбранный день, где вы исполнитель, — те же, что на вкладке «Задачи», — плюс регламентные процессы за день.',
      tone: 'orange',
      progress: dayPct,
      ring: true
    },
    {
      id: 'onec',
      label: '1С мне',
      value: onecLoading ? '' : countText(onecToMe),
      loading: onecLoading,
      hint: 'исполнитель',
      tooltip: 'Задачи 1С на выбранный день, где вы исполнитель. Тот же список, что на вкладке «Задачи».',
      tone: 'blue',
      progress: onecLoading ? undefined : pct(onecDone, onecToMe || data.erpTaskCount || 1),
      ring: true
    },
    {
      id: 'onec-from-me',
      label: '1С от меня',
      value: onecLoading ? '' : countText(onecFromMe),
      loading: onecLoading,
      hint: 'автор',
      tooltip: 'Задачи 1С на выбранный день, где вы автор. Тот же список, что на вкладке «Задачи».',
      tone: 'lilac'
    },
    {
      id: 'proj-mine',
      label: 'Turbo мне',
      value: turboLoading ? '' : countText(turboMine),
      loading: turboLoading,
      hint: 'исполнитель',
      tooltip: 'Открытые задачи TurboProject, назначенные на вас. Клик — виджет «Проектные задачи»',
      tone: 'purple'
    },
    {
      id: 'proj-mgr',
      label: 'Turbo РП',
      value: turboLoading ? '' : countText(turboMgr),
      loading: turboLoading,
      hint: 'руководитель',
      tooltip:
        'Задачи в проектах, где вы руководитель (сегодня и просроченные у команды). Клик — режим «как руководитель»',
      tone: 'purple'
    },
    {
      id: 'reg',
      label: 'Регламент',
      value: regLoading ? '' : factPlan(regDone, regTotal),
      loading: regLoading,
      hint: !regLoading && !regTotal ? 'Constructor' : 'процессы',
      tooltip:
        'Регламентные процессы за день: один процесс — одна задача, повторные запуски в тот же день не суммируются',
      tone: 'green',
      progress: regLoading ? undefined : pct(regDone, regTotal || 1),
      ring: true
    },
    {
      id: 'ev',
      label: 'События',
      value: meetingsLoading ? '' : countText(meetToday),
      loading: meetingsLoading,
      hint: periodIsToday ? 'Outlook' : 'календарь',
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
