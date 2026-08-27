import type { AgentEvent } from '../api/types'

const FORMATION_KINDS = new Set(['design', 'demo', 'readiness'])

/** Published-agent events that the run store should keep even if UI did not start them. */
export function shouldTrackLiveRun(event: AgentEvent): boolean {
  const kind = String(event.kind || '')
  if (FORMATION_KINDS.has(kind)) return false
  if (!String(event.workflowId || '').trim()) return false
  if (kind === 'run') return true
  if (event.type === 'question' || event.type === 'hitl') return true
  const payloadType = String(event.payload?.type || '')
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
  if (kind === 'trigger' || kind === 'check_trigger') {
    if (event.type === 'result' && event.fired === false) return false
    return payloadType === 'run'
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
