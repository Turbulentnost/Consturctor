import type { SpecTaskRow } from './specV04DemoData'

export type OnecImportance = 'high' | 'normal' | 'low' | ''

const HIGH = /высок|критич|срочн/i
const LOW = /низк/i
const NORMAL = /обычн|средн|нормальн/i

/** «Важность» задачи 1С из ДО → high | normal | low. */
export function parseOnecImportance(raw: string | undefined): OnecImportance {
  const text = String(raw || '').trim()
  if (!text) return ''
  if (text === 'high' || text === 'normal' || text === 'low') return text
  if (HIGH.test(text)) return 'high'
  if (LOW.test(text)) return 'low'
  if (NORMAL.test(text)) return 'normal'
  return ''
}

/**
 * Подсветка строки задачи 1С: «мои» и «от меня». Просроченная задача считается
 * важной, даже когда 1С не отдала «Важность».
 */
export function onecRowImportance(row: SpecTaskRow): OnecImportance {
  if (row.sourceKind !== 'docflow' && row.sourceKind !== 'erp') return ''
  const explicit = parseOnecImportance(row.importance)
  if (explicit) return explicit
  return row.urgent ? 'high' : ''
}
