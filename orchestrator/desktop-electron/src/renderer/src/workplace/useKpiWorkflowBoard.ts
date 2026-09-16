import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowBoard } from '../api/types'

const EMPTY: WorkflowBoard = { stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' }, agents: [], events: [] }

/** Календарь запусков агентов за выбранный KPI-период. */
export function useKpiWorkflowBoard(from: string, to: string): {
  board: WorkflowBoard
  loading: boolean
} {
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void api
      .getWorkflowBoard({ window_from: from, window_to: to })
      .then((next) => {
        if (!cancelled) setBoard(next)
      })
      .catch(() => {
        if (!cancelled) setBoard(EMPTY)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [from, to])

  return { board, loading }
}
