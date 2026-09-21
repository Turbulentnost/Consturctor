const STORAGE_KEY = 'orch-workplace-task-progress-v1'

type ProgressMap = Record<string, number>

function readMap(): ProgressMap {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    const out: ProgressMap = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      const n = Number(value)
      if (key && Number.isFinite(n)) out[key] = Math.max(0, Math.min(100, Math.round(n)))
    }
    return out
  } catch {
    return {}
  }
}

function writeMap(map: ProgressMap): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* ignore quota */
  }
}

/** User-set progress override keyed by workplace row id (task id, erp:…, proj:…). */
export function getStoredTaskProgress(rowId: string, fallback: number): number {
  const key = rowId.trim()
  if (!key) return fallback
  const stored = readMap()[key]
  return stored === undefined ? fallback : stored
}

export function saveStoredTaskProgress(rowId: string, value: number): number {
  const key = rowId.trim()
  const pct = Math.max(0, Math.min(100, Math.round(value)))
  if (!key) return pct
  const map = readMap()
  map[key] = pct
  writeMap(map)
  return pct
}

export function clearStoredTaskProgress(rowId: string): void {
  const key = rowId.trim()
  if (!key) return
  const map = readMap()
  if (!(key in map)) return
  delete map[key]
  writeMap(map)
}
