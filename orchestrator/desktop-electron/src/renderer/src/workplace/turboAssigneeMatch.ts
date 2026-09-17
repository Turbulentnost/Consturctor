/** Normalized person key for TurboProject resource_name vs session FIO. */
export function normalizePersonKey(value: string): string {
  return (value || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[ьъ]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export type PersonMatchMode = 'fio' | 'surname'

function surnameAndInitials(key: string): { surname: string; initials: string[] } | null {
  const parts = key.split(' ')
  if (parts.length < 2) return null
  const tail = parts.slice(1).join(' ')
  if (!tail.includes('.')) return null
  const initials = tail
    .replace(/\./g, ' ')
    .split(/\s+/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => chunk[0])
  if (!initials.length) return null
  return { surname: parts[0], initials }
}

function initialsMatchNameParts(initials: string[], nameParts: string[]): boolean {
  if (!initials.length || !nameParts.length) return false
  if (initials.length === 1) return initials[0] === nameParts[0][0]
  const needed = Math.min(initials.length, nameParts.length)
  for (let index = 0; index < needed; index += 1) {
    if (initials[index] !== nameParts[index][0]) return false
  }
  return true
}

export function personNameMatches(
  actor: string,
  candidate: string,
  mode: PersonMatchMode = 'fio'
): boolean {
  const actorKey = normalizePersonKey(actor)
  const candKey = normalizePersonKey(candidate)
  if (!actorKey || !candKey) return false
  const actorParts = actorKey.split(' ')
  const candParts = candKey.split(' ')
  if (mode === 'surname') {
    return Boolean(actorParts[0] && candParts[0] && actorParts[0] === candParts[0])
  }
  if (actorKey === candKey) return true
  if (actorKey.includes(candKey) || candKey.includes(actorKey)) {
    const shorter = actorKey.length <= candKey.length ? actorKey : candKey
    if (shorter.split(' ').length >= 2) return true
  }
  if (actorParts.length >= 2 && candParts.length >= 2) {
    if (actorParts[0] === candParts[0] && actorParts[1] === candParts[1]) return true
  }
  const actorInit = surnameAndInitials(actorKey)
  const candInit = surnameAndInitials(candKey)
  if (actorInit && candParts.length >= 2) {
    if (
      actorInit.surname === candParts[0] &&
      initialsMatchNameParts(actorInit.initials, candParts.slice(1))
    ) {
      return true
    }
  }
  if (candInit && actorParts.length >= 2) {
    if (
      candInit.surname === actorParts[0] &&
      initialsMatchNameParts(candInit.initials, actorParts.slice(1))
    ) {
      return true
    }
  }
  return false
}

function turboTaskExecutorNames(task: Record<string, unknown>): string[] {
  const executors = Array.isArray(task.executors)
    ? task.executors.filter((item): item is string => typeof item === 'string' && item.trim())
    : []
  if (executors.length) return executors
  const assignments = Array.isArray(task.assignments) ? task.assignments : []
  const names: string[] = []
  for (const item of assignments) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const direct = String(row.resource_name ?? row.ResourceName ?? row.resourceName ?? '').trim()
    if (direct) {
      names.push(direct)
      continue
    }
    const resource = row.resource
    if (resource && typeof resource === 'object') {
      const nested = String((resource as Record<string, unknown>).name ?? '').trim()
      if (nested) names.push(nested)
    }
  }
  return names
}

export function turboTaskAssignedToActor(
  task: Record<string, unknown>,
  actorFio: string,
  resourceIds: string[] = [],
  mode: PersonMatchMode = 'fio'
): boolean {
  const fio = actorFio.trim()
  const ids = new Set(resourceIds.map((item) => item.trim()).filter(Boolean))
  const executors = turboTaskExecutorNames(task)
  if (fio && executors.some((name) => personNameMatches(fio, name, mode))) return true
  const rawIds = task.executor_resource_ids
  if (ids.size && Array.isArray(rawIds)) {
    for (const item of rawIds) {
      if (ids.has(String(item).trim())) return true
    }
  }
  return false
}

/** Match by full FIO first; if nothing found, retry by surname only. */
export function filterTurboTasksByActor<T extends Record<string, unknown>>(
  tasks: T[],
  actorFio: string,
  resourceIds: string[] = []
): T[] {
  if (!actorFio.trim()) return tasks
  const fioHits = tasks.filter((task) => turboTaskAssignedToActor(task, actorFio, resourceIds, 'fio'))
  if (fioHits.length) return fioHits
  return tasks.filter((task) => turboTaskAssignedToActor(task, actorFio, resourceIds, 'surname'))
}
