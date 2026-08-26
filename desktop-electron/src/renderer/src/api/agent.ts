import type { AgentEvent } from './types'

export interface DesignCommand {
  kind: 'design'
  id?: string
  workflowId: string
}

export interface ReadinessCommand {
  kind: 'readiness'
  id?: string
  draftId: string
}

export interface DemoCommand {
  kind: 'demo'
  id?: string
  workflowId: string
}

export interface RunCommand {
  kind: 'run'
  id?: string
  workflowId: string
  message: string
  source?: string
  triggerId?: string
  resumeAgentId?: string
  filePaths?: string[]
}

export interface CheckTriggerCommand {
  kind: 'check_trigger'
  id?: string
  triggerId: string
  workflowId?: string
}

export type StartCommand = DesignCommand | ReadinessCommand | DemoCommand | RunCommand | CheckTriggerCommand

function newRunId(): string {
  return `run-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * Thin renderer-side wrapper around window.agent (the sidecar bridge).
 * Every start returns the runId so callers can correlate events/results.
 */
export const agentClient = {
  ready(token: string | null): Promise<{ ok: boolean }> {
    if (!window.agent?.ready) return Promise.resolve({ ok: false })
    return window.agent.ready(token)
  },

  start(command: StartCommand): string {
    const id = command.id || newRunId()
    const { kind, ...rest } = command
    void window.agent.start({ ...rest, id, type: kind })
    return id
  },

  answer(requestId: string, answer: string, ok = true, filePaths: string[] = []): void {
    void window.agent.answer({ requestId, answer, ok, filePaths })
  },

  hitl(requestId: string, approved: boolean): void {
    void window.agent.hitl({ requestId, approved })
  },

  skip(requestId = ''): void {
    void window.agent.skip({ requestId })
  },

  cancel(runId = ''): void {
    void window.agent.cancel({ id: runId })
  },

  onEvent(callback: (event: AgentEvent) => void): () => void {
    return window.agent.onEvent((payload) => callback(payload as unknown as AgentEvent))
  }
}
