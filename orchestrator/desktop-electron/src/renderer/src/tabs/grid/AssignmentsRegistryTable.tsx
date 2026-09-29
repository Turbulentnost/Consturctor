import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { ArrowDown, ArrowUp, Check, ChevronLeft, EyeOff, Filter } from 'lucide-react'
import {
  ASSIGNMENT_REGISTRY_COLUMNS,
  type AssignmentRegistryColumnId,
  type AssignmentRegistryRow
} from '../../workplace/assignmentRegistryTypes'
import { rowDateSortKey } from '../../workplace/assignmentRegistryMappers'
import { selectRegistryReportRows } from '../../workplace/registryReportRows'

type SortDir = 'asc' | 'desc'

const DATE_COLUMNS = new Set<AssignmentRegistryColumnId>([
  'date',
  'weeklyReportDate',
  'fullRemediationDue',
  'finalReportDate'
])

const CLAMP_COLUMNS = new Set<AssignmentRegistryColumnId>(['topic', 'basis'])

function longestWordLength(text: string): number {
  const parts = text.split(/\s+/).filter(Boolean)
  if (!parts.length) return 0
  return parts.reduce((max, word) => Math.max(max, word.length), 0)
}

function cellValue(row: AssignmentRegistryRow, col: AssignmentRegistryColumnId): string {
  return String(row[col] ?? '')
}

function compareRows(
  left: AssignmentRegistryRow,
  right: AssignmentRegistryRow,
  col: AssignmentRegistryColumnId,
  dir: SortDir
): number {
  let cmp = 0
  if (DATE_COLUMNS.has(col)) {
    const a = rowDateSortKey(left, col)
    const b = rowDateSortKey(right, col)
    cmp = (Number.isNaN(a) ? 0 : a) - (Number.isNaN(b) ? 0 : b)
  } else {
    cmp = cellValue(left, col).localeCompare(cellValue(right, col), 'ru')
  }
  return dir === 'asc' ? cmp : -cmp
}

type SortState = { col: AssignmentRegistryColumnId; dir: SortDir } | null

export type RegistryColumnFilter = {
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}

function ColumnFilterMenu({
  label,
  filter,
  anchor,
  onClose
}: {
  label: string
  filter: RegistryColumnFilter
  anchor: DOMRect
  onClose: () => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const outside = (target: EventTarget | null): boolean =>
      !menuRef.current?.contains(target as Node)
    const onDown = (event: MouseEvent): void => {
      const target = event.target as Element | null
      if (target?.closest?.('.registry-col-btn--filter')) return
      if (outside(target)) onClose()
    }
    const onScroll = (event: Event): void => {
      if (outside(event.target)) onClose()
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onClose)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onClose)
    }
  }, [onClose])

  const needle = query.trim().toLocaleLowerCase('ru')
  const options = needle
    ? filter.options.filter((option) => option.label.toLocaleLowerCase('ru').includes(needle))
    : filter.options
  const width = 240
  const left = Math.max(8, Math.min(anchor.left + anchor.width / 2 - width / 2, window.innerWidth - width - 8))
  const pick = (value: string): void => {
    filter.onChange(value)
    onClose()
  }

  return createPortal(
    <div
      ref={menuRef}
      className="registry-col-filter-menu"
      role="listbox"
      aria-label={`Фильтр: ${label}`}
      style={{ top: anchor.bottom + 4, left, width }}
    >
      {filter.options.length > 8 ? (
        <input
          className="wp-input registry-col-filter-search"
          value={query}
          placeholder="Найти…"
          autoFocus
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      <div className="registry-col-filter-options">
        <button
          type="button"
          className={`registry-col-filter-option${!filter.value ? ' is-active' : ''}`}
          onClick={() => pick('')}
        >
          <span>Все</span>
          {!filter.value ? <Check size={14} aria-hidden /> : null}
        </button>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`registry-col-filter-option${filter.value === option.value ? ' is-active' : ''}`}
            title={option.label}
            onClick={() => pick(option.value)}
          >
            <span>{option.label}</span>
            {filter.value === option.value ? <Check size={14} aria-hidden /> : null}
          </button>
        ))}
        {!options.length ? <p className="registry-col-filter-empty">Ничего не найдено</p> : null}
      </div>
    </div>,
    document.body
  )
}

const VALID_COLUMN_IDS = new Set(ASSIGNMENT_REGISTRY_COLUMNS.map((col) => col.id))

