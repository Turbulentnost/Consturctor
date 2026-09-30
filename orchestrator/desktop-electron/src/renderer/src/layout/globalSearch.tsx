import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import type { WorkplaceTabKey } from './tabRegistry'
import {
  rankGlobalSearch,
  type GlobalSearchEntry,
  type GlobalSearchKind,
  type GlobalSearchTarget
} from './globalSearchRanking'

export { rankGlobalSearch }
export type { GlobalSearchEntry, GlobalSearchKind, GlobalSearchTarget }

type GlobalSearchContextValue = {
  query: string
  setQuery: (value: string) => void
  results: GlobalSearchEntry[]
  choose: (entry: GlobalSearchEntry) => void
  register: (source: string, entries: GlobalSearchEntry[]) => void
}

const GlobalSearchContext = createContext<GlobalSearchContextValue | null>(null)

const PAGE_ENTRIES: Array<[WorkplaceTabKey, string, string]> = [
  ['today', 'Сегодня', 'Рабочее место'],
  ['processes', 'Процессы', 'Все процессы должности'],
  ['tasks', 'Задачи', 'Единый центр задач'],
  ['projects', 'Проекты', 'Проекты, роли и сроки'],
  ['mail', 'Письма', 'Почта Outlook'],
  ['docflow', 'Документооборот', 'Документы и поручения'],
  ['meetings', 'Совещания', 'Календарь и материалы'],
  ['decisions', 'Решения', 'Рекомендации и подтверждения'],
  ['kpi', 'KPI', 'Ключевые показатели'],
  ['history', 'История', 'Журнал действий'],
  ['knowledge', 'База знаний', 'Регламенты и инструкции'],
  ['extensions', 'Расширения', 'Дополнительные вкладки'],
  ['assignments_registry', 'Реестр поручений', 'Контроль поручений'],
  ['agent_library', 'Библиотека агентов', 'Опубликованные ИИ-агенты'],
  ['task_create', 'Создание задачи в 1С', 'Новая задача в документообороте'],
  ['platform_task_create', 'Создание задачи в платформе', 'Новая внутренняя задача']
]

const SECTION_ENTRIES: Array<[WorkplaceTabKey, string, string, GlobalSearchKind]> = [
  ['today', 'plan', 'План на день', 'widget'],
  ['today', 'results', 'Результаты агентов', 'widget'],
  ['today', 'outlook', 'Письма Outlook', 'widget'],
  ['today', 'onec', 'Задачи на сегодня', 'widget'],
  ['today', 'events', 'События', 'widget'],
  ['today', 'decisions', 'Решения', 'widget'],
  ['processes', 'all', 'Все процессы', 'section'],
  ['processes', 'reg', 'Регламентные процессы', 'section'],
  ['processes', 'onec', 'Задачи из 1С', 'section'],
  ['processes', 'proj', 'Проектные процессы', 'section'],
  ['processes', 'mail', 'Письма в процессах', 'section'],
  ['processes', 'meet', 'Совещания в процессах', 'section'],
  ['docflow', 'correspondence', 'Корреспонденция', 'section'],
  ['docflow', 'memos', 'Служебные записки', 'section'],
  ['docflow', 'orders', 'Приказы и распоряжения', 'section'],
  ['docflow', 'assignments', 'Поручения', 'section'],
  ['docflow', 'protocols', 'Протоколы', 'section']
]

export const STATIC_GLOBAL_SEARCH_ENTRIES: GlobalSearchEntry[] = [
  ...PAGE_ENTRIES.map(([pageKey, title, subtitle]) => ({
    id: `page:${pageKey}`,
    source: 'static:pages',
    pageKey,
    kind: 'page' as const,
    targetId: `page:${pageKey}`,
    title,
    subtitle
  })),
  ...SECTION_ENTRIES.map(([pageKey, targetId, title, kind]) => ({
    id: `${kind}:${pageKey}:${targetId}`,
    source: 'static:sections',
    pageKey,
    kind,
    targetId,
    title,
    subtitle: PAGE_ENTRIES.find(([key]) => key === pageKey)?.[1] || ''
  }))
]

export function GlobalSearchProvider({
  onChoose,
  children
}: {
  onChoose: (target: GlobalSearchTarget) => void
  children: ReactNode
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const sourcesRef = useRef(new Map<string, GlobalSearchEntry[]>())
  const [revision, setRevision] = useState(0)

  const register = useCallback((source: string, entries: GlobalSearchEntry[]) => {
    sourcesRef.current.set(source, entries)
    setRevision((value) => value + 1)
  }, [])

  const entries = useMemo(
    () => [...STATIC_GLOBAL_SEARCH_ENTRIES, ...Array.from(sourcesRef.current.values()).flat()],
    [revision]
  )
  const results = useMemo(() => rankGlobalSearch(entries, query), [entries, query])
  const choose = useCallback(
    (entry: GlobalSearchEntry) => {
      setQuery('')
      onChoose({
        pageKey: entry.pageKey,
        kind: entry.kind,
        targetId: entry.targetId,
        sectionId: entry.sectionId,
        title: entry.title
      })
    },
    [onChoose]
  )
  const value = useMemo(
    () => ({ query, setQuery, results, choose, register }),
    [query, results, choose, register]
  )
  return <GlobalSearchContext.Provider value={value}>{children}</GlobalSearchContext.Provider>
}

export function useGlobalSearch(): GlobalSearchContextValue {
  const context = useContext(GlobalSearchContext)
  if (!context) throw new Error('useGlobalSearch must be used within GlobalSearchProvider')
  return context
}

export function useRegisterGlobalSearch(source: string, entries: GlobalSearchEntry[]): void {
  const { register } = useGlobalSearch()
  useEffect(() => {
    register(source, entries)
  }, [source, entries, register])
}
