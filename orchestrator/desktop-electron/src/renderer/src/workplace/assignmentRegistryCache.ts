import type { AssignmentRegistryRow } from './assignmentRegistryTypes'

export type AssignmentRegistryCacheEntry = {
  rows: AssignmentRegistryRow[]
  fetchedAt: number
}

const memory = new Map<string, AssignmentRegistryCacheEntry>()

export function registryCacheKey(userId: string, dateFrom: string, dateTo: string): string {
  return `${(userId || 'default').trim()}:${dateFrom.trim()}:${dateTo.trim()}`
}

export function readRegistryCache(key: string): AssignmentRegistryCacheEntry | null {
  return memory.get(key) ?? null
}

export function writeRegistryCache(key: string, rows: AssignmentRegistryRow[]): void {
  memory.set(key, { rows, fetchedAt: Date.now() })
}
