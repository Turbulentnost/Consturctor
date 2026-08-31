import type { BoardAgent } from '../api/types'
import { DEFINITIONS, MEETING_ID, REVISION_ID, type ProcessDefinition } from './models'

export const REVISION_WORKFLOW_ID = 'orch-revision-commission'
export const MEETING_WORKFLOW_ID = 'orch-meeting-prep'

const WORKFLOW_IDS: Record<string, string> = {
  [REVISION_ID]: REVISION_WORKFLOW_ID,
  [MEETING_ID]: MEETING_WORKFLOW_ID
}

const TITLE_KEYS: Record<string, string[]> = {
  [REVISION_ID]: ['ревизион'],
  [MEETING_ID]: ['совещани']
}

export function isLocalWorkflow(workflowId: string): boolean {
  return Object.values(WORKFLOW_IDS).includes((workflowId || '').trim())
}

export function matchBoardAgent(
  definition: ProcessDefinition,
  agents: BoardAgent[]
): BoardAgent | undefined {
  const keys = TITLE_KEYS[definition.id] || []
  const wanted = WORKFLOW_IDS[definition.id] || ''
  const exact = definition.title.toLowerCase()
  return agents.find((agent) => {
    if (agent.kind !== 'workflow') return false
    if (wanted && agent.id === wanted) return true
    const title = (agent.title || '').toLowerCase()
    return title === exact || keys.some((key) => title.includes(key))
  })
}

export function boundWorkflowId(definition: ProcessDefinition, agents: BoardAgent[]): string {
  const matched = matchBoardAgent(definition, agents)
  if (matched?.id) return matched.id
  return WORKFLOW_IDS[definition.id] || ''
}

export { DEFINITIONS }
