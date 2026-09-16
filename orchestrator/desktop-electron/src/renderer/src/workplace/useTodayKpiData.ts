import { useMemo } from 'react'
import type { UserProfile } from '../api/types'
import type { SpecPillTone } from './specV04DemoData'
import type { SpecSummaryTile } from './specV04Shell'
import { type SpecV04SourcesState, useSpecV04Sources } from './useSpecV04Data'

function pct(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((done / total) * 100)
}

function dash(loading: boolean, text: string): string {
  return loading ? '—' : text
}

export type TodayDayBreakdownItem = {
  id: string
  title: string
  source: string
  status: string
  statusTone: SpecPillTone
  deadline: string
  done: boolean
}

export type TodayDayBreakdown = {
  done: TodayDayBreakdownItem[]
  todo: TodayDayBreakdownItem[]
  dayDone: number
  dayTotal: number
}

function isDoneStatus(status: string): boolean {
  return status === 'Выполнена' || status === 'Выполнен'
}

/** 1С задачи + регламентные агенты с работой сегодня. Без выдуманных строк. */
export function buildTodayDayBreakdown(data: SpecV04SourcesState): TodayDayBreakdown {
  const items: TodayDayBreakdownItem[] = [
    ...data.erpTasks.map((task) => ({
      id: `erp:${task.id}`,
      title: task.title,
      source: task.source || '1С',
      status: task.status,
      statusTone: task.statusTone,
      deadline: task.deadline,
      done: isDoneStatus(task.status)
    })),
    ...data.todayProcessRows.map((row) => ({
      id: `reg:${row.id}`,
      title: row.name,
      source: row.source || 'Регламент',
      status: row.status,
      statusTone: row.statusTone,
      deadline: row.deadline,
      done: isDoneStatus(row.status)
    }))
  ]
  return {
    done: items.filter((item) => item.done),
    todo: items.filter((item) => !item.done),
    dayDone: items.filter((item) => item.done).length,
    dayTotal: items.length
  }
}

/**
 * KPI «Сегодня»: агрегаты из useSpecV04Sources (1С:Документооборот SOAP, Turbo, агенты, Outlook).
 * «Выполнение дня» — композит: выполненные задачи 1С + регламентные агенты сегодня / их сумма (без Turbo).
 * «Регламентные работы» — только агенты с запуском сегодня (`todayProcessRows`).
 * «Задачи 1С» — onec.docflow_tasks (HTTP SOAP /doc/ws/dm.1cws).
 */
export function buildTodayKpiTiles(data: SpecV04SourcesState): SpecSummaryTile[] {
  const dayLoading = data.erpLoading || data.tableLoading
  const onecDead = Boolean(data.erpError) && !data.erpTaskCount && !data.erpLoading
  const turboDead = Boolean(data.turboError) && !data.projectCount && !data.turboLoading

  const onecTotal = data.erpTaskCount
  const onecDone = data.erpTasks.filter((t) => t.status === 'Выполнена').length

  const regRows = data.todayProcessRows
  const regTotal = regRows.length
  const regDone = regRows.filter((r) => r.status === 'Выполнен').length

  const dayTotal = onecTotal + regTotal
  const dayDone = onecDone + regDone
  const dayPct = dayLoading ? undefined : pct(dayDone, dayTotal || 1)

  const projTotal = data.projectCount
  const projActive = data.projects.filter(
    (p) => !/заверш|закрыт|complete|done/i.test(p.status)
  ).length
  const meetToday = data.meetingCountToday

  return [
    {
      id: 'day',
      label: 'Выполнение дня',
      value: dash(dayLoading, dayTotal ? `${dayDone} из ${dayTotal}` : '—'),
      hint: dayLoading
        ? 'загрузка…'
        : dayTotal
          ? '1С + регламентные агенты'
          : 'нет задач на учёте',
      tone: 'orange',
      progress: dayPct,
      ring: true
    },
    {
      id: 'onec',
      label: 'Задачи из 1С',
      value: dash(data.erpLoading || onecDead, onecTotal ? String(onecTotal) : '—'),
      hint: data.erpLoading
        ? 'загрузка…'
        : onecDead
          ? ''
          : onecTotal
            ? `${onecDone} выполнено`
            : '',
      tone: 'blue',
      progress: data.erpLoading || onecDead ? undefined : pct(onecDone, onecTotal || 1),
      ring: true
    },
    {
      id: 'reg',
      label: 'Регламентные работы',
      value: dash(data.tableLoading, regTotal ? String(regTotal) : '—'),
      hint: data.tableLoading
        ? 'загрузка…'
        : regTotal
          ? `${regDone} из ${regTotal} выполнено`
          : 'запуски сегодня',
      tone: 'green',
      progress: data.tableLoading ? undefined : pct(regDone, regTotal || 1),
      ring: true
    },
    {
      id: 'proj',
      label: 'Проекты',
      value: dash(data.turboLoading || turboDead, projTotal ? String(projTotal) : '—'),
      hint: data.turboLoading ? 'загрузка…' : projTotal ? `${projActive} активных` : '',
      tone: 'purple',
      progress: data.turboLoading || turboDead ? undefined : pct(projActive, projTotal || 1),
      ring: true
    },
    {
      id: 'ev',
      label: 'События дня',
      value: dash(data.meetingsLoading, meetToday ? String(meetToday) : '—'),
      hint: data.meetingsLoading ? 'загрузка…' : 'Outlook, сегодня',
      tone: 'yellow',
      progress: data.meetingsLoading ? undefined : meetToday ? Math.min(100, 25 + meetToday * 15) : 0,
      ring: true
    }
  ]
}

export function useTodayKpiData(user: UserProfile | null): {
  data: SpecV04SourcesState
  tiles: SpecSummaryTile[]
} {
  const data = useSpecV04Sources(user)
  const tiles = useMemo(() => buildTodayKpiTiles(data), [data])
  return { data, tiles }
}
