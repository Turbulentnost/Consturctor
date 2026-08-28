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
  const lastCommandRef = useRef<StartCommand | null>(null)
  const retriesRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options

  const resendLast = useCallback((): void => {
    const command = lastCommandRef.current
    const runId = activeRunRef.current
    if (!command || !runId) return
    agentClient.start({ ...command, id: runId })
  }, [])

  useEffect(() => {
    const unsubscribe = agentClient.onEvent((event: AgentEvent) => {
      const runId = event.runId
      const adoptId = event.type === 'event' ? String(event.payload?.activeRunId || '') : ''
      const current = activeRunRef.current
      const isAdoptForUs = Boolean(adoptId && current && runId === current)
      if (isAdoptForUs && adoptId !== current) {
        activeRunRef.current = adoptId
      }
      const matches = current !== null && (!runId || runId === current || isAdoptForUs)
      if (!matches) return
      const outcome = applyAgentEvent(stateRef.current, event)
      stateRef.current = outcome.state
      setState(outcome.state)
      if (event.type === 'sidecar_exit' && lastCommandRef.current && retriesRef.current < 3) {
        retriesRef.current += 1
        if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
        retryTimerRef.current = setTimeout(() => {
          retryTimerRef.current = null
          resendLast()
        }, 1200)
      }
      if (event.type !== 'sidecar_exit' && event.type !== 'ready' && event.type !== 'ready_state') {
        retriesRef.current = 0
      }
      if (outcome.state.activeRunId === null && (event.type === 'result' || event.type === 'error')) {
        activeRunRef.current = null
        lastCommandRef.current = null
      }
      if (outcome.result) optionsRef.current.onResult?.(outcome.result)
      if (outcome.error) optionsRef.current.onError?.(outcome.error)
    })
    return () => {
      unsubscribe()
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    }
  }, [resendLast])

  const start = useCallback((command: StartCommand): string => {
    const prev = lastCommandRef.current
    const sameTarget =
      Boolean(activeRunRef.current) &&
      stateRef.current.running &&
      prev &&
      prev.kind === command.kind &&
      (('draftId' in prev && 'draftId' in command && prev.draftId === command.draftId) ||
        ('workflowId' in prev && 'workflowId' in command && prev.workflowId === command.workflowId))
    if (sameTarget && activeRunRef.current) {
      return activeRunRef.current
    }
    const id = agentClient.start(command)
    lastCommandRef.current = { ...command, id }
    retriesRef.current = 0
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
    activeRunRef.current = null
    setState((s) => ({
      ...s,
      running: false,
      pendingQuestion: null,
      pendingHitl: null,
      activeRunId: null,
      status: 'Агент остановлен'
    }))
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
