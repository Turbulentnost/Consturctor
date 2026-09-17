import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { AgentRunHistoryItem, UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_PROCESS_LAYOUT } from './useTabChromeLayout'
import {
  SpecPanel,
  SpecPill,
  SpecProgress,
  SpecQuickActions,
  SpecTableTabs
} from '../../workplace/specV04Components'
import { type SpecProcessRow } from '../../workplace/specV04DemoData'
import {
  buildProcessTiles,
  countProcessRowsByTab,
  filterProcessRowsByTab,
  processTabLoading,
  useSpecV04Sources
} from '../../workplace/useSpecV04Data'
import { isDeadProcessSource, parseTaskDueDate } from '../../workplace/tileFilters'
import { GridFilterBar, toFilterOptions, uniqueFilterValues } from './gridFilters'
import { buildProcessesQuickActions } from '../../workplace/specGridQuickActions'
import { applyMeetingDoneToRow, isMeetingRowId } from '../../workplace/meetingCompletion'
import { useMeetingCompletion } from '../../workplace/useMeetingCompletion'
import { formatRunWhen, historySourceLabel, historyStatusLabel, historyStatusTone } from '../../pages/historyDetail'
import { OrchDateRangePicker } from './OrchDateRangePicker'
import { startOfDay, type AdminDateRange } from '../../admin/utils/dateRange'

const DETAIL_TABS = [
  { id: 'general', label: 'Общее' },
  { id: 'tasks', label: 'Задачи' },
  { id: 'reg', label: 'Регламент' },
  { id: 'files', label: 'Файлы' },
  { id: 'history', label: 'История' }
] as const

type DetailTabId = (typeof DETAIL_TABS)[number]['id']

const PROCESS_TABS = [
  { id: 'all', label: 'Все процессы' },
  { id: 'reg', label: 'Регламентные' },
  { id: 'onec', label: 'Задачи из 1С' },
  { id: 'proj', label: 'Проекты' },
  { id: 'mail', label: 'Письма' },
  { id: 'meet', label: 'Совещания' }
]

function processRowDate(row: SpecProcessRow): Date | null {
  return parseTaskDueDate(row.deadline)
}

function inDateRange(stamp: Date | null, range: AdminDateRange): boolean {
  if (!stamp) return true
  const day = startOfDay(stamp).getTime()
  return day >= startOfDay(range.start).getTime() && day <= startOfDay(range.end).getTime()
}

function rangeFromRows(rows: SpecProcessRow[]): AdminDateRange {
  const today = startOfDay(new Date())
  let min = today.getTime()
  let max = today.getTime()
  let found = false
  for (const row of rows) {
    const due = processRowDate(row)
    if (!due) continue
    const t = startOfDay(due).getTime()
    if (!found) {
      min = t
      max = t
      found = true
      continue
    }
    if (t < min) min = t
    if (t > max) max = t
  }
  return { start: new Date(min), end: new Date(max) }
}

