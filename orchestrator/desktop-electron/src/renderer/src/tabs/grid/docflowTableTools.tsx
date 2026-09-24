import { useCallback, useMemo, useState } from 'react'
import { ChevronDown, Search } from 'lucide-react'

export type SortDir = 'asc' | 'desc'
export type SortState = { key: string; dir: SortDir } | null

/** Все слова запроса должны встретиться в строке журнала. */
export function rowMatchesWords(haystack: string, query: string): boolean {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const text = haystack.toLowerCase()
  return words.every((word) => text.includes(word))
}

function compare(left: unknown, right: unknown): number {
  if (typeof left === 'number' && typeof right === 'number') return left - right
  const a = String(left ?? '')
  const b = String(right ?? '')
  const emptyA = !a.trim() || a.trim() === '—'
  const emptyB = !b.trim() || b.trim() === '—'
  // Пустые ячейки всегда внизу, каким бы ни было направление.
  if (emptyA !== emptyB) return emptyA ? 1 : -1
  return a.localeCompare(b, 'ru', { numeric: true, sensitivity: 'base' })
}

/**
 * Поиск по словам и сортировка по колонке для таблиц документооборота.
 * `value` отдаёт значение строки по ключу колонки, `text` — строку для поиска.
 */
export function useDocflowTable<T>(
  rows: T[],
  options: {
    text: (row: T) => string
    value: (row: T, key: string) => string | number
    initialSort?: SortState
    query?: string
  }
): {
  query: string
  setQuery: (value: string) => void
  sort: SortState
  toggleSort: (key: string) => void
  rows: T[]
} {
  const { text, value, initialSort = null } = options
  const [innerQuery, setInnerQuery] = useState('')
  const [sort, setSort] = useState<SortState>(initialSort)
  const query = options.query ?? innerQuery

  const toggleSort = useCallback((key: string) => {
    setSort((current) => {
      if (!current || current.key !== key) return { key, dir: 'desc' }
      if (current.dir === 'desc') return { key, dir: 'asc' }
      return null
    })
  }, [])

  const result = useMemo(() => {
    const found = query.trim() ? rows.filter((row) => rowMatchesWords(text(row), query)) : rows
    if (!sort) return found
    const sorted = [...found]
    sorted.sort((left, right) => {
      const diff = compare(value(left, sort.key), value(right, sort.key))
      return sort.dir === 'asc' ? diff : -diff
    })
    return sorted
    // text/value — стабильные колбэки вызывающего компонента.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, query, sort])

  return { query, setQuery: setInnerQuery, sort, toggleSort, rows: result }
}

/** Заголовок колонки со стрелкой: клик — сортировка по убыванию, дальше по возрастанию, потом сброс. */
export function SortTh({
  label,
  sortKey,
  sort,
  onSort,
  title
}: {
  label: string
  sortKey: string
  sort: SortState
  onSort: (key: string) => void
  title?: string
}): React.JSX.Element {
  const active = sort?.key === sortKey
  const dir = active ? sort?.dir : undefined
  return (
    <th className={`docflow-th-sort${active ? ' is-active' : ''}`} aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        className="docflow-sort-btn"
        title={title || `Сортировать по «${label}»`}
        onClick={() => onSort(sortKey)}
      >
        <span>{label}</span>
        <ChevronDown
          size={13}
          aria-hidden
          className={`docflow-sort-ico${active ? ' is-active' : ''}${dir === 'asc' ? ' is-asc' : ''}`}
        />
      </button>
    </th>
  )
}

/** Поиск по словам над таблицей журнала. */
export function DocflowSearch({
  value,
  onChange,
  placeholder = 'Поиск по словам…',
  found,
  total
}: {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  found?: number
  total?: number
}): React.JSX.Element {
  return (
    <label className="docflow-search">
      <Search size={14} aria-hidden />
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {value.trim() && typeof found === 'number' && typeof total === 'number' ? (
        <span className="docflow-search-count">
          {found} из {total}
        </span>
      ) : null}
    </label>
  )
}