function readTableState(key: string): { sort: SortState; collapsed: Set<AssignmentRegistryColumnId> } {
  const fallback = { sort: null as SortState, collapsed: new Set<AssignmentRegistryColumnId>() }
  if (!key) return fallback
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as {
      sort?: { col?: string; dir?: string } | null
      collapsed?: string[]
    }
    const collapsed = new Set(
      (parsed.collapsed || []).filter((id): id is AssignmentRegistryColumnId =>
        VALID_COLUMN_IDS.has(id as AssignmentRegistryColumnId)
      )
    )
    const sortCol = parsed.sort?.col
    const sort: SortState =
      sortCol && VALID_COLUMN_IDS.has(sortCol as AssignmentRegistryColumnId)
        ? {
            col: sortCol as AssignmentRegistryColumnId,
            dir: parsed.sort?.dir === 'desc' ? 'desc' : 'asc'
          }
        : null
    return { sort, collapsed }
  } catch {
    return fallback
  }
}

function writeTableState(key: string, sort: SortState, collapsed: Set<AssignmentRegistryColumnId>): void {
  if (!key) return
  try {
    sessionStorage.setItem(key, JSON.stringify({ sort, collapsed: [...collapsed] }))
  } catch {
    /* ignore */
  }
}

function ReportMeasures({ row }: { row: AssignmentRegistryRow }): React.JSX.Element {
  if (!row.lines.length) {
    return <p className="registry-report-empty">Мероприятия не указаны.</p>
  }
  return (
    <ol className="registry-report-measures">
      {row.lines.map((line, index) => (
        <li key={`${row.id}-${line.line}-${index}`}>
          <p className="registry-report-measure-text">
            <b>{line.line || index + 1}.</b> {line.text || '—'}
          </p>
          <p className="registry-report-measure-meta">
            Исполнитель: {line.executor || '—'} · Срок: {line.due || '—'}
            {line.priority && line.priority !== '—' ? ` · ${line.priority}` : ''}
          </p>
        </li>
      ))}
    </ol>
  )
}

function ReportSection({
  title,
  rows,
  selectedId,
  onSelectRow
}: {
  title: string
  rows: AssignmentRegistryRow[]
  selectedId?: string | null
  onSelectRow?: (row: AssignmentRegistryRow) => void
}): React.JSX.Element | null {
  if (!rows.length) return null
  return (
    <section className="registry-report-section">
      <h3 className="registry-report-section-title">{title}</h3>
      {rows.map((row) => (
        <article
          key={row.id}
          className={[
            'registry-report-card',
            `tone-${row.tone}`,
            selectedId === row.id ? 'is-selected' : ''
          ]
            .filter(Boolean)
            .join(' ')}
          onClick={() => onSelectRow?.(row)}
        >
          <header className="registry-report-card-head">
            <strong>
              {row.number} · {row.topic}
            </strong>
            <span>
              {row.status} · срок {row.fullRemediationDue} · {row.manager}
            </span>
          </header>
          <h4 className="registry-report-measures-title">Мероприятия ({row.lines.length})</h4>
          <ReportMeasures row={row} />
        </article>
      ))}
    </section>
  )
}

/** Таблица отчёта: те же группы, что в печати/PDF, и все мероприятия поручения. */
export function AssignmentsRegistryReportTable({
  rows,
  linesLoading,
  selectedId,
  onSelectRow
}: {
  rows: AssignmentRegistryRow[]
  linesLoading?: boolean
  selectedId?: string | null
  onSelectRow?: (row: AssignmentRegistryRow) => void
}): React.JSX.Element {
  const { overdue, closedThisWeek, dueSoon } = useMemo(() => selectRegistryReportRows(rows), [rows])
  const empty = !overdue.length && !closedThisWeek.length && !dueSoon.length
  return (
    <div className="registry-report">
      {linesLoading ? <p className="registry-table-hint">Догружаем мероприятия из 1С…</p> : null}
      {empty ? (
        <p className="registry-table-status">Нет поручений для отчёта</p>
      ) : (
        <>
          <ReportSection
            title={`Просроченные (${overdue.length})`}
            rows={overdue}
            selectedId={selectedId}
            onSelectRow={onSelectRow}
          />
          <ReportSection
            title={`Закрытые за текущую неделю (${closedThisWeek.length})`}
            rows={closedThisWeek}
            selectedId={selectedId}
            onSelectRow={onSelectRow}
          />
          <ReportSection
            title={`Срок в ближайшие 3 рабочих дня (${dueSoon.length})`}
            rows={dueSoon}
            selectedId={selectedId}
            onSelectRow={onSelectRow}
          />
        </>
      )}
    </div>
  )
}

