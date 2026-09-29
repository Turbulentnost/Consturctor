import type { AssignmentRegistryRow } from './assignmentRegistryTypes'

export type AssignmentRegistryCacheEntry = {
  rows: AssignmentRegistryRow[]
  fetchedAt: number
  complete?: boolean
  dateFrom?: string
  dateTo?: string
}

const memory = new Map<string, AssignmentRegistryCacheEntry>()
const poolByUser = new Map<string, AssignmentRegistryRow[]>()

function userKey(userId: string): string {
  return (userId || 'default').trim() || 'default'
}

export function registryCacheKey(userId: string, dateFrom: string, dateTo: string): string {
  return `${userKey(userId)}:${dateFrom.trim()}:${dateTo.trim()}`
}

export function readRegistryCache(key: string): AssignmentRegistryCacheEntry | null {
  return memory.get(key) ?? null
}

export function writeRegistryCache(
  key: string,
  rows: AssignmentRegistryRow[],
  meta?: { complete?: boolean; dateFrom?: string; dateTo?: string }
): void {
  memory.set(key, {
    rows,
    fetchedAt: Date.now(),
    complete: meta?.complete,
    dateFrom: meta?.dateFrom,
    dateTo: meta?.dateTo
  })
}

function mergeRowsById(
  current: AssignmentRegistryRow[],
  batch: AssignmentRegistryRow[]
): AssignmentRegistryRow[] {
  if (!batch.length) return current
  const seen = new Set(current.map((row) => row.id))
  const next = [...current]
  for (const row of batch) {
    if (seen.has(row.id)) continue
    seen.add(row.id)
    next.push(row)
  }
  return next
}

export function readRegistryPool(userId: string): AssignmentRegistryRow[] {
  return poolByUser.get(userKey(userId)) ?? []
}

export function mergeRegistryPool(userId: string, batch: AssignmentRegistryRow[]): AssignmentRegistryRow[] {
  const merged = mergeRowsById(readRegistryPool(userId), batch)
  poolByUser.set(userKey(userId), merged)
  return merged
}

export function clearRegistryPool(userId: string): void {
  poolByUser.delete(userKey(userId))
}
