/** Фильтр каталога расширений по целевой должности (расширяется по мере появления модулей). */
export type ExtensionPositionFilter = 'all' | 'director_assistants' | 'department_heads'

export const EXTENSION_POSITION_FILTERS: { id: ExtensionPositionFilter; label: string }[] = [
  { id: 'all', label: 'Все должности' },
  { id: 'department_heads', label: 'Руководители подразделений' },
  { id: 'director_assistants', label: 'Помощники директоров' }
]

export function extensionMatchesPositionFilter(
  positionGroups: ExtensionPositionFilter[],
  filter: ExtensionPositionFilter
): boolean {
  if (filter === 'all') return true
  if (positionGroups.includes('all')) return true
  return positionGroups.includes(filter)
}
