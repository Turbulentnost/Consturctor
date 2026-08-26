import type { WorkflowFileItem } from '../api/types'

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

export type SessionKind = 'formation' | 'run'

export interface FileSessionGroup {
  key: string
  workflowId: string
  agentTitle: string
  kind: SessionKind
  runId: string
  title: string
  stamp: string
  ours: WorkflowFileItem[]
  agent: WorkflowFileItem[]
}

export function parseFileDate(raw?: string): Date | null {
  const text = (raw || '').trim()
  if (!text) return null
  const stamp = new Date(text)
  return Number.isNaN(stamp.getTime()) ? null : stamp
}

export function sessionKind(item: WorkflowFileItem): SessionKind {
  if ((item.runId || '').trim() || item.source === 'agent') return 'run'
  return 'formation'
}

export function sessionStamp(items: WorkflowFileItem[]): string {
  const latest = items
    .map((item) => parseFileDate(item.createdAt))
    .filter((item): item is Date => item !== null)
    .sort((a, b) => b.getTime() - a.getTime())[0]
  if (!latest) return ''
  const hours = String(latest.getHours()).padStart(2, '0')
  const minutes = String(latest.getMinutes()).padStart(2, '0')
  return `${latest.getDate()} ${MONTHS[latest.getMonth()]}, ${hours}:${minutes}`
}

export function groupFileSessions(items: WorkflowFileItem[]): FileSessionGroup[] {
  const buckets = new Map<string, WorkflowFileItem[]>()
  const order: string[] = []
  for (const item of items) {
    const kind = sessionKind(item)
    const runId = (item.runId || '').trim()
    const workflowId = item.workflowId || ''
    const key = kind === 'formation' ? `${workflowId}:formation` : `${workflowId}:run:${runId || 'unknown'}`
    if (!buckets.has(key)) {
      buckets.set(key, [])
      order.push(key)
    }
    buckets.get(key)?.push(item)
  }

  const groups = order.map((key) => {
    const rows = buckets.get(key) ?? []
    const first = rows[0]
    const kind = sessionKind(first)
    const runId = kind === 'run' ? (first.runId || '').trim() : ''
    return {
      key,
      workflowId: first.workflowId || '',
      agentTitle: first.agentTitle || 'Агент',
      kind,
      runId,
      title: kind === 'formation' ? 'Формирование агента' : runId ? 'Запуск агента' : 'Результаты агента',
      stamp: sessionStamp(rows),
      ours: rows.filter((item) => item.source !== 'agent'),
      agent: rows.filter((item) => item.source === 'agent')
    }
  })

  return groups.sort((a, b) => {
    const titleCmp = a.agentTitle.localeCompare(b.agentTitle, 'ru')
    if (titleCmp !== 0) return titleCmp
    if (a.kind !== b.kind) return a.kind === 'formation' ? -1 : 1
    const aTime = Math.max(0, ...a.ours.concat(a.agent).map((item) => parseFileDate(item.createdAt)?.getTime() ?? 0))
    const bTime = Math.max(0, ...b.ours.concat(b.agent).map((item) => parseFileDate(item.createdAt)?.getTime() ?? 0))
    return bTime - aTime
  })
}
