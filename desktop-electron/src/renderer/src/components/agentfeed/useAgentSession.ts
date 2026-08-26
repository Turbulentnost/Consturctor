import { useCallback, useEffect, useRef, useState } from 'react'
import { agentClient, type StartCommand } from '../../api/agent'
import type { AgentEvent } from '../../api/types'
import {
  applyAgentEvent,
  createRunState,
  pushSystem,
  pushUserMessage as reducerPushUser,
  type AgentResult,
  type RunState
} from './runReducer'
import type { PendingHitl, PendingQuestion, FeedItem } from './types'

export type { AgentResult } from './runReducer'

interface UseAgentSessionOptions {
  onResult?: (result: AgentResult) => void
  onError?: (message: string) => void
}

export interface UseAgentSessionValue {
  items: FeedItem[]
  status: string
  running: boolean
  error: string
  pendingQuestion: PendingQuestion | null
  pendingHitl: PendingHitl | null
  activeRunId: string | null
  start: (command: StartCommand) => string
  answer: (requestId: string, value: string, filePaths?: string[], ok?: boolean) => void
  respondHitl: (requestId: string, approved: boolean) => void
  skip: () => void
  cancel: () => void
  reset: () => void
  pushUserMessage: (text: string) => void
  pushSystem: (text: string) => void
}

/**
 * One agent session bound to a single run. Feed events are routed strictly by
 * runId so that other concurrent runs (handled by the run store) never leak
 * into this session's feed.
 */
export function useAgentSession(options: UseAgentSessionOptions = {}): UseAgentSessionValue {
  const [state, setState] = useState<RunState>(createRunState)
  const stateRef = useRef(state)
  stateRef.current = state

  const activeRunRef = useRef<string | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options

  useEffect(() => {
    const unsubscribe = agentClient.onEvent((event: AgentEvent) => {
      const runId = event.runId
      const matches = activeRunRef.current !== null && (!runId || runId === activeRunRef.current)
      if (!matches) return
      const outcome = applyAgentEvent(stateRef.current, event)
      stateRef.current = outcome.state
      setState(outcome.state)
      if (outcome.state.activeRunId === null && (event.type === 'result' || event.type === 'error')) {
        activeRunRef.current = null
      }
      if (outcome.result) optionsRef.current.onResult?.(outcome.result)
      if (outcome.error) optionsRef.current.onError?.(outcome.error)
    })
    return unsubscribe
  }, [])

  const start = useCallback((command: StartCommand): string => {
    const id = agentClient.start(command)
    activeRunRef.current = id
    setState((s) => ({
      ...s,
      error: '',
      pendingQuestion: null,
      pendingHitl: null,
      running: true,
      status: 'Агент запускается…',
      activeRunId: id
    }))
    return id
  }, [])

  const answer = useCallback((requestId: string, value: string, filePaths?: string[], ok = true) => {
    agentClient.answer(requestId, value, ok, filePaths || [])
    setState((s) => ({ ...s, pendingQuestion: null, status: 'Агент работает…' }))
  }, [])

  const respondHitl = useCallback((requestId: string, approved: boolean) => {
    agentClient.hitl(requestId, approved)
    setState((s) => ({
      ...s,
      pendingHitl: null,
      status: approved ? 'Выполняю действие…' : 'Действие отклонено'
    }))
  }, [])

  const skip = useCallback(() => {
    agentClient.skip('')
    setState((s) => ({ ...s, pendingHitl: null, status: 'Пропускаю инструмент…' }))
  }, [])

  const cancel = useCallback(() => {
    if (activeRunRef.current) agentClient.cancel(activeRunRef.current)
    setState((s) => ({ ...s, status: 'Останавливаю…' }))
  }, [])

  const reset = useCallback(() => {
    activeRunRef.current = null
    setState(createRunState())
  }, [])

  const pushUserMessage = useCallback((text: string) => {
    setState((s) => ({ ...s, items: reducerPushUser(s.items, text) }))
  }, [])

  const pushSystemMessage = useCallback((text: string) => {
    setState((s) => ({ ...s, items: pushSystem(s.items, text) }))
  }, [])

  return {
    items: state.items,
    status: state.status,
    running: state.running,
    error: state.error,
    pendingQuestion: state.pendingQuestion,
    pendingHitl: state.pendingHitl,
    activeRunId: state.activeRunId,
    start,
    answer,
    respondHitl,
    skip,
    cancel,
    reset,
    pushUserMessage,
    pushSystem: pushSystemMessage
  }
}
