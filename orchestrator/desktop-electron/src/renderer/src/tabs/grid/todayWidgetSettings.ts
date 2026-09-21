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

export function visibleTodayWidgetIds(visibility: Record<TodayWidgetId, boolean>): TodayWidgetId[] {
  return TODAY_WIDGET_IDS.filter((id) => visibility[id] !== false)
}
