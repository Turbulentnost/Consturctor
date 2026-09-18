import { useMemo, useState } from 'react'
import { FileDown, Printer } from 'lucide-react'
import { buildRegistryReportHtml } from '../../workplace/registryPrint'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT } from './useTabChromeLayout'
import { GridFilterBar } from './gridFilters'
import { SpecIconCalendar } from '../../workplace/specV04Icons'
import { useAssignmentRegistry } from '../../workplace/useAssignmentRegistry'
import { isDueWithinDays } from '../../workplace/assignmentRegistryMappers'
import type { AssignmentRegistryTileId } from '../../workplace/assignmentRegistryTypes'
import { canUseExtension } from '../../extensions/extensionRegistry'
import { AssignmentsRegistryTable } from './AssignmentsRegistryTable'
import { AssignmentsRegistryDetailPanel } from './AssignmentsRegistryDetailPanel'
import { useRuns } from '../../store/runs'
import { personalAgentWorkflowId } from '../../workplace/personalAgent'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import './extensionsGrid.css'
import './registryGrid.css'

export const ASSIGNMENTS_REGISTRY_AI_CONTEXT = 'Расширение «Реестр поручений»'

const TILE_FILTER_IDS = new Set<string>(['done', 'overdue', 'due_soon'])

const AI_REVIEW_PROMPT =
  'Проверь все незакрытые поручения в журнале АСТ00 за выбранный период: для каждого открытого поручения проверь наличие артефактов (файлов через onec.erp_assignments action=files) и оцени, есть ли реальные основания для закрытия. Сформируй список сомнительных и готовых к закрытию с кратким обоснованием.'

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
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, appContext: string) => void
}): React.JSX.Element {
  const allowed = canUseExtension(user, 'assignments_registry')
  const storagePrefix = `orch-registry:${user.id || 'default'}`
  const filtersKey = `${storagePrefix}:filters`
  const tableStateKey = `${storagePrefix}:table`

  const initialFilters = useMemo(() => {
    const range = defaultRange()
    const fallback = { from: range.from, to: range.to, tile: 'all' as AssignmentRegistryTileId | 'all' }
    try {
      const raw = sessionStorage.getItem(filtersKey)
      if (!raw) return fallback
      const parsed = JSON.parse(raw) as { from?: string; to?: string; tile?: string }
      return {
        from: /^\d{4}-\d{2}-\d{2}$/.test(parsed.from || '') ? String(parsed.from) : fallback.from,
        to: /^\d{4}-\d{2}-\d{2}$/.test(parsed.to || '') ? String(parsed.to) : fallback.to,
        tile: TILE_FILTER_IDS.has(parsed.tile || '')
          ? (parsed.tile as AssignmentRegistryTileId)
          : ('all' as const)
      }
    } catch {
      return fallback
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey])

  const [dateFrom, setDateFrom] = useState(initialFilters.from)
  const [dateTo, setDateTo] = useState(initialFilters.to)
  const [tileFilter, setTileFilter] = useState<AssignmentRegistryTileId | 'all'>(initialFilters.tile)

  const persistFilters = (from: string, to: string, tile: AssignmentRegistryTileId | 'all'): void => {
    try {
      sessionStorage.setItem(filtersKey, JSON.stringify({ from, to, tile }))
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

  const selectionKey = `orch-registry-selection:${user.id || 'default'}`
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(selectionKey)
    } catch {
      return null
    }
  })
  const { rows, loading, refreshing, error, refresh } = useAssignmentRegistry(user.id || '', dateFrom, dateTo)

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

  const personalId = personalAgentWorkflowId(user.id || '')
  const aiRun = runs.entries[personalId]
  const aiBusy = Boolean(aiRun?.state?.running)
  const aiHint = aiBusy ? 'Идёт проверка…' : 'Запустить'

  const tiles = useMemo(() => buildRegistryTiles(rows, aiHint), [rows, aiHint])

  const filteredRows = useMemo(() => {
    if (tileFilter === 'all') return rows
    if (tileFilter === 'done') return rows.filter((row) => !row.open)
    if (tileFilter === 'overdue') return rows.filter((row) => row.open && row.overdue)
    if (tileFilter === 'due_soon') return rows.filter((row) => row.open && isDueWithinDays(row, 3))
    return rows
  }, [rows, tileFilter])

  const onTileSelect = (id: string): void => {
    if (id === 'ai') {
      onAskOrchestrator(AI_REVIEW_PROMPT, ASSIGNMENTS_REGISTRY_AI_CONTEXT)
      return
    }
    changeTileFilter(tileFilter === id ? 'all' : (id as AssignmentRegistryTileId))
  }

  const activeTileId = tileFilter === 'all' ? null : tileFilter

  const [printBusy, setPrintBusy] = useState(false)
  const [printError, setPrintError] = useState('')

  /** Отчёт всегда по всем строкам периода: разделы группируют сами. */
  const buildCurrentReportHtml = (): string =>
    buildRegistryReportHtml(rows, {
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
      const result = await window.api.printToPdf({
        html: buildCurrentReportHtml(),
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
      const result = await window.api.printDialog({
        html: buildCurrentReportHtml(),
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
    () => filteredRows.find((row) => row.id === selectedId) ?? rows.find((row) => row.id === selectedId) ?? null,
    [filteredRows, rows, selectedId]
  )

  if (!allowed) {
    return (
      <div className="wp-card extensions-access-denied">
        <h2>Реестр поручений</h2>
        <p>Раздел доступен промпт-инженерам и помощнику Председателя совета директоров.</p>
      </div>
    )
  }

  return (
    <StandardTabChrome
      tabId="assignments_registry"
      userId={user.id || ''}
      defaults={DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT}
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
          <GridFilterBar
            onReset={() => {
              const next = defaultRange()
              setDateFrom(next.from)
              setDateTo(next.to)
              setTileFilter('all')
              setSelectedId(null)
              try {
                sessionStorage.removeItem(filtersKey)
                sessionStorage.removeItem(tableStateKey)
                sessionStorage.removeItem(selectionKey)
              } catch {
                /* ignore */
              }
            }}
            extra={
              <div className="registry-date-filters">
                <label className="spec-filter-input spec-filter-period registry-date-field">
                  <SpecIconCalendar />
                  <span className="registry-date-label">С</span>
                  <input
                    type="date"
                    className="wp-input registry-date-input"
                    value={dateFrom}
                    onChange={(event) => changeDateFrom(event.target.value)}
                  />
                </label>
                <label className="spec-filter-input spec-filter-period registry-date-field">
                  <SpecIconCalendar />
                  <span className="registry-date-label">По</span>
                  <input
                    type="date"
                    className="wp-input registry-date-input"
                    value={dateTo}
                    onChange={(event) => changeDateTo(event.target.value)}
                  />
                </label>
                <button type="button" className="today-link-btn" onClick={() => refresh()}>
                  Обновить
                </button>
              </div>
            }
          />
        ),
        main: (
          <div className="wp-card registry-table-card registry-widget-fill">
            {error ? <p className="registry-table-error">{error}</p> : null}
            {printError ? <p className="registry-table-error">{printError}</p> : null}
            {refreshing && rows.length ? (
              <p className="registry-table-hint">Обновление данных…</p>
            ) : null}
            <AssignmentsRegistryTable
              rows={filteredRows}
              loading={loading && !rows.length}
              selectedId={selectedId}
              stateKey={tableStateKey}
              onSelectRow={(row) => pickRow(row)}
              emptyText={
                tileFilter !== 'all' ? 'Нет поручений по выбранной плитке' : 'Нет поручений за период'
              }
            />
          </div>
        ),
        side: (
          <div className="wp-card registry-side-card registry-widget-fill">
            <AssignmentsRegistryDetailPanel row={selectedRow} onClose={() => pickRow(null)} />
          </div>
        )
      }}
    />
  )
}
