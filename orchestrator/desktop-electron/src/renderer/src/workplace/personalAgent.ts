export const PERSONAL_AGENT_PREFIX = 'personal-agent:'

export function personalAgentWorkflowId(userId: string): string {
  const raw = (userId || '').trim()
  const safe = raw ? raw.replace(/[^A-Za-z0-9_.-]/g, '_') : 'local'
  return `${PERSONAL_AGENT_PREFIX}${safe}`
}

export function isPersonalAgentWorkflowId(workflowId: string): boolean {
  return (workflowId || '').startsWith(PERSONAL_AGENT_PREFIX)
}
