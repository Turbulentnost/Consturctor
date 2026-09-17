import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowFileItem } from '../api/types'
import { parseFileDate } from '../pages/filesGrouping'
import { parseIso, sameDay } from '../utils/calendar'
import { cleanRunResult } from '../utils/cleanRunResult'
import { useRuns } from '../store/runs'
import { isInFlightRunStatus } from '../store/liveRun'
import type { SpecPillTone } from './specV04DemoData'
import {
  extractToolDecisions,
  feedItemsToRunnerEvents,
  isDecisionTool,
  toolIntent,
  type ToolDecisionItem
} from './decisionTools'
import { isUserFacingResultFile, readVerdict } from './preparedDecisions'
import { useWorkplaceData } from './WorkplaceBoard'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'
import { agentClient } from '../api/agent'
import {
  subtitleFromAgentResultFile,
  subtitleFromToolDecision
} from '../tabs/grid/todayAgentActionSummary'
import type { TodayAgentResultItem } from './useTodayAgentResults'
import { TODAY_PREPARED_DECISIONS } from '../tabs/grid/todayDemoData'

export type TodayPreparedDecisionRow = {
  id: string
  title: string
  status: string
  statusTone: SpecPillTone
  statusIcon: '✓' | '!' | '…'
  tag: string
  tagTone: SpecPillTone
  subtitle: string
  workflowId: string
  agentName: string
  runId?: string
  requestId?: string
  fileId?: string
  kind: 'tool' | 'file' | 'waiting' | 'result'
  at: string
}

export interface TodayPreparedDecisionsState {
  loading: boolean
  error: string
  items: TodayPreparedDecisionRow[]
}

function isOnPeriodDay(at: string, periodDay: Date): boolean {
  const stamp = parseIso(at)
  return stamp ? sameDay(stamp, periodDay) : false
}

function runStamp(run: AgentRunHistoryItem): Date | null {
  return parseIso(run.finishedAt || run.startedAt || '')
}

function isOpenRun(status: string): boolean {
  const key = (status || '').trim().toLowerCase()
  return key === 'started' || key === 'running'
}

function rowFromTool(item: ToolDecisionItem): TodayPreparedDecisionRow {
  let status = 'На проверке'
  let statusTone: SpecPillTone = 'orange'
  let statusIcon: TodayPreparedDecisionRow['statusIcon'] = '!'
  if (item.status === 'confirmed' || item.status === 'done') {
    status = 'Готово'
    statusTone = 'green'
    statusIcon = '✓'
  } else if (item.status === 'rejected') {
    status = 'Возвращено'
    statusTone = 'orange'
    statusIcon = '!'
  } else if (item.status === 'pending' && !item.live) {
    status = 'Черновик'
    statusTone = 'gray'
    statusIcon = '…'
  }
  return {
    id: item.id,
    title: item.title,
    status,
    statusTone,
    statusIcon,
    tag: 'ИИ',
    tagTone: 'purple',
    subtitle: subtitleFromToolDecision(item),
    workflowId: item.workflowId,
    agentName: item.agentName,
    runId: item.runId || undefined,
    requestId: item.requestId || undefined,
    kind: 'tool',
    at: item.at
  }
}

function rowFromFile(
  file: WorkflowFileItem,
  agentName: string,
  mapped: TodayAgentResultItem
): TodayPreparedDecisionRow {
  return {
    id: `file:${file.workflowId}:${file.id || file.name}`,
    title: file.name || 'Файл результата',
    status: 'На проверке',
    statusTone: 'orange',
    statusIcon: '!',
    tag: 'ИИ',
    tagTone: 'purple',
    subtitle: subtitleFromAgentResultFile(mapped),
    workflowId: file.workflowId || '',
    agentName,
    runId: file.runId || undefined,
    fileId: file.id || file.name,
    kind: 'file',
    at: file.createdAt || ''
  }
}

function rowFromRunResult(
  workflowId: string,
  agentName: string,
  runId: string,
  at: string,
  title: string,
  text: string
): TodayPreparedDecisionRow {
  const summary = (text || '').trim()
  return {
    id: `run:${workflowId}:${runId}`,
    title: title || `Итог: ${agentName}`,
    status: 'Готово',
    statusTone: 'green',
    statusIcon: '✓',
    tag: 'ИИ',
    tagTone: 'purple',
    subtitle: summary.length > 160 ? `${summary.slice(0, 157)}…` : summary,
    workflowId,
    agentName,
    runId,
    kind: 'result',
    at
  }
}

