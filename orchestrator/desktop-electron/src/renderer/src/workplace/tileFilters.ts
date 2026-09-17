import { parseMeetingTime } from '../utils/outlookMeetings'
import { parseIso, sameDay } from '../utils/calendar'
import type { MeetingEvent } from '../utils/outlookMeetings'
import type { SpecMailRow, SpecProcessRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { personNameMatches } from './turboAssigneeMatch'
import type { SpecV04SourcesState } from './useSpecV04Data'
import type { WorkplaceKpiAgentRow } from './workplaceKpiTypes'

export type TaskSourceFilter = 'all' | 'onec' | 'onec-from-me' | 'proj' | 'reg'

export type TaskTileFilter = {
  source: TaskSourceFilter
  overdueOnly: boolean
}

export const EMPTY_TASK_TILE_FILTER: TaskTileFilter = { source: 'all', overdueOnly: false }

/** Today tile «Задачи из 1С»: только срок сегодня / просроченные, роль executor|both. */
export const TODAY_ONEC_TASK_FILTER: TaskTileFilter = { source: 'onec', overdueOnly: false }

const TASK_SOURCE_IDS = new Set<string>(['all', 'onec', 'onec-from-me', 'proj', 'reg'])

function norm(value: string | undefined): string {
  return String(value || '').trim().toLowerCase()
}

/** SOAP role only — never source text (`документооборот (от меня)` is also used for role=both). */
export function docflowRoleOf(row: { role?: string }): string {
  return norm(row.role)
}

export function isDocflowToMe(
  row: { role?: string; performer?: string; executor?: string },
  actorFio = ''
): boolean {
  const role = docflowRoleOf(row)
  if (role === 'author') return false
  const performer = String(row.performer || '').trim()
  if (actorFio && performer && performer !== '—' && personNameMatches(actorFio, performer)) {
    return true
  }
  return role === 'executor' || role === 'both'
}

export function isTurboTaskToMe(row: { turboScope?: string }): boolean {
  return row.turboScope !== 'managed'
}

export function isTurboTaskAsManager(row: { turboScope?: string }): boolean {
  return row.turboScope === 'managed' || row.turboScope === 'both'
}

export function isDocflowFromMe(row: { role?: string; author?: string }, actorFio = ''): boolean {
  const role = docflowRoleOf(row)
  if (role === 'author' || role === 'both') return true
  const author = String(row.author || '').trim()
  return Boolean(author && actorFio.trim() && personNameMatches(actorFio, author))
}

/** «Иванов Иван Иванович» / «Иванов И.И.» → «Иванов И.И.». */
export function formatSurnameInitials(fio: string): string {
  const raw = String(fio || '').trim()
  if (!raw || raw === '—') return '—'
  const compact = raw.replace(/\s+/g, ' ')
  const already = compact.match(/^(\S+)\s+([A-Za-zА-Яа-яЁё])\.\s*([A-Za-zА-Яа-яЁё])\.?$/)
  if (already) return `${already[1]} ${already[2].toUpperCase()}.${already[3].toUpperCase()}.`
  const parts = compact.replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '—'
  if (parts.length === 1) return parts[0]
  const initials = parts.slice(1, 3).map((part) => `${part[0].toUpperCase()}.`)
  return `${parts[0]} ${initials.join('')}`
}

export function isTaskDueOnDay(row: { deadline?: string }, day: Date): boolean {
  const raw = String(row.deadline || '').trim()
  if (!raw || raw === '—') return false
  if (/сегодня/i.test(raw)) return sameDay(day, new Date())
  const due = parseTaskDueDate(raw)
  if (!due) return false
  return sameDay(due, day)
}

/** Вкладка «Сегодня»: срок выбранного дня или просрочка как в 1С (не любой прошлый срок). */
export function isTodayOrOverdueTask(row: SpecTaskRow, day: Date, now = new Date()): boolean {
  if (row.status === 'Выполнена') return false
  if (isTaskDueOnDay(row, day)) return true
  if (!sameDay(day, now)) return false
  return /просроч/i.test(row.status || '') || Boolean(row.urgent)
}

/** Виджет/плитка «Задачи из 1С» на Сегодня: мне (или «от меня»), только сегодня + просроченные. */
export function filterOnecTodayRows(
  rows: SpecTaskRow[],
  day: Date,
  opts?: { fromMe?: boolean; actorFio?: string }
): SpecTaskRow[] {
  const fromMe = Boolean(opts?.fromMe)
  const fio = opts?.actorFio || ''
  return rows.filter((row) => {
    if (!isTodayOrOverdueTask(row, day)) return false
    if (fromMe) return isDocflowFromMe(row, fio)
    return isDocflowToMe(row, fio)
  })
}

export function parseTaskDueDate(deadline: string): Date | null {
  const raw = String(deadline || '').trim()
  if (!raw || raw === '—') return null
  const now = new Date()
  const timeMatch = /(\d{1,2}):(\d{2})/.exec(raw)
  const hours = timeMatch ? Number(timeMatch[1]) : 23
  const minutes = timeMatch ? Number(timeMatch[2]) : 59
  if (/сегодня/i.test(raw)) {
    return new Date(now.getFullYear(), now.getMonth(), now.getDate(), hours, minutes, timeMatch ? 0 : 59)
  }
  if (/завтра/i.test(raw)) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, hours, minutes, timeMatch ? 0 : 59)
    return day
  }
  const dotted = /^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?:\s|$|,)/.exec(raw)
  if (dotted) {
    const day = Number(dotted[1])
    const month = Number(dotted[2]) - 1
    let year = dotted[3] ? Number(dotted[3]) : now.getFullYear()
    if (year < 100) year += 2000
    return new Date(year, month, day, hours, minutes, timeMatch ? 0 : 59)
  }
  const iso = parseIso(raw) || parseIso(raw.replace(' ', 'T'))
  if (iso) return iso
  return null
}

