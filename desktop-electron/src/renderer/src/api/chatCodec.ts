import type { AgentSharePayload } from './types'

const PREFIX = 'constructor.agent.v1:'

function toBase64(value: string): string {
  return btoa(unescape(encodeURIComponent(value)))
}

function fromBase64(value: string): string {
  return decodeURIComponent(escape(atob(value)))
}

export function encodeAgentMessage(agent: AgentSharePayload, text = ''): string {
  const packed = PREFIX + toBase64(JSON.stringify(agent))
  const extra = text.trim()
  return extra ? `${packed}\n${extra}` : packed
}

export function decodeAgentMessage(text: string): { agent: AgentSharePayload | null; text: string } {
  const raw = text || ''
  if (!raw.startsWith(PREFIX)) return { agent: null, text: raw }
  const nl = raw.indexOf('\n')
  const head = nl >= 0 ? raw.slice(0, nl) : raw
  const rest = nl >= 0 ? raw.slice(nl + 1) : ''
  try {
    const parsed = JSON.parse(fromBase64(head.slice(PREFIX.length))) as AgentSharePayload
    if (parsed && parsed.type === 'agent_card') {
      return { agent: parsed, text: rest }
    }
  } catch {
    /* keep raw text */
  }
  return { agent: null, text: raw }
}

export function previewText(text: string): string {
  const decoded = decodeAgentMessage(text)
  if (decoded.agent) {
    const title = decoded.agent.title || 'ИИ-агент'
    return decoded.text.trim() || `Агент: ${title}`
  }
  return decoded.text
}

export function agentShareFromBoard(agent: {
  id: string
  title: string
  description: string
  triggerSummary: string
  triggerKind: string
  status: string
  phase: string
}): AgentSharePayload {
  return {
    type: 'agent_card',
    workflowId: agent.id,
    title: agent.title || 'ИИ-агент',
    description: agent.description || '',
    goal: agent.description || '',
    triggerSummary: agent.triggerSummary || '',
    triggerKind: agent.triggerKind || '',
    status: agent.status || 'active',
    phase: agent.phase || 'done',
    tools: []
  }
}
