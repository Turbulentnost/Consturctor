import { isPlaceholderResult } from './cleanRunResult'

export const HISTORY_STATUS_LABELS: Record<string, string> = {
  ok: 'Успешно',
  error: 'Ошибка',
  running: 'Выполняется',
  started: 'Выполняется',
  canceled: 'Отменён',
  cancelled: 'Отменён'
}

export function isHistoryResult(text: string): boolean {
  const value = (text || '').trim()
  if (!value) return false
  return !isPlaceholderResult(value)
}

export function historyRunStatus(run: { status: string; answer?: string; summary?: string }): string {
  const status = (run.status || '').trim().toLowerCase()
  const result = (run.answer || run.summary || '').trim()
  if (status === 'started' || status === 'running') return status
  if (status === 'error' && isHistoryResult(result)) return 'error'
  if (status === 'ok' && isHistoryResult(result)) return 'ok'
  return 'canceled'
}

export function statusPillClass(status: string): string {
  if (status === 'ok') return 'wp-pill-done'
  if (status === 'error') return 'wp-pill-needs_decision'
  if (status === 'started' || status === 'running') return 'wp-pill-running'
  return 'wp-pill-paused'
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

export function dayKey(iso: string): string {
  if (!iso) return 'none'
  const stamp = new Date(iso)
  if (Number.isNaN(stamp.getTime())) return 'none'
  return `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}`
}

export function dayLabel(key: string): string {
  if (key === 'none') return 'Без даты'
  const [year, month, day] = key.split('-').map(Number)
  if (!year || !month || !day) return 'Без даты'
  const that = new Date(year, month - 1, day)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((today.getTime() - that.getTime()) / 86_400_000)
  if (diff === 0) return 'Сегодня'
  if (diff === 1) return 'Вчера'
  return that.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

export function formatRunTime(iso: string): string {
  if (!iso) return ''
  const stamp = new Date(iso)
  if (Number.isNaN(stamp.getTime())) return ''
  return stamp.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export function formatRunWhen(iso: string): string {
  if (!iso) return ''
  const stamp = new Date(iso)
  if (Number.isNaN(stamp.getTime())) return iso
  return stamp.toLocaleString('ru-RU')
}

export interface DayGroup<T> {
  key: string
  label: string
  items: T[]
}

export function groupRunsByDay<T extends { startedAt: string }>(runs: T[]): DayGroup<T>[] {
  const groups: DayGroup<T>[] = []
  const index = new Map<string, DayGroup<T>>()
  for (const item of runs) {
    const key = dayKey(item.startedAt)
    let group = index.get(key)
    if (!group) {
      group = { key, label: dayLabel(key), items: [] }
      index.set(key, group)
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
}