export function isOverdueTask(row: SpecTaskRow, _now = new Date()): boolean {
  if (row.status === 'Выполнена') return false
  // Как в шапке 1С «Просроченных»: не любой прошедший срок, только пометка ДО.
  return /просроч/i.test(row.status || '') || Boolean(row.urgent)
}

export function compareTasksByUrgency(left: SpecTaskRow, right: SpecTaskRow): number {
  const leftOver = isOverdueTask(left) ? 0 : 1
  const rightOver = isOverdueTask(right) ? 0 : 1
  if (leftOver !== rightOver) return leftOver - rightOver
  const leftDue = parseTaskDueDate(left.deadline)?.getTime() ?? Number.POSITIVE_INFINITY
  const rightDue = parseTaskDueDate(right.deadline)?.getTime() ?? Number.POSITIVE_INFINITY
  return leftDue - rightDue
}

export function processRowToTaskRow(row: SpecProcessRow): SpecTaskRow {
  return {
    id: row.id.startsWith('reg:') ? row.id : `reg:${row.id}`,
    title: row.name,
    source: row.source,
    sourceTone: 'green',
    process: row.type,
    project: row.project,
    deadline: row.deadline,
    urgent: row.deadlineUrgent,
    priority: row.deadlineUrgent ? 'Высокий' : 'Средний',
    priorityTone: row.deadlineUrgent ? 'red' : 'orange',
    status: row.status,
    statusTone: row.statusTone,
    executor: '—',
    who: 'Я',
    progress: row.progress
  }
}

export function buildTaskCatalog(
  erpTasks: SpecTaskRow[],
  turboTasks: SpecTaskRow[],
  processRows: SpecProcessRow[]
): { rows: SpecTaskRow[]; erpIds: Set<string>; turboIds: Set<string> } {
  return {
    rows: [...erpTasks, ...turboTasks, ...processRows.map(processRowToTaskRow)],
    erpIds: new Set(erpTasks.map((row) => row.id)),
    turboIds: new Set(turboTasks.map((row) => row.id))
  }
}

function taskOrigin(
  row: SpecTaskRow,
  erpIds: Set<string>,
  turboIds: Set<string>
): TaskSourceFilter {
  if (erpIds.has(row.id)) return 'onec'
  if (turboIds.has(row.id)) return 'proj'
  return 'reg'
}

function matchesTaskSource(
  row: SpecTaskRow,
  source: TaskSourceFilter,
  erpIds: Set<string>,
  turboIds: Set<string>,
  actorFio = ''
): boolean {
  if (source === 'all') return true
  const origin = taskOrigin(row, erpIds, turboIds)
  if (source === 'proj' || source === 'reg') return origin === source
  if (origin !== 'onec') return false
  if (source === 'onec') return isDocflowToMe(row, actorFio)
  if (source === 'onec-from-me') return isDocflowFromMe(row, actorFio)
  return false
}

export function filterTaskRows(
  rows: SpecTaskRow[],
  filter: TaskTileFilter,
  erpIds: Set<string>,
  turboIds: Set<string>,
  actorFio = ''
): SpecTaskRow[] {
  return rows.filter((row) => {
    if (!matchesTaskSource(row, filter.source, erpIds, turboIds, actorFio)) return false
    if (filter.overdueOnly && !isOverdueTask(row)) return false
    return true
  })
}

export function isDeadTaskSource(data: SpecV04SourcesState, id: string): boolean {
  if (id === 'onec' || id === 'onec-from-me') {
    return Boolean(data.erpError) && !data.erpTaskCount && !data.erpLoading
  }
  if (id === 'proj') {
    return Boolean(data.turboError) && !data.turboTaskCount && !data.turboLoading
  }
  return false
}

