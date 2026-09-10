import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import { extractToolDecisions } from './decisionTools'
import { isInFlightRunStatus } from '../store/liveRun'

const STORAGE_KEY = 'orchestrator.preparedDecisions.v1'

export type ResultVerdict = 'confirmed' | 'returned'

type StoredDecisions = Record<string, ResultVerdict>

function readAll(): StoredDecisions {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed as StoredDecisions
  } catch {
    return {}
  }
}

function writeAll(value: StoredDecisions): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    /* ignore quota errors */
  }
}

export function decisionKey(workflowId: string, fileId: string): string {
  return `${workflowId}:${fileId}`
}

export function runDecisionId(runId: string): string {
  return `run:${(runId || '').trim()}`
}

export function readVerdict(workflowId: string, fileId: string): ResultVerdict | null {
  const key = decisionKey(workflowId, fileId)
  return readAll()[key] || null
}

export function writeVerdict(workflowId: string, fileId: string, verdict: ResultVerdict): void {
  const next = { ...readAll(), [decisionKey(workflowId, fileId)]: verdict }
  writeAll(next)
}

const INTERNAL_FILE_RE =
  /^(session\.json|\.?env|state\.json|run\.json|debug\.json|trace\.json|events\.json)$/i

export function isInternalResultFile(name: string): boolean {
  const base = (name || '').trim().split(/[/\\]/).pop() || ''
  if (!base) return true
  if (INTERNAL_FILE_RE.test(base)) return true
  if (/^\.(log|tmp|bak)$/i.test(base.split('.').pop() || '')) return true
  return false
}

export function isUserFacingResultFile(file: WorkflowFileItem): boolean {
  const name = (file.name || '').trim()
  if (!name || isInternalResultFile(name)) return false
  const lower = name.toLowerCase()
  if (/\.(docx|xlsx|xls|pdf|pptx|csv|md|txt|zip|html|htm|png|jpg|jpeg)$/.test(lower)) return true
  if (lower.endsWith('.json') && !isInternalResultFile(name)) {
    return /report|result|decision|meeting|session/i.test(name) && !/^session\.json$/i.test(name)
  }
  return false
}

export async function findPendingToolRequest(
  workflowId: string,
  liveRequestId?: string
): Promise<{ requestId: string; live: boolean } | null> {
  const pendingId = (liveRequestId || '').trim()
  if (pendingId) return { requestId: pendingId, live: true }

  const history = await api.listAgentRuns(workflowId).catch(() => [])
  const latest = history[0]
  if (!latest?.runId) return null
  const detail = await api.getAgentRunDetail(workflowId, latest.runId).catch(() => null)
  if (!detail || !isInFlightRunStatus(detail.item.status)) return null
  const tools = extractToolDecisions(detail.events || [], {
    workflowId,
    agentName: '',
    runId: latest.runId,
    at: latest.finishedAt || latest.startedAt || '',
    runClosed: false
  })
  const pending = tools.find((item) => item.status === 'pending' && item.requestId)
  if (!pending?.requestId) return null
  return { requestId: pending.requestId, live: false }
}
