import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { agentClient } from '../api/agent'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowFileItem } from '../api/types'
import { meetingsFromEvents, type MiniMeeting } from '../components/agentfeed/MiniCalendar'
import { parseIso } from '../utils/calendar'
import { cleanRunResult } from '../utils/cleanRunResult'
import { useRuns } from '../store/runs'
import {
  extractPermissionDecisions,
  feedItemsToRunnerEvents,
  isDecisionTool,
  isPermissionDecision,
  toolIntent,
  type ToolDecisionItem
} from './decisionTools'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'
import { isUserFacingResultFile } from './preparedDecisions'
import { useSpecV04SourcesContext } from './SpecV04SourcesProvider'
import { useWorkplaceData, type WorkplaceAgent } from './WorkplaceBoard'

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

export function decisionDayKey(stamp: Date): string {
  return `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}`
}

export function todayDecisionDayKey(): string {
  return decisionDayKey(new Date())
}

export function shiftDecisionDay(base: string, delta: number): string {
  const stamp = parseIso(`${base}T12:00:00`) || new Date()
  stamp.setDate(stamp.getDate() + delta)
  return decisionDayKey(stamp)
}

export function decisionInRange(stamp: Date | null, fromDay: string, toDay: string): boolean {
  if (!stamp) return false
  const key = decisionDayKey(stamp)
  const start = fromDay <= toDay ? fromDay : toDay
  const end = fromDay <= toDay ? toDay : fromDay
  return key >= start && key <= end
}

export function runStamp(run: AgentRunHistoryItem): Date | null {
  return parseIso(run.finishedAt || run.startedAt || '')
}

function isOpenRun(status: string): boolean {
  const key = (status || '').trim().toLowerCase()
  return key === 'started' || key === 'running'
}

export function uniqueDecisionFiles(items: WorkflowFileItem[]): WorkflowFileItem[] {
  const seen = new Set<string>()
  const out: WorkflowFileItem[] = []
  for (const file of items) {
    const key = file.id || `${file.runId || ''}:${file.name}`
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push(file)
  }
  return out
}

export function attachmentNames(item: ToolDecisionItem): string[] {
  const names: string[] = []
  const visit = (value: unknown): void => {
    if (typeof value === 'string') {
      const base = value.split(/[\\/]/).pop() || value
      if (/\.(xlsx|xls|xlsm|docx|pdf|pptx|csv|png|jpe?g|zip)$/i.test(base)) names.push(base)
      return
    }
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (value && typeof value === 'object') {
      Object.values(value as Record<string, unknown>).forEach(visit)
    }
  }
  visit(item.arguments || {})
  return Array.from(new Set(names))
}

function mentionedFileNames(item: ToolDecisionItem): Set<string> {
  return new Set(attachmentNames(item).map((name) => name.toLowerCase()))
}

export function pickFilesForDecision(
  item: ToolDecisionItem,
  pool: WorkflowFileItem[]
): WorkflowFileItem[] {
  const facing = pool.filter(isUserFacingResultFile)
  const mentioned = mentionedFileNames(item)
  const byName = facing.filter((file) => mentioned.has((file.name || '').toLowerCase()))
  const byRun = facing.filter((file) => {
    const rid = (file.runId || '').trim()
    return Boolean(item.runId) && Boolean(rid) && (rid === item.runId || rid === 'local')
  })
  const runAttach = facing.filter(
    (file) => file.scope === 'run_attachment' && (!file.runId || file.runId === item.runId)
  )
  const picked = uniqueDecisionFiles([...byName, ...byRun, ...runAttach])
  if (picked.length) return picked
  return facing
    .slice()
    .sort((left, right) => String(right.createdAt || '').localeCompare(String(left.createdAt || '')))
    .slice(0, 8)
}

const FIRST_SEEN_STORAGE = 'orchestrator.decisionFirstSeen.v1'

