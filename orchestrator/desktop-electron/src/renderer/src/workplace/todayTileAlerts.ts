import { MEETING_WORKFLOW_ID } from '../orchestrator/agents'

export const START_RUN_TITLE = 'Запуск начался'
export const FINISH_RUN_TITLE = 'Запуск закончен'
export const WAIT_CONFIRM_TITLE = 'Агент ожидает подтверждения'
export const PLANNED_START_TITLE = 'Начат плановый запуск'

export type TodayAlertTile = 'meet' | 'decisions' | 'results'

export type TodayTileAlertFlags = Record<TodayAlertTile, boolean>

export type TodayAlertNotice = {
  title?: string
  body?: string
  workflowId?: string
  unread?: boolean
}

export type TodayAlertAgent = {
  id?: string
  title?: string
  description?: string
  triggerSummary?: string
}

export type TodayAlertLiveRun = {
  workflowId?: string
  title?: string
  background?: boolean
  running?: boolean
  pendingHitl?: boolean
  pendingQuestion?: boolean
}

const MEETING_AGENT_RE = /совещан|board_meeting|meeting_prep|orch-meeting/i
const CONFIRM_RE = /ожидает подтверждения|нужно подтверждение|подтвердите|подтвердить действие/i

export function agentLooksLikeMeeting(agent: TodayAlertAgent): boolean {
  const id = String(agent.id || '').trim()
  if (id && id === MEETING_WORKFLOW_ID) return true
  return MEETING_AGENT_RE.test(`${agent.title || ''} ${agent.description || ''} ${agent.triggerSummary || ''} ${id}`)
}

export function noticeLooksLikeConfirm(notice: TodayAlertNotice): boolean {
  const title = String(notice.title || '').trim()
  const body = String(notice.body || '').trim()
  return title.startsWith(WAIT_CONFIRM_TITLE) || CONFIRM_RE.test(title) || CONFIRM_RE.test(body)
}

export function noticeLooksLikeFinish(notice: TodayAlertNotice): boolean {
  const title = String(notice.title || '').trim()
  const body = String(notice.body || '').trim()
  return title.startsWith(FINISH_RUN_TITLE) || /завершил запуск/i.test(body)
}

export function noticeLooksLikeStart(notice: TodayAlertNotice): boolean {
  const title = String(notice.title || '').trim()
  return title.startsWith(START_RUN_TITLE) || title === PLANNED_START_TITLE
}

export function routeInboxNotification(
  notice: TodayAlertNotice,
  agents: TodayAlertAgent[] = []
): TodayAlertTile | null {
  const workflowId = String(notice.workflowId || '').trim()
  const agent = agents.find((item) => String(item.id || '').trim() === workflowId)
  const meeting = agentLooksLikeMeeting({
    id: workflowId || agent?.id,
    title: `${notice.title || ''} ${agent?.title || ''}`,
    description: `${notice.body || ''} ${agent?.description || ''}`,
    triggerSummary: agent?.triggerSummary
  })

  if (noticeLooksLikeConfirm(notice)) return 'decisions'
  if (noticeLooksLikeFinish(notice)) return 'results'
  if (meeting) return 'meet'
  return null
}

export function emptyTodayTileAlerts(): TodayTileAlertFlags {
  return { meet: false, decisions: false, results: false }
}

export function collectTodayTileAlerts(opts: {
  notices?: TodayAlertNotice[]
  agents?: TodayAlertAgent[]
  liveRuns?: TodayAlertLiveRun[]
}): TodayTileAlertFlags {
  const flags = emptyTodayTileAlerts()
  const agents = opts.agents || []

  for (const notice of opts.notices || []) {
    if (notice.unread === false) continue
    const tile = routeInboxNotification(notice, agents)
    if (tile) flags[tile] = true
  }

  for (const run of opts.liveRuns || []) {
    if (run.background) continue
    if (run.pendingHitl || run.pendingQuestion) {
      flags.decisions = true
      continue
    }
    if (run.running && agentLooksLikeMeeting({ id: run.workflowId, title: run.title })) {
      flags.meet = true
    }
  }

  return flags
}

export function widgetIdForTodayTile(tileId: string): 'plan' | 'onec' | 'events' | 'projects' | null {
  if (tileId === 'day') return 'plan'
  if (tileId === 'onec') return 'onec'
  if (tileId === 'ev' || tileId === 'meet') return 'events'
  if (tileId === 'proj') return 'projects'
  return null
}

export function alertTileForWidget(widgetId: string): TodayAlertTile | null {
  if (widgetId === 'events') return 'meet'
  if (widgetId === 'decisions') return 'decisions'
  if (widgetId === 'results') return 'results'
  return null
}
