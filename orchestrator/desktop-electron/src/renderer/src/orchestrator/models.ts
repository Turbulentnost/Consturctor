export const READY = 'READY'
export const ACTIVE = 'ACTIVE'
export const WAITING_HUMAN = 'WAITING_HUMAN'
export const PAUSED = 'PAUSED'
export const COMPLETED = 'COMPLETED'
export const ERROR = 'ERROR'

export const REVISION_ID = 'revision_commission'
export const MEETING_ID = 'meeting_prep'

export interface ProcessDefinition {
  id: string
  title: string
}

export interface ProcessInstance {
  id: string
  definition_id: string
  status: string
  waiting: number
  updated_at: string
  events: Array<Record<string, string>>
}

export const DEFINITIONS: ProcessDefinition[] = [
  { id: REVISION_ID, title: 'Работа ревизионной комиссии' },
  { id: MEETING_ID, title: 'Подготовка совещания' }
]
