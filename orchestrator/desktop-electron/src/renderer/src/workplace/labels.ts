export type ProcessStatus = 'READY' | 'ACTIVE' | 'WAITING_HUMAN' | 'PAUSED' | 'COMPLETED' | 'ERROR'
export type TaskSource = 'onec' | 'agent' | 'human'
export type DayTaskStatus = 'todo' | 'running' | 'done' | 'needs_decision'

export interface DayTask {
  id: string
  processId: string
  time: string
  title: string
  source: TaskSource
  due: string
  status: DayTaskStatus
}

export interface RunStage {
  id: string
  label: string
  hint: string
  at?: string
}

export interface PreparedSolution {
  id: string
  processId: string
  title: string
  note: string
}

export const TASK_SOURCE_LABEL: Record<TaskSource, string> = {
  onec: 'Задача 1С',
  agent: 'Прогон агента',
  human: 'Решение человека'
}

export const TASK_STATUS_LABEL: Record<DayTaskStatus, string> = {
  todo: 'К выполнению',
  running: 'В работе',
  done: 'Готово',
  needs_decision: 'Требует решения'
}

export const STATUS_LABEL: Record<ProcessStatus, string> = {
  READY: 'Готов',
  ACTIVE: 'Активен',
  WAITING_HUMAN: 'Ждёт человека',
  PAUSED: 'Пауза',
  COMPLETED: 'Завершён',
  ERROR: 'Ошибка'
}

export const TICKET_STATUS_LABEL: Record<string, string> = {
  queued: 'В очереди',
  assigned: 'Назначена',
  diagnosing: 'Диагностика',
  new: 'Новая',
  closed: 'Закрыта'
}
