import { useEffect, useMemo, useState } from 'react'
import { FileDown, Plus, Printer } from 'lucide-react'
import { buildRegistryReportHtml } from '../../workplace/registryPrint'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT } from './useTabChromeLayout'
import { KpiDayPicker } from '../../pages/KpiRangePicker'
import { useAssignmentRegistry } from '../../workplace/useAssignmentRegistry'
import { isDueWithinDays } from '../../workplace/assignmentRegistryMappers'
import { selectRegistryReportRows } from '../../workplace/registryReportRows'
import {
  fetchAssignmentLines,
  fetchAssignmentLinesBatch,
  mergeRowsWithLines,
  readCachedLines
} from '../../workplace/assignmentRegistryLazyLoad'
import type {
  AssignmentRegistryLine,
  AssignmentRegistryRow,
  AssignmentRegistryTileId
} from '../../workplace/assignmentRegistryTypes'
import { toFilterOptions, uniqueFilterValues } from './gridFilters'
import { usePageSearch, valuesMatchPageSearch } from '../../layout/pageSearchContext'
import { canUseExtension } from '../../extensions/extensionRegistry'
import { AssignmentsRegistryReportTable, AssignmentsRegistryTable } from './AssignmentsRegistryTable'
import { AssignmentsRegistryDetailPanel } from './AssignmentsRegistryDetailPanel'
import { AssignmentsRegistryCreateDialog } from './AssignmentsRegistryCreateDialog'
import { useRuns } from '../../store/runs'
import {
  buildClosureCheckMessage,
  CLOSURE_AGENT_TITLE,
  findClosureAgentWorkflowId,
  resolveClosureAgentWorkflowId
} from '../../workplace/assignmentClosureAgent'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import './extensionsGrid.css'
import './registryGrid.css'

const TILE_FILTER_IDS = new Set<string>(['done', 'overdue', 'due_soon', 'report'])

type RegistryColumnFilterKey = 'reporter' | 'secretary' | 'status' | 'manager'

const REGISTRY_COLUMN_FILTERS: { id: RegistryColumnFilterKey; emptyLabel: string }[] = [
  { id: 'reporter', emptyLabel: 'Кто доложит: все' },
  { id: 'secretary', emptyLabel: 'Секретарь: все' },
  { id: 'status', emptyLabel: 'Статус: все' },
  { id: 'manager', emptyLabel: 'Руководитель: все' }
]

function emptyRegistryColumnFilters(): Record<RegistryColumnFilterKey, string> {
  return { reporter: '', secretary: '', status: '', manager: '' }
}

function readRegistryColumnFilters(raw: unknown): Record<RegistryColumnFilterKey, string> {
  const next = emptyRegistryColumnFilters()
  if (!raw || typeof raw !== 'object') return next
  const record = raw as Partial<Record<RegistryColumnFilterKey, string>>
  for (const { id } of REGISTRY_COLUMN_FILTERS) {
    const value = String(record[id] || '').trim()
    if (value) next[id] = value
  }
  return next
}

function registryRowSearchValues(row: AssignmentRegistryRow): string[] {
  return [
    row.date,
    row.number,
    row.topic,
    row.basis,
    row.weeklyReportDate,
    row.fullRemediationDue,
    row.reporter,
    row.secretary,
    row.finalReportDate,
    row.status,
    row.organization,
    row.manager,
    ...row.lines.flatMap((line) => [line.text, line.executor, line.priority, line.due])
  ]
}

function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function defaultRange(): { from: string; to: string } {
  const to = new Date()
  const from = new Date(to.getFullYear(), to.getMonth() - 6, to.getDate())
  return { from: isoDate(from), to: isoDate(to) }
}

