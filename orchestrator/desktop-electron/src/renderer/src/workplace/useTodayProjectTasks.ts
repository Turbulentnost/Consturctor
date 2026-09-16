import { useEffect, useMemo, useState } from 'react'
import { TODAY_PROJECT_TASK_ROWS } from '../tabs/grid/todayDemoData'
import { api } from '../api/client'
import type { SpecPillTone } from './specV04DemoData'
import type { SpecV04SourcesState } from './useSpecV04Data'
import { toneForStatus } from './specV04Mappers'
import { parseIso, sameDay } from '../utils/calendar'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'

export type TodayProjectTaskRow = {
  id: string
  title: string
  deadline: string
  status: string
  statusTone: SpecPillTone
  assignee: string
  assigneeTone: SpecPillTone
}

function formatDeadline(raw: string): string {
  const value = (raw || '').trim()
  if (!value) return '—'
  const stamp = parseIso(value) || parseIso(value.replace(' ', 'T'))
  if (!stamp) return value.length > 10 ? value.slice(0, 10) : value
  const dd = String(stamp.getDate()).padStart(2, '0')
  const mm = String(stamp.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}`
}

function taskStatusLabel(percent: number, delayDays: number): string {
  if (percent >= 1) return 'Выполнена'
  if (delayDays > 0) return 'Просрочена'
  if (percent > 0) return 'В работе'
  return 'Запланировано'
}

function assigneeLabel(executors: string[], actorFio: string): { label: string; tone: SpecPillTone } {
  const first = (executors[0] || '').trim()
  if (!first) return { label: '—', tone: 'gray' }
  if (/^(ии|ai|агент)/i.test(first)) return { label: 'ИИ', tone: 'purple' }
  const actor = actorFio.trim().toLowerCase()
  if (actor && first.toLowerCase().includes(actor.split(/\s+/)[0] || '')) {
    return { label: 'Сотрудник', tone: 'blue' }
  }
  return { label: first, tone: 'blue' }
}

function isOpenTask(task: Record<string, unknown>): boolean {
  const percent = Number(task.percent_complete ?? 0)
  return !Number.isFinite(percent) || percent < 1
}

function taskMatchesDay(task: Record<string, unknown>, day: Date): boolean {
  if (!isOpenTask(task)) return false
  const finish = String(task.finish_date || '').trim()
  if (!finish) return true
  const stamp = parseIso(finish) || parseIso(finish.replace(' ', 'T'))
  if (!stamp) return true
  return sameDay(stamp, day)
}

function mapTask(
  task: Record<string, unknown>,
  projectId: string,
  actorFio: string
): TodayProjectTaskRow {
  const percent = Number(task.percent_complete ?? 0)
  const delayDays = Number(task.delay_days ?? 0)
  const status = taskStatusLabel(Number.isFinite(percent) ? percent : 0, Number.isFinite(delayDays) ? delayDays : 0)
  const executors = Array.isArray(task.executors)
    ? task.executors.filter((item): item is string => typeof item === 'string')
    : []
  const { label, tone } = assigneeLabel(executors, actorFio)
  const id = String(task.uid ?? task.id ?? `${projectId}:${task.name ?? 'task'}`)
  return {
    id,
    title: String(task.name || 'Задача').trim(),
    deadline: formatDeadline(String(task.finish_date || '')),
    status,
    statusTone: toneForStatus(status),
    assignee: label,
    assigneeTone: tone
  }
}

export interface TodayProjectTasksState {
  loading: boolean
  noSession: boolean
  error: string
  rows: TodayProjectTaskRow[]
}

export function useTodayProjectTasks(
  periodDay: Date,
  spec: Pick<SpecV04SourcesState, 'sourcesLoading' | 'turboNoSession' | 'projects' | 'erpFio'>
): TodayProjectTasksState {
  const generation = useGridRefreshGeneration()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [rows, setRows] = useState<TodayProjectTaskRow[]>([])

  const dayKey = `${periodDay.getFullYear()}-${periodDay.getMonth()}-${periodDay.getDate()}`
  const portfolioKey = spec.projects.map((item) => `${item.id}:${item.tasks}`).join('|')

  useEffect(() => {
    if (spec.sourcesLoading) {
      setLoading(true)
      setError('')
      return
    }
    if (spec.turboNoSession) {
      setLoading(false)
      setError('')
      setRows([])
      return
    }

    const candidates = spec.projects
      .filter((project) => project.tasks > 0)
      .sort((left, right) => right.tasks - left.tasks)
      .slice(0, 3)

    if (!candidates.length) {
      setLoading(false)
      setError('')
      setRows([])
      return
    }

    let alive = true
    const cacheKey = `today-project-tasks:${dayKey}:${portfolioKey}`
    if (!shouldRunGridFetch(cacheKey, generation)) {
      const cached = readGridCache<TodayProjectTaskRow[]>(cacheKey)
      if (cached) {
        setRows(cached)
        setLoading(false)
        return
      }
    }
    setLoading(true)
    setError('')
    ;(async () => {
      try {
        const batches = await Promise.all(
          candidates.map(async (project) => {
            const res = await api.invokeServerTool('turboproject.get_project_tasks', {
              project_id: project.id,
              status: 'open',
              limit: 40
            })
            if (!res.ok || !res.result || typeof res.result !== 'object') {
              return { projectId: project.id, tasks: [] as Record<string, unknown>[] }
            }
            const payload = res.result as Record<string, unknown>
            const raw = Array.isArray(payload.tasks) ? payload.tasks : []
            return {
              projectId: project.id,
              tasks: raw.filter(
                (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object'
              )
            }
          })
        )
        if (!alive) return
        const merged = batches
          .flatMap((batch) =>
            batch.tasks
              .filter((task) => taskMatchesDay(task, periodDay))
              .map((task) => ({ task, projectId: batch.projectId }))
          )
          .sort((left, right) => {
            const leftDelay = Number(left.task.delay_days ?? 0)
            const rightDelay = Number(right.task.delay_days ?? 0)
            if (rightDelay !== leftDelay) return rightDelay - leftDelay
            return String(left.task.finish_date || '').localeCompare(String(right.task.finish_date || ''))
          })
          .slice(0, 4)
          .map(({ task, projectId }) => mapTask(task, projectId, spec.erpFio))
        setRows(merged)
        writeGridCache(cacheKey, merged)
      } catch (err) {
        if (!alive) return
        setRows([])
        setError(err instanceof Error ? err.message : 'Не удалось загрузить задачи TurboProject')
      } finally {
        if (alive) setLoading(false)
      }
    })()

    return () => {
      alive = false
    }
  }, [
    dayKey,
    portfolioKey,
    generation,
    spec.sourcesLoading,
    spec.turboNoSession,
    spec.erpFio,
    periodDay
  ])

  const resolvedRows = useMemo(() => {
    if (rows.length) return rows
    return TODAY_PROJECT_TASK_ROWS
  }, [rows])

  return {
    loading: (spec.sourcesLoading || loading) && rows.length === 0,
    noSession: spec.turboNoSession,
    error: resolvedRows.length ? '' : error,
    rows: resolvedRows
  }
}
