/** Stable pastel accent from workflowId (hash → 8 colors). Thin stripe, not a full paint. */

export type AgentAccent = {
  bg: string
  border: string
}

const PALETTE: AgentAccent[] = [
  { bg: '#E8F1FB', border: '#1565C0' },
  { bg: '#EDE7F6', border: '#5E35B1' },
  { bg: '#E0F2F1', border: '#00897B' },
  { bg: '#FFF3E0', border: '#EF6C00' },
  { bg: '#FCE4EC', border: '#C2185B' },
  { bg: '#E8F5E9', border: '#2E7D32' },
  { bg: '#FFF8E1', border: '#F9A825' },
  { bg: '#E3F2FD', border: '#0277BD' }
]

function hashId(value: string): number {
  let hash = 0
  const text = value.trim()
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  }
  return hash
}

export function agentAccent(workflowId: string): AgentAccent {
  return PALETTE[hashId(workflowId || 'agent') % PALETTE.length]
}

export function agentAccentStyle(workflowId: string): { [key: string]: string } {
  const accent = agentAccent(workflowId)
  return {
    '--agent-accent': accent.border,
    '--agent-accent-bg': accent.bg
  }
}

export function shortAgentLabel(code: string | undefined, title: string): string {
  const fromCode = String(code || '').trim()
  if (fromCode && !/^(wf-|workflow)/i.test(fromCode) && fromCode.length <= 24) {
    return fromCode
  }
  const words = String(title || '')
    .trim()
    .split(/\s+/)
    .filter((word) => word && !/^(агент|ии|ai|the|a)$/i.test(word))
  return words[0] || String(title || '').trim() || 'Агент'
}
