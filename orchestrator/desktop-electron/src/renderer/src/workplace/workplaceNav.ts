import type { TaskTileFilter } from './tileFilters'
import type { GlobalSearchTarget } from '../layout/globalSearch'

export const ORCH_OPEN_TAB = 'orchestrator:open-tab'
export const ORCH_CREATE_TASK = 'orchestrator:create-task'
export const ORCH_LAUNCH_AGENT = 'orchestrator:launch-agent'

/** Агент TurboTester (turbotest.agents), которого запускает «Запустить процесс». */
export const MEETING_PLANNER_AGENT = {
  id: 'd4324cdc-e330-4c66-9e60-0427cdccbb72',
  title: 'Планировщик совещаний из 1С'
} as const

export type LaunchAgentDetail = {
  agentId: string
  title: string
}

export function launchPlatformAgent(agentId: string, title: string): void {
  window.dispatchEvent(new CustomEvent<LaunchAgentDetail>(ORCH_LAUNCH_AGENT, { detail: { agentId, title } }))
}

export type CreateTaskChannel = 'onec' | 'platform'

export const CREATE_TASK_CHANNEL_LABEL: Record<CreateTaskChannel, string> = {
  onec: '1С',
  platform: 'В платформе'
}

/** Optional filter applied after App switches the workplace tab. */
export type WorkplaceTabIntent = {
  taskFilter?: TaskTileFilter
  processTab?: string
  searchTarget?: GlobalSearchTarget
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
