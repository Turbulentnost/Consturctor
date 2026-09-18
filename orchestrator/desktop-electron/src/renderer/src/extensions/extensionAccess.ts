import type { UserProfile } from '../api/types'

function normText(value: string): string {
  return (value || '')
    .trim()
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/\s+/g, ' ')
}

export function isPromptEngineer(user: UserProfile): boolean {
  if (user.isAdmin) return true
  const blob = normText(`${user.position} ${user.department} ${user.role}`)
  return /промпт|prompt/.test(blob)
}

export function isChairmanBoardAssistant(user: UserProfile): boolean {
  const pos = normText(user.position)
  if (/помощник/.test(pos) && /председател/.test(pos) && /совет/.test(pos) && /директор/.test(pos)) {
    return true
  }
  return /помощник председателя совета директоров/.test(pos)
}

export function canUseAssignmentsRegistry(user: UserProfile): boolean {
  return isPromptEngineer(user) || isChairmanBoardAssistant(user)
}
