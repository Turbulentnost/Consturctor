import type { SpecTaskRow } from './specV04DemoData'

const STORAGE_PREFIX = 'orch-onec-task-snapshot-v1'

type SnapshotPayload = { day: string; keys: string[] }

/** Та же идентичность, что в dedupeSpecTaskRows: id, иначе подпись название|срок|исполнитель. */
export function onecTaskKey(row: Pick<SpecTaskRow, 'id' | 'title' | 'deadline' | 'executor'>): string {
  const id = String(row.id || '').trim().toLowerCase()
  if (id && id !== '—') return `id:${id}`
  return `sig:${String(row.title || '').trim().toLowerCase()}|${row.deadline || ''}|${String(row.executor || '').trim().toLowerCase()}`
}

function localDay(date = new Date()): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}:${(userId || 'default').trim() || 'default'}`
}

function readSnapshot(userId: string, day: string): Set<string> | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(storageKey(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<SnapshotPayload>
    if (!parsed || parsed.day !== day || !Array.isArray(parsed.keys)) return null
    return new Set(parsed.keys.map(String))
  } catch {
    return null
  }
}

function writeSnapshot(userId: string, day: string, keys: string[]): void {
  if (typeof window === 'undefined') return
  try {
    const payload: SnapshotPayload = { day, keys }
    window.localStorage.setItem(storageKey(userId), JSON.stringify(payload))
  } catch {
    /* ignore quota */
  }
}

/**
 * Сравнивает задачи 1С с сегодняшним снимком предыдущего входа и перезаписывает снимок.
 * Нет снимка за сегодня (первый вход дня) — новых задач нет.
 */
export function diffAndStoreOneCTaskSnapshot(userId: string, rows: SpecTaskRow[]): Set<string> {
  const day = localDay()
  const current = [...new Set(rows.map(onecTaskKey))]
  const previous = readSnapshot(userId, day)
  writeSnapshot(userId, day, current)
  if (!previous) return new Set()
  return new Set(current.filter((key) => !previous.has(key)))
}

export function isNewOneCTask(
  newKeys: ReadonlySet<string>,
  row: Pick<SpecTaskRow, 'id' | 'title' | 'deadline' | 'executor'>
): boolean {
  return newKeys.size > 0 && newKeys.has(onecTaskKey(row))
}