function mapAgentFile(item: WorkflowFileItem): TodayAgentResultItem {
  const lower = (item.name || '').toLowerCase()
  const kind = /\.pdf$/.test(lower) ? 'pdf' : /\.(xlsx?|csv)$/.test(lower) ? 'xls' : 'doc'
  return {
    id: item.id,
    name: item.name || 'file',
    kind,
    tag: 'ИИ',
    tagTone: 'purple',
    downloadUrl: item.downloadUrl,
    workflowId: item.workflowId,
    runId: item.runId,
    agentTitle: item.agentTitle || undefined,
    summary: item.summary || undefined
  }
}

function dedupeKey(row: TodayPreparedDecisionRow): string {
  if (row.requestId) return `${row.workflowId}:${row.requestId}`
  if (row.fileId) return `file:${row.workflowId}:${row.fileId}`
  return `${row.kind}:${row.id}`
}

const MAX_AGENTS = 40
const MAX_ROWS = 8
const MAX_RUNS_PER_AGENT = 12

/** Подготовленные решения за выбранный день: HITL, подтверждения инструментов, файлы агентов без вердикта. */
export function useTodayPreparedDecisions(periodDay: Date, userId?: string): TodayPreparedDecisionsState {
  const dayScope = `${periodDay.getFullYear()}-${periodDay.getMonth()}-${periodDay.getDate()}`
  const generation = useGridRefreshGeneration()
  const cacheKey = `today-prepared-decisions:${userId || 'anon'}:${dayScope}`
  const { agents, loading: agentsLoading, error: agentsError } = useWorkplaceData()
  const runs = useRuns()
  const agentsRef = useRef(agents)
  agentsRef.current = agents

  const [loadingDetails, setLoadingDetails] = useState(true)
  const [error, setError] = useState('')
  const [toolRows, setToolRows] = useState<TodayPreparedDecisionRow[]>([])
  const [fileRows, setFileRows] = useState<TodayPreparedDecisionRow[]>([])
  const [waitingRows, setWaitingRows] = useState<TodayPreparedDecisionRow[]>([])
  const [resultRows, setResultRows] = useState<TodayPreparedDecisionRow[]>([])

  const runActivityKey = useMemo(
    () =>
      Object.entries(runs.entries)
        .map(([wid, entry]) => {
          const state = entry.state
          return [
            wid,
            entry.backendRunId,
            state.activeRunId,
            state.running,
            state.items.length,
            state.status,
            state.pendingHitl?.requestId || '',
            state.pendingQuestion?.requestId || ''
          ].join(':')
        })
        .join('|'),
    [runs.entries]
  )

  const agentKey = useMemo(
    () => agents.filter((a) => !a.standalone).map((a) => a.workflowId).join('|'),
    [agents]
  )

  const load = useCallback(async (): Promise<void> => {
    setError('')
    const allAgents = agentsRef.current
    if (!allAgents.length) {
      setToolRows([])
      setFileRows([])
      setWaitingRows([])
      setResultRows([])
      return
    }

    const collectedTools: ToolDecisionItem[] = []
    const collectedFiles: TodayPreparedDecisionRow[] = []
    const collectedWaiting: TodayPreparedDecisionRow[] = []
    const collectedResults: TodayPreparedDecisionRow[] = []
    const seenRuns = new Set<string>()
    const liveEntries = runs.entries
    const viewingToday = sameDay(periodDay, new Date())

    try {
      const allPlatformFiles = await api.listPlatformFiles().catch(() => [] as WorkflowFileItem[])
      const platformByWorkflow = new Map<string, WorkflowFileItem[]>()
      for (const file of allPlatformFiles) {
        if (file.source !== 'agent' || !isUserFacingResultFile(file)) continue
        const stamp = parseFileDate(file.createdAt)
        if (!stamp || !sameDay(stamp, periodDay)) continue
        const wid = file.workflowId || ''
        if (!wid) continue
        const bucket = platformByWorkflow.get(wid) || []
        bucket.push(file)
        platformByWorkflow.set(wid, bucket)
      }

      const jobs = allAgents.slice(0, MAX_AGENTS).map(async (agent) => {
        const history = await api.listAgentRuns(agent.workflowId).catch(() => [] as AgentRunHistoryItem[])
        const agentPlatformFiles = platformByWorkflow.get(agent.workflowId) || []

        for (const file of agentPlatformFiles) {
          const fileId = file.id || file.name
          if (readVerdict(agent.workflowId, fileId)) continue
          collectedFiles.push(rowFromFile(file, agent.name, mapAgentFile(file)))
        }

        const live = liveEntries[agent.workflowId]
        if (live?.state.pendingHitl && viewingToday) {
          const hitl = live.state.pendingHitl
          const tool = String(hitl.tool || '')
          if (isDecisionTool(tool, true)) {
            collectedWaiting.push({
              id: `wait:${agent.workflowId}:${hitl.requestId}`,
              title: hitl.title || tool || `Решение: ${agent.name}`,
              status: 'На проверке',
              statusTone: 'orange',
              statusIcon: '!',
              tag: 'ИИ',
              tagTone: 'purple',
              subtitle: toolIntent(tool, hitl.arguments),
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: live.backendRunId || live.state.activeRunId || undefined,
              requestId: hitl.requestId,
              kind: 'waiting',
              at: new Date(live.state.runningSinceMs || Date.now()).toISOString()
            })
          }
        }
        if (live?.state.pendingQuestion && viewingToday) {
          const question = live.state.pendingQuestion
          collectedWaiting.push({
            id: `wait:${agent.workflowId}:${question.requestId}`,
            title: question.question || `Вопрос: ${agent.name}`,
            status: 'На проверке',
            statusTone: 'orange',
            statusIcon: '!',
            tag: 'ИИ',
            tagTone: 'purple',
            subtitle: 'Агент ждёт ответ, чтобы продолжить прогон.',
            workflowId: agent.workflowId,
            agentName: agent.name,
            runId: live.backendRunId || live.state.activeRunId || undefined,
            requestId: question.requestId,
            kind: 'waiting',
            at: new Date(live.state.runningSinceMs || Date.now()).toISOString()
          })
        }

        if (
          agent.status === 'WAITING_HUMAN' &&
          viewingToday &&
          !live?.state.pendingHitl &&
          !live?.state.pendingQuestion
        ) {
          const taskTitle = agent.tasks.find((task) => task.status === 'needs_decision')?.title
          collectedWaiting.push({
            id: `wait-board:${agent.workflowId}`,
            title: taskTitle || `Решение: ${agent.name}`,
            status: 'На проверке',
            statusTone: 'orange',
            statusIcon: '!',
            tag: 'ИИ',
            tagTone: 'purple',
            subtitle: 'Агент подготовил материал и ждёт подтверждения человека.',
            workflowId: agent.workflowId,
            agentName: agent.name,
            runId: live?.backendRunId || agent.tasks.find((task) => task.runId)?.runId,
            kind: 'waiting',
            at: new Date().toISOString()
          })
        }

        if (live?.state.items.length) {
          const liveEvents = feedItemsToRunnerEvents(live.state.items)
          const liveRunId = live.backendRunId || live.state.activeRunId || `live:${agent.workflowId}`
          const liveAt = new Date(live.state.runningSinceMs || Date.now()).toISOString()
          if (liveEvents.length && (viewingToday || isOnPeriodDay(liveAt, periodDay))) {
            seenRuns.add(`${agent.workflowId}:${liveRunId}`)
            const extracted = extractToolDecisions(liveEvents, {
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: liveRunId,
              at: liveAt,
              runClosed: !live.state.running
            })
            for (const item of extracted) {
              if (!isOnPeriodDay(item.at, periodDay) && !viewingToday) continue
              collectedTools.push(item)
            }
          }
        }

        const matched = history
          .filter((run) => {
            const stamp = runStamp(run)
            return stamp ? sameDay(stamp, periodDay) : false
          })
          .slice(0, MAX_RUNS_PER_AGENT)

        const latestResult = matched.reduce<AgentRunHistoryItem | null>((best, run) => {
          if (isInFlightRunStatus(run.status)) return best
          if (!best) return run
          const bestAt = runStamp(best)?.getTime() || 0
          const runAt = runStamp(run)?.getTime() || 0
          return runAt >= bestAt ? run : best
        }, null)

        for (const run of matched) {
          const runKey = `${agent.workflowId}:${run.runId}`
          if (seenRuns.has(runKey)) continue
          seenRuns.add(runKey)
          const detail = await api.getAgentRunDetail(agent.workflowId, run.runId).catch(() => null)
          const events: AgentRunnerEvent[] = detail?.events || []
          const at = run.finishedAt || run.startedAt || ''
          const extracted = extractToolDecisions(events, {
            workflowId: agent.workflowId,
            agentName: agent.name,
            runId: run.runId,
            at,
            runClosed: !isOpenRun(run.status)
          })
          collectedTools.push(...extracted.filter((item) => isOnPeriodDay(item.at, periodDay)))

          if (latestResult && run.runId === latestResult.runId) {
            const cleaned = cleanRunResult({
              answer: detail?.item.answer || latestResult.answer,
              summary: latestResult.summary,
              events,
              status: latestResult.status
            })
            const summary = (cleaned.text || latestResult.summary || '').trim()
            if (summary) {
              collectedResults.push(
                rowFromRunResult(
                  agent.workflowId,
                  agent.name,
                  latestResult.runId,
                  at,
                  latestResult.summary?.trim() || `Итог: ${agent.name}`,
                  summary
                )
              )
            }
          }
        }
      })
      await Promise.all(jobs)
    } catch (err) {
      setToolRows([])
      setFileRows([])
      setWaitingRows([])
      setResultRows([])
      setError(err instanceof Error ? err.message : 'Не удалось загрузить решения')
      return
    }

    const toolMapped = collectedTools
      .sort((left, right) => String(right.at).localeCompare(String(left.at)))
      .map(rowFromTool)

    setToolRows(toolMapped)
    setFileRows(collectedFiles.sort((a, b) => String(b.at).localeCompare(String(a.at))))
    setWaitingRows(collectedWaiting.sort((a, b) => String(b.at).localeCompare(String(a.at))))
    setResultRows(collectedResults.sort((a, b) => String(b.at).localeCompare(String(a.at))))
    writeGridCache(cacheKey, {
      toolRows: toolMapped,
      fileRows: collectedFiles.sort((a, b) => String(b.at).localeCompare(String(a.at))),
      waitingRows: collectedWaiting.sort((a, b) => String(b.at).localeCompare(String(a.at))),
      resultRows: collectedResults.sort((a, b) => String(b.at).localeCompare(String(a.at)))
    })
  }, [periodDay, runActivityKey, runs.entries, cacheKey])

  useEffect(() => {
    let alive = true
    const policyKey = `${cacheKey}:${runActivityKey}|${agentKey}`
    if (!shouldRunGridFetch(policyKey, generation)) {
      const cached = readGridCache<{
        toolRows: TodayPreparedDecisionRow[]
        fileRows: TodayPreparedDecisionRow[]
        waitingRows: TodayPreparedDecisionRow[]
        resultRows: TodayPreparedDecisionRow[]
      }>(cacheKey)
      if (cached) {
        setToolRows(cached.toolRows)
        setFileRows(cached.fileRows)
        setWaitingRows(cached.waitingRows)
        setResultRows(cached.resultRows || [])
        setLoadingDetails(false)
        return
      }
    }
    setLoadingDetails(true)
    void load()
      .catch(() => {
        /* handled in load */
      })
      .finally(() => {
        if (alive) setLoadingDetails(false)
      })
    return () => {
      alive = false
    }
  }, [load, agentKey, cacheKey, generation, runActivityKey])

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

  const items = useMemo(() => {
    const seen = new Set<string>()
    const merged: TodayPreparedDecisionRow[] = []
    for (const row of [...waitingRows, ...resultRows, ...toolRows, ...fileRows]) {
      const key = dedupeKey(row)
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(row)
    }
    merged.sort((left, right) => String(right.at).localeCompare(String(left.at)))
    return merged.slice(0, MAX_ROWS)
  }, [waitingRows, resultRows, toolRows, fileRows])

  const resolvedItems = useMemo(() => {
    if (items.length) return items
    return TODAY_PREPARED_DECISIONS.map((row) => ({
      id: row.id,
      title: row.title,
      status: row.status,
      statusTone: row.statusTone,
      statusIcon:
        row.status === 'Согласовано' || row.status === 'Готово'
          ? ('✓' as const)
          : row.status === 'На проверке' || row.status === 'В работе'
            ? ('!' as const)
            : ('…' as const),
      tag: row.tag,
      tagTone: row.tagTone,
      subtitle: '',
      workflowId: '',
      agentName: '',
      kind: 'file' as const,
      at: ''
    }))
  }, [items])

  const loading = (agentsLoading || loadingDetails) && items.length === 0
  const combinedError = agentsError || error

  return {
    loading,
    error: resolvedItems.length ? '' : combinedError,
    items: resolvedItems
  }
}
