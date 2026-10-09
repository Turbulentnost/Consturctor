import {
  TODAY_WIDGET_IDS,
  TODAY_WIDGET_LABELS,
  TODAY_WIDGET_VISIBILITY_EVENT,
  readTodayWidgetVisibilitySettings,
  writeTodayWidgetVisibilitySettings,
  type TodayWidgetId
} from './useTodayWidgetLayout'

export {
  TODAY_WIDGET_IDS,
  TODAY_WIDGET_LABELS,
  TODAY_WIDGET_VISIBILITY_EVENT,
  type TodayWidgetId
}

export function defaultTodayWidgetVisibility(): Record<TodayWidgetId, boolean> {
  return Object.fromEntries(TODAY_WIDGET_IDS.map((id) => [id, true])) as Record<TodayWidgetId, boolean>
}

export function readTodayWidgetVisibility(userId: string): Record<TodayWidgetId, boolean> {
  return readTodayWidgetVisibilitySettings(userId)
}

export function writeTodayWidgetVisibility(
  userId: string,
  visibility: Record<TodayWidgetId, boolean>
): void {
  writeTodayWidgetVisibilitySettings(userId, visibility)
  window.dispatchEvent(new CustomEvent(TODAY_WIDGET_VISIBILITY_EVENT))
}

export const TODAY_TILE_IDS = [
  'assignments',
  'ev',
  'day',
  'onec',
  'onec-from-me',
  'proj-mine',
  'proj-mgr',
  'reg'
] as const

export type TodayTileId = (typeof TODAY_TILE_IDS)[number]

export const TODAY_TILE_LABELS: Record<TodayTileId, string> = {
  assignments: 'Поручения',
  ev: 'События',
  day: 'Выполнение дня',
  onec: '1С мне',
  'onec-from-me': '1С от меня',
  'proj-mine': 'Turbo мне',
  'proj-mgr': 'Turbo РП',
  reg: 'Регламент'
}

export const TODAY_TILE_VISIBILITY_EVENT = 'orchestrator:today-tiles-changed'

function tileStorageKey(userId: string): string {
  return `orch-today-tiles-v1:${userId.trim() || 'default'}`
}

function tileOrderKey(userId: string): string {
  return `orch-today-tile-order-v1:${userId.trim() || 'default'}`
}

function isTodayTileId(id: string): id is TodayTileId {
  return (TODAY_TILE_IDS as readonly string[]).includes(id)
}

export function defaultTodayTileVisibility(): Record<TodayTileId, boolean> {
  return Object.fromEntries(TODAY_TILE_IDS.map((id) => [id, true])) as Record<TodayTileId, boolean>
}

export function readTodayTileVisibility(userId: string): Record<TodayTileId, boolean> {
  const out = defaultTodayTileVisibility()
  try {
    const parsed = JSON.parse(localStorage.getItem(tileStorageKey(userId)) || '{}') as Record<string, unknown>
    for (const id of TODAY_TILE_IDS) {
      if (parsed[id] === false) out[id] = false
    }
  } catch {
    /* corrupted save → all visible */
  }
  return out
}

export function writeTodayTileVisibility(userId: string, visibility: Record<TodayTileId, boolean>): void {
  const hidden = Object.fromEntries(TODAY_TILE_IDS.filter((id) => visibility[id] === false).map((id) => [id, false]))
  try {
    localStorage.setItem(tileStorageKey(userId), JSON.stringify(hidden))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(TODAY_TILE_VISIBILITY_EVENT))
}

/** Порядок плиток над виджетами. Нет сохранённого порядка — Поручения, События, Выполнение дня, плитки 1С. */
export function readTodayTileOrder(userId: string): TodayTileId[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(tileOrderKey(userId)) || 'null') as unknown
    if (Array.isArray(parsed)) {
      const kept = parsed.filter((id): id is TodayTileId => typeof id === 'string' && isTodayTileId(id))
      const missing = TODAY_TILE_IDS.filter((id) => !kept.includes(id))
      return [...kept, ...missing]
    }
  } catch {
    /* corrupted save → default order */
  }
  return [...TODAY_TILE_IDS]
}

export function writeTodayTileOrder(userId: string, order: TodayTileId[]): void {
  const kept = order.filter((id) => isTodayTileId(id))
  const missing = TODAY_TILE_IDS.filter((id) => !kept.includes(id))
  try {
    localStorage.setItem(tileOrderKey(userId), JSON.stringify([...kept, ...missing]))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(TODAY_TILE_VISIBILITY_EVENT))
}

export function visibleTodayWidgetIds(visibility: Record<TodayWidgetId, boolean>): TodayWidgetId[] {
  return TODAY_WIDGET_IDS.filter((id) => visibility[id] !== false)
}
