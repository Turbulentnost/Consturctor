import type { AgentEvent, AgentRunnerEvent } from '../api/types'
import type { PendingHitl, PendingQuestion } from '../components/agentfeed/types'

const FORMATION_KINDS = new Set(['design', 'demo', 'readiness'])

/** Published-agent events that the run store should keep even if UI did not start them. */
export function shouldTrackLiveRun(event: AgentEvent): boolean {
  const kind = String(event.kind || '')
  if (FORMATION_KINDS.has(kind)) return false
  if (kind === 'eval') return false
  if (!String(event.workflowId || '').trim()) return false
  if (event.type === 'question' || event.type === 'hitl') return true
  const payloadType = String(event.payload?.type || '')
  // Empty trigger polls must not open or append to the run chat.
  if (kind === 'trigger' || kind === 'check_trigger') {
    if (event.type === 'result' && event.fired === false) return false
    return payloadType === 'run'
  }
  if (kind === 'run') return true
  if (payloadType === 'run') return true
  if (
    event.type === 'event' &&
    [
      'thinking',
      'tool_call',
      'tool_result',
      'assistant',
      'agent_message',
      'status',
      'progress',
      'decision'
    ].includes(payloadType)
  ) {
    return true
  }
  return false
}

export function eventWorkflowId(event: AgentEvent): string {
  return String(event.workflowId || '').trim()
}

export function eventBackendRunId(event: AgentEvent): string {
  const fromResult = String(event.runRef || '').trim()
  if (fromResult) return fromResult
  const payload = event.payload
  if (payload && typeof payload === 'object') {
    return String(payload.run_id || '').trim()
  }
  return ''
}

export function isLiveRunState(state: {
  running: boolean
  pendingQuestion: unknown
  pendingHitl: unknown
}): boolean {
  return state.running || Boolean(state.pendingQuestion) || Boolean(state.pendingHitl)
}

/** Backend in-flight AgentRun.status is `started`; the board maps it to `running`. */
export function isInFlightRunStatus(status: string): boolean {
  const raw = (status || '').trim().toLowerCase()
  return raw === 'started' || raw === 'running'
}

export function liveRunProgress(state: {
  running: boolean
  pendingQuestion: unknown
  pendingHitl: unknown
  timing?: { phase?: string }
  items?: Array<{ kind?: string; done?: boolean; role?: string }>
}): number {
  if (!state.running && !state.pendingQuestion && !state.pendingHitl) return 100
  if (state.pendingQuestion || state.pendingHitl) return 88
  const phase = String(state.timing?.phase || '').toLowerCase()
  if (phase === 'human') return 84
  const items = state.items || []
  const completedTools = items.filter((item) => item.kind === 'tool' && item.done).length
  if (completedTools >= 4) return 76
  if (completedTools >= 2) return 58
  if (completedTools >= 1) return 42
  if (items.some((item) => item.kind === 'message' && item.role === 'agent')) return 28
  return 12
}

export function pendingWaitsFromEvents(events: AgentRunnerEvent[]): {
  pendingHitl: PendingHitl | null
  pendingQuestion: PendingQuestion | null
} {
  let pendingHitl: PendingHitl | null = null
  let pendingQuestion: PendingQuestion | null = null
  const closed = new Set<string>()
  for (const event of events) {
    const type = String(event.type || '').toLowerCase()
    const requestId = String(event.requestId || '').trim()
    const status = String(event.status || '').toLowerCase()
    if (
      requestId &&
      (status === 'approved' || status === 'rejected' || event.skipped === true)
    ) {
      closed.add(requestId)
      if (pendingHitl?.requestId === requestId) pendingHitl = null
      if (pendingQuestion?.requestId === requestId) pendingQuestion = null
      continue
    }
    if (type === 'hitl' && requestId && !closed.has(requestId)) {
      const tool = String(event.tool || '')
      const args =
        event.arguments && typeof event.arguments === 'object' ? event.arguments : {}
      pendingHitl = {
        requestId,
        tool,
        title: String(event.title || tool),
        arguments: args
      }
    }
    if (type === 'question' && requestId && !closed.has(requestId)) {
      pendingQuestion = {
        requestId,
        question: String(event.text || event.message || event.title || 'Вопрос агента'),
        options: []
      }
    }
  }
  return { pendingHitl, pendingQuestion }
}
