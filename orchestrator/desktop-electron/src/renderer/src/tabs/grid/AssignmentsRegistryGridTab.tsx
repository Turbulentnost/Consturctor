import { useMemo, useState } from 'react'
import { buildRegistryPrintHtml } from '../../workplace/registryPrint'
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

const TILE_FILTER_LABELS: Record<AssignmentRegistryTileId | 'all', string> = {
  all: '',
  done: 'Выполненные',
  overdue: 'Просроченные',
  due_soon: 'Подходит срок',
  ai: ''
}

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
      hint: '3 дня от сегодня',
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
  const range = defaultRange()
  const [dateFrom, setDateFrom] = useState(range.from)
  const [dateTo, setDateTo] = useState(range.to)
  const [tileFilter, setTileFilter] = useState<AssignmentRegistryTileId | 'all'>('all')
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
    setTileFilter((current) => (current === id ? 'all' : (id as AssignmentRegistryTileId)))
  }

  const activeTileId = tileFilter === 'all' ? null : tileFilter

  const [printBusy, setPrintBusy] = useState(false)
  const [printError, setPrintError] = useState('')

  const buildCurrentPrintHtml = (): string =>
    buildRegistryPrintHtml(filteredRows, {
      periodFrom: dateFrom,
      periodTo: dateTo,
      filterLabel: TILE_FILTER_LABELS[tileFilter]
    })

  /** «PDF»: сохранение через диалог, файл открывается после сохранения (предпросмотр). */
  const exportRegistryPdf = async (): Promise<void> => {
    if (printBusy) return
    setPrintBusy(true)
    setPrintError('')
    try {
      const result = await window.api.printToPdf({
        html: buildCurrentPrintHtml(),
        landscape: true,
        openAfter: true
      })
      if (!result.ok && !result.canceled) {
        setPrintError(result.error || 'Не удалось сохранить PDF')
      }
    } finally {
      setPrintBusy(false)
    }
  }

  /** «Печать»: системный диалог печати Windows. */
  const printRegistry = async (): Promise<void> => {
    if (printBusy) return
    setPrintBusy(true)
    setPrintError('')
    try {
      const result = await window.api.printDialog({
        html: buildCurrentPrintHtml(),
        landscape: true
      })
      if (!result.ok && !result.canceled) {
        setPrintError(result.error || 'Не удалось выполнить печать')
      }
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
      widgets={{
        filters: (
          <GridFilterBar
            onReset={() => {
              const next = defaultRange()
              setDateFrom(next.from)
              setDateTo(next.to)
              setTileFilter('all')
              setSelectedId(null)
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
                    onChange={(event) => setDateFrom(event.target.value)}
                  />
                </label>
                <label className="spec-filter-input spec-filter-period registry-date-field">
                  <SpecIconCalendar />
                  <span className="registry-date-label">По</span>
                  <input
                    type="date"
                    className="wp-input registry-date-input"
                    value={dateTo}
                    onChange={(event) => setDateTo(event.target.value)}
                  />
                </label>
                <button type="button" className="today-link-btn" onClick={() => refresh()}>
                  Обновить
                </button>
                <button
                  type="button"
                  className="today-link-btn"
                  title="Сохранить таблицу в PDF (файл откроется после сохранения)"
                  disabled={printBusy || !filteredRows.length}
                  onClick={() => void exportRegistryPdf()}
                >
                  PDF
                </button>
                <button
                  type="button"
                  className="today-link-btn"
                  title="Печать таблицы через системный диалог"
                  disabled={printBusy || !filteredRows.length}
                  onClick={() => void printRegistry()}
                >
                  Печать
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