function readFirstSeen(): Record<string, string> {
  try {
    const raw = localStorage.getItem(FIRST_SEEN_STORAGE)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function stampFirstSeen(store: Record<string, string>, key: string, fallback?: string): string {
  if (store[key]) return store[key]
  const value = fallback || new Date().toISOString()
  store[key] = value
  try {
    localStorage.setItem(FIRST_SEEN_STORAGE, JSON.stringify(store))
  } catch {
    /* ignore */
  }
  return value
}

export function decisionItemKey(item: ToolDecisionItem): string {
  if (item.requestId) return `${item.workflowId}:${item.requestId}`
  if (item.tool === 'waiting_human') return `wait-board:${item.workflowId}`
  if (item.tool === 'agent_result') return `run:${item.workflowId}:${item.runId}`
  return `${item.workflowId}:${item.runId}:${item.tool}:${item.status}`
}

export function mergeDecisionItems(
  livePending: ToolDecisionItem[],
  tools: ToolDecisionItem[]
): ToolDecisionItem[] {
  const seen = new Set<string>()
  const merged: ToolDecisionItem[] = []
  for (const item of [...livePending, ...tools]) {
    const key = decisionItemKey(item)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

export type DecisionRunResult = {
  workflowId: string
  agentName: string
  runId: string
  at: string
  text: string
  status: string
  meetings: MiniMeeting[]
}

type CatalogCache = {
  tools: ToolDecisionItem[]
  results: DecisionRunResult[]
  filesByWorkflow: Record<string, WorkflowFileItem[]>
}

const MAX_AGENTS = 40
const MAX_RUNS_PER_AGENT = 10

export function useDecisionCatalog(options: {
  userId?: string
  fromDay: string
  toDay: string
}): {
  agents: WorkplaceAgent[]
  loading: boolean
  loadingDetails: boolean
  error: string
  tools: ToolDecisionItem[]
  livePending: ToolDecisionItem[]
  items: ToolDecisionItem[]
  results: DecisionRunResult[]
  filesByWorkflow: Record<string, WorkflowFileItem[]>
  ensureWorkflowFiles: (workflowId: string) => void
} {
  const specUserId = useSpecV04SourcesContext().user?.id || ''
  const userId = (options.userId || specUserId || '').trim()
  const { fromDay, toDay } = options
  const generation = useGridRefreshGeneration()
  const cacheKey = `decision-catalog-perm-v2:${userId || 'anon'}:${fromDay}:${toDay}`
  const { agents, loading: agentsLoading, error: agentsError } = useWorkplaceData(
    userId ? { userId, fio: '' } : null
  )
  const runs = useRuns()
  const agentsRef = useRef(agents)
  agentsRef.current = agents
  const firstSeenRef = useRef<Record<string, string>>(readFirstSeen())
  const loadingFilesRef = useRef<Set<string>>(new Set())

  const [loadingDetails, setLoadingDetails] = useState(true)
  const [error, setError] = useState('')
  const [tools, setTools] = useState<ToolDecisionItem[]>([])
  const [results, setResults] = useState<DecisionRunResult[]>([])
  const [filesByWorkflow, setFilesByWorkflow] = useState<Record<string, WorkflowFileItem[]>>({})

  const catalogAgents = useMemo(() => agents.filter((agent) => !agent.standalone), [agents])
  const agentKey = useMemo(
    () => catalogAgents.map((item) => item.workflowId).join('|'),
    [catalogAgents]
  )
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

  const load = useCallback(async (): Promise<void> => {
    const allAgents = agentsRef.current.filter((agent) => !agent.standalone)
    if (!allAgents.length) {
      setTools([])
      setResults([])
      setFilesByWorkflow({})
      setLoadingDetails(false)
      return
    }
    setError('')
    const collectedTools: ToolDecisionItem[] = []
    const collectedResults: DecisionRunResult[] = []
    const collectedFiles: Record<string, WorkflowFileItem[]> = {}
    const seenRuns = new Set<string>()
    const liveEntries = runs.entries
    try {
      const jobs = allAgents.slice(0, MAX_AGENTS).map(async (agent) => {
        const [history, workflowFiles] = await Promise.all([
          api.listAgentRuns(agent.workflowId).catch(() => [] as AgentRunHistoryItem[]),
          api.listWorkflowFiles(agent.workflowId).catch(() => [] as WorkflowFileItem[])
        ])
        const visibleFiles = workflowFiles.filter(isUserFacingResultFile)
        collectedFiles[agent.workflowId] = visibleFiles

        const live = liveEntries[agent.workflowId]
        if (live?.state.items.length) {
          const liveEvents = feedItemsToRunnerEvents(live.state.items)
          const liveRunId = live.backendRunId || live.state.activeRunId || `live:${agent.workflowId}`
          const liveAt = new Date(live.state.runningSinceMs || Date.now()).toISOString()
          if (liveEvents.length) {
            seenRuns.add(`${agent.workflowId}:${liveRunId}`)
            const extracted = extractPermissionDecisions(liveEvents, {
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: liveRunId,
              at: liveAt,
              runClosed: !live.state.running
            })
            for (const item of extracted) {
              item.files = pickFilesForDecision(item, visibleFiles)
            }
            collectedTools.push(...extracted)
          }
          const cleaned = cleanRunResult({
            answer: '',
            events: liveEvents,
            status: live.state.running ? 'running' : 'ok'
          })
          const meetings = meetingsFromEvents(liveEvents)
          if (cleaned.text || meetings.length) {
            collectedResults.push({
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: liveRunId,
              at: liveAt,
              text: cleaned.text,
              status: live.state.running ? 'running' : 'ok',
              meetings
            })
          }
        }

        const matched = history
          .filter((run) => decisionInRange(runStamp(run), fromDay, toDay))
          .slice(0, MAX_RUNS_PER_AGENT)
        for (const run of matched) {
          const runKey = `${agent.workflowId}:${run.runId}`
          if (seenRuns.has(runKey)) continue
          seenRuns.add(runKey)
          const detail = await api.getAgentRunDetail(agent.workflowId, run.runId).catch(() => null)
          const events: AgentRunnerEvent[] = detail?.events || []
          const at = run.finishedAt || run.startedAt || ''
          const extracted = extractPermissionDecisions(events, {
            workflowId: agent.workflowId,
            agentName: agent.name,
            runId: run.runId,
            at,
            runClosed: !isOpenRun(run.status)
          })
          for (const item of extracted) {
            item.files = pickFilesForDecision(item, visibleFiles)
          }
          collectedTools.push(...extracted)
          const cleaned = cleanRunResult({
            answer: detail?.item.answer || run.answer,
            summary: run.summary,
            events,
            status: run.status
          })
          const meetings = meetingsFromEvents(events)
          const storedMeetings = detail?.item.calendarMeetings || []
          const plan = meetings.length ? meetings : storedMeetings
          if (cleaned.text || plan.length) {
            collectedResults.push({
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: run.runId,
              at,
              text: cleaned.text,
              status: run.status,
              meetings: plan
            })
          }
        }
      })
      await Promise.all(jobs)
    } catch (err) {
      setTools([])
      setResults([])
      setFilesByWorkflow({})
      setError(err instanceof Error ? err.message : 'Не удалось загрузить решения')
      return
    }

    collectedTools.sort((left, right) => String(right.at).localeCompare(String(left.at)))
    collectedResults.sort((left, right) => String(right.at).localeCompare(String(left.at)))
    setTools(collectedTools)
    setResults(collectedResults)
    setFilesByWorkflow((prev) => ({ ...prev, ...collectedFiles }))
    writeGridCache(cacheKey, {
      tools: collectedTools,
      results: collectedResults,
      filesByWorkflow: collectedFiles
    } satisfies CatalogCache)
  }, [fromDay, toDay, runActivityKey, runs.entries, cacheKey])

  useEffect(() => {
    let alive = true
    const policyKey = `${cacheKey}:${runActivityKey}|${agentKey}`
    if (!shouldRunGridFetch(policyKey, generation)) {
      const cached = readGridCache<CatalogCache>(cacheKey)
      if (cached) {
        setTools(cached.tools)
        setResults(cached.results)
        setFilesByWorkflow((prev) => ({ ...prev, ...cached.filesByWorkflow }))
        setLoadingDetails(false)
        return
      }
    }
    if (!agentKey) {
      setLoadingDetails(agentsLoading)
      return
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
  }, [load, agentKey, agentsLoading, cacheKey, generation, runActivityKey])

  useEffect(() => {
    return agentClient.onEvent((event) => {
      if (event.type !== 'files_updated') return
      void load()
    })
  }, [load])

  useEffect(() => {
    const timer = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(timer)
  }, [load])

  const livePending = useMemo(() => {
    if (!decisionInRange(new Date(), fromDay, toDay)) return []
    const items: ToolDecisionItem[] = []
    const seen = new Set<string>()
    for (const entry of Object.values(runs.entries)) {
      const hitl = entry.state.pendingHitl
      if (hitl) {
        const tool = String(hitl.tool || '')
        if (isDecisionTool(tool, true)) {
          const seenKey = `${entry.workflowId}:${hitl.requestId}`
          const item: ToolDecisionItem = {
            id: `live:${entry.workflowId}:${hitl.requestId}`,
            workflowId: entry.workflowId,
            agentName: entry.title,
            runId: entry.backendRunId || entry.state.activeRunId || '',
            tool,
            title: hitl.title || tool,
            intent: toolIntent(tool, hitl.arguments),
            result: '',
            status: 'pending',
            requestId: hitl.requestId,
            at: stampFirstSeen(firstSeenRef.current, seenKey),
            live: true,
            permissionRequested: true,
            arguments: hitl.arguments && typeof hitl.arguments === 'object' ? hitl.arguments : {}
          }
          item.files = pickFilesForDecision(item, filesByWorkflow[entry.workflowId] || [])
          items.push(item)
          seen.add(entry.workflowId)
        }
      }
      const question = entry.state.pendingQuestion
      if (question?.requestId) {
        const seenKey = `${entry.workflowId}:${question.requestId}`
        items.push({
          id: `live:${entry.workflowId}:${question.requestId}`,
          workflowId: entry.workflowId,
          agentName: entry.title,
          runId: entry.backendRunId || entry.state.activeRunId || '',
          tool: 'askQuestion',
          title: question.question || 'Вопрос агента',
          intent: question.question || 'Агент ждёт ответ, чтобы продолжить прогон.',
          result: '',
          status: 'pending',
          requestId: question.requestId,
          at: stampFirstSeen(firstSeenRef.current, seenKey),
          live: true,
          permissionRequested: true
        })
        seen.add(entry.workflowId)
      }
    }
    for (const agent of catalogAgents) {
      if (agent.status !== 'WAITING_HUMAN' || seen.has(agent.workflowId)) continue
      const live = runs.entries[agent.workflowId]
      if (live?.state.pendingHitl || live?.state.pendingQuestion) continue
      const taskTitle = agent.tasks.find((task) => task.status === 'needs_decision')?.title
      const seenKey = `wait-board:${agent.workflowId}`
      items.push({
        id: `wait-board:${agent.workflowId}`,
        workflowId: agent.workflowId,
        agentName: agent.name,
        runId: live?.backendRunId || agent.tasks.find((task) => task.runId)?.runId || '',
        tool: 'waiting_human',
        title: taskTitle || `Решение: ${agent.name}`,
        intent: 'Агент подготовил материал и ждёт подтверждения человека.',
        result: '',
        status: 'pending',
        requestId: '',
        at: stampFirstSeen(firstSeenRef.current, seenKey),
        live: true,
        permissionRequested: true
      })
    }
    return items
  }, [runs.entries, fromDay, toDay, filesByWorkflow, catalogAgents])

  const items = useMemo(
    () => mergeDecisionItems(livePending, tools).filter(isPermissionDecision),
    [livePending, tools]
  )

  const ensureWorkflowFiles = useCallback((workflowId: string) => {
    const id = (workflowId || '').trim()
    if (!id || filesByWorkflow[id] || loadingFilesRef.current.has(id)) return
    loadingFilesRef.current.add(id)
    void api
      .listWorkflowFiles(id)
      .catch(() => [] as WorkflowFileItem[])
      .then((files) => {
        setFilesByWorkflow((prev) => ({ ...prev, [id]: files.filter(isUserFacingResultFile) }))
      })
      .finally(() => {
        loadingFilesRef.current.delete(id)
      })
  }, [filesByWorkflow])

  return {
    agents: catalogAgents,
    loading: agentsLoading || loadingDetails,
    loadingDetails,
    error: agentsError || error,
    tools,
    livePending,
    items,
    results,
    filesByWorkflow,
    ensureWorkflowFiles
  }
}
