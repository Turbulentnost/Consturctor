import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import type { AgentEvent, CalendarEvent } from '../api/types'
import { comCredentials } from './session'
import { buildFeedItems } from '../components/agentfeed/build'
import {
  applyAgentEvent,
  createRunState,
  deriveLatestOutput,
  pushSystem,
  pushUserMessage as reducerPushUser,
  type RunState
} from '../components/agentfeed/runReducer'
import { beginAgentPhase, closeTiming, EMPTY_TIMING } from '../workplace/runTiming'
import { windowFor } from '../utils/calendar'
import {
  eventBackendRunId,
  eventWorkflowId,
  isInFlightRunStatus,
  isLiveRunState,
  shouldTrackLiveRun
} from './liveRun'

const HUNG_STARTED_MS = 4 * 60 * 1000
const SDK_DEAD_ANSWER = 'Cursor SDK не отвечает'

export interface RunEntry {
  workflowId: string
  title: string
  /** Cursor SDK agent id to resume the same thread on the next message. */
  resumeAgentId: string
  /** Backend AgentRun id, when the sidecar reports it. */
  backendRunId: string
  state: RunState
  /** Silent evaluation run: hidden from live banners / chat. */
  background?: boolean
}

interface StartRunOptions {
  workflowId: string
  title: string
  message: string
  /** Message text shown in the feed (may include attachment names). */
  shownMessage?: string
  filePaths?: string[]
  resumeAgentId?: string
  forceRestart?: boolean
  /** Run without chat UI / active-agent banner. */
  background?: boolean
}

function backgroundEntryKey(workflowId: string): string {
  return `__bg_explain__${workflowId}`
}

export interface RunStore {
  entries: Record<string, RunEntry>
  getRun: (workflowId: string) => RunEntry | undefined
  /** Running or waiting-for-user runs, for the top banner. */
  activeAgents: () => RunEntry[]
  startRun: (opts: StartRunOptions) => string
  answer: (workflowId: string, requestId: string, value: string, filePaths?: string[], ok?: boolean) => void
  respondHitl: (workflowId: string, requestId: string, approved: boolean) => void
  skip: (workflowId: string) => void
  cancel: (workflowId: string) => void
  clear: (workflowId: string) => void
  /** Drop every run and stop sidecar workers. Used on logout / user switch. */
  clearAll: () => void
  /** Attach a scheduled/trigger run that the UI did not start itself. */
  noteRunning: (workflowId: string, title: string, backendRunId?: string) => void
  /** Load persisted events for a started run so the feed is not empty. */
  attachHistoryFeed: (workflowId: string) => Promise<void>
  /** Refresh banners from the board (running calendar events / lastRunStatus). */
  hydrateLive: () => Promise<void>
}

const RunContext = createContext<RunStore | null>(null)

function isActive(entry: RunEntry): boolean {
  return !entry.background && isLiveRunState(entry.state)
}

function emptyLiveEntry(
  workflowId: string,
  title: string,
  backendRunId = '',
  runId: string | null = null,
  runningSinceMs: number | null = Date.now()
): RunEntry {
  return {
    workflowId,
    title: title || 'ИИ-агент',
    resumeAgentId: '',
    backendRunId,
    state: {
      ...createRunState(),
      running: true,
      status: 'Агент работает…',
      runningSinceMs,
      activeRunId: runId,
      timing: beginAgentPhase(EMPTY_TIMING, runningSinceMs || Date.now())
    }
  }
}