export function AssignmentsRegistryTable({
  rows,
  loading,
  emptyText,
  selectedId,
  onSelectRow,
  stateKey = '',
  checkedIds,
  onToggleChecked,
  columnFilters
}: {
  rows: AssignmentRegistryRow[]
  loading?: boolean
  emptyText?: string
  selectedId?: string | null
  onSelectRow?: (row: AssignmentRegistryRow) => void
  /** Ключ sessionStorage для сохранения сортировки и скрытых столбцов. */
  stateKey?: string
  checkedIds?: ReadonlySet<string>
  onToggleChecked?: (row: AssignmentRegistryRow, checked: boolean) => void
  columnFilters?: Partial<Record<AssignmentRegistryColumnId, RegistryColumnFilter>>
}): React.JSX.Element {
  const initial = useMemo(() => readTableState(stateKey), [stateKey])
  const [sort, setSort] = useState<SortState>(initial.sort)
  const [collapsed, setCollapsed] = useState<Set<AssignmentRegistryColumnId>>(initial.collapsed)
  const [filterMenu, setFilterMenu] = useState<{ col: AssignmentRegistryColumnId; anchor: DOMRect } | null>(null)
  const closeFilterMenu = useMemo(() => () => setFilterMenu(null), [])

  const sortedRows = useMemo(() => {
    if (!sort) return rows
    return [...rows].sort((left, right) => compareRows(left, right, sort.col, sort.dir))
  }, [rows, sort])

  const toggleSort = (col: AssignmentRegistryColumnId): void => {
    setSort((current) => {
      const next: SortState =
        !current || current.col !== col
          ? { col, dir: 'asc' }
          : current.dir === 'asc'
            ? { col, dir: 'desc' }
            : null
      writeTableState(stateKey, next, collapsed)
      return next
    })
  }

  const collapseCol = (col: AssignmentRegistryColumnId): void => {
    setCollapsed((current) => {
      const next = new Set([...current, col])
      writeTableState(stateKey, sort, next)
      return next
    })
  }

  const expandCol = (col: AssignmentRegistryColumnId): void => {
    setCollapsed((current) => {
      const next = new Set(current)
      next.delete(col)
      writeTableState(stateKey, sort, next)
      return next
    })
  }

  const visibleColumns = ASSIGNMENT_REGISTRY_COLUMNS.filter((col) => !collapsed.has(col.id))

  const clampMinCh = useMemo(() => {
    let topic = 6
    let basis = 6
    for (const row of rows) {
      topic = Math.max(topic, longestWordLength(cellValue(row, 'topic')))
      basis = Math.max(basis, longestWordLength(cellValue(row, 'basis')))
    }
    return {
      topic: Math.min(32, Math.max(6, topic)),
      basis: Math.min(32, Math.max(6, basis))
    }
  }, [rows])

  const menuFilter = filterMenu ? columnFilters?.[filterMenu.col] : undefined

  return (
    <div className="spec-v04-table-wrap registry-table-wrap">
      {filterMenu && menuFilter ? (
        <ColumnFilterMenu
          label={ASSIGNMENT_REGISTRY_COLUMNS.find((col) => col.id === filterMenu.col)?.label || ''}
          filter={menuFilter}
          anchor={filterMenu.anchor}
          onClose={closeFilterMenu}
        />
      ) : null}
      <table
        className="spec-v04-table registry-table"
        style={
          {
            '--registry-topic-min-ch': clampMinCh.topic,
            '--registry-basis-min-ch': clampMinCh.basis
          } as CSSProperties
        }
      >
        <thead>
          <tr>
            {onToggleChecked ? (
              <th className="registry-th registry-th--check">
                <input
                  type="checkbox"
                  aria-label="Выбрать все поручения на экране"
                  checked={sortedRows.length > 0 && sortedRows.every((row) => checkedIds?.has(row.id))}
                  onChange={(event) => {
                    const on = event.target.checked
                    for (const row of sortedRows) onToggleChecked(row, on)
                  }}
                />
              </th>
            ) : null}
            {ASSIGNMENT_REGISTRY_COLUMNS.map((col) => {
              if (collapsed.has(col.id)) {
                return (
                  <th
                    key={col.id}
                    className="registry-th registry-th--collapsed"
                    data-col={col.id}
                    title={`Развернуть: ${col.label}`}
                  >
                    <button
                      type="button"
                      className="registry-col-expand-btn"
                      title={`Развернуть: ${col.label}`}
                      aria-label={`Развернуть столбец «${col.label}»`}
                      onClick={() => expandCol(col.id)}
                    >
                      <ChevronLeft size={14} aria-hidden />
                    </button>
                  </th>
                )
              }
              const active = sort?.col === col.id
              const dir = active ? sort?.dir : null
              const colFilter = columnFilters?.[col.id]
              const filtered = Boolean(colFilter?.value)
              return (
                <th
                  key={col.id}
                  className={[
                    'registry-th',
                    col.compact ? 'registry-th--compact' : '',
                    filtered ? 'registry-th--filtered' : ''
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  data-col={col.id}
                >
                  <span className="registry-th-label">{col.label}</span>
                  {filtered ? (
                    <span className="registry-th-filter-value" title={colFilter?.value}>
                      {colFilter?.value}
                    </span>
                  ) : null}
                  <div className="registry-th-tools">
                    {colFilter ? (
                      <button
                        type="button"
                        className={`registry-col-btn registry-col-btn--filter${filtered ? ' is-active' : ''}`}
                        title={filtered ? `Фильтр: ${colFilter.value}` : 'Фильтр по столбцу'}
                        aria-label={`Фильтр по столбцу «${col.label}»`}
                        aria-expanded={filterMenu?.col === col.id}
                        onClick={(event) => {
                          const anchor = event.currentTarget.getBoundingClientRect()
                          setFilterMenu((current) => (current?.col === col.id ? null : { col: col.id, anchor }))
                        }}
                      >
                        <Filter size={11} aria-hidden />
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={`registry-col-btn${active ? ' is-active' : ''}`}
                      title={
                        !active
                          ? 'Сортировать по возрастанию'
                          : dir === 'asc'
                            ? 'Сортировать по убыванию'
                            : 'Сбросить сортировку'
                      }
                      onClick={() => toggleSort(col.id)}
                    >
                      {!active ? (
                        <ArrowUp size={12} aria-hidden />
                      ) : dir === 'asc' ? (
                        <ArrowUp size={12} aria-hidden />
                      ) : (
                        <ArrowDown size={12} aria-hidden />
                      )}
                    </button>
                    <button
                      type="button"
                      className="registry-col-btn registry-col-btn--hide"
                      title="Скрыть столбец"
                      aria-label={`Скрыть столбец «${col.label}»`}
                      onClick={() => collapseCol(col.id)}
                    >
                      <EyeOff size={12} aria-hidden />
                    </button>
                  </div>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading && !rows.length ? (
            <tr>
              <td colSpan={ASSIGNMENT_REGISTRY_COLUMNS.length + (onToggleChecked ? 1 : 0)} className="registry-table-status">
                <span className="registry-table-status-spin" aria-hidden>
                  <span className="spinner" />
                </span>
                <span>Загружаем реестр из 1С… (до 1 мин)</span>
              </td>
            </tr>
          ) : !sortedRows.length ? (
            <tr>
              <td colSpan={ASSIGNMENT_REGISTRY_COLUMNS.length + (onToggleChecked ? 1 : 0)} className="registry-table-status">
                {emptyText || 'Нет поручений по выбранным условиям'}
              </td>
            </tr>
          ) : (
            sortedRows.map((row) => {
              const selected = selectedId === row.id
              return (
                <tr
                  key={row.id}
                  className={[
                    `registry-tr tone-${row.tone}`,
                    selected ? 'is-selected' : '',
                    onSelectRow ? 'is-clickable' : ''
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => onSelectRow?.(row)}
                >
                  {onToggleChecked ? (
                    <td className="registry-td registry-td--check" onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Выбрать поручение ${row.number}`}
                        checked={Boolean(checkedIds?.has(row.id))}
                        onChange={(event) => onToggleChecked(row, event.target.checked)}
                      />
                    </td>
                  ) : null}
                  {ASSIGNMENT_REGISTRY_COLUMNS.map((col) => {
                    if (collapsed.has(col.id)) {
                      return <td key={col.id} className="registry-td registry-td--collapsed" />
                    }
                    const text = cellValue(row, col.id)
                    const clamp = CLAMP_COLUMNS.has(col.id)
                    return (
                      <td
                        key={col.id}
                        className={`registry-td${col.compact ? ' registry-td--compact' : ''}${clamp ? ' registry-td--clamp' : ''}`}
                        data-col={col.id}
                        title={clamp ? text : undefined}
                      >
                        <span className={`registry-cell-text${clamp ? ' registry-cell-text--clamp' : ''}`}>
                          {text}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
      {visibleColumns.length === 0 ? (
        <p className="registry-table-hint">
          Все столбцы скрыты — нажмите «‹» в заголовке, чтобы вернуть столбец.
        </p>
      ) : null}
    </div>
  )
}
