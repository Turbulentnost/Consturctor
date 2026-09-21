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

function isFinishedOk(status: string): boolean {
  const raw = (status || '').trim().toLowerCase()
  return raw === 'ok' || raw === 'success' || raw === 'done'
}

function stampOnDay(raw: string | undefined, day: Date): boolean {
  const stamp = parseFileDate(raw)
  return Boolean(stamp && sameDay(stamp, day))
}

async function oralRunsWithoutFiles(
  periodDay: Date,
  files: TodayAgentResultItem[]
): Promise<TodayAgentResultItem[]> {
  const have = new Set(files.map((item) => (item.workflowId || '').trim()).filter(Boolean))
  const board = await api.getWorkflowBoard().catch(() => null)
  const missing = (board?.agents || []).filter((agent) => {
    if (!agent.id || have.has(agent.id)) return false
    if (agent.lastRunStatus && !isFinishedOk(agent.lastRunStatus)) return false
    return stampOnDay(agent.lastRunAt, periodDay)
  })
  if (!missing.length) return []
  const extra = await Promise.all(
    missing.map(async (agent) => {
      const runs = await api.listAgentRuns(agent.id).catch(() => [])
      const run = runs.find((item) => {
        if (!isFinishedOk(item.status)) return false
        const text = (item.answer || item.summary || '').trim()
        if (!text) return false
        return stampOnDay(item.finishedAt || item.startedAt, periodDay)
      })
      if (!run) return null
      return {
        id: `run:${run.runId}`,
        name: 'Результат.md',
        kind: 'doc' as const,
        tag: 'ИИ',
        tagTone: 'purple' as SpecPillTone,
        workflowId: agent.id,
        runId: run.runId,
        agentTitle: agent.title || undefined,
        summary: (run.answer || run.summary || '').trim(),
        createdAt: run.finishedAt || run.startedAt
      } satisfies TodayAgentResultItem
    })
  )
  return extra.filter((item): item is TodayAgentResultItem => item != null)
}

export interface TodayAgentResultsState {
  loading: boolean
  error: string
  items: TodayAgentResultItem[]
  fetchedCount: number
}

/** Результаты агентов за выбранный день: файлы и устные прогоны без файла. */
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
      const fromFiles = rows
        .filter((item) => isAgentFileOnDay(item, periodDay))
        .sort((left, right) => (right.createdAt || '').localeCompare(left.createdAt || ''))
        .map(mapFile)
      const fromRuns = await oralRunsWithoutFiles(periodDay, fromFiles)
      const filtered = [...fromFiles, ...fromRuns].sort((left, right) =>
        (right.createdAt || '').localeCompare(left.createdAt || '')
      )
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
      if (event.type !== 'files_updated' && event.type !== 'result' && event.type !== 'error') return
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
