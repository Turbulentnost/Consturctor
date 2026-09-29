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

export const TODAY_TILE_IDS = ['day', 'onec', 'onec-from-me', 'proj-mine', 'proj-mgr', 'reg', 'ev'] as const

export type TodayTileId = (typeof TODAY_TILE_IDS)[number]

export const TODAY_TILE_LABELS: Record<TodayTileId, string> = {
  day: 'Выполнение дня',
  onec: '1С мне',
  'onec-from-me': '1С от меня',
  'proj-mine': 'Turbo мне',
  'proj-mgr': 'Turbo РП',
  reg: 'Регламент',
  ev: 'События'
}

export const TODAY_TILE_VISIBILITY_EVENT = 'orchestrator:today-tiles-changed'

function tileStorageKey(userId: string): string {
  return `orch-today-tiles-v1:${userId.trim() || 'default'}`
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

export function visibleTodayWidgetIds(visibility: Record<TodayWidgetId, boolean>): TodayWidgetId[] {
  return TODAY_WIDGET_IDS.filter((id) => visibility[id] !== false)
}
