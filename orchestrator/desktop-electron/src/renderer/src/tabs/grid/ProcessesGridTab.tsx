import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { AgentRunHistoryItem, UserProfile } from '../../api/types'
import {
  OrchSlotBotA,
  OrchSlotBotB,
  OrchSlotBotC,
  OrchSlotFilters,
  OrchSlotMain,
  OrchSlotMetrics,
  OrchSlotSide
} from '../../layout/GridSlots'
import {
  SpecAskOrchestratorBlock,
  SpecFilters,
  SpecPanel,
  SpecPill,
  SpecProgress,
  SpecQuickActions,
  SpecSummaryTiles,
  SpecTableTabs
} from '../../workplace/specV04Components'
import { ASK_CHIPS, type SpecProcessRow } from '../../workplace/specV04DemoData'
import {
  buildProcessTiles,
  countProcessRowsByTab,
  filterProcessRowsByTab,
  useSpecV04Sources
} from '../../workplace/useSpecV04Data'
import { SpecIconCalendar, SpecIconSearch } from '../../workplace/specV04Icons'
import { buildProcessesQuickActions } from '../../workplace/specGridQuickActions'
import { applyMeetingDoneToRow, isMeetingRowId } from '../../workplace/meetingCompletion'
import { useMeetingCompletion } from '../../workplace/useMeetingCompletion'
import { formatRunWhen, historySourceLabel, historyStatusLabel, historyStatusTone } from '../../pages/historyDetail'

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
  onAskOrchestrator
}: {
  user: UserProfile
  onOpen: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  onAskOrchestrator?: (message: string, context: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const meetingCompletion = useMeetingCompletion()
  const [tab, setTab] = useState('all')
  const [rowMenuId, setRowMenuId] = useState('')
  const allRows = data.allProcessRows
  const rows = useMemo(() => filterProcessRowsByTab(allRows, tab), [allRows, tab])
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

  const ask = (message: string): void => {
    onAskOrchestrator?.(message, 'Вкладка «Процессы»')
  }

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

  return (
    <>
      <OrchSlotMetrics>
        <SpecSummaryTiles tiles={buildProcessTiles(data)} />
      </OrchSlotMetrics>
      <OrchSlotFilters>
        <SpecFilters layout="row">
          <select className="wp-select spec-filter-field" defaultValue="">
            <option value="">Все типы</option>
            <option value="reg">Регламент</option>
            <option value="onec">Задача из 1С</option>
            <option value="proj">Проект</option>
            <option value="mail">Письмо</option>
            <option value="meet">Совещание</option>
          </select>
          <select className="wp-select spec-filter-field" defaultValue="">
            <option value="">Все статусы</option>
          </select>
          <select className="wp-select spec-filter-field" defaultValue="">
            <option value="">Все источники</option>
          </select>
          <select className="wp-select spec-filter-field" defaultValue="">
            <option value="">Все проекты</option>
            {data.projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <label className="spec-filter-input spec-filter-search">
            <SpecIconSearch />
            <input className="wp-search" type="search" placeholder="Поиск…" />
          </label>
          <label className="spec-filter-input spec-filter-period">
            <SpecIconCalendar />
            <select className="wp-select" defaultValue="week">
              <option value="week">Период: Неделя</option>
            </select>
          </label>
          <button type="button" className="spec-filter-reset">
            Сбросить фильтры
          </button>
        </SpecFilters>
      </OrchSlotFilters>
      <OrchSlotMain>
        <div className="spec-table-toolbar">
          <SpecTableTabs tabs={tabs} active={tab} onChange={setTab} />
          <select className="wp-select" defaultValue="priority">
            <option value="priority">Сортировка: По приоритету</option>
          </select>
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
                <th>Статус</th>
                <th>Срок</th>
                <th>Прогресс</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tableBusy ? (
                <tr>
                  <td colSpan={9} className="spec-v04-empty">
                    Загружаем регламентные процессы…
                  </td>
                </tr>
              ) : null}
              {tableEmpty ? (
                <tr>
                  <td colSpan={9} className="spec-v04-empty">
                    {data.sourcesLoading ? 'Подгружаем данные…' : 'Нет процессов в категории.'}
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
                  <td>
                    <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                  </td>
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
      </OrchSlotMain>
      <OrchSlotSide>
        {selected ? (
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
        )}
      </OrchSlotSide>
      <OrchSlotBotA>
        <SpecPanel title="Проекты и проектные задачи">
          {data.projects.length ? (
            <table className="spec-v04-table spec-v04-table-compact">
              <tbody>
                {data.projects.slice(0, 3).map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{p.code}</td>
                    <td>{p.tasks} задач</td>
                    <td>
                      <SpecProgress value={p.progress} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="spec-v04-muted">Портфель TurboProject пуст или недоступен.</p>
          )}
        </SpecPanel>
      </OrchSlotBotA>
      <OrchSlotBotB>
        <SpecPanel title="Быстрые действия">
          <SpecQuickActions items={quickActions} />
        </SpecPanel>
      </OrchSlotBotB>
      <OrchSlotBotC>
        <SpecAskOrchestratorBlock placeholder="Спросить про процессы…" chips={ASK_CHIPS.processes} onSubmit={ask} />
      </OrchSlotBotC>
    </>
  )
}
