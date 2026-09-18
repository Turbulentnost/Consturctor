import { useMemo, useState, type CSSProperties } from 'react'
import { ArrowDown, ArrowUp, ChevronLeft, EyeOff } from 'lucide-react'
import {
  ASSIGNMENT_REGISTRY_COLUMNS,
  type AssignmentRegistryColumnId,
  type AssignmentRegistryRow
} from '../../workplace/assignmentRegistryTypes'
import { rowDateSortKey } from '../../workplace/assignmentRegistryMappers'

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

export function AssignmentsRegistryTable({
  rows,
  loading,
  emptyText,
  selectedId,
  onSelectRow,
  stateKey = ''
}: {
  rows: AssignmentRegistryRow[]
  loading?: boolean
  emptyText?: string
  selectedId?: string | null
  onSelectRow?: (row: AssignmentRegistryRow) => void
  /** Ключ sessionStorage для сохранения сортировки и скрытых столбцов. */
  stateKey?: string
}): React.JSX.Element {
  const initial = useMemo(() => readTableState(stateKey), [stateKey])
  const [sort, setSort] = useState<SortState>(initial.sort)
  const [collapsed, setCollapsed] = useState<Set<AssignmentRegistryColumnId>>(initial.collapsed)

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

  return (
    <div className="spec-v04-table-wrap registry-table-wrap">
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
              return (
                <th
                  key={col.id}
                  className={`registry-th${col.compact ? ' registry-th--compact' : ''}`}
                  data-col={col.id}
                >
                  <span className="registry-th-label">{col.label}</span>
                  <div className="registry-th-tools">
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
              <td colSpan={ASSIGNMENT_REGISTRY_COLUMNS.length} className="registry-table-status">
                Загружаем реестр из 1С… (до 1 мин)
              </td>
            </tr>
          ) : !sortedRows.length ? (
            <tr>
              <td colSpan={ASSIGNMENT_REGISTRY_COLUMNS.length} className="registry-table-status">
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