function buildRegistryTiles(
  rows: ReturnType<typeof useAssignmentRegistry>['rows'],
  aiHint: string
): SpecSummaryTile[] {
  const open = rows.filter((row) => row.open)
  const done = rows.filter((row) => !row.open)
  const overdue = open.filter((row) => row.overdue)
  const dueSoon = open.filter((row) => isDueWithinDays(row, 3))
  return [
    {
      id: 'done',
      label: 'Выполненные',
      value: String(done.length),
      hint: 'Закрытые / принятые поручения',
      tone: 'green'
    },
    {
      id: 'overdue',
      label: 'Просроченные',
      value: String(overdue.length),
      hint: 'Открытые с истёкшим сроком',
      tone: overdue.length ? 'red' : 'neutral'
    },
    {
      id: 'due_soon',
      label: 'Подходит срок',
      value: String(dueSoon.length),
      hint: '3 рабочих дня от сегодня',
      tone: dueSoon.length ? 'orange' : 'neutral'
    },
    {
      id: 'ai',
      label: 'Анализ ИИ',
      value: aiHint,
      hint: 'Проверка артефактов и оснований для закрытия',
      tone: 'purple'
    }
  ]
}

export function AssignmentsRegistryGridTab({
  user,
  onRunAgent
}: {
  user: UserProfile
  onRunAgent: (workflowId: string, title: string, message: string) => void
}): React.JSX.Element {
  const allowed = canUseExtension(user, 'assignments_registry')
  const storagePrefix = `orch-registry:${user.id || 'default'}`
  const filtersKey = `${storagePrefix}:filters`
  const tableStateKey = `${storagePrefix}:table`

  const initialFilters = useMemo(() => {
    const range = defaultRange()
    const fallback = {
      from: range.from,
      to: range.to,
      tile: 'all' as AssignmentRegistryTileId | 'all',
      columns: emptyRegistryColumnFilters()
    }
    try {
      const raw = sessionStorage.getItem(filtersKey)
      if (!raw) return fallback
      const parsed = JSON.parse(raw) as {
        from?: string
        to?: string
        tile?: string
        columns?: unknown
      }
      return {
        from: /^\d{4}-\d{2}-\d{2}$/.test(parsed.from || '') ? String(parsed.from) : fallback.from,
        to: /^\d{4}-\d{2}-\d{2}$/.test(parsed.to || '') ? String(parsed.to) : fallback.to,
        tile: TILE_FILTER_IDS.has(parsed.tile || '')
          ? (parsed.tile as AssignmentRegistryTileId)
          : ('all' as const),
        columns: readRegistryColumnFilters(parsed.columns)
      }
    } catch {
      return fallback
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey])

  const [dateFrom, setDateFrom] = useState(initialFilters.from)
  const [dateTo, setDateTo] = useState(initialFilters.to)
  const [tileFilter, setTileFilter] = useState<AssignmentRegistryTileId | 'all'>(initialFilters.tile)
  const [columnFilters, setColumnFilters] = useState(initialFilters.columns)
  const { query: pageQuery, setQuery: setPageQuery } = usePageSearch()

  const persistFilters = (
    from: string,
    to: string,
    tile: AssignmentRegistryTileId | 'all',
    columns: Record<RegistryColumnFilterKey, string> = columnFilters
  ): void => {
    try {
      sessionStorage.setItem(filtersKey, JSON.stringify({ from, to, tile, columns }))
    } catch {
      /* ignore */
    }
  }
  const changeDateFrom = (value: string): void => {
    setDateFrom(value)
    persistFilters(value, dateTo, tileFilter)
  }
  const changeDateTo = (value: string): void => {
    setDateTo(value)
    persistFilters(dateFrom, value, tileFilter)
  }
  const changeTileFilter = (next: AssignmentRegistryTileId | 'all'): void => {
    setTileFilter(next)
    persistFilters(dateFrom, dateTo, next)
  }
  const changeColumnFilter = (key: RegistryColumnFilterKey, value: string): void => {
    setColumnFilters((current) => {
      const next = { ...current, [key]: value }
      persistFilters(dateFrom, dateTo, tileFilter, next)
      return next
    })
  }

  const selectionKey = `orch-registry-selection:${user.id || 'default'}`
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(selectionKey)
    } catch {
      return null
    }
  })
  const { rows, loading, refreshing, loadingMore, firstRowReady, error, refresh } = useAssignmentRegistry(
    user.id || '',
    dateFrom,
    dateTo
  )
  const [lineOverlay, setLineOverlay] = useState<Record<string, AssignmentRegistryLine[]>>({})
  const [detailLinesLoading, setDetailLinesLoading] = useState(false)

  const rowsHydrated = useMemo(
    () => mergeRowsWithLines(rows, new Map(Object.entries(lineOverlay))),
    [rows, lineOverlay]
  )

  const pickRow = (row: { id: string } | null): void => {
    setSelectedId((current) => {
      const next = row ? (current === row.id ? null : row.id) : null
      try {
        if (next) sessionStorage.setItem(selectionKey, next)
        else sessionStorage.removeItem(selectionKey)
      } catch {
        /* ignore */
      }
      return next
    })
  }
  const runs = useRuns()

  const [closureAgentId, setClosureAgentId] = useState('')
  const [aiStarting, setAiStarting] = useState(false)
  const [aiError, setAiError] = useState('')
  useEffect(() => {
    let cancelled = false
    void findClosureAgentWorkflowId()
      .then((id) => {
        if (!cancelled && id) setClosureAgentId(id)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])
  const aiRun = closureAgentId ? runs.entries[closureAgentId] : undefined
  const aiBusy = aiStarting || Boolean(aiRun?.state?.running)
  const aiHint = aiBusy ? 'Идёт проверка…' : 'Запустить'

  const tiles = useMemo(() => buildRegistryTiles(rowsHydrated, aiHint), [rowsHydrated, aiHint])

  const columnFilterOptions = useMemo(
    () => ({
      reporter: toFilterOptions(uniqueFilterValues(rowsHydrated.map((row) => row.reporter))),
      secretary: toFilterOptions(uniqueFilterValues(rowsHydrated.map((row) => row.secretary))),
      status: toFilterOptions(uniqueFilterValues(rowsHydrated.map((row) => row.status))),
      manager: toFilterOptions(uniqueFilterValues(rowsHydrated.map((row) => row.manager)))
    }),
    [rowsHydrated]
  )

  const filteredRows = useMemo(() => {
    let list = rowsHydrated
    if (tileFilter === 'report') list = selectRegistryReportRows(list).all
    else if (tileFilter === 'done') list = list.filter((row) => !row.open)
    else if (tileFilter === 'overdue') list = list.filter((row) => row.open && row.overdue)
    else if (tileFilter === 'due_soon') list = list.filter((row) => row.open && isDueWithinDays(row, 3))

    for (const { id } of REGISTRY_COLUMN_FILTERS) {
      const picked = columnFilters[id]
      if (!picked) continue
      list = list.filter((row) => String(row[id] || '').trim() === picked)
    }

    if (pageQuery.trim()) {
      list = list.filter((row) => valuesMatchPageSearch(registryRowSearchValues(row), pageQuery))
    }
    return list
  }, [rowsHydrated, tileFilter, columnFilters, pageQuery])

  const [reportLinesLoading, setReportLinesLoading] = useState(false)
  useEffect(() => {
    if (tileFilter !== 'report') return
    const refKeys = filteredRows
      .filter((row) => row.refKey && !row.lines.length)
      .map((row) => row.refKey)
    if (!refKeys.length) return
    let cancelled = false
    setReportLinesLoading(true)
    void fetchAssignmentLinesBatch(refKeys)
      .then((batch) => {
        if (cancelled) return
        const patch: Record<string, AssignmentRegistryLine[]> = {}
        for (const [refKey, lines] of batch) {
          if (lines.length) patch[refKey] = lines
        }
        if (Object.keys(patch).length) {
          setLineOverlay((current) => ({ ...current, ...patch }))
        }
      })
      .finally(() => {
        if (!cancelled) setReportLinesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tileFilter, filteredRows])

  const filterRowCountLabel = useMemo((): string | null => {
    if (!firstRowReady && !filteredRows.length) return null
    if (loadingMore && filteredRows.length) return `${filteredRows.length} поручений…`
    return `${filteredRows.length} поручений`
  }, [filteredRows.length, firstRowReady, loadingMore])

  const startClosureCheck = async (): Promise<void> => {
    if (aiStarting) return
    setAiStarting(true)
    setAiError('')
    try {
      const workflowId = closureAgentId || (await resolveClosureAgentWorkflowId())
      setClosureAgentId(workflowId)
      // A live run opens its feed; the run page does not start a second one.
      const message = runs.entries[workflowId]?.state?.running ? '' : buildClosureCheckMessage(dateFrom, dateTo)
      onRunAgent(workflowId, CLOSURE_AGENT_TITLE, message)
    } catch (err) {
      setAiError(err instanceof Error ? err.message : 'Не удалось запустить проверку поручений')
    } finally {
      setAiStarting(false)
    }
  }

  const onTileSelect = (id: string): void => {
    if (id === 'ai') {
      void startClosureCheck()
      return
    }
    changeTileFilter(tileFilter === id ? 'all' : (id as AssignmentRegistryTileId))
  }

  const activeTileId = tileFilter === 'all' || tileFilter === 'report' ? null : tileFilter

  const resetRegistryFilters = (): void => {
    const next = defaultRange()
    setDateFrom(next.from)
    setDateTo(next.to)
    setTileFilter('all')
    setColumnFilters(emptyRegistryColumnFilters())
    setPageQuery('')
    setSelectedId(null)
    try {
      sessionStorage.removeItem(filtersKey)
      sessionStorage.removeItem(tableStateKey)
      sessionStorage.removeItem(selectionKey)
    } catch {
      /* ignore */
    }
  }

  const [printBusy, setPrintBusy] = useState(false)
  const [printError, setPrintError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createNotice, setCreateNotice] = useState('')

  const hydrateReportRows = async (): Promise<typeof rowsHydrated> => {
    const { all } = selectRegistryReportRows(rowsHydrated)
    const refKeys = all.filter((row) => row.refKey && !row.lines.length).map((row) => row.refKey)
    if (!refKeys.length) return rowsHydrated
    const batch = await fetchAssignmentLinesBatch(refKeys)
    const merged = mergeRowsWithLines(rowsHydrated, batch)
    const patch: Record<string, AssignmentRegistryLine[]> = {}
    for (const [refKey, lines] of batch) {
      if (lines.length) patch[refKey] = lines
    }
    if (Object.keys(patch).length) {
      setLineOverlay((current) => ({ ...current, ...patch }))
    }
    return merged
  }

  /** Отчёт по строкам периода; задачи догружаются пакетом только для попавших в отчёт. */
  const buildCurrentReportHtml = (sourceRows: typeof rowsHydrated): string =>
    buildRegistryReportHtml(sourceRows, {
      periodFrom: dateFrom,
      periodTo: dateTo
    })

  const PRINT_RESTART_HINT =
    'Модуль печати обновился — полностью перезапустите приложение (закрыть и открыть заново).'

  /** «PDF»: сохранение отчёта через диалог, файл открывается после сохранения. */
  const exportRegistryPdf = async (): Promise<void> => {
    if (printBusy) return
    setPrintBusy(true)
    setPrintError('')
    try {
      if (typeof window.api.printToPdf !== 'function') {
        setPrintError(PRINT_RESTART_HINT)
        return
      }
      const reportRows = await hydrateReportRows()
      const result = await window.api.printToPdf({
        html: buildCurrentReportHtml(reportRows),
        landscape: true,
        openAfter: true
      })
      if (!result.ok && !result.canceled) {
        setPrintError(result.error || 'Не удалось сохранить PDF')
      }
    } catch (err) {
      setPrintError(err instanceof Error ? err.message : 'Не удалось сохранить PDF')
    } finally {
      setPrintBusy(false)
    }
  }

  /**
   * «Печать»: сразу системный диалог печати готового отчёта
   * (выполненные / в работе / просроченные) из уже загруженных строк.
   */
  const printRegistry = async (): Promise<void> => {
    if (printBusy) return
    setPrintBusy(true)
    setPrintError('')
    try {
      if (typeof window.api.printDialog !== 'function') {
        setPrintError(PRINT_RESTART_HINT)
        return
      }
      const reportRows = await hydrateReportRows()
      const result = await window.api.printDialog({
        html: buildCurrentReportHtml(reportRows),
        landscape: true
      })
      if (!result.ok && !result.canceled) {
        setPrintError(result.error || 'Не удалось выполнить печать')
      }
    } catch (err) {
      setPrintError(err instanceof Error ? err.message : 'Не удалось выполнить печать')
    } finally {
      setPrintBusy(false)
    }
  }

  const selectedRow = useMemo(
    () =>
      filteredRows.find((row) => row.id === selectedId) ??
      rowsHydrated.find((row) => row.id === selectedId) ??
      null,
    [filteredRows, rowsHydrated, selectedId]
  )

  useEffect(() => {
    const refKey = selectedRow?.refKey?.trim()
    if (!refKey) {
      setDetailLinesLoading(false)
      return
    }
    if (selectedRow.lines.length) {
      setDetailLinesLoading(false)
      return
    }
    const cached = readCachedLines(refKey) ?? lineOverlay[refKey]
    if (cached?.length) {
      setLineOverlay((current) =>
        current[refKey]?.length ? current : { ...current, [refKey]: cached }
      )
      setDetailLinesLoading(false)
      return
    }
    let alive = true
    setDetailLinesLoading(true)
    void fetchAssignmentLines(refKey).then((lines) => {
      if (!alive) return
      setLineOverlay((current) => ({ ...current, [refKey]: lines }))
      setDetailLinesLoading(false)
    })
    return () => {
      alive = false
    }
  }, [selectedRow?.refKey, selectedRow?.lines.length])

  if (!allowed) {
    return (
      <div className="wp-card extensions-access-denied">
        <h2>Реестр поручений</h2>
        <p>Раздел доступен промпт-инженерам и помощнику Председателя совета директоров.</p>
      </div>
    )
  }

  return (
    <>
    <AssignmentsRegistryCreateDialog
      open={createOpen}
      onClose={() => setCreateOpen(false)}
      onCreated={(message) => {
        setCreateNotice(message)
        refresh()
      }}
    />
    <StandardTabChrome
      tabId="assignments_registry"
      userId={user.id || ''}
      defaults={DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT}
      hideGlobalPeriod
      labels={{ main: 'Таблица', side: 'Карточка поручения' }}
      chromeTiles={summaryTilesAsChrome(tiles, activeTileId, onTileSelect)}
      filterToolbarExtra={
        <div className="registry-filter-toolbar-actions">
          <button
            type="button"
            className="registry-filter-icon-btn"
            title="Сохранить отчёт в PDF"
            disabled={printBusy}
            onClick={() => void exportRegistryPdf()}
          >
            <FileDown size={16} aria-hidden />
            <span className="sr-only">PDF</span>
          </button>
          <button
            type="button"
            className="registry-filter-icon-btn registry-filter-icon-btn--primary"
            title="Печать готового отчёта"
            disabled={printBusy}
            onClick={() => void printRegistry()}
          >
            <Printer size={16} aria-hidden />
            <span className="sr-only">Печать</span>
          </button>
        </div>
      }
      widgets={{
        filters: (
          <div className="registry-filter-panel">
          <div
            className="registry-filter-strip registry-filter-one-row"
            role="toolbar"
            aria-label="Фильтры реестра поручений"
          >
            <div className="registry-date-filters">
              <KpiDayPicker
                prefixLabel="С"
                value={dateFrom}
                onChange={changeDateFrom}
                ariaLabel="Дата начала периода"
              />
              <KpiDayPicker
                prefixLabel="По"
                value={dateTo}
                onChange={changeDateTo}
                ariaLabel="Дата окончания периода"
              />
              <button type="button" className="today-link-btn" onClick={() => refresh()}>
                Обновить
              </button>
              <button
                type="button"
                className={`today-filter-layout-btn registry-report-filter-btn${tileFilter === 'report' ? ' is-active' : ''}`}
                aria-pressed={tileFilter === 'report'}
                title="Таблица для отчёта: просроченные, закрытые за неделю и срок в 3 рабочих дня, с мероприятиями"
                onClick={() => changeTileFilter(tileFilter === 'report' ? 'all' : 'report')}
              >
                Отчёт
              </button>
              <button
                type="button"
                className="today-filter-layout-btn registry-create-open-btn"
                title="Создать поручение в журнале АСТ00"
                onClick={() => {
                  setCreateNotice('')
                  setCreateOpen(true)
                }}
              >
                <Plus size={14} aria-hidden /> Создать
              </button>
            </div>
            <div className="registry-column-filters-inline" aria-label="Фильтры по столбцам">
              {REGISTRY_COLUMN_FILTERS.map((field) => (
                <select
                  key={field.id}
                  className="wp-select registry-column-filter"
                  value={columnFilters[field.id]}
                  aria-label={field.emptyLabel}
                  onChange={(event) => changeColumnFilter(field.id, event.target.value)}
                >
                  <option value="">{field.emptyLabel}</option>
                  {columnFilterOptions[field.id].map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              ))}
            </div>
            {filterRowCountLabel ? (
              <span className="registry-filter-row-count" aria-live="polite">
                {filterRowCountLabel}
              </span>
            ) : null}
            <span className="registry-filter-strip-spacer" aria-hidden />
            <button type="button" className="spec-filter-reset" onClick={resetRegistryFilters}>
              Сбросить
            </button>
          </div>
          </div>
        ),
        main: (
          <div className="wp-card registry-table-card registry-widget-fill">
            {error ? <p className="registry-table-error">{error}</p> : null}
            {printError ? <p className="registry-table-error">{printError}</p> : null}
            {aiError ? <p className="registry-table-error">{aiError}</p> : null}
            {createNotice ? <p className="registry-table-hint registry-table-success">{createNotice}</p> : null}
            {refreshing && rows.length && !loadingMore ? (
              <p className="registry-table-hint">Обновление данных…</p>
            ) : null}
            {loadingMore && rows.length ? (
              <p className="registry-table-hint registry-table-hint--progress">
                Загружено {rows.length}… подгружаем следующие поручения
              </p>
            ) : null}
            {tileFilter === 'report' ? (
              <AssignmentsRegistryReportTable
                rows={filteredRows}
                linesLoading={reportLinesLoading}
                selectedId={selectedId}
                onSelectRow={(row) => pickRow(row)}
              />
            ) : (
              <AssignmentsRegistryTable
                rows={filteredRows}
                loading={(!firstRowReady && !error) || (loading && !rows.length)}
                selectedId={selectedId}
                stateKey={tableStateKey}
                onSelectRow={(row) => pickRow(row)}
                emptyText={
                  pageQuery.trim() || Object.values(columnFilters).some(Boolean)
                    ? 'Нет поручений по фильтрам и поиску'
                    : tileFilter !== 'all'
                      ? 'Нет поручений по выбранной плитке'
                      : 'Нет поручений за период'
                }
              />
            )}
          </div>
        ),
        side: (
          <div className="wp-card registry-side-card registry-widget-fill">
            <AssignmentsRegistryDetailPanel
              row={selectedRow}
              linesLoading={detailLinesLoading}
              onClose={() => pickRow(null)}
            />
          </div>
        )
      }}
    />
    </>
  )
}
