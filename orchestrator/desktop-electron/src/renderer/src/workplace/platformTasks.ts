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

function firstLine(text: string): string {
  const line = text.trim().split('\n')[0]?.trim() || 'Задача'
  return line.length > 160 ? `${line.slice(0, 157)}…` : line
}

export function platformTaskToRow(task: PlatformTask): SpecTaskRow {
  const done = task.status === 'done'
  const status = task.status === 'open' && task.overdue ? 'Просрочена' : PLATFORM_STATUS_LABEL[task.status]
  const statusTone: SpecPillTone =
    task.status === 'done' ? 'green' : task.status === 'rejected' ? 'gray' : task.overdue ? 'red' : 'blue'
  const mine = isPlatformTaskMine(task)
  return {
    id: `platform:${task.id}`,
    title: firstLine(task.description),
    source: 'Платформа',
    sourceTone: 'purple',
    process: mine ? `От: ${task.authorFio}` : `Кому: ${task.assigneeFio}`,
    project: '—',
    deadline: formatPlatformDue(task.dueAt),
    urgent: task.status === 'open' && task.overdue,
    priority: PLATFORM_PRIORITY_LABEL[task.priority],
    priorityTone: PRIORITY_TONE[task.priority],
    status,
    statusTone,
    executor: task.assigneeFio,
    who: task.role === 'both' ? 'Я / от меня' : mine ? 'Я' : 'от меня',
    progress: done ? 100 : 0,
    author: task.authorFio,
    performer: task.assigneeFio,
    sourceKind: 'platform',
    platform: task
  }
}

/** Открытая задача, у которой срок сегодня или уже прошёл. */
export function isPlatformTaskForDay(task: PlatformTask, day = new Date()): boolean {
  if (task.status !== 'open') return false
  const due = new Date(task.dueAt)
  if (Number.isNaN(due.getTime())) return false
  const end = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 23, 59, 59)
  return due.getTime() <= end.getTime()
}
