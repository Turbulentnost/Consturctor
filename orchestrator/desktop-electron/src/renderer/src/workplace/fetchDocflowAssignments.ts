import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

export type AssignmentLine = {
  n: number
  text: string
  due: string
  executor: string
  priority: string
  overdue: boolean
}

/** Строка журнала поручений (onec.docflow_assignments). */
export type AssignmentRow = {
  id: string
  number: string
  date: string
  topic: string
  basis: string
  status: string
  statusCode: string
  open: boolean
  posted: boolean
  head: string
  organization: string
  reporter: string
  secretary: string
  due: string
  finalReport: string
  weeklyReport: string
  overdue: boolean
  priority: string
  executors: string[]
  lines: AssignmentLine[]
}

export type AssignmentStatus = { code: string; label: string }

export type AssignmentPage = {
  rows: AssignmentRow[]
  nextSkip: number
  hasMore: boolean
  statuses: AssignmentStatus[]
}

export type AssignmentTask = {
  id: string
  performer: string
  title: string
  result: string
  begin: string
  due: string
  doneAt: string
  executed: boolean
}

export type AssignmentCard = {
  assignment: AssignmentRow
  tasks: AssignmentTask[]
  files: { id: string; name: string; extension: string; size: string; created: string }[]
  progress: { lines: number; overdueLines: number; tasks: number; tasksDone: number }
}

export const ASSIGNMENT_PAGE_SIZE = 40

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function mapRow(raw: Record<string, unknown>): AssignmentRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    topic: str(raw.topic),
    basis: str(raw.basis),
    status: str(raw.status),
    statusCode: str(raw.status_code),
    open: Boolean(raw.open),
    posted: Boolean(raw.posted),
    head: str(raw.head),
    organization: str(raw.organization),
    reporter: str(raw.reporter),
    secretary: str(raw.secretary),
    due: str(raw.due),
    finalReport: str(raw.final_report),
    weeklyReport: str(raw.weekly_report),
    overdue: Boolean(raw.overdue),
    priority: str(raw.priority),
    executors: list(raw.executors).map(str).filter(Boolean),
    lines: list(raw.lines).map((item) => {
      const line = rec(item)
      return {
        n: Number(line.n) || 0,
        text: str(line.text),
        due: str(line.due),
        executor: str(line.executor),
        priority: str(line.priority),
        overdue: Boolean(line.overdue)
      }
    })
  }
}

export async function loadAssignmentPage(
  user: UserProfile | null,
  opts: { from: string; to: string; skip: number; status: string }
): Promise<AssignmentPage> {
  const res = await api.invokeServerTool(
    'onec.docflow_assignments',
    onecGatewayInvokeArgs(user, {
      top: ASSIGNMENT_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to,
      ...(opts.status ? { status: opts.status } : {})
    }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать поручения из 1С')
  const payload = rec(res.result)
  const rows = list(payload.rows).map((row) => mapRow(rec(row)))
  return {
    rows,
    nextSkip: Number(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    statuses: list(payload.statuses).map((item) => ({ code: str(rec(item).code), label: str(rec(item).label) }))
  }
}

const cardCache = new Map<string, AssignmentCard>()

/** Подробный запрос по одному поручению: мероприятия, задачи исполнителей и файлы. */
export async function loadAssignmentCard(user: UserProfile | null, id: string): Promise<AssignmentCard> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_assignment_card',
    onecGatewayInvokeArgs(user, { ref_key: id }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось открыть поручение')
  const payload = rec(res.result)
  const progress = rec(payload.progress)
  const card: AssignmentCard = {
    assignment: mapRow(rec(payload.assignment)),
    tasks: list(payload.tasks).map((item) => {
      const task = rec(item)
      return {
        id: str(task.id),
        performer: str(task.performer),
        title: str(task.title),
        result: str(task.result),
        begin: str(task.begin),
        due: str(task.due),
        doneAt: str(task.done_at),
        executed: Boolean(task.executed)
      }
    }),
    files: list(payload.files).map((item) => {
      const file = rec(item)
      return {
        id: str(file.id),
        name: str(file.name),
        extension: str(file.extension),
        size: str(file.size),
        created: str(file.created)
      }
    }),
    progress: {
      lines: Number(progress.lines) || 0,
      overdueLines: Number(progress.overdue_lines) || 0,
      tasks: Number(progress.tasks) || 0,
      tasksDone: Number(progress.tasks_done) || 0
    }
  }
  cardCache.set(id, card)
  return card
}
