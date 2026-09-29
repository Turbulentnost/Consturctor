import { api } from '../api/client'
import { mapLine } from './assignmentRegistryMappers'
import type { AssignmentRegistryLine, AssignmentRegistryRow } from './assignmentRegistryTypes'

const detailCache = new Map<string, AssignmentRegistryLine[]>()
const inflight = new Map<string, Promise<AssignmentRegistryLine[]>>()

function parseLinesFromGet(result: unknown): AssignmentRegistryLine[] {
  if (!result || typeof result !== 'object') return []
  const payload = result as Record<string, unknown>
  const one = payload.assignment
  if (!one || typeof one !== 'object') return []
  const linesRaw = Array.isArray((one as Record<string, unknown>).lines)
    ? ((one as Record<string, unknown>).lines as unknown[])
    : []
  return linesRaw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(mapLine)
    .sort((a, b) => a.line - b.line)
}

function parseLinesBatch(result: unknown): Map<string, AssignmentRegistryLine[]> {
  const out = new Map<string, AssignmentRegistryLine[]>()
  if (!result || typeof result !== 'object') return out
  const payload = result as Record<string, unknown>
  const byRef = payload.lines_by_ref
  if (!byRef || typeof byRef !== 'object') return out
  for (const [refKey, rawLines] of Object.entries(byRef as Record<string, unknown>)) {
    if (!Array.isArray(rawLines)) continue
    const lines = rawLines
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      .map(mapLine)
      .sort((a, b) => a.line - b.line)
    if (lines.length) out.set(refKey, lines)
  }
  return out
}

/** Одна карточка: строки ТЧ по ref_key (кэш + dedupe). */
export async function fetchAssignmentLines(refKey: string): Promise<AssignmentRegistryLine[]> {
  const key = refKey.trim()
  if (!key) return []
  const cached = detailCache.get(key)
  if (cached) return cached
  const pending = inflight.get(key)
  if (pending) return pending

  const task = (async (): Promise<AssignmentRegistryLine[]> => {
    const res = await api.invokeServerTool(
      'onec.erp_assignments',
      { action: 'get', ref_key: key },
      120_000
    )
    if (!res.ok) return []
    const lines = parseLinesFromGet(res.result)
    detailCache.set(key, lines)
    return lines
  })()

  inflight.set(key, task)
  try {
    return await task
  } finally {
    inflight.delete(key)
  }
}

/** Пакет для печати: до 50 ref_key за один invoke. */
export async function fetchAssignmentLinesBatch(refKeys: string[]): Promise<Map<string, AssignmentRegistryLine[]>> {
  const unique = [...new Set(refKeys.map((k) => k.trim()).filter(Boolean))]
  const missing = unique.filter((key) => !detailCache.has(key))
  if (!missing.length) {
    const out = new Map<string, AssignmentRegistryLine[]>()
    for (const key of unique) {
      const lines = detailCache.get(key)
      if (lines?.length) out.set(key, lines)
    }
    return out
  }

  for (let i = 0; i < missing.length; i += 50) {
    const chunk = missing.slice(i, i + 50)
    const res = await api.invokeServerTool(
      'onec.erp_assignments',
      { action: 'lines_batch', ref_keys: chunk },
      180_000
    )
    if (!res.ok) continue
    const parsed = parseLinesBatch(res.result)
    for (const [refKey, lines] of parsed) {
      detailCache.set(refKey, lines)
    }
  }

  const out = new Map<string, AssignmentRegistryLine[]>()
  for (const key of unique) {
    const lines = detailCache.get(key)
    if (lines?.length) out.set(key, lines)
  }
  return out
}

export function mergeRowsWithLines(
  rows: AssignmentRegistryRow[],
  linesByRef: Map<string, AssignmentRegistryLine[]>
): AssignmentRegistryRow[] {
  if (!linesByRef.size) return rows
  return rows.map((row) => {
    if (!row.refKey || row.lines.length) return row
    const lines = linesByRef.get(row.refKey)
    return lines?.length ? { ...row, lines } : row
  })
}

export function readCachedLines(refKey: string): AssignmentRegistryLine[] | undefined {
  return detailCache.get(refKey.trim())
}
