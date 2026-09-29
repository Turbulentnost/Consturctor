import type { BoardAgent, CalendarEvent } from '../api/types'
import { parseIso, sameDay } from '../utils/calendar'

const AUTO_LAUNCH_SOURCES = new Set(['schedule', 'trigger', 'event'])
const SUCCESS_STATUSES = new Set(['ok', 'done', 'completed'])

export type DayLaunchSummary = {
  slotCount: number
  slotDone: number
  agentIds: string[]
  agentDoneIds: string[]
}

export function isKpiPlanBoardAgent(agent: BoardAgent): boolean {
  if (agent.paused) return false
  if ((agent.kind || 'workflow').toLowerCase() === 'draft') return false
  if ((agent.status || '').toLowerCase() === 'draft') return false
  const phase = (agent.phase || '').toLowerCase()
  if (phase && phase !== 'done') return false
  return true
}

export function isAutoLaunchSource(source: string): boolean {
  const value = (source || '').trim().toLowerCase()
  if (value === 'manual' || value === 'chat') return false
  return !value || AUTO_LAUNCH_SOURCES.has(value)
}

export function isSuccessfulLaunchStatus(status: string): boolean {
  return SUCCESS_STATUSES.has((status || '').trim().toLowerCase())
}

function isCanceledLaunch(event: CalendarEvent): boolean {
  const status = (event.status || '').toLowerCase()
  return status === 'canceled' || status === 'cancelled'
}

function isNoiseLaunch(event: CalendarEvent): boolean {
  if (isCanceledLaunch(event)) return true
  const text = `${event.subtitle || ''} ${event.title || ''}`.trim().toLowerCase()
  return text.startsWith('агент уже выполняется')
}

export function filterDayLaunchEvents(
  events: CalendarEvent[],
  agents: BoardAgent[],
  day: Date
): CalendarEvent[] {
  const allowed = new Set(
    agents.filter(isKpiPlanBoardAgent).map((agent) => agent.id).filter(Boolean)
  )
  return events.filter((event) => {
    if (!allowed.has(event.workflowId)) return false
    if (!isAutoLaunchSource(event.source)) return false
    if (isNoiseLaunch(event)) return false
    const stamp = parseIso(event.startAt)
    return Boolean(stamp && sameDay(stamp, day))
  })
}

export function summarizeDayLaunches(
  events: CalendarEvent[],
  agents: BoardAgent[],
  day: Date
): DayLaunchSummary {
  const slots = filterDayLaunchEvents(events, agents, day)
  const agentIds = [...new Set(slots.map((event) => event.workflowId))]
  const agentDoneIds = [
    ...new Set(slots.filter((event) => isSuccessfulLaunchStatus(event.status)).map((event) => event.workflowId))
  ]
  return {
    slotCount: slots.length,
    slotDone: slots.filter((event) => isSuccessfulLaunchStatus(event.status)).length,
    agentIds,
    agentDoneIds
  }
}
