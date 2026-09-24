import type { SpecPillTone, SpecTaskRow } from './specV04DemoData'

export type PlatformPriority = 'high' | 'normal' | 'low'
export type PlatformStatus = 'open' | 'done' | 'rejected'

export interface PlatformTaskFile {
  id: string
  filename: string
  size: number
}

export interface PlatformTask {
  id: string
  authorUserId: string
  authorFio: string
  assigneeUserId: string
  assigneeFio: string
  description: string
  priority: PlatformPriority
  postedAt: string
  dueAt: string
  status: PlatformStatus
  statusComment: string
  statusAt: string
  overdue: boolean
  /** Кем приходится текущему пользователю. */
  role: 'author' | 'assignee' | 'both'
  /** Исполнитель закрыл задачу, постановщик ещё не принял результат. */
  awaitingReview: boolean
  /** До какого момента постановщику принять результат (конец дня). */
  reviewDueAt: string
  reviewOverdue: boolean
  acceptedAt: string
  /** Сколько раз задача уходила на доработку. */
  reworkCount: number
  files: PlatformTaskFile[]
}

export const PLATFORM_PRIORITY_LABEL: Record<PlatformPriority, string> = {
  high: 'Высокий',
  normal: 'Обычный',
  low: 'Низкий'
}

const PRIORITY_TONE: Record<PlatformPriority, SpecPillTone> = {
  high: 'red',
  normal: 'orange',
  low: 'gray'
}

export const PLATFORM_STATUS_LABEL: Record<PlatformStatus, string> = {
  open: 'В работе',
  done: 'Выполнена',
  rejected: 'Отклонена'
}

function str(value: unknown): string {
  return value == null ? '' : String(value)
}

export function parsePlatformTask(raw: unknown): PlatformTask {
  const item = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const priority = str(item.priority) as PlatformPriority
  const status = str(item.status) as PlatformStatus
  const role = str(item.role)
  return {
    id: str(item.id),
    authorUserId: str(item.author_user_id),
    authorFio: str(item.author_fio),
    assigneeUserId: str(item.assignee_user_id),
    assigneeFio: str(item.assignee_fio),
    description: str(item.description),
    priority: priority in PLATFORM_PRIORITY_LABEL ? priority : 'normal',
    postedAt: str(item.posted_at),
    dueAt: str(item.due_at),
    status: status in PLATFORM_STATUS_LABEL ? status : 'open',
    statusComment: str(item.status_comment),
    statusAt: str(item.status_at),
    overdue: Boolean(item.overdue),
    role: role === 'assignee' || role === 'both' ? role : 'author',
    awaitingReview: Boolean(item.awaiting_review),
    reviewDueAt: str(item.review_due_at),
    reviewOverdue: Boolean(item.review_overdue),
    acceptedAt: str(item.accepted_at),
    reworkCount: Number(item.rework_count || 0),
    files: Array.isArray(item.files)
      ? item.files.map((file) => {
          const row = (file || {}) as Record<string, unknown>
          return { id: str(row.id), filename: str(row.filename), size: Number(row.size || 0) }
        })
      : []
  }
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** «25.09 14:30» в местном времени. */
export function formatPlatformDue(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatPlatformDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function isPlatformTaskMine(task: PlatformTask): boolean {
  return task.role === 'assignee' || task.role === 'both'
}

export function isPlatformTaskFromMe(task: PlatformTask): boolean {
  return task.role === 'author' || task.role === 'both'
}

/** Постановщику пора принять результат или вернуть задачу на доработку. */
export function needsPlatformReview(task: PlatformTask): boolean {
  return task.awaitingReview && isPlatformTaskFromMe(task)
}

/** Задача ждёт исполнителя: работа или повторная доработка. */
export function isPlatformTaskInWork(task: PlatformTask): boolean {
  return task.status === 'open'
}

function firstLine(text: string): string {
  const line = text.trim().split('\n')[0]?.trim() || 'Задача'
  return line.length > 160 ? `${line.slice(0, 157)}…` : line
}

function platformStatusLabel(task: PlatformTask): string {
  if (task.awaitingReview) {
    return task.status === 'done' ? 'Ждёт приёмки' : 'Отклонена, ждёт приёмки'
  }
  if (task.status === 'open' && task.overdue) return 'Просрочена'
  if (task.status === 'open' && task.reworkCount > 0) return 'На доработке'
  return PLATFORM_STATUS_LABEL[task.status]
}

function platformStatusTone(task: PlatformTask): SpecPillTone {
  if (task.awaitingReview) return task.reviewOverdue ? 'red' : 'orange'
  if (task.status === 'done') return 'green'
  if (task.status === 'rejected') return 'gray'
  return task.overdue ? 'red' : 'blue'
}

export function platformTaskToRow(task: PlatformTask): SpecTaskRow {
  const closed = !task.awaitingReview && task.status !== 'open'
  const mine = isPlatformTaskMine(task)
  const review = needsPlatformReview(task)
  // На приёмке срок задачи — конец дня у постановщика, а не исходный срок исполнителя.
  const deadlineIso = review && task.reviewDueAt ? task.reviewDueAt : task.dueAt
  return {
    id: `platform:${task.id}`,
    title: firstLine(task.description),
    source: 'Платформа',
    sourceTone: 'purple',
    process: review
      ? `Принять: ${task.assigneeFio}`
      : mine
        ? `От: ${task.authorFio}`
        : `Кому: ${task.assigneeFio}`,
    project: '—',
    deadline: formatPlatformDue(deadlineIso),
    urgent: review ? task.reviewOverdue : task.status === 'open' && task.overdue,
    priority: PLATFORM_PRIORITY_LABEL[task.priority],
    priorityTone: PRIORITY_TONE[task.priority],
    status: platformStatusLabel(task),
    statusTone: platformStatusTone(task),
    executor: task.assigneeFio,
    who: task.role === 'both' ? 'Я / от меня' : mine ? 'Я' : 'от меня',
    progress: closed && task.status === 'done' ? 100 : task.awaitingReview ? 90 : 0,
    author: task.authorFio,
    performer: task.assigneeFio,
    sourceKind: 'platform',
    platform: task
  }
}

/** Задача требует действия и её срок сегодня либо уже прошёл. */
export function isPlatformTaskForDay(task: PlatformTask, day = new Date()): boolean {
  const iso = needsPlatformReview(task) ? task.reviewDueAt || task.dueAt : task.dueAt
  if (!needsPlatformReview(task) && task.status !== 'open') return false
  const due = new Date(iso)
  if (Number.isNaN(due.getTime())) return false
  const end = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 23, 59, 59)
  return due.getTime() <= end.getTime()
}
