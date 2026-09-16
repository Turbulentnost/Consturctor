import { useContext } from 'react'
import { type MeetingEvent } from '../utils/outlookMeetings'
import type { UserProfile } from '../api/types'
import type { SpecSummaryTile } from './specV04Shell'
import type { SpecMailRow, SpecProcessRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { SpecV04SourcesContext } from './SpecV04SourcesProvider'
import { buildTaskCatalog, filterTaskRows } from './tileFilters'

export interface SpecV04SourcesState {
  /** Любой из долгих источников ещё грузится. Не использовать как стоп-кран виджета. */
  sourcesLoading: boolean
  /** Только доска агентов Constructor — таблица процессов. */
  tableLoading: boolean
  /** Совместимость: баннер/таблицы на других вкладках. */
  loading: boolean
  error: string
  outlookMailbox: string
  erpFio: string
  erpTasks: SpecTaskRow[]
  erpTaskCount: number
  /** TurboProject open tasks (только текущий исполнитель). */
  turboTasks: SpecTaskRow[]
  turboTaskCount: number
  /** ERP + Turbo + регламентные агенты для KPI «Все задачи». */
  allTaskCount: number
  projects: SpecProjectRow[]
  projectCount: number
  mailRows: SpecMailRow[]
  mailCount: number
  mailLoading: boolean
  mailImapPrimary: boolean
  mailComError: string
  mailImapError: string
  mailImapStatus: string
  processRows: SpecProcessRow[]
  /** Регламентные агенты с запуском сегодня (`agentLaunchesToday`), не весь каталог. */
  todayProcessRows: SpecProcessRow[]
  allProcessRows: SpecProcessRow[]
  meetingCount: number
  /** Совещания с датой начала = сегодня (локальный календарь). */
  meetingCountToday: number
  meetings: MeetingEvent[]
  meetingsLoading: boolean
  /** Ошибка загрузки 1С (SOAP документооборот). */
  erpError: string
  erpLoading: boolean
  /** Ошибка TurboProject (сессия / API / задачи), не пустой портфель. */
  turboError: string
  turboLoading: boolean
  /** Документооборот /doc — подсказка, когда задачи erp_pm уже загружены. */
  erpSecondaryHint: string
  sources: {
    erp: string
    turbo: string
    mail: string
  }
  /** TurboProject API / учётка недоступны (не путать с пустым портфелем). */
  turboNoSession: boolean
  /** Профиль для turboproject.* (email/nameMail из сессии). */
  user: UserProfile | null
  /** Пароль 1С из экрана входа в памяти renderer (не localStorage). */
  comPasswordInSession: boolean
  /** Нужен повторный ввод пароля 1С (COM / gateway / OData). */
  oneCAuthFailure: boolean
}

function pct(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((done / total) * 100)
}

function processTabKind(row: SpecProcessRow): 'reg' | 'onec' | 'proj' | 'mail' | 'meet' {
  if (row.type === 'Задача из 1С') return 'onec'
  if (row.type === 'Проект') return 'proj'
  if (row.type === 'Письмо') return 'mail'
  if (row.type === 'Совещание') return 'meet'
  return 'reg'
}

export function processTabLoading(data: SpecV04SourcesState, tab: string): boolean {
  if (tab === 'onec') return data.erpLoading
  if (tab === 'proj') return data.turboLoading
  if (tab === 'mail') return data.mailLoading
  if (tab === 'meet') return data.meetingsLoading
  if (tab === 'reg') return data.tableLoading
  return false
}

export function filterProcessRowsByTab(rows: SpecProcessRow[], tab: string): SpecProcessRow[] {
  if (tab === 'all') return rows
  return rows.filter((row) => processTabKind(row) === tab)
}

export function countProcessRowsByTab(rows: SpecProcessRow[]): Record<string, number> {
  const counts: Record<string, number> = {
    all: rows.length,
    reg: 0,
    onec: 0,
    proj: 0,
    mail: 0,
    meet: 0
  }
  for (const row of rows) {
    counts[processTabKind(row)] += 1
  }
  return counts
}

/** Данные из SpecV04SourcesProvider (App); сигнатура с user сохранена для call sites. */
export function useSpecV04Sources(_user: UserProfile | null): SpecV04SourcesState {
  return useContext(SpecV04SourcesContext)
}

export function buildProcessTiles(data: SpecV04SourcesState): SpecSummaryTile[] {
  const regRows = data.allProcessRows.filter((r) => processTabKind(r) === 'reg')
  const regTotal = regRows.length
  const regDone = regRows.filter((r) => r.status === 'Выполнен').length
  const onecTotal = data.erpTaskCount
  const onecDone = data.erpTasks.filter((t) => t.status === 'Выполнена').length
  const projTotal = data.projectCount
  const mailTotal = data.mailCount
  const onecDead = Boolean(data.erpError) && !onecTotal && !data.erpLoading
  const projDead = Boolean(data.turboError) && !projTotal && !data.turboLoading
  const mailDead =
    Boolean(data.mailComError && data.mailImapError) && !mailTotal && !data.mailLoading
  return [
    {
      id: 'reg',
      label: 'Регламентные процессы',
      value: regTotal ? `${regTotal} активных` : '—',
      hint: regTotal ? `${regDone} выполнено из ${regTotal}` : 'Оркестратор',
      tone: 'green',
      progress: pct(regDone, regTotal || 1),
      ring: true
    },
    {
      id: 'onec',
      label: 'Задачи из 1С',
      value: onecDead ? '—' : onecTotal ? `${onecTotal} активных` : '—',
      hint: onecDead ? '' : onecTotal ? `${onecDone} выполнено` : '',
      tone: 'blue',
      progress: onecDead ? undefined : pct(onecDone, onecTotal || 1),
      ring: true
    },
    {
      id: 'proj',
      label: 'Проекты',
      value: projDead ? '—' : projTotal ? `${projTotal} в портфеле` : '—',
      hint: projDead ? '' : projTotal ? `${projTotal} в портфеле` : '',
      tone: 'purple',
      progress: projDead ? undefined : projTotal ? 50 : 0,
      ring: true
    },
    {
      id: 'mail',
      label: 'Письма',
      value: mailDead ? '—' : mailTotal ? `${mailTotal} за неделю` : '—',
      hint: mailDead ? '' : mailTotal ? 'за неделю' : '',
      tone: 'orange',
      progress: mailDead ? undefined : mailTotal ? 30 : 0,
      ring: true
    },
    {
      id: 'meet',
      label: 'Совещания',
      value: data.meetingCount ? `${data.meetingCount} на неделе` : '—',
      hint: 'Outlook календарь',
      tone: 'yellow',
      progress: data.meetingCount ? 60 : 0,
      ring: true
    }
  ]
}

function taskTileValue(loading: boolean, count: number, dead?: boolean): string {
  if (dead || loading) return '—'
  return count ? String(count) : '—'
}

export function buildTaskTiles(data: SpecV04SourcesState): SpecSummaryTile[] {
  const allPending = (data.erpLoading || data.turboLoading || data.tableLoading) && !data.allTaskCount
  const catalog = buildTaskCatalog(data.erpTasks, data.turboTasks, data.processRows)
  const overdue = filterTaskRows(
    catalog.rows,
    { source: 'all', overdueOnly: true },
    catalog.erpIds,
    catalog.turboIds
  ).length
  const fromMe = data.erpTasks.filter((t) => {
    const role = String(t.role || '').trim().toLowerCase()
    return role === 'author' || role === 'both'
  }).length
  const regTotal = data.processRows.length
  const onecDead = Boolean(data.erpError) && !data.erpTaskCount && !data.erpLoading
  const turboDead = Boolean(data.turboError) && !data.turboTaskCount && !data.turboLoading
  const onecDone = data.erpTasks.filter((t) => t.status === 'Выполнена').length
  const allHint = allPending ? 'загрузка…' : ''
  const onecHint = data.erpLoading
    ? 'загрузка…'
    : onecDead
      ? ''
      : data.erpTaskCount
        ? `${onecDone} выполнено`
        : ''
  const fromMeHint = data.erpLoading ? 'загрузка…' : onecDead ? '' : fromMe ? `${fromMe} от меня` : ''
  const turboHint = data.turboLoading
    ? 'загрузка…'
    : turboDead
      ? ''
      : data.turboTaskCount
        ? `${data.turboTaskCount} открытых`
        : ''
  return [
    {
      id: 'all',
      label: 'Все задачи',
      value: taskTileValue(allPending, data.allTaskCount),
      hint: allHint,
      tone: 'blue'
    },
    {
      id: 'onec',
      label: 'Задачи из 1С',
      value: taskTileValue(data.erpLoading, data.erpTaskCount, onecDead),
      hint: onecHint,
      tone: 'blue'
    },
    {
      id: 'onec-from-me',
      label: '1С от меня',
      value: taskTileValue(data.erpLoading, fromMe, onecDead),
      hint: fromMeHint,
      tone: 'lilac'
    },
    {
      id: 'proj',
      label: 'Проектные',
      value: taskTileValue(data.turboLoading, data.turboTaskCount, turboDead),
      hint: turboHint,
      tone: 'purple'
    },
    {
      id: 'reg',
      label: 'Регламентные',
      value: taskTileValue(data.tableLoading && !regTotal, regTotal),
      tone: 'green'
    },
    {
      id: 'bad',
      label: 'Просроченные',
      value: taskTileValue(allPending, overdue),
      tone: 'orange'
    }
  ]
}
