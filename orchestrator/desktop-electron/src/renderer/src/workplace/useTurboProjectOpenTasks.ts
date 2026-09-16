import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { turboProjectTaskToTodayRow } from './specV04Mappers'
import type { TodayProjectTaskRow } from './useTodayProjectTasks'
import { turboProjectInvokeArgs } from './userContext'
import { turboTaskAssignedToActor } from './turboAssigneeMatch'
import { isTechnicalTurboMessage } from './turboSession'

export type TurboProjectOpenTaskRow = TodayProjectTaskRow

export type TurboProjectTasksFetchOptions = {
  /** When true, only incomplete tasks (status=open on gateway). */
  openOnly?: boolean
  /** When true, filter by session FIO (default). When false, all_assignees on gateway. */
  assigneeOnly?: boolean
  limit?: number
}

const DEFAULT_FETCH: Required<TurboProjectTasksFetchOptions> = {
  openOnly: true,
  assigneeOnly: true,
  limit: 100
}

export function useTurboProjectOpenTasks(
  projectId: string,
  user: UserProfile | null,
  erpFio: string,
  enabled: boolean,
  fetchOptions: TurboProjectTasksFetchOptions = {}
): {
  loading: boolean
  rows: TurboProjectOpenTaskRow[]
  error: string
  matchedCount: number
  showingAllAssignees: boolean
} {
  const { openOnly, assigneeOnly, limit } = { ...DEFAULT_FETCH, ...fetchOptions }
  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<TurboProjectOpenTaskRow[]>([])
  const [error, setError] = useState('')
  const [matchedCount, setMatchedCount] = useState(0)
  const [showingAllAssignees, setShowingAllAssignees] = useState(false)

  useEffect(() => {
    if (!enabled || !projectId || !user?.id) {
      setRows([])
      setError('')
      setMatchedCount(0)
      setShowingAllAssignees(false)
      setLoading(false)
      return
    }
    let alive = true
    setLoading(true)
    setError('')
    ;(async () => {
      try {
        const extra: Record<string, unknown> = {
          project_id: projectId,
          limit
        }
        if (openOnly) extra.status = 'open'
        extra.all_assignees = true

        const res = await api.invokeServerTool(
          'turboproject.get_project_tasks',
          turboProjectInvokeArgs(user, extra)
        )
        if (!alive) return
        if (!res.ok || !res.result || typeof res.result !== 'object') {
          setRows([])
          setMatchedCount(0)
          setShowingAllAssignees(false)
          const hint = (res.error || '').trim()
          setError(hint && !isTechnicalTurboMessage(hint) ? hint : '')
          return
        }
        const payload = res.result as Record<string, unknown>
        const matched = Number(payload.matched_tasks_count ?? 0)
        const raw = Array.isArray(payload.tasks) ? payload.tasks : []
        const all = raw.filter(
          (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object'
        )
        const mine = erpFio.trim()
          ? all.filter((task) => turboTaskAssignedToActor(task, erpFio))
          : all
        const fallbackAll = Boolean(assigneeOnly && mine.length === 0 && all.length > 0)
        const list = assigneeOnly && !fallbackAll ? mine : all
        setShowingAllAssignees(fallbackAll)
        list.sort((left, right) => {
          const leftDelay = Number(left.delay_days ?? 0)
          const rightDelay = Number(right.delay_days ?? 0)
          if (rightDelay !== leftDelay) return rightDelay - leftDelay
          return String(left.finish_date || '').localeCompare(String(right.finish_date || ''))
        })
        const mapped = list.map((task) => turboProjectTaskToTodayRow(task, projectId, erpFio))
        setRows(mapped)
        setMatchedCount(Number.isFinite(matched) && matched > 0 ? matched : mapped.length)
      } catch (err) {
        if (!alive) return
        setRows([])
        setMatchedCount(0)
        setShowingAllAssignees(false)
        setError(err instanceof Error ? err.message : 'Не удалось загрузить задачи проекта')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [projectId, user?.id, erpFio, enabled, openOnly, assigneeOnly, limit])

  return { loading, rows, error, matchedCount, showingAllAssignees }
}
