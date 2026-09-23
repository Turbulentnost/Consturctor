import type { SpecProcessRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import type { DocflowTaskKind } from './docflowTaskKind'

export type TaskSourceKind = 'docflow' | 'turbo' | 'erp' | 'none'

export type TaskActionContext = {
  kind: TaskSourceKind
  rowId: string
  title: string
  refKey?: string
  taskNumber?: string
  step?: string
  taskName?: string
  docflowKind?: DocflowTaskKind
  /** Роль в задаче ДО: executor | author | both. */
  role?: string
  targetId?: string
  projectId?: string
  taskUid?: string
  turboScope?: SpecTaskRow['turboScope']
}

export function isDocflowSourceLabel(source: string): boolean {
  return /1с\s*до|документооборот|docflow/i.test(source || '')
}

export function isTurboSourceLabel(source: string): boolean {
  return /turboproject|турбо/i.test(source || '')
}

export function taskActionContextFromTaskRow(row: SpecTaskRow): TaskActionContext {
  const kind: TaskSourceKind = row.sourceKind
    ? row.sourceKind
    : isDocflowSourceLabel(row.source)
      ? 'docflow'
      : row.id.startsWith('turbo:')
        ? 'turbo'
        : 'none'
  return {
    kind,
    rowId: row.id,
    title: row.title,
    refKey: row.refKey,
    taskNumber: row.taskNumber,
    step: row.step,
    taskName: row.taskName,
    docflowKind: row.docflowKind,
    role: row.role,
    targetId: row.targetId,
    projectId: row.projectId,
    taskUid: row.taskUid,
    turboScope: row.turboScope
  }
}

export function taskActionContextFromProcessRow(
  row: SpecProcessRow,
  linkedTask?: SpecTaskRow | null
): TaskActionContext | null {
  if (linkedTask) return taskActionContextFromTaskRow(linkedTask)
  if (row.id.startsWith('erp:')) {
    const ref = row.id.slice(4)
    return {
      kind: isDocflowSourceLabel(row.source) || row.type.includes('1С') ? 'docflow' : 'erp',
      rowId: row.id,
      title: row.name,
      refKey: ref,
      taskNumber: row.code !== ref ? row.code : undefined,
      step: row.taskToday
    }
  }
  if (row.id.startsWith('proj:')) {
    return {
      kind: 'turbo',
      rowId: row.id,
      title: row.name,
      projectId: row.id.slice(5)
    }
  }
  return null
}

export function taskActionContextFromTurboOpenTask(
  task: {
    id: string
    title: string
    progress?: number
    projectId?: string
    taskUid?: string
  },
  projectId: string
): TaskActionContext {
  return {
    kind: 'turbo',
    rowId: `turbo:${projectId}:${task.taskUid || task.id}`,
    title: task.title,
    projectId,
    taskUid: task.taskUid || task.id
  }
}

export function taskActionContextFromProject(project: SpecProjectRow): TaskActionContext {
  return {
    kind: 'turbo',
    rowId: `proj:${project.id}`,
    title: project.name,
    projectId: project.id
  }
}
