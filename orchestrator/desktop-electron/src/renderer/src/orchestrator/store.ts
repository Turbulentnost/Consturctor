import { hasPositionKpi, seedIlchenkoInstances } from './kpi'
import {
  MEETING_ID,
  READY,
  REVISION_ID,
  WAITING_HUMAN,
  type ProcessInstance
} from './models'

function storageKey(userId: string): string {
  const safe = (userId || 'local').replace(/[^a-zA-Z0-9]+/g, '_') || 'local'
  return `constructor.orchestrator.${safe}`
}

function parse(item: Record<string, unknown>): ProcessInstance | null {
  const id = String(item.id || '')
  const definitionId = String(item.definition_id || '')
  const status = String(item.status || '')
  if (!id || !definitionId || !status) return null
  return {
    id,
    definition_id: definitionId,
    status,
    waiting: Number(item.waiting || 0),
    updated_at: String(item.updated_at || ''),
    events: Array.isArray(item.events) ? (item.events as Array<Record<string, string>>) : []
  }
}

function seed(userId: string): ProcessInstance[] {
  if (hasPositionKpi(userId)) return seedIlchenkoInstances()
  const now = new Date().toISOString()
  return [
    {
      id: crypto.randomUUID(),
      definition_id: REVISION_ID,
      status: WAITING_HUMAN,
      waiting: 1,
      updated_at: now,
      events: [{ type: 'seed', status: WAITING_HUMAN, at: now }]
    },
    {
      id: crypto.randomUUID(),
      definition_id: MEETING_ID,
      status: READY,
      waiting: 0,
      updated_at: now,
      events: [{ type: 'seed', status: READY, at: now }]
    }
  ]
}

export function loadInstances(userId: string): ProcessInstance[] {
  try {
    const raw = localStorage.getItem(storageKey(userId))
    if (!raw) {
      const seeded = seed(userId)
      saveInstances(userId, seeded)
      return seeded
    }
    const payload = JSON.parse(raw) as { instances?: unknown }
    const rows = Array.isArray(payload.instances) ? payload.instances : []
    const instances = rows
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      .map(parse)
      .filter((item): item is ProcessInstance => item != null)
    if (!instances.length) {
      const seeded = seed(userId)
      saveInstances(userId, seeded)
      return seeded
    }
    return instances
  } catch {
    return seed(userId)
  }
}

export function saveInstances(userId: string, instances: ProcessInstance[]): void {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify({ instances }))
  } catch {
    /* keep working from memory */
  }
}

export function counts(instances: ProcessInstance[]): { waiting: number; active: number; errors: number } {
  return {
    waiting: instances.filter((item) => item.status === WAITING_HUMAN).length,
    active: instances.filter((item) => item.status === 'ACTIVE').length,
    errors: instances.filter((item) => item.status === 'ERROR').length
  }
}