export function applyTaskTileClick(
  current: TaskTileFilter,
  clickedId: string,
  dead: boolean
): TaskTileFilter {
  if (dead) return current
  if (clickedId === 'bad') {
    if (current.overdueOnly && current.source === 'all') {
      return EMPTY_TASK_TILE_FILTER
    }
    return { source: 'all', overdueOnly: true }
  }
  if (clickedId === 'all') {
    return EMPTY_TASK_TILE_FILTER
  }
  if (!TASK_SOURCE_IDS.has(clickedId)) return current
  if (clickedId === current.source) {
    return { ...current, source: 'all' }
  }
  return { ...current, source: clickedId as TaskSourceFilter }
}

export function taskTileActiveIds(filter: TaskTileFilter): string[] {
  const ids: string[] = []
  if (filter.source !== 'all') ids.push(filter.source)
  else if (!filter.overdueOnly) ids.push('all')
  if (filter.overdueOnly) ids.push('bad')
  return ids
}

export function toggleSimpleTile(current: string, clickedId: string): string {
  if (clickedId === 'all' || clickedId === current) return 'all'
  return clickedId
}

export function isDeadProcessSource(data: SpecV04SourcesState, id: string): boolean {
  if (id === 'onec') return Boolean(data.erpError) && !data.erpTaskCount && !data.erpLoading
  if (id === 'proj') return Boolean(data.turboError) && !data.projectCount && !data.turboLoading
  if (id === 'mail') {
    return Boolean(data.mailComError && data.mailImapError) && !data.mailCount && !data.mailLoading
  }
  return false
}

export function isDeadTodaySource(data: SpecV04SourcesState, id: string): boolean {
  if (id === 'onec') return Boolean(data.erpError) && !data.erpTaskCount && !data.erpLoading
  if (id === 'proj') return Boolean(data.turboError) && !data.projectCount && !data.turboLoading
  return false
}

/** Keep rows of the selected Today widget; leave others empty. Dead-source clicks never reach here. */
export function todayRowsForTile<T>(filter: string, widgetId: string, rows: T[]): T[] {
  if (filter === 'all' || filter === 'day') return rows
  if (filter === 'reg') return rows
  return filter === widgetId ? rows : []
}

export function mailMatchesTile(row: SpecMailRow, id: string): boolean {
  if (id === 'all' || id === 'new') return true
  if (id === 'proc') return /обработ|непрочитан/i.test(row.status)
  if (id === 'hi') return /высок/i.test(row.priority) || row.unread === true
  const blob = `${row.subject} ${row.category} ${row.link}`
  if (id === 'proj') return /проект|turbo|crm/i.test(blob)
  if (id === 'reg') return /регламент|договор|акт|согласован/i.test(blob)
  return true
}

export function countMailTiles(rows: SpecMailRow[]): Record<string, number> {
  return {
    new: rows.filter((row) => row.unread).length || rows.length,
    proc: rows.filter((row) => mailMatchesTile(row, 'proc')).length,
    hi: rows.filter((row) => mailMatchesTile(row, 'hi')).length,
    proj: rows.filter((row) => mailMatchesTile(row, 'proj')).length,
    reg: rows.filter((row) => mailMatchesTile(row, 'reg')).length
  }
}

export function projectMatchesTile(row: SpecProjectRow, id: string): boolean {
  if (id === 'all' || id === 'active') return true
  if (id === 'tasks') return row.tasks > 0
  if (id === 'risk') return row.riskTone === 'red' || row.riskTone === 'orange'
  if (id === 'done') return row.progress >= 100 || /заверш|закрыт|complete|done/i.test(row.status)
  return true
}

export function meetingMatchesTile(meeting: MeetingEvent, id: string, now = new Date()): boolean {
  if (id === 'all' || id === 'period') return true
  const start = parseMeetingTime(meeting.start)
  const end = parseMeetingTime(meeting.end) || start
  if (id === 'today') return Boolean(start && sameDay(start, now))
  if (id === 'done' || id === 'past') return Boolean(end && end.getTime() < now.getTime())
  if (id === 'upcoming' || id === 'next') {
    return Boolean(start && start.getTime() >= now.getTime() && !sameDay(start, now))
  }
  return false
}

export function countMeetingTiles(meetings: MeetingEvent[], now = new Date()): Record<string, number> {
  return {
    period: meetings.length,
    today: meetings.filter((item) => meetingMatchesTile(item, 'today', now)).length,
    upcoming: meetings.filter((item) => meetingMatchesTile(item, 'upcoming', now)).length,
    done: meetings.filter((item) => meetingMatchesTile(item, 'done', now)).length
  }
}

export function agentMatchesKpiTile(row: WorkplaceKpiAgentRow, cardId: string): boolean {
  if (row.id === cardId) return true
  if (cardId === 'tasks') return row.completionPct < 90
  if (cardId === 'sla') return row.slaPct < 90
  if (cardId === 'load') return row.loadPct >= 75
  if (cardId === 'auto') return row.automationPct < 60
  if (cardId === 'quality') return row.statusTone !== 'green'
  if (cardId === 'ai') return /ии|ai|агент/i.test(`${row.name} ${row.process}`)
  return false
}
