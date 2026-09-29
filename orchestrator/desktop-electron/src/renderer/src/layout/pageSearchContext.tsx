import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { WorkplaceTabKey } from './tabRegistry'

type PageSearchContextValue = {
  tabKey: WorkplaceTabKey
  query: string
  setQuery: (value: string) => void
}

const PageSearchContext = createContext<PageSearchContextValue | null>(null)

export function PageSearchProvider({
  tabKey,
  children
}: {
  tabKey: WorkplaceTabKey
  children: ReactNode
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  useEffect(() => {
    setQuery('')
  }, [tabKey])

  const value = useMemo(() => ({ tabKey, query, setQuery }), [tabKey, query])
  return <PageSearchContext.Provider value={value}>{children}</PageSearchContext.Provider>
}

export function usePageSearch(): PageSearchContextValue {
  const ctx = useContext(PageSearchContext)
  if (!ctx) {
    throw new Error('usePageSearch must be used within PageSearchProvider')
  }
  return ctx
}

export function usePageSearchOptional(): PageSearchContextValue | null {
  return useContext(PageSearchContext)
}

export function normalizePageSearchQuery(value: string): string {
  return (value || '').trim().toLowerCase().replace(/ё/g, 'е')
}

export function textMatchesPageSearch(haystack: string, rawQuery: string): boolean {
  const needle = normalizePageSearchQuery(rawQuery)
  if (!needle) return true
  const hay = normalizePageSearchQuery(haystack)
  return hay.includes(needle)
}

export function valuesMatchPageSearch(values: Array<string | undefined | null>, rawQuery: string): boolean {
  const needle = normalizePageSearchQuery(rawQuery)
  if (!needle) return true
  const hay = normalizePageSearchQuery(values.map((value) => String(value ?? '')).join(' '))
  return hay.includes(needle)
}

export const PAGE_SEARCH_PLACEHOLDER: Partial<Record<WorkplaceTabKey, string>> = {
  today: 'Поиск на вкладке «Сегодня»…',
  processes: 'Поиск по процессам…',
  tasks: 'Поиск по задачам…',
  projects: 'Поиск по проектам…',
  mail: 'Поиск в письмах…',
  meetings: 'Поиск совещаний…',
  decisions: 'Найти решение…',
  knowledge: 'Поиск по материалам…',
  history: 'Поиск в истории…',
  extensions: 'Поиск расширений…',
  assignments_registry: 'Поиск в реестре поручений…',
  agent_library: 'Поиск агентов…',
  kpi: 'Поиск на странице KPI…'
}
