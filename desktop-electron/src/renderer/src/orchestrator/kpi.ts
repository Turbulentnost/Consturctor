import {
  COMPLETED,
  ERROR,
  MEETING_ID,
  READY,
  REVISION_ID,
  WAITING_HUMAN,
  type ProcessInstance
} from './models'

export const ILCHENKO_USER_IDS = new Set([
  'A2DCC949FEDEC70D40318ABA83C618F4',
  'E11C4E11K00000000000000000000001'
])

export interface KpiRow {
  number: number
  name: string
  target: number
  weight: number
  fact: number | null
  color: string
}

const KPI = [
  { number: 1, name: 'Своевременность пакета к заседаниям (СД + РК)', target: 95, weight: 25, kind: 'package_on_time' },
  { number: 2, name: 'Своевременность протоколов (СД + РК)', target: 95, weight: 25, kind: 'protocol_on_time' },
  { number: 3, name: 'Реестр и контроль исполнения поручений (СД + РК)', target: 95, weight: 25, kind: 'instructions' },
  { number: 4, name: 'Качество протокола и материалов (без возвратов по замечаниям)', target: 98, weight: 25, kind: 'quality' }
] as const

export function hasPositionKpi(userId = '', fio = ''): boolean {
  if (ILCHENKO_USER_IDS.has((userId || '').trim())) return true
  return (fio || '').toLowerCase().includes('ильченко')
}

function ratio(ok: number, total: number): number | null {
  if (total <= 0) return null
  return (100 * ok) / total
}

function closed(instances: ProcessInstance[]): ProcessInstance[] {
  return instances.filter((item) => item.status === COMPLETED)
}

function hasReturn(instance: ProcessInstance): boolean {
  return instance.events.some((event) => String(event.type || '') === 'returned')
}

function fact(kind: string, instances: ProcessInstance[]): number | null {
  if (kind === 'package_on_time' || kind === 'protocol_on_time') {
    const done = instances.filter((item) => item.status === COMPLETED || item.status === ERROR)
    return ratio(done.filter((item) => item.status === COMPLETED).length, done.length)
  }
  if (kind === 'instructions') {
    const started = instances.filter((item) => item.status !== READY)
    return ratio(closed(instances).length, started.length)
  }
  if (kind === 'quality') {
    const done = closed(instances)
    return ratio(done.filter((item) => !hasReturn(item)).length, done.length)
  }
  return null
}

function color(value: number | null, target: number): string {
  if (value == null) return '#6B7773'
  if (value + 1e-9 >= target) return '#08745F'
  if (value + 1e-9 >= target - 10) return '#C9A227'
  return '#C0392B'
}

export function scoreRows(instances: ProcessInstance[]): KpiRow[] {
  return KPI.map((item) => {
    const value = fact(item.kind, instances)
    return {
      number: item.number,
      name: item.name,
      target: item.target,
      weight: item.weight,
      fact: value,
      color: color(value, item.target)
    }
  })
}

export function weightedScore(rows: KpiRow[]): number | null {
  let total = 0
  let acc = 0
  for (const row of rows) {
    if (row.fact == null) continue
    acc += row.fact * row.weight
    total += row.weight
  }
  return total > 0 ? acc / total : null
}

export function formatPercent(value: number | null): string {
  if (value == null) return 'нет данных'
  return `${value.toFixed(1)}%`.replace('.0%', '%')
}

export function seedIlchenkoInstances(): ProcessInstance[] {
  const now = new Date().toISOString()
  const rows: ProcessInstance[] = []
  const add = (
    definitionId: string,
    status: string,
    events: Array<Record<string, string>>,
    waiting = 0
  ): void => {
    rows.push({
      id: crypto.randomUUID(),
      definition_id: definitionId,
      status,
      waiting,
      updated_at: now,
      events
    })
  }
  for (let i = 0; i < 8; i += 1) {
    add(MEETING_ID, COMPLETED, [{ type: 'approved', status: COMPLETED, at: now }])
  }
  for (let i = 0; i < 7; i += 1) {
    add(REVISION_ID, COMPLETED, [{ type: 'approved', status: COMPLETED, at: now }])
  }
  add(MEETING_ID, COMPLETED, [
    { type: 'returned', status: 'ACTIVE', at: now },
    { type: 'approved', status: COMPLETED, at: now }
  ])
  add(REVISION_ID, WAITING_HUMAN, [{ type: 'seed', status: WAITING_HUMAN, at: now }], 1)
  add(MEETING_ID, READY, [{ type: 'seed', status: READY, at: now }])
  return rows
}
