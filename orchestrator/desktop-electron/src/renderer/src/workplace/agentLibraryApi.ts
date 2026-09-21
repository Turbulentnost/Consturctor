import type { AgentSharePayload } from '../api/types'
import { api } from '../api/client'

export type AgentLibraryPurpose = 'functional' | 'positional'

export type AgentLibraryEntry = AgentSharePayload & {
  ownerId?: string
  ownerFio?: string
  purpose?: AgentLibraryPurpose
  alreadyAdded?: boolean
  adoptedWorkflowId?: string
}

export function agentPurposeLabel(purpose?: AgentLibraryPurpose | string): string {
  return purpose === 'positional' ? 'долностной' : 'функциональный'
}

function parsePurpose(raw: unknown): AgentLibraryPurpose {
  const value = String(raw ?? '').trim().toLowerCase()
  return value === 'positional' ? 'positional' : 'functional'
}

export type AgentLibrarySnapshot = {
  catalog: AgentLibraryEntry[]
  adopted: AgentLibraryEntry[]
}

function parseEntry(raw: Record<string, unknown>): AgentLibraryEntry {
  return {
    type: 'agent_card',
    workflowId: String(raw.workflow_id ?? raw.workflowId ?? ''),
    title: String(raw.title ?? 'ИИ-агент'),
    description: String(raw.description ?? ''),
    goal: String(raw.goal ?? ''),
    triggerSummary: String(raw.trigger_summary ?? raw.triggerSummary ?? ''),
    triggerKind: String(raw.trigger_kind ?? raw.triggerKind ?? ''),
    status: String(raw.status ?? 'published'),
    phase: String(raw.phase ?? 'done'),
    tools: Array.isArray(raw.tools) ? raw.tools.map((x) => String(x)) : [],
    ownerId: String(raw.owner_id ?? raw.ownerId ?? ''),
    ownerFio: String(raw.owner_fio ?? raw.ownerFio ?? ''),
    purpose: parsePurpose(raw.purpose),
    alreadyAdded: Boolean(raw.already_added ?? raw.alreadyAdded),
    adoptedWorkflowId: String(raw.adopted_workflow_id ?? raw.adoptedWorkflowId ?? '')
  }
}

export async function fetchAgentLibrary(): Promise<AgentLibrarySnapshot> {
  const data = await api.listAgentLibrary()
  return {
    catalog: data.catalog.map(parseEntry),
    adopted: data.adopted.map(parseEntry)
  }
}

export async function adoptAgentFromLibrary(sourceWorkflowId: string): Promise<{
  workflowId: string
  title: string
  card: AgentLibraryEntry
}> {
  const data = await api.adoptAgentFromLibrary(sourceWorkflowId)
  const cardRaw = (data.card as Record<string, unknown>) ?? {}
  return {
    workflowId: String(data.workflow_id ?? data.workflowId ?? ''),
    title: String(data.title ?? ''),
    card: parseEntry(cardRaw)
  }
}