function ProcessDetail({
  row,
  onOpen,
  onOpenRun,
  meetingDone,
  onToggleMeetingDone
}: {
  row: SpecProcessRow
  onOpen?: (workflowId: string, title: string) => void
  onOpenRun?: (workflowId: string, title: string, runId?: string) => void
  meetingDone?: boolean
  onToggleMeetingDone?: () => void
}): React.JSX.Element {
  const openId =
    row.id.startsWith('erp:') || row.id.startsWith('mail:') || row.id.startsWith('meet:') || row.id.startsWith('proj:')
      ? ''
      : row.id
  const [detailTab, setDetailTab] = useState<DetailTabId>('general')
  const [historyRuns, setHistoryRuns] = useState<AgentRunHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')

  useEffect(() => {
    setDetailTab('general')
    setHistoryRuns([])
    setHistoryLoading(false)
    setHistoryError('')
  }, [row.id])

  useEffect(() => {
    if (detailTab !== 'history') return
    if (!openId) {
      setHistoryRuns([])
      setHistoryError('История запусков доступна только для агентов Constructor.')
      return
    }
    let alive = true
    setHistoryLoading(true)
    setHistoryError('')
    void api
      .listAgentRuns(openId)
      .then((runs) => {
        if (!alive) return
        setHistoryRuns(runs)
      })
      .catch((err) => {
        if (!alive) return
        setHistoryRuns([])
        setHistoryError(err instanceof Error ? err.message : 'Не удалось загрузить историю запусков')
      })
      .finally(() => {
        if (alive) setHistoryLoading(false)
      })
    return () => {
      alive = false
    }
  }, [detailTab, openId])

  return (
    <div className="spec-detail-card">
      <header className="spec-detail-head">
        <div>
          <h2>{row.name}</h2>
          <span className="wp-code">{row.code}</span>
        </div>
        <button type="button" className="spec-detail-menu" aria-label="Действия">
          ⋯
        </button>
      </header>
      <div className="spec-detail-tabs">
        {DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={detailTab === tab.id ? 'active' : ''}
            onClick={() => setDetailTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {detailTab === 'general' ? (
        <>
          <dl className="spec-detail-meta">
            <div>
              <dt>Тип процесса</dt>
              <dd>{row.type}</dd>
            </div>
            <div>
              <dt>Источник</dt>
              <dd>{row.source}</dd>
            </div>
            <div>
              <dt>Проект</dt>
              <dd>{row.project}</dd>
            </div>
            <div>
              <dt>Моя задача сегодня</dt>
              <dd>{row.taskToday}</dd>
            </div>
            <div>
              <dt>Срок</dt>
              <dd className={row.deadlineUrgent ? 'spec-deadline-urgent' : undefined}>{row.deadline}</dd>
            </div>
          </dl>
          <SpecProgress value={row.progress} />
        </>
      ) : null}
      {detailTab === 'tasks' ? (
        <div className="spec-detail-pane">
          <ul className="spec-detail-list">
            <li>{row.taskToday}</li>
          </ul>
        </div>
      ) : null}
      {detailTab === 'reg' ? (
        <div className="spec-detail-pane">
          <p className="spec-v04-muted">Регламент для «{row.name}».</p>
        </div>
      ) : null}
      {detailTab === 'files' ? (
        <div className="spec-detail-pane">
          <p className="spec-v04-muted">Файлы — в паспорте агента Constructor.</p>
        </div>
      ) : null}
      {detailTab === 'history' ? (
        <div className="spec-detail-pane">
          <div className="spec-detail-pane-head">
            <p className="spec-v04-muted">История запусков агента.</p>
            {openId && onOpenRun ? (
              <button type="button" className="btn-ghost" onClick={() => onOpenRun(openId, row.name)}>
                Открыть страницу истории
              </button>
            ) : null}
          </div>
          {historyLoading ? <p className="spec-v04-muted">Загружаю историю…</p> : null}
          {!historyLoading && historyError ? <div className="feed-system error">{historyError}</div> : null}
          {!historyLoading && !historyError && !historyRuns.length ? (
            <p className="spec-v04-muted">Пока нет запусков для этого процесса.</p>
          ) : null}
          {!historyLoading && !historyError && historyRuns.length > 0 ? (
            <div className="history-list">
              {historyRuns.map((run) => (
                <div key={run.runId} className="history-row">
                  <div>
                    <div className={`history-status is-${historyStatusTone(run.status)}`}>
                      {historyStatusLabel(run.status)}
                    </div>
                    <div className="history-when">
                      {formatRunWhen(run.startedAt)}
                      {run.source ? ` · ${historySourceLabel(run)}` : ''}
                    </div>
                    {run.triggerReason ? <div className="history-summary">{run.triggerReason}</div> : null}
                  </div>
                  {onOpenRun ? (
                    <button type="button" className="btn-ghost" onClick={() => onOpenRun(openId || row.id, row.name, run.runId)}>
                      Открыть
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <footer className="spec-detail-actions">
        {isMeetingRowId(row.id) && onToggleMeetingDone ? (
          <button
            type="button"
            className={meetingDone ? 'spec-btn-outline spec-btn-outline-block' : 'spec-btn-launch spec-btn-launch-block'}
            onClick={onToggleMeetingDone}
          >
            {meetingDone ? 'Снять отметку выполнения' : 'Отметить выполненным'}
          </button>
        ) : null}
        {openId ? (
          <>
            <button type="button" className="spec-btn-outline spec-btn-outline-block" onClick={() => onOpen?.(openId, row.name)}>
              Открыть процесс
            </button>
            <button type="button" className="spec-btn-launch spec-btn-launch-block" onClick={() => onOpen?.(openId, row.name)}>
              <span>Запустить исполнение</span>
            </button>
          </>
        ) : isMeetingRowId(row.id) ? null : (
          <p className="spec-v04-muted">Открытие в Constructor — для регламентных агентов.</p>
        )}
      </footer>
    </div>
  )
}

export function ProcessesGridTab({
  user,
  onOpen,
  onOpenRun,
  navProcessTab
}: {
  user: UserProfile
  onOpen: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  navProcessTab?: string | null
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const meetingCompletion = useMeetingCompletion()
  const [tab, setTab] = useState(navProcessTab || 'all')
  const [query, setQuery] = useState('')
  const [barType, setBarType] = useState('')
  const [barSource, setBarSource] = useState('')
  const [barProject, setBarProject] = useState('')
  const [dateRange, setDateRange] = useState<AdminDateRange>(() => rangeFromRows([]))
  const [dateRangeTouched, setDateRangeTouched] = useState(false)
  useEffect(() => {
    if (navProcessTab) setTab(navProcessTab)
  }, [navProcessTab])
  const [rowMenuId, setRowMenuId] = useState('')
  const allRows = data.allProcessRows
  useEffect(() => {
    if (dateRangeTouched || !allRows.length) return
    setDateRange(rangeFromRows(allRows))
  }, [allRows, dateRangeTouched])
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return filterProcessRowsByTab(allRows, tab).filter((row) => {
      if (barType && row.type !== barType) return false
      if (barSource && row.source !== barSource) return false
      if (barProject && row.project !== barProject) return false
      if (!inDateRange(processRowDate(row), dateRange)) return false
      if (q && !`${row.name} ${row.code} ${row.type} ${row.source} ${row.project}`.toLowerCase().includes(q)) {
        return false
      }
      return true
    })
  }, [allRows, tab, query, barType, barSource, barProject, dateRange])
  const displayRows = useMemo(
    () =>
      rows.map((row) =>
        isMeetingRowId(row.id) && meetingCompletion.isDone(row.id)
          ? applyMeetingDoneToRow(row, true)
          : row
      ),
    [rows, meetingCompletion.revision, meetingCompletion.isDone]
  )
  const tabCounts = useMemo(() => countProcessRowsByTab(allRows), [allRows])
  const [selectedId, setSelectedId] = useState('')
  const effectiveId = selectedId || displayRows[0]?.id || ''
  const selected = displayRows.find((item) => item.id === effectiveId)

  const tabs = useMemo(
    () =>
      PROCESS_TABS.map((item) => ({
        ...item,
        count: tabCounts[item.id] ?? 0
      })),
    [tabCounts]
  )

  const tableBusy = data.tableLoading && tab === 'reg' && !rows.length
  const tableEmpty = !tableBusy && !rows.length

  const quickActions = useMemo(
    () =>
      buildProcessesQuickActions({}).map((action) => ({
        id: action.id,
        label: action.label,
        tone: action.tone,
        icon: action.icon,
        onClick: () => void action.run()
      })),
    []
  )

  const chromeTiles = useMemo(
    () =>
      summaryTilesAsChrome(buildProcessTiles(data), tab === 'all' ? null : tab, (id) => {
        if (isDeadProcessSource(data, id)) return
        setTab((current) => (id === current ? 'all' : id))
      }),
    [data, tab]
  )

  return (
    <StandardTabChrome
      tabId="processes"
      userId={user.id || ''}
      defaults={DEFAULT_PROCESS_LAYOUT}
      chromeTiles={chromeTiles}
      widgets={{
        filters: (
        <GridFilterBar
          search={{ value: query, onChange: setQuery, placeholder: 'Поиск…' }}
          selects={[
            {
              id: 'type',
              value: barType,
              emptyLabel: 'Все типы',
              onChange: setBarType,
              options: toFilterOptions(uniqueFilterValues(allRows.map((row) => row.type)))
            },
            {
              id: 'source',
              value: barSource,
              emptyLabel: 'Все источники',
              onChange: setBarSource,
              options: toFilterOptions(uniqueFilterValues(allRows.map((row) => row.source)))
            },
            {
              id: 'project',
              value: barProject,
              emptyLabel: 'Все проекты',
              onChange: setBarProject,
              options: toFilterOptions(uniqueFilterValues(allRows.map((row) => row.project)))
            }
          ]}
          onReset={() => {
            setQuery('')
            setBarType('')
            setBarSource('')
            setBarProject('')
            setDateRangeTouched(false)
            setDateRange(rangeFromRows(allRows))
            setTab('all')
          }}
        />
        ),
        main: (
        <div className="orch-process-main">
        <div className="spec-table-toolbar orch-process-tabs">
          <SpecTableTabs tabs={tabs} active={tab} onChange={setTab} />
          <div className="orch-process-tabs-tools">
            <OrchDateRangePicker
              value={dateRange}
              label="Период"
              onChange={(next) => {
                setDateRangeTouched(true)
                setDateRange(next)
              }}
            />
            <select className="wp-select orch-process-tabs-sort" defaultValue="priority">
              <option value="priority">Сортировка: По приоритету</option>
            </select>
          </div>
        </div>
        <div className="spec-v04-table-wrap wp-card">
          <table className="spec-v04-table">
            <thead>
              <tr>
                <th>Процесс</th>
                <th>Тип</th>
                <th>Источник</th>
                <th>Проект</th>
                <th>Моя задача сегодня</th>
                <th>Срок</th>
                <th>Прогресс</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tableBusy ? (
                <tr>
                  <td colSpan={8} className="spec-v04-empty">
                    Загружаем регламентные процессы…
                  </td>
                </tr>
              ) : null}
              {tableEmpty ? (
                <tr>
                  <td colSpan={8} className="spec-v04-empty">
                    {processTabLoading(data, tab) ? 'Подгружаем данные…' : 'Нет процессов в категории.'}
                  </td>
                </tr>
              ) : null}
              {displayRows.map((row) => (
                <tr
                  key={row.id}
                  className={effectiveId === row.id ? 'selected' : ''}
                  onClick={() => setSelectedId(row.id)}
                >
                  <td>
                    <strong>{row.name}</strong>
                    <div className="wp-code">{row.code}</div>
                  </td>
                  <td>
                    <SpecPill tone={row.typeTone}>{row.type}</SpecPill>
                  </td>
                  <td>{row.source}</td>
                  <td>{row.project}</td>
                  <td>{row.taskToday}</td>
                  <td className={row.deadlineUrgent ? 'spec-deadline-urgent' : undefined}>{row.deadline}</td>
                  <td>
                    <SpecProgress value={row.progress} />
                  </td>
                  <td>
                    <div className="spec-row-menu-wrap">
                      <button
                        type="button"
                        className="btn-ghost spec-row-menu"
                        aria-expanded={rowMenuId === row.id}
                        onClick={(event) => {
                          event.stopPropagation()
                          if (isMeetingRowId(row.id)) {
                            setRowMenuId((current) => (current === row.id ? '' : row.id))
                            return
                          }
                          setRowMenuId('')
                          if (
                            !row.id.startsWith('erp:') &&
                            !row.id.startsWith('mail:') &&
                            !row.id.startsWith('proj:')
                          ) {
                            onOpenRun(row.id, row.name)
                          }
                        }}
                      >
                        ⋮
                      </button>
                      {rowMenuId === row.id && isMeetingRowId(row.id) ? (
                        <div className="files-menu spec-row-menu-dropdown">
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation()
                              setRowMenuId('')
                              meetingCompletion.toggle(row.id)
                            }}
                          >
                            {meetingCompletion.isDone(row.id) ? 'Снять отметку' : 'Отметить выполненным'}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
        ),
        side: selected ? (
          <ProcessDetail
            row={selected}
            onOpen={onOpen}
            onOpenRun={onOpenRun}
            meetingDone={isMeetingRowId(selected.id) ? meetingCompletion.isDone(selected.id) : undefined}
            onToggleMeetingDone={
              isMeetingRowId(selected.id) ? () => meetingCompletion.toggle(selected.id) : undefined
            }
          />
        ) : (
          <div className="wp-card spec-v04-muted">Выберите процесс в таблице</div>
        ),
        botB: (
        <SpecPanel title="Быстрые действия" className="orch-quick-actions-panel">
          <SpecQuickActions items={quickActions} layout="row" />
        </SpecPanel>
        )
      }}
    />
  )
}
