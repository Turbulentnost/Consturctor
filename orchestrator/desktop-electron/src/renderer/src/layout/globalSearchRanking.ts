import type { WorkplaceTabKey } from './tabRegistry'

export type GlobalSearchKind = 'page' | 'section' | 'widget' | 'entity'

export type GlobalSearchTarget = {
  pageKey: WorkplaceTabKey
  kind: GlobalSearchKind
  targetId: string
  sectionId?: string
  title: string
}

export type GlobalSearchEntry = GlobalSearchTarget & {
  id: string
  source: string
  subtitle?: string
  keywords?: Array<string | null | undefined>
}

export function normalizeGlobalSearch(value: string): string {
  return (value || '').trim().toLowerCase().replace(/ё/g, 'е')
}

function searchText(entry: GlobalSearchEntry): string {
  return normalizeGlobalSearch(
    [entry.title, entry.subtitle, ...(entry.keywords || [])].filter(Boolean).join(' ')
  )
}

export function rankGlobalSearch(
  entries: GlobalSearchEntry[],
  rawQuery: string,
  limit = 24
): GlobalSearchEntry[] {
  const query = normalizeGlobalSearch(rawQuery)
  if (!query) return []
  const seen = new Set<string>()
  return entries
    .map((entry) => {
      const title = normalizeGlobalSearch(entry.title)
      const text = searchText(entry)
      if (!text.includes(query)) return null
      const score = title === query ? 0 : title.startsWith(query) ? 1 : title.includes(query) ? 2 : 3
      return { entry, score }
    })
    .filter((item): item is { entry: GlobalSearchEntry; score: number } => Boolean(item))
    .sort((left, right) => left.score - right.score || left.entry.title.localeCompare(right.entry.title, 'ru'))
    .filter(({ entry }) => {
      const key = `${entry.pageKey}:${entry.kind}:${entry.targetId}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, limit)
    .map(({ entry }) => entry)
}
