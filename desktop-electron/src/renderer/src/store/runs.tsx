import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import type { AgentEvent } from '../api/types'
import {
  applyAgentEvent,
  createRunState,
  deriveLatestOutput,
  pushUserMessage as reducerPushUser,
  type RunState
} from '../components/agentfeed/runReducer'

export interface RunEntry {
  workflowId: string
  title: string
  /** Cursor SDK agent id to resume the same thread on the next message. */
  resumeAgentId: string
  state: RunState
}

interface StartRunOptions {
  workflowId: string
  title: string
  message: string
  /** Message text shown in the feed (may include attachment names). */
  shownMessage?: string
  filePaths?: string[]
  resumeAgentId?: string
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
}

const RunContext = createContext<RunStore | null>(null)

function isActive(entry: RunEntry): boolean {
  return entry.state.running || Boolean(entry.state.pendingQuestion) || Boolean(entry.state.pendingHitl)
}

export function RunProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [entries, setEntries] = useState<Record<string, RunEntry>>({})
  const entriesRef = useRef(entries)
  entriesRef.current = entries
  const indexRef = useRef<Record<string, string>>({})

  useEffect(() => {
    const unsubscribe = agentClient.onEvent((event: AgentEvent) => {
      const runId = event.runId
      if (!runId) return
      const workflowId = indexRef.current[runId]
      if (!workflowId) return
      setEntries((prev) => {
        const entry = prev[workflowId]
        if (!entry) return prev
        const outcome = applyAgentEvent(entry.state, event)
        const resumeAgentId = outcome.result?.agentId || entry.resumeAgentId
        return { ...prev, [workflowId]: { ...entry, resumeAgentId, state: outcome.state } }
      })
      if (event.type === 'result' || event.type === 'error') {
        delete indexRef.current[runId]
      }
    })
    return unsubscribe
  }, [])

  const startRun = useCallback((opts: StartRunOptions): string => {
    const { workflowId, title, message, shownMessage, filePaths, resumeAgentId } = opts
    const existing = entriesRef.current[workflowId]
    if (existing && existing.state.running) {
      // The same agent cannot run twice at once - focus the live run instead.
      return existing.state.activeRunId || ''
    }
    const resume = resumeAgentId || existing?.resumeAgentId || ''
    const runId = agentClient.start({
      kind: 'run',
      workflowId,
      message,
      resumeAgentId: resume || undefined,
      filePaths: filePaths && filePaths.length ? filePaths : undefined
    })
    indexRef.current[runId] = workflowId
    setEntries((prev) => {
      const prevEntry = prev[workflowId]
      const baseState = prevEntry?.state ?? createRunState()
      const items = shownMessage ? reducerPushUser(baseState.items, shownMessage) : baseState.items
      const state: RunState = {
        ...baseState,
        items,
        error: '',
        pendingQuestion: null,
        pendingHitl: null,
        running: true,
        status: 'Агент запускается…',
        activeRunId: runId
      }
      return {
        ...prev,
        [workflowId]: {
          workflowId,
          title: title || prevEntry?.title || 'ИИ-агент',
          resumeAgentId: resume,
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
            state: { ...entry.state, pendingQuestion: null, status: 'Агент работает…' }
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
            status: approved ? 'Выполняю действие…' : 'Действие отклонено'
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
    if (runId) agentClient.cancel(runId)
    setEntries((prev) => {
      const current = prev[workflowId]
      if (!current) return prev
      return { ...prev, [workflowId]: { ...current, state: { ...current.state, status: 'Останавливаю…' } } }
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

  const getRun = useCallback((workflowId: string) => entriesRef.current[workflowId], [])

  const activeAgents = useCallback(
    () => Object.values(entriesRef.current).filter(isActive),
    []
  )

  const value = useMemo<RunStore>(
    () => ({ entries, getRun, activeAgents, startRun, answer, respondHitl, skip, cancel, clear, clearAll }),
    [entries, getRun, activeAgents, startRun, answer, respondHitl, skip, cancel, clear, clearAll]
  )

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>
}

export function useRuns(): RunStore {
  const ctx = useContext(RunContext)
  if (!ctx) throw new Error('useRuns must be used within a RunProvider')
  return ctx
}

export { deriveLatestOutput }
