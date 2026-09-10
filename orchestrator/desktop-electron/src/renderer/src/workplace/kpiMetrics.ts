import type { AgentKpi, AgentRunHistoryItem } from '../api/types'
import { liveTotals, type LiveTiming } from './runTiming'
import type { WorkplaceAgent } from './WorkplaceBoard'

export function metricNumber(raw: unknown): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null
  if (typeof raw !== 'string') return null
  const cleaned = raw.replace(',', '.').replace(/[^\d.-]/g, '')
  if (!cleaned) return null
  const value = Number(cleaned)
  return Number.isFinite(value) ? value : null
}

export function kpiScore(kpi: AgentKpi | null): number | null {
  const scores = (kpi?.tiles || [])
    .map((tile) => tile.scorePercent)
    .filter((value): value is number => value != null && Number.isFinite(value))
  if (scores.length) return Math.round(scores.reduce((acc, value) => acc + value, 0) / scores.length)

  const ratios = (kpi?.tiles || [])
    .map((tile) => {
      const plan = metricNumber(tile.plan?.value)
      const fact = metricNumber(tile.fact?.value)
      if (plan == null || fact == null || plan <= 0) return null
      return Math.round((fact / plan) * 100)
    })
    .filter((value): value is number => value != null)
  if (ratios.length) return Math.round(ratios.reduce((acc, value) => acc + value, 0) / ratios.length)

  return null
}

export function taskCompletionPercent(agent: WorkplaceAgent): number | null {
  if (!agent.tasks.length) return null
  const done = agent.tasks.filter((task) => task.status === 'done').length
  return Math.round((100 * done) / agent.tasks.length)
}

export function resolvePlanFact(kpi: AgentKpi | null, agent: WorkplaceAgent): number | null {
  return kpiScore(kpi) ?? taskCompletionPercent(agent)
}

export function latestAgentRun(items: AgentRunHistoryItem[]): AgentRunHistoryItem | null {
  if (!items.length) return null
  return [...items].sort((left, right) => {
    const leftAt = left.startedAt || left.finishedAt || ''
    const rightAt = right.startedAt || right.finishedAt || ''
    return rightAt.localeCompare(leftAt)
  })[0]
}

export function backendRunTotals(run: AgentRunHistoryItem | null, now: number): { agentMs: number; humanMs: number } {
  if (!run) return { agentMs: 0, humanMs: 0 }
  let agentMs = run.agentWorkMs || 0
  let humanMs = run.humanWaitMs || 0
  const openAt = Date.parse(run.openSegmentAt || '')
  if (run.openSegment && Number.isFinite(openAt)) {
    const open = Math.max(0, now - openAt)
    if (run.openSegment === 'agent') agentMs += open
    if (run.openSegment === 'human') humanMs += open
  }
  const start = Date.parse(run.startedAt || '')
  const finished = Date.parse(run.finishedAt || '')
  const status = (run.status || '').toLowerCase()
  const end = Number.isFinite(finished)
    ? finished
    : run.openSegment || status === 'started' || status === 'running' || status === 'waiting_human'
      ? now
      : NaN
  if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
    const wall = end - start
    if (!agentMs && !humanMs) {
      agentMs = wall
    } else if (!agentMs && humanMs > 0 && humanMs < wall) {
      agentMs = wall - humanMs
    }
  }
  return { agentMs, humanMs }
}

export type ProcessKpiMetrics = {
  planFact: number | null
  agentDelay: number | null
  humanDelay: number | null
  automation: number | null
}

export function buildProcessKpiMetrics(
  agent: WorkplaceAgent,
  kpi: AgentKpi | null,
  latestRun: AgentRunHistoryItem | null,
  liveTiming: LiveTiming | null | undefined,
  liveActive: boolean,
  now = Date.now()
): ProcessKpiMetrics {
  const planFact = resolvePlanFact(kpi, agent)
  const totals =
    liveActive && liveTiming ? liveTotals(liveTiming, now) : backendRunTotals(latestRun, now)
  const hasRun = liveActive || Boolean(latestRun)
  const agentDelay = hasRun ? Math.max(0, Math.round(totals.agentMs / 60_000)) : null
  const humanDelay = hasRun
    ? Math.max(0, Math.round(totals.humanMs / 60_000))
    : planFact != null
      ? 0
      : null
  const automation =
    planFact != null
      ? Math.round((100 * planFact) / (planFact + (humanDelay ?? 0) / 10 + 1))
      : null
  return { planFact, agentDelay, humanDelay, automation }
}
