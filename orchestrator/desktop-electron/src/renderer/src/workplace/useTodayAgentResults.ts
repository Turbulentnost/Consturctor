import { useCallback, useEffect, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import { parseFileDate } from '../pages/filesGrouping'
import { sameDay } from '../utils/calendar'
import type { SpecPillTone } from './specV04DemoData'
import { isUserFacingResultFile } from './preparedDecisions'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'

export type TodayAgentResultItem = {
  id: string
  name: string
  kind: 'doc' | 'pdf' | 'xls' | 'csv'
  tag: string
  tagTone: SpecPillTone
  downloadUrl?: string
  workflowId?: string
  runId?: string
  agentTitle?: string
  summary?: string
  createdAt?: string
}

function fileKind(name: string): 'doc' | 'pdf' | 'xls' | 'csv' {
  const lower = (name || '').toLowerCase()
  if (/\.pdf$/.test(lower)) return 'pdf'
  if (/\.csv$/.test(lower)) return 'csv'
  if (/\.xlsx?$/.test(lower)) return 'xls'
  return 'doc'
}

function mapFile(item: WorkflowFileItem): TodayAgentResultItem {
  const fromAgent = item.source === 'agent'
  return {
    id: item.id,
    name: item.name || 'file',
    kind: fileKind(item.name),
    tag: fromAgent ? 'ИИ' : 'Сотрудник',
    tagTone: fromAgent ? 'purple' : 'blue',
    downloadUrl: item.downloadUrl,
    workflowId: item.workflowId,
    runId: item.runId,
    agentTitle: item.agentTitle || undefined,
    summary: item.summary || undefined,
    createdAt: item.createdAt || undefined
  }
}

function isAgentFileOnDay(item: WorkflowFileItem, day: Date): boolean {
  if (!isUserFacingResultFile(item)) return false
  const source = String(item.source || '').toLowerCase()
  const origin = String(item.origin || '').toLowerCase()
  if (source !== 'agent' && source !== 'result' && !origin.includes('agent') && !origin.includes('result')) {
    return false
  }
  const stamp = parseFileDate(item.createdAt)
  if (!stamp) return false
  return sameDay(stamp, day)
}

export interface TodayAgentResultsState {
  loading: boolean
  error: string
  items: TodayAgentResultItem[]
  fetchedCount: number
}

/** Файлы, созданные агентами за выбранный день (период «Сегодня»). */
export function useTodayAgentResults(periodDay: Date, userId?: string): TodayAgentResultsState {
  const dayKey = `${periodDay.getFullYear()}-${periodDay.getMonth()}-${periodDay.getDate()}`
  const generation = useGridRefreshGeneration()
  const cacheKey = `today-agent-results:${userId || 'anon'}:${dayKey}`
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [items, setItems] = useState<TodayAgentResultItem[]>([])

  const load = useCallback(async (): Promise<void> => {
    setError('')
    try {
      const rows = await api.listPlatformFiles()
      const filtered = rows
        .filter((item) => isAgentFileOnDay(item, periodDay))
        .sort((left, right) => (right.createdAt || '').localeCompare(left.createdAt || ''))
        .map(mapFile)
      setItems(filtered)
      writeGridCache(cacheKey, filtered)
    } catch (err) {
      setItems([])
      setError(err instanceof Error ? err.message : 'Не удалось загрузить файлы')
    }
  }, [cacheKey, dayKey, periodDay])

  useEffect(() => {
    let alive = true
    if (!shouldRunGridFetch(cacheKey, generation)) {
      const cached = readGridCache<TodayAgentResultItem[]>(cacheKey)
      if (cached) {
        setItems(cached)
        setLoading(false)
        return
      }
    }
    setLoading(true)
    void load()
      .catch(() => {
        /* handled in load */
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [load, cacheKey, generation])

  useEffect(() => {
    return agentClient.onEvent((event) => {
      if (event.type !== 'files_updated') return
      void load()
    })
  }, [load])

  useEffect(() => {
    const timer = window.setInterval(() => void load(), 60_000)
    return () => window.clearInterval(timer)
  }, [load])

  return {
    loading: loading && items.length === 0,
    error,
    items,
    fetchedCount: items.length
  }
}
