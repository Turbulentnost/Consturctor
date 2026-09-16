import type { TaskTileFilter } from './tileFilters'

export const ORCH_OPEN_TAB = 'orchestrator:open-tab'
export const ORCH_CREATE_TASK = 'orchestrator:create-task'

export type CreateTaskChannel = 'onec' | 'turbo' | 'draft'

export const CREATE_TASK_CHANNEL_LABEL: Record<CreateTaskChannel, string> = {
  onec: '1С',
  turbo: 'Turbo',
  draft: 'Локальный черновик'
}

/** Optional filter applied after App switches the workplace tab. */
export type WorkplaceTabIntent = {
  taskFilter?: TaskTileFilter
  processTab?: string
}

export type OpenWorkplaceTabDetail = {
  key: string
  intent?: WorkplaceTabIntent
}

export function openWorkplaceTab(key: string, intent?: WorkplaceTabIntent): void {
  window.dispatchEvent(new CustomEvent(ORCH_OPEN_TAB, { detail: { key, intent } }))
}

export function requestCreateTask(channel: CreateTaskChannel): void {
  window.dispatchEvent(new CustomEvent(ORCH_CREATE_TASK, { detail: { channel } }))
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim())
}

export function openHttpUrl(url: string): boolean {
  const href = url.trim()
  if (!isHttpUrl(href)) return false
  window.open(href, '_blank', 'noopener,noreferrer')
  return true
}
