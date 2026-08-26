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

export function formatFileWhen(raw?: string, now = new Date()): string {
  const stamp = parseFileDate(raw)
  if (!stamp) return ''
  const hours = String(stamp.getHours()).padStart(2, '0')
  const minutes = String(stamp.getMinutes()).padStart(2, '0')
  const sameDay =
    stamp.getFullYear() === now.getFullYear() &&
    stamp.getMonth() === now.getMonth() &&
    stamp.getDate() === now.getDate()
  if (sameDay) return `Сегодня, ${hours}:${minutes}`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const sameYesterday =
    stamp.getFullYear() === yesterday.getFullYear() &&
    stamp.getMonth() === yesterday.getMonth() &&
    stamp.getDate() === yesterday.getDate()
  if (sameYesterday) return `Вчера, ${hours}:${minutes}`
  return `${stamp.getDate()} ${MONTHS[stamp.getMonth()]}, ${hours}:${minutes}`
}

export function fileExt(name: string): string {
  return (name.split('.').pop() || '').trim().toLowerCase()
}

export function elideFilenameMiddle(name: string, maxChars = 22): string {
  const raw = (name || '').trim() || 'file'
  if (maxChars <= 4 || raw.length <= maxChars) return raw
  const suffix = raw.includes('.') ? `.${raw.split('.').pop()}` : ''
  const stem = suffix && raw.endsWith(suffix) ? raw.slice(0, -suffix.length) : raw
  const keep = Math.max(1, maxChars - suffix.length - 3)
  if (stem.length <= keep) return raw
  return `${stem.slice(0, keep)}...${suffix}`
}

export function normalizeAgentTitle(title: string): string {
  return (title || '')
    .trim()
    .toLowerCase()
    .replace(/^ии-агент:\s*/i, '')
    .replace(/\s+/g, ' ')
}

export function uniqueAgentOptions(items: WorkflowFileItem[]): { value: string; label: string }[] {
  const seen = new Set<string>()
  const options: { value: string; label: string }[] = []
  for (const item of items) {
    const label = (item.agentTitle || '').trim() || 'Агент'
    const value = normalizeAgentTitle(label)
    if (!value || seen.has(value)) continue
    seen.add(value)
    options.push({ value, label })
  }
  return options.sort((a, b) => a.label.localeCompare(b.label, 'ru'))
}

export function formatSize(bytes: number): string {
  const value = Math.max(0, Number(bytes) || 0)
  if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} МБ`
  if (value >= 1024) return `${(value / 1024).toFixed(1)} КБ`
  if (!value) return ''
  return `${value} Б`
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
