import { parseRegistryDay } from './assignmentRegistryMappers'
import type { AssignmentRegistryRow } from './assignmentRegistryTypes'

export type RegistryLoadedSpan = {
  dateFrom: string
  dateTo: string
  complete: boolean
}

export type RegistryFetchSlice = {
  dateFrom: string
  dateTo: string
  /** Продолжить skip-пагинацию для этого интервала (тот же запрос, что уже шёл). */
  continuePagination?: boolean
}

function parseIsoDay(iso: string, end = false): Date | null {
  const text = (iso || '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null
  const [y, m, d] = text.split('-').map(Number)
  return new Date(y, m - 1, d, end ? 23 : 59, end ? 59 : 59, end ? 999 : 0)
}

export function formatIsoDay(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function dayBeforeIso(iso: string): string {
  const day = parseIsoDay(iso)
  if (!day) return iso
  day.setDate(day.getDate() - 1)
  return formatIsoDay(day)
}

export function dayAfterIso(iso: string): string {
  const day = parseIsoDay(iso)
  if (!day) return iso
  day.setDate(day.getDate() + 1)
  return formatIsoDay(day)
}

function cmpIso(left: string, right: string): number {
  return (left || '').trim().localeCompare((right || '').trim())
}

export function filterRegistryRowsByPeriod(
  rows: AssignmentRegistryRow[],
  dateFrom: string,
  dateTo: string
): AssignmentRegistryRow[] {
  const from = parseIsoDay(dateFrom)
  const to = parseIsoDay(dateTo, true)
  if (!from || !to) return rows
  return rows.filter((row) => {
    const doc = parseRegistryDay(row.date)
    return doc && doc >= from && doc <= to
  })
}

/** Какие интервалы дат ещё нужно запросить у 1С. */
export function planRegistryFetchSlices(
  loaded: RegistryLoadedSpan | null,
  wantFrom: string,
  wantTo: string
): RegistryFetchSlice[] {
  const from = wantFrom.trim()
  const to = wantTo.trim()
  if (!from || !to) return [{ dateFrom: from, dateTo: to }]

  if (!loaded) {
    return [{ dateFrom: from, dateTo: to }]
  }

  const disjoint =
    cmpIso(to, loaded.dateFrom) < 0 || cmpIso(from, loaded.dateTo) > 0
  if (disjoint) {
    return [{ dateFrom: from, dateTo: to }]
  }

  const wantInsideLoaded =
    cmpIso(from, loaded.dateFrom) >= 0 && cmpIso(to, loaded.dateTo) <= 0
  if (wantInsideLoaded) {
    if (loaded.complete) return []
    return [{ dateFrom: loaded.dateFrom, dateTo: loaded.dateTo, continuePagination: true }]
  }

  const slices: RegistryFetchSlice[] = []
  if (cmpIso(from, loaded.dateFrom) < 0) {
    slices.push({ dateFrom: from, dateTo: dayBeforeIso(loaded.dateFrom) })
  }
  if (cmpIso(to, loaded.dateTo) > 0) {
    slices.push({ dateFrom: dayAfterIso(loaded.dateTo), dateTo: to })
  }
  if (!slices.length && !loaded.complete) {
    slices.push({ dateFrom: loaded.dateFrom, dateTo: loaded.dateTo, continuePagination: true })
  }
  return slices
}