export function RunProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [entries, setEntries] = useState<Record<string, RunEntry>>({})
  const entriesRef = useRef(entries)
  entriesRef.current = entries
  const indexRef = useRef<Record<string, string>>({})
  const cancelledRunIdsRef = useRef<Record<string, boolean>>({})

  const fillTitle = useCallback((workflowId: string) => {
    void api
      .getWorkflow(workflowId)
      .then((record) => {
        const title = String(record.title || '').trim()
        if (!title) return
        setEntries((prev) => {
          const entry = prev[workflowId]
          if (!entry || entry.title === title) return prev
          return { ...prev, [workflowId]: { ...entry, title } }
        })
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    const unsubscribe = agentClient.onEvent((event: AgentEvent) => {
      const kind = String(event.kind || '')
      if (kind === 'design' || kind === 'demo' || kind === 'readiness') return
      const runId = event.runId
      if (!runId) return
      if (cancelledRunIdsRef.current[runId]) {
        if (event.type === 'result' || event.type === 'error') {
          delete cancelledRunIdsRef.current[runId]
          delete indexRef.current[runId]
        }
        return
      }
      let workflowId = indexRef.current[runId]
      if (!workflowId) {
        workflowId = eventWorkflowId(event)
        if (!workflowId) return
        if (!shouldTrackLiveRun(event) && !entriesRef.current[workflowId]) return
        indexRef.current[runId] = workflowId
        if (!entriesRef.current[workflowId]?.title) fillTitle(workflowId)
      }
      const backendRunId = eventBackendRunId(event)
      let cancelBackground = false
      setEntries((prev) => {
        const entry = prev[workflowId] ?? emptyLiveEntry(workflowId, '', backendRunId, runId)
        const outcome = applyAgentEvent(entry.state, event)
        let state = outcome.state
        if (!state.activeRunId && event.type !== 'result' && event.type !== 'error') {
          state = { ...state, activeRunId: runId }
        }
        if (state.running && !state.runningSinceMs) {
          state = { ...state, runningSinceMs: Date.now() }
        }
        const isBackground = Boolean(entry.background) || workflowId.startsWith('__bg_explain__')
        if (
          isBackground &&
          (event.type === 'question' || event.type === 'hitl')
        ) {
          cancelBackground = true
          state = {
            ...state,
            running: false,
            pendingQuestion: null,
            pendingHitl: null,
            error: 'Фоновая оценка остановилась: агент запросил действие пользователя.',
            status: 'Оценка прервана',
            activeRunId: null
          }
        }
        const next: RunEntry = {
          ...entry,
          background: isBackground || entry.background,
          backendRunId: backendRunId || entry.backendRunId,
          resumeAgentId: outcome.result?.agentId || entry.resumeAgentId,
          state
        }
        return { ...prev, [workflowId]: next }
      })
      if (cancelBackground) {
        cancelledRunIdsRef.current[runId] = true
        agentClient.cancel(runId)
        delete indexRef.current[runId]
        return
      }
      if (event.type === 'result' || event.type === 'error') {
        delete indexRef.current[runId]
      }
    })
    return unsubscribe
  }, [fillTitle])

  const startRun = useCallback((opts: StartRunOptions): string => {
    const { workflowId, title, message, shownMessage, filePaths, resumeAgentId, forceRestart, background } = opts
    const entryKey = background ? backgroundEntryKey(workflowId) : workflowId
    const existing = entriesRef.current[entryKey]
    if (existing && existing.state.running) {
      if (!forceRestart && !background) {
        // The same agent cannot run twice at once - focus the live run instead.
        return existing.state.activeRunId || ''
      }
      if (existing.state.activeRunId) {
        agentClient.cancel(existing.state.activeRunId)
      }
    }
    const token = api.getToken()
    const creds = comCredentials()
    void agentClient
      .ready(token, { login: creds.login, password: creds.password })
      .catch(() => undefined)
    // Background evaluations always start a fresh thread (no resume / no chat).
    const resume = background ? '' : resumeAgentId || existing?.resumeAgentId || ''
    const runId = agentClient.start({
      kind: 'run',
      workflowId,
      message,
      resumeAgentId: resume || undefined,
      filePaths: filePaths && filePaths.length ? filePaths : undefined
    })
    indexRef.current[runId] = entryKey
    setEntries((prev) => {
      const prevEntry = prev[entryKey]
      const baseState = prevEntry?.state ?? createRunState()
      const items = shownMessage ? reducerPushUser(baseState.items, shownMessage) : baseState.items
      const state: RunState = {
        ...baseState,
        items,
        error: '',
        pendingQuestion: null,
        pendingHitl: null,
        running: true,
        status: forceRestart ? 'Перезапускаю агент…' : 'Агент запускается…',
        runningSinceMs: Date.now(),
        activeRunId: runId,
        timing: beginAgentPhase(EMPTY_TIMING)
      }
      return {
        ...prev,
        [entryKey]: {
          workflowId,
          title: title || prevEntry?.title || 'ИИ-агент',
          resumeAgentId: resume,
          backendRunId: prevEntry?.backendRunId || '',
          background: Boolean(background),
          state
        }
      }
    })
    return runId
  }, [])

  const answer = useCallback(
    (workflowId: string, requestId: string, value: string, filePaths?: string[], ok = true) => {
      agentClient.answer(requestId, value, ok, filePaths || [])
      setEntries((prev) => {
        const entry = prev[workflowId]
        if (!entry) return prev
        return {
          ...prev,
          [workflowId]: {
            ...entry,
            state: {
              ...entry.state,
              pendingQuestion: null,
              status: 'Агент работает…',
              timing: beginAgentPhase(entry.state.timing || EMPTY_TIMING)
            }
          }
        }
      })
    },
    []
  )

  const respondHitl = useCallback((workflowId: string, requestId: string, approved: boolean) => {
    agentClient.hitl(requestId, approved)
    setEntries((prev) => {
      const entry = prev[workflowId]
      if (!entry) return prev
      return {
        ...prev,
        [workflowId]: {
          ...entry,
          state: {
            ...entry.state,
            pendingHitl: null,
            status: approved ? 'Выполняю действие…' : 'Действие отклонено',
            runningSinceMs: approved ? entry.state.runningSinceMs || Date.now() : entry.state.runningSinceMs,
            timing: beginAgentPhase(entry.state.timing || EMPTY_TIMING)
          }
        }
      }
    })
  }, [])

  const skip = useCallback((workflowId: string) => {
    agentClient.skip('')
    setEntries((prev) => {
      const entry = prev[workflowId]
      if (!entry) return prev
      return {
        ...prev,
        [workflowId]: { ...entry, state: { ...entry.state, pendingHitl: null, status: 'Пропускаю инструмент…' } }
      }
    })
  }, [])

  const cancel = useCallback((workflowId: string) => {
    const entry = entriesRef.current[workflowId]
    const runId = entry?.state.activeRunId
    if (runId) {
      cancelledRunIdsRef.current[runId] = true
      delete indexRef.current[runId]
      agentClient.cancel(runId, workflowId)
    } else {
      agentClient.cancel('', workflowId)
    }
    const backendRunId = entry?.backendRunId || ''
    if (backendRunId) {
      void api
        .finishLocalAgentRun(workflowId, backendRunId, {
          status: 'canceled',
          answer: 'Остановлено пользователем'
        })
        .catch(() => undefined)
    }
    setEntries((prev) => {
      const current = prev[workflowId]
      if (!current) return prev
      return {
        ...prev,
        [workflowId]: {
          ...current,
          state: {
            ...current.state,
            running: false,
            runningSinceMs: null,
            status: '',
            pendingQuestion: null,
            pendingHitl: null,
            activeRunId: null,
            timing: closeTiming(current.state.timing || EMPTY_TIMING),
            items: pushSystem(current.state.items, 'Запуск остановлен.', 'info')
          }
        }
      }
    })
  }, [])

  const clear = useCallback((workflowId: string) => {
    setEntries((prev) => {
      if (!prev[workflowId]) return prev
      const next = { ...prev }
      delete next[workflowId]
      return next
    })
  }, [])

  const clearAll = useCallback(() => {
    agentClient.cancel('')
    indexRef.current = {}
    setEntries({})
  }, [])

  const attachHistoryFeed = useCallback(async (workflowId: string) => {
    const wid = workflowId.trim()
    if (!wid) return
    const current = entriesRef.current[wid]
    if (current?.state.activeRunId && (current.state.items?.length ?? 0) > 0) return
    try {
      let runId = current?.backendRunId || ''
      if (!runId) {
        const list = await api.listAgentRuns(wid)
        runId =
          list.find((item) => isInFlightRunStatus(item.status))?.runId ||
          list[0]?.runId ||
          ''
      }
      if (!runId) {
        if (current && current.state.running && !current.state.activeRunId && (current.state.items?.length ?? 0) === 0) {
          setEntries((prev) => {
            const entry = prev[wid]
            if (!entry || entry.state.activeRunId) return prev
            return {
              ...prev,
              [wid]: {
                ...entry,
                state: {
                  ...entry.state,
                  running: false,
                  runningSinceMs: null,
                  status: '',
                  items: pushSystem(entry.state.items, 'Локальный агент не запустил этот слот.', 'error')
                }
              }
            }
          })
        }
        return
      }
      const detail = await api.getAgentRunDetail(wid, runId)
      const historyItems = buildFeedItems(detail.events)
      const inFlight = isInFlightRunStatus(detail.item.status)
      const startedAt = Date.parse(detail.item.startedAt || '')
      const startedMs = Number.isFinite(startedAt) ? startedAt : null
      const hung =
        inFlight &&
        !current?.state.activeRunId &&
        historyItems.length === 0 &&
        Number.isFinite(startedAt) &&
        Date.now() - startedAt > HUNG_STARTED_MS
      if (hung) {
        await api
          .finishLocalAgentRun(wid, runId, { status: 'error', answer: SDK_DEAD_ANSWER })
          .catch(() => undefined)
      }
      setEntries((prev) => {
        const entry = prev[wid] ?? emptyLiveEntry(wid, '', runId)
        if (entry.state.activeRunId && (entry.state.items?.length ?? 0) > 0) return prev
        const liveItems = entry.state.items || []
        const items =
          liveItems.length >= historyItems.length
            ? liveItems
            : historyItems
        const answer = (detail.item.answer || detail.item.summary || '').trim()
        let nextItems = items
        if (!inFlight && answer && !nextItems.some((item) => item.kind === 'result')) {
          nextItems = [...nextItems, { kind: 'result', id: `hist-res-${runId}`, text: answer }]
        }
        if (hung) {
          nextItems = pushSystem(nextItems, SDK_DEAD_ANSWER, 'error')
        } else if (inFlight && nextItems.length === 0) {
          nextItems = pushSystem(
            nextItems,
            'Запуск по расписанию. Ход появится, когда локальный агент начнёт работу.'
          )
        }
        return {
          ...prev,
          [wid]: {
            ...entry,
            backendRunId: runId || entry.backendRunId,
            state: {
              ...entry.state,
              items: nextItems,
              running: inFlight && !hung,
              runningSinceMs: inFlight && !hung ? startedMs || entry.state.runningSinceMs || Date.now() : null,
              status: inFlight && !hung ? entry.state.status || 'Агент работает…' : '',
              error: hung ? SDK_DEAD_ANSWER : entry.state.error
            }
          }
        }
      })
    } catch {
      /* board/history attach is best-effort */
    }
  }, [])

  const noteRunning = useCallback((workflowId: string, title: string, backendRunId = '') => {
    const wid = workflowId.trim()
    if (!wid) return
    setEntries((prev) => {
      const existing = prev[wid]
      if (existing) {
        if (isActive(existing)) {
          if (title && existing.title === title && (!backendRunId || existing.backendRunId === backendRunId)) {
            return prev
          }
          return {
            ...prev,
            [wid]: {
              ...existing,
              title: title || existing.title,
              backendRunId: backendRunId || existing.backendRunId
            }
          }
        }
        return {
          ...prev,
          [wid]: {
            ...existing,
            title: title || existing.title,
            backendRunId: backendRunId || existing.backendRunId,
            state: {
              ...existing.state,
              running: true,
              runningSinceMs: existing.state.runningSinceMs || Date.now(),
              status: existing.state.status || 'Агент работает…'
            }
          }
        }
      }
      return { ...prev, [wid]: emptyLiveEntry(wid, title, backendRunId) }
    })
    if (!title) fillTitle(wid)
  }, [fillTitle])

  const hydrateLive = useCallback(async () => {
    try {
      const win = windowFor('week', new Date())
      const board = await api.getWorkflowBoard({ window_from: win.from, window_to: win.to })
      const running = new Map<string, { title: string; backendRunId: string }>()
      for (const ev of board.events as CalendarEvent[]) {
        if (ev.status !== 'running' || !ev.workflowId) continue
        running.set(ev.workflowId, { title: ev.title || '', backendRunId: ev.runId || '' })
      }
      for (const agent of board.agents) {
        if (!isInFlightRunStatus(agent.lastRunStatus) || !agent.id) continue
        if (!running.has(agent.id)) {
          running.set(agent.id, { title: agent.title || '', backendRunId: '' })
        }
      }
      setEntries((prev) => {
        let changed = false
        const next = { ...prev }
        for (const [wid, info] of running) {
          const existing = next[wid]
          if (!existing) {
            next[wid] = emptyLiveEntry(wid, info.title, info.backendRunId)
            changed = true
            continue
          }
          const finishedLocally =
            !existing.state.activeRunId &&
            !isActive(existing) &&
            existing.state.items.length > 0
          if (finishedLocally) continue
          if (!isActive(existing)) {
            next[wid] = {
              ...existing,
              title: existing.title || info.title,
              backendRunId: info.backendRunId || existing.backendRunId,
              state: {
                ...existing.state,
                running: true,
                status: existing.state.status || 'Агент работает…'
              }
            }
            changed = true
          }
        }
        for (const [wid, entry] of Object.entries(next)) {
          if (running.has(wid)) continue
          if (entry.state.activeRunId) continue
          if ((entry.state.items?.length ?? 0) > 0) continue
          if (!entry.state.running) continue
          delete next[wid]
          changed = true
        }
        return changed ? next : prev
      })
      for (const [wid, info] of running) {
        const entry = entriesRef.current[wid]
        if (!entry) continue
        if ((entry.state.items?.length ?? 0) > 0) continue
        if (entry.state.activeRunId) continue
        void attachHistoryFeed(wid)
      }
    } catch {
      /* board refresh is best-effort */
    }
  }, [attachHistoryFeed])

  const getRun = useCallback((workflowId: string) => entriesRef.current[workflowId], [])

  const activeAgents = useCallback(
    () => Object.values(entriesRef.current).filter(isActive),
    []
  )

  const value = useMemo<RunStore>(
    () => ({
      entries,
      getRun,
      activeAgents,
      startRun,
      answer,
      respondHitl,
      skip,
      cancel,
      clear,
      clearAll,
      noteRunning,
      attachHistoryFeed,
      hydrateLive
    }),
    [
      entries,
      getRun,
      activeAgents,
      startRun,
      answer,
      respondHitl,
      skip,
      cancel,
      clear,
      clearAll,
      noteRunning,
      attachHistoryFeed,
      hydrateLive
    ]
  )

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>
}

export function useRuns(): RunStore {
  const ctx = useContext(RunContext)
  if (!ctx) throw new Error('useRuns must be used within a RunProvider')
  return ctx
}

export { deriveLatestOutput }
