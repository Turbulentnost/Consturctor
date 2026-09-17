import {
  TODAY_WIDGET_IDS,
  type TodayWidgetId,
  TODAY_WIDGET_LABELS
} from './useTodayWidgetLayout'

export const TODAY_WIDGET_VISIBILITY_EVENT = 'orchestrator:today-widgets-changed'

const VISIBILITY_STORAGE_KEY = 'orch-today-widgets-v1'

function storageKeyForUser(userId: string): string {
  return `${VISIBILITY_STORAGE_KEY}:${userId.trim() || 'default'}`
}

export function defaultTodayWidgetVisibility(): Record<TodayWidgetId, boolean> {
  return Object.fromEntries(TODAY_WIDGET_IDS.map((id) => [id, true])) as Record<TodayWidgetId, boolean>
}

export function readTodayWidgetVisibility(userId: string): Record<TodayWidgetId, boolean> {
  const defaults = defaultTodayWidgetVisibility()
  try {
    const raw = localStorage.getItem(storageKeyForUser(userId))
    if (!raw) return defaults
    const parsed = JSON.parse(raw) as Partial<Record<TodayWidgetId, boolean>>
    for (const id of TODAY_WIDGET_IDS) {
      if (typeof parsed[id] === 'boolean') defaults[id] = parsed[id]
    }
    return defaults
  } catch {
    return defaults
  }
}

export function writeTodayWidgetVisibility(
  userId: string,
  visibility: Record<TodayWidgetId, boolean>
): void {
  try {
    localStorage.setItem(storageKeyForUser(userId), JSON.stringify(visibility))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(TODAY_WIDGET_VISIBILITY_EVENT))
}

export function visibleTodayWidgetIds(visibility: Record<TodayWidgetId, boolean>): TodayWidgetId[] {
  return TODAY_WIDGET_IDS.filter((id) => visibility[id] !== false)
}

export { TODAY_WIDGET_IDS, TODAY_WIDGET_LABELS }
export type { TodayWidgetId }
