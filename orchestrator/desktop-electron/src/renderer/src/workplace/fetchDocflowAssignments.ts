import { api } from '../api/client'
import type { ClosureCheckAssignment, ClosureCheckLine } from '../components/agentfeed/docflowActions'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'
import { readDocflowPage, writeDocflowPage } from './docflowPageCache'

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

export type AssignmentFile = {
  id: string
  name: string
  extension: string
  size: string
  created: string
  /** Кто загрузил файл в 1С (поле «Изменил»: автор у файлов поручений пуст). */
  uploadedBy: string
}

/** Комментарий шага задачи: отчёт исполнителя или причина возврата. */
export type AssignmentTaskComment = { step: string; performer: string; begin: string; comment: string }

export type AssignmentTask = {
  id: string
  performer: string
  title: string
  result: string
  begin: string
  due: string
  doneAt: string
  /** Автор принял задачу в Документообороте. */
  executed: boolean
  state: string
  returns: number
  /** Открытая проверка автора — закрыть или вернуть. */
  openCheckTaskId: string
  openCheckStep: string
  openCheckName: string
  /** Открытая задача исполнителя. */
  openExecuteTaskId: string
  comments: AssignmentTaskComment[]
  /** Файлы, загруженные исполнителем во время этой задачи. */
  files: AssignmentFile[]
}

export type AssignmentCard = {
  assignment: AssignmentRow
  /** Задачи поручения в 1С:Документооборот: каждая отправка исполнителю со своей историей. */
  tasks: AssignmentTask[]
  /** Исполнители мероприятий без единой задачи в Документообороте. */
  missingExecutors: string[]
  /** Документооборот прочитан не полностью (только открытые задачи из выгрузки). */
  note: string
  /** Файлы поручения, не загруженные исполнителями задач. */
  files: AssignmentFile[]
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
        n: Number(line.n || line.line) || 0,
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
  const cacheKey = `assignments:${user?.id || user?.fio || ''}:${opts.from}:${opts.to}:${opts.skip}:${opts.status}`
  const cached = readDocflowPage<AssignmentPage>(cacheKey)
  if (cached) return cached
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
  const page: AssignmentPage = {
    rows,
    nextSkip: Number(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    statuses: list(payload.statuses).map((item) => ({ code: str(rec(item).code), label: str(rec(item).label) }))
  }
  writeDocflowPage(cacheKey, page)
  return page
}

function mapTaskFromPayload(item: unknown): AssignmentTask {
  const task = rec(item)
  const comments = list(task.comments).length ? list(task.comments) : list(task.history)
  return {
    id: str(task.id || task.task_id || task.open_execute_task_id || task.open_check_task_id),
    performer: str(task.performer),
    title: str(task.title || task.text || task.task),
    result: str(task.result),
    begin: str(task.begin),
    due: str(task.due),
    doneAt: str(task.done_at || task.accepted_at),
    executed: Boolean(task.executed),
    state: str(task.state || task.task_state),
    returns: Number(task.returns) || 0,
    openCheckTaskId: str(task.open_check_task_id),
    openCheckStep: str(task.open_check_step),
    openCheckName: str(task.open_check_name),
    openExecuteTaskId: str(task.open_execute_task_id || task.open_task_id),
    comments: comments.map((entry) => {
      const step = rec(entry)
      return {
        step: str(step.step),
        performer: str(step.performer),
        begin: str(step.begin),
        comment: str(step.comment)
      }
    }),
    files: list(task.files).map(mapFile)
  }
}

export function mapReviewToCard(raw: Record<string, unknown>): AssignmentCard {
  const tasks = list(raw.tasks).map(mapTaskFromPayload)
  const lines = list(raw.lines)
  return {
    assignment: mapRow({
      ...raw,
      id: str(raw.ref_key || raw.id),
      head: str(raw.manager || raw.head || raw.customer),
      weekly_report: str(raw.weekly_report_date || raw.weekly_report),
      final_report: str(raw.final_report_date || raw.final_report)
    }),
    tasks,
    missingExecutors: [],
    note: '',
    files: list(raw.files).map(mapFile),
    progress: {
      lines: lines.length,
      overdueLines: 0,
      tasks: tasks.length,
      tasksDone: tasks.filter((task) => task.executed).length
    }
  }
}

export function mapReviewToCheck(raw: Record<string, unknown>): ClosureCheckAssignment {
  const guid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  return {
    number: str(raw.number),
    targetId: str(raw.ref_key || raw.target_id),
    conclusion: str(raw.conclusion),
    done: Number(raw.done) || 0,
    total: Number(raw.total) || 0,
    reason: str(raw.reason),
    lines: list(raw.tasks).map((item): ClosureCheckLine => {
      const task = rec(item)
      const actionKind = str(task.action)
      const actionId = str(task.task_id || task.open_check_task_id)
      return {
        line: `задача ${str(task.n) || '1'}`,
        event: str(task.task || task.title || task.text),
        executor: str(task.performer),
        conclusion: str(task.conclusion),
        evidence: str(task.evidence),
        taskState: str(task.task_state || task.state),
        advice: str(task.advice),
        comment: str(task.comment),
        action:
          guid.test(actionId) && (actionKind === 'close' || actionKind === 'return')
            ? {
                assignment: str(raw.number),
                line: `задача ${str(task.n) || '1'}`,
                event: str(task.task || task.title),
                performer: str(task.performer),
                taskId: actionId,
                step: str(task.step),
                title: str(task.title || task.task),
                targetId: str(raw.ref_key),
                action: actionKind,
                reason: str(task.reason || task.comment),
                comment: str(task.comment)
              }
            : null,
        openTaskId: guid.test(str(task.open_task_id || task.open_execute_task_id))
          ? str(task.open_task_id || task.open_execute_task_id)
          : ''
      }
    })
  }
}

function mapFile(item: unknown): AssignmentFile {
  const file = rec(item)
  return {
    id: str(file.id),
    name: str(file.name),
    extension: str(file.extension),
    size: str(file.size),
    created: str(file.created),
    uploadedBy: str(file.uploaded_by)
  }
}

const cardCache = new Map<string, AssignmentCard>()

export function forgetAssignmentCard(id: string): void {
  cardCache.delete(id.trim())
}

/** Подробный запрос по одному поручению: мероприятия, задачи в Документообороте и файлы. */
export async function loadAssignmentCard(user: UserProfile | null, id: string): Promise<AssignmentCard> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const stored = await api.getAssignmentReview(id)
  if (stored && stored.open === false) {
    const card = mapReviewToCard(stored)
    cardCache.set(id, card)
    return card
  }
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
    tasks: list(payload.tasks).map(mapTaskFromPayload),
    missingExecutors: list(rec(payload.docflow_summary).executors_without_tasks).map(str).filter(Boolean),
    note: str(payload.docflow_note),
    files: list(payload.files).map(mapFile),
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
