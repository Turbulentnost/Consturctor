import type { ToolDecisionItem } from './decisionTools'
import { shortAgentLabel } from './agentAccent'

export function clipDecisionSummary(text: string, max = 160): string {
  const value = text.trim()
  if (value.length <= max) return value
  return `${value.slice(0, max - 1)}…`
}

export function isFinishedAgentRunStatus(status: string): boolean {
  const key = (status || '').trim().toLowerCase()
  if (!key) return false
  if (key === 'started' || key === 'running') return false
  return true
}

export function agentResultToToolDecision(input: {
  workflowId: string
  agentName: string
  agentCode?: string
  runId: string
  at: string
  text: string
  status: string
  hasFile?: boolean
}): ToolDecisionItem | null {
  if (!isFinishedAgentRunStatus(input.status)) return null
  const summary = (input.text || '').trim()
  if (!summary && !input.hasFile) return null
  const failed = /error|fail|ошиб/i.test(input.status)
  const title = summary
    ? clipDecisionSummary(summary, 80)
    : `Итог: ${shortAgentLabel(input.agentCode, input.agentName)}`
  return {
    id: `run:${input.workflowId}:${input.runId}`,
    workflowId: input.workflowId,
    agentName: input.agentName,
    runId: input.runId,
    tool: 'agent_result',
    title,
    intent: summary,
    result: summary,
    status: failed ? 'rejected' : 'done',
    requestId: '',
    at: input.at,
    live: false
  }
}
