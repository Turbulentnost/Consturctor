import { useMemo } from 'react'
import { parseIso } from '../utils/calendar'
import type { SpecPillTone } from './specV04DemoData'
import { isPermissionDecision, isQuestionDecision, type ToolDecisionItem } from './decisionTools'
import { decisionDayKey, useDecisionCatalog } from './useDecisionCatalog'

export type TodayPreparedDecisionRow = {
  id: string
  title: string
  status: string
  statusTone: SpecPillTone
  statusIcon: '✓' | '!' | '…'
  tag: string
  tagTone: SpecPillTone
  subtitle: string
  workflowId: string
  agentName: string
  runId?: string
  requestId?: string
  fileId?: string
  kind: 'tool' | 'file' | 'waiting' | 'result'
  at: string
}

export interface TodayPreparedDecisionsState {
  loading: boolean
  error: string
  items: TodayPreparedDecisionRow[]
  total: number
}

const MAX_ROWS = 8

function permissionTitle(item: ToolDecisionItem): string {
  const title = (item.title || '').trim()
  if (title) return title
  if (isQuestionDecision(item.tool)) return 'Агенту нужен ответ, чтобы продолжить'
  if (item.tool && item.tool !== 'waiting_human') return `Разрешение на операцию ${item.tool}`
  return 'Агенту потребовалось разрешение на выполнение операции'
}

function permissionSubtitle(item: ToolDecisionItem): string {
  const agent = (item.agentName || '').trim()
  const who = agent ? `Агенту «${agent}»` : 'Агенту'
  if (item.status === 'confirmed' || item.status === 'done') {
    return `${who} потребовалось разрешение — выдано`
  }
  if (item.status === 'rejected') {
    return `${who} потребовалось разрешение — отклонено`
  }
  return `${who} потребовалось разрешение на выполнение операции`
}

function rowFromTool(item: ToolDecisionItem): TodayPreparedDecisionRow {
  let status = 'Ждёт разрешения'
  let statusTone: SpecPillTone = 'orange'
  let statusIcon: TodayPreparedDecisionRow['statusIcon'] = '!'
  if (item.status === 'confirmed' || item.status === 'done') {
    status = 'Разрешение выдано'
    statusTone = 'green'
    statusIcon = '✓'
  } else if (item.status === 'rejected') {
    status = 'Разрешение отклонено'
    statusTone = 'orange'
    statusIcon = '!'
  } else if (item.status === 'pending' && !item.live) {
    status = 'Ждёт разрешения'
    statusTone = 'gray'
    statusIcon = '…'
  }
  const kind: TodayPreparedDecisionRow['kind'] =
    item.live || item.tool === 'waiting_human' || isQuestionDecision(item.tool) ? 'waiting' : 'tool'
  return {
    id: item.id,
    title: permissionTitle(item),
    status,
    statusTone,
    statusIcon,
    tag: 'ИИ',
    tagTone: 'purple',
    subtitle: permissionSubtitle(item),
    workflowId: item.workflowId,
    agentName: item.agentName,
    runId: item.runId || undefined,
    requestId: item.requestId || undefined,
    kind,
    at: item.at
  }
}

/** Подготовленные решения — только запросы разрешения агента на операцию. */
export function useTodayPreparedDecisions(periodDay: Date, userId?: string): TodayPreparedDecisionsState {
  const day = decisionDayKey(periodDay)
  const catalog = useDecisionCatalog({ userId, fromDay: day, toDay: day })

  const permissionItems = useMemo(
    () => catalog.items.filter(isPermissionDecision),
    [catalog.items]
  )

  const items = useMemo(() => {
    const dueMs = (item: ToolDecisionItem): number => {
      const start = parseIso(item.at) || new Date(item.at)
      return start.getTime()
    }
    return permissionItems
      .slice()
      .sort((left, right) => dueMs(left) - dueMs(right))
      .slice(0, MAX_ROWS)
      .map(rowFromTool)
  }, [permissionItems])

  const loading = catalog.loading && items.length === 0
  return {
    loading,
    error: items.length ? '' : catalog.error,
    items,
    total: permissionItems.length
  }
}
