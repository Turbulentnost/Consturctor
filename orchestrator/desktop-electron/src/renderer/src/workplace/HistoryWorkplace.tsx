import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  AgentRunHistoryItem,
  AgentRunnerEvent,
  WorkflowBoard,
  WorkflowFileItem
} from '../api/types'
import { MarkdownBody } from '../components/agentfeed/MarkdownBody'
import { MiniCalendar, meetingsForHistoryRun, meetingsFromFeed } from '../components/agentfeed/MiniCalendar'
import { historyResultText } from '../pages/historyDetail'
import { useRuns } from '../store/runs'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { cleanRunResult } from '../utils/cleanRunResult'
import {
  formatRunTime,
  formatRunWhen,
  groupRunsByDay,
  HISTORY_STATUS_LABELS,
  historyRunStatus,
  statusPillClass
} from '../utils/historyDisplay'
import { filesForHistoryRun } from '../utils/historyFiles'
import { formatSize } from '../pages/filesGrouping'
import { FilterBar } from './FilterBar'

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

type StatusFilter = '' | 'ok' | 'error' | 'canceled' | 'started'

export function HistoryWorkplace({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [agentId, setAgentId] = useState('')
  const [status, setStatus] = useState<StatusFilter>('')
  const [selected, setSelected] = useState('')
  const [answer, setAnswer] = useState('')
  const [events, setEvents] = useState<AgentRunnerEvent[]>([])
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const [detailMeetings, setDetailMeetings] = useState<AgentRunHistoryItem['calendarMeetings']>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const liveStore = useRuns()
  const reloadRef = useRef<() => Promise<void>>(async () => undefined)

  const agents = useMemo(
    () => board.agents.filter((item) => item.kind === 'workflow'),
    [board.agents]
  )

  function titleOf(workflowId: string): string {
    return (
      titles[workflowId] ||
      agents.find((item) => item.id === workflowId)?.title ||
      'ИИ-агент'
    )
  }

  async function reload(): Promise<void> {
    try {
      const [nextBoard, workflows] = await Promise.all([
        api.getWorkflowBoard(),
        api.listWorkflows().catch(() => [])
      ])
      setBoard(nextBoard)
      const nextTitles: Record<string, string> = {}
      for (const agent of nextBoard.agents) {
        if (agent.id && (agent.kind === 'workflow' || agent.kind === 'draft')) {
          nextTitles[agent.id] = agent.title || 'ИИ-агент'
        }
      }
      for (const item of workflows) {
        if (!item.id) continue
        if ((item.phase || '').toLowerCase() === 'deleted') continue
        if (!nextTitles[item.id]) nextTitles[item.id] = item.title || 'ИИ-агент'
      }
      setTitles(nextTitles)
      const lists = await Promise.all(
        Object.keys(nextTitles).map((id) =>
          api.listAgentRuns(id).catch(() => [] as AgentRunHistoryItem[])
        )
      )
      const items = lists
        .flat()
        .filter((item) => item.runId)
        .sort((left, right) => (right.startedAt || '').localeCompare(left.startedAt || ''))
      setRuns(items)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Нет связи с сервером')
    } finally {
      setLoading(false)
    }
  }
  reloadRef.current = reload

  useEffect(() => {
    void reload()
    const unsubscribe = window.api.onBoardUpdated?.(() => {
      void reloadRef.current()
    })
    return () => unsubscribe?.()
  }, [])

  const agentOptions = useMemo(() => {
    const seen = new Set<string>()
    const options: { id: string; title: string }[] = []
    for (const run of runs) {
      if (seen.has(run.workflowId)) continue
      seen.add(run.workflowId)
      options.push({ id: run.workflowId, title: titleOf(run.workflowId) })
    }
    return options.sort((left, right) => left.title.localeCompare(right.title, 'ru'))
  }, [runs, agents, titles])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return runs.filter((item) => {
      if (agentId && item.workflowId !== agentId) return false
      const key = historyRunStatus(item)
      if (status === 'canceled' && key !== 'canceled' && key !== 'cancelled') return false
      if (status === 'started' && key !== 'started' && key !== 'running') return false
      if (status === 'ok' && key !== 'ok') return false
      if (status === 'error' && key !== 'error') return false
      if (!q) return true
      const title = titleOf(item.workflowId).toLowerCase()
      return title.includes(q)
    })
  }, [runs, query, agentId, status, agents, titles])

  const groups = useMemo(() => groupRunsByDay(visible), [visible])

  useEffect(() => {
    if (!visible.length) {
      setSelected('')
      return
    }
    if (!visible.some((item) => item.runId === selected)) {
      setSelected(visible[0].runId)
    }
  }, [visible, selected])

  useEffect(() => {
    if (!selected) {
      setAnswer('')
      setEvents([])
      setFiles([])
      setDetailMeetings([])
      return
    }
    const run = runs.find((item) => item.runId === selected)
    if (!run) {
      setAnswer('')
      setEvents([])
      setFiles([])
      setDetailMeetings([])
      return
    }
    let alive = true
    setDetailLoading(true)
    void Promise.all([
      api.getAgentRunDetail(run.workflowId, selected),
      api.listWorkflowFiles(run.workflowId),
      api.getCalendarOverlay(run.workflowId)
    ])
      .then(([detail, allFiles, overlay]) => {
        if (!alive) return
        const stored = (detail.item.answer || detail.item.summary || '').trim()
        const text = historyResultText(stored, detail.events)
        setAnswer(text)
        setEvents(detail.events)
        setFiles(filesForHistoryRun(allFiles, selected, text, detail.events))
        setDetailMeetings(detail.item.calendarMeetings?.length ? detail.item.calendarMeetings : overlay)
      })
      .catch(() => {
        if (!alive) return
        setAnswer('')
        setEvents([])
        setFiles([])
        setDetailMeetings([])
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [selected, runs])

  const selectedRun = runs.find((item) => item.runId === selected)
  const selectedStatus = selectedRun ? historyRunStatus(selectedRun) : ''
  const cleaned = useMemo(
    () => cleanRunResult({ answer, events, status: selectedStatus }),
    [answer, events, selectedStatus]
  )
  const live = selectedRun ? liveStore.entries[selectedRun.workflowId] : undefined
  const planMeetings = useMemo(() => {
    const stored = meetingsForHistoryRun(events, detailMeetings)
    if (stored.length) return stored
    if (live?.backendRunId && live.backendRunId === selected) {
      return meetingsFromFeed(live.state.items)
    }
    return []
  }, [events, detailMeetings, live, selected])

  return (
    <div className="wp-page wp-history">
      <div className="wp-head">
        <div>
          <h1 className="page-title">История</h1>
          <div className="wp-sub">
            Запуски по дням. Справа только результат: план совещаний и итог, без хода работы агента.
          </div>
        </div>
        <span className="orch-badge">{loading ? 'загрузка' : `${visible.length} прогонов`}</span>
        <span className="wp-count">{visible.length}</span>
      </div>
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}

      <FilterBar
        query={query}
        onQuery={setQuery}
        queryPlaceholder="Найти агента"
        chips={[
          { id: 'q', label: query ? `поиск: ${query}` : '', onClear: () => setQuery('') },
          {
            id: 'a',
            label: agentId ? `агент: ${titleOf(agentId)}` : '',
            onClear: () => setAgentId('')
          },
          {
            id: 's',
            label: status ? `статус: ${HISTORY_STATUS_LABELS[status] || status}` : '',
            onClear: () => setStatus('')
          }
        ]}
        onReset={() => {
          setQuery('')
          setAgentId('')
          setStatus('')
        }}
      >
        <select className="wp-select" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="">Агент: все</option>
          {agentOptions.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title}
            </option>
          ))}
        </select>
        <select
          className="wp-select"
          value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilter)}
        >
          <option value="">Статус: все</option>
          <option value="ok">Успешно</option>
          <option value="error">Ошибка</option>
          <option value="canceled">Отменён</option>
          <option value="started">Выполняется</option>
        </select>
      </FilterBar>

      <div className="wp-history-layout">
        <aside className="wp-history-runs">
          <div className="wp-history-runs-scroll">
            {loading && !runs.length ? <p className="wp-history-empty">Загружаем прогоны с сервера…</p> : null}
            {!loading && !visible.length ? (
              <p className="wp-history-empty">
                {runs.length ? 'Нет запусков по текущему фильтру.' : 'Прогонов ещё не было.'}
              </p>
            ) : null}
            {groups.map((group) => (
              <div key={group.key} className="wp-history-day">
                <div className="wp-history-day-label">{group.label}</div>
                {group.items.map((item) => {
                  const key = historyRunStatus(item)
                  return (
                    <button
                      key={item.runId}
                      className={
                        selected === item.runId ? 'wp-history-run active' : 'wp-history-run'
                      }
                      type="button"
                      onClick={() => setSelected(item.runId)}
                    >
                      <div className="wp-history-run-top">
                        <span className="wp-history-run-time">{formatRunTime(item.startedAt) || '—'}</span>
                        <span className={`wp-pill ${statusPillClass(key)}`}>
                          {HISTORY_STATUS_LABELS[key] || 'Отменён'}
                        </span>
                      </div>
                      <span className="wp-history-run-title" title={titleOf(item.workflowId)}>
                        {titleOf(item.workflowId)}
                      </span>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </aside>

        <section className="wp-history-result">
          {!selected ? (
            <div className="wp-history-result-empty">Выберите запуск слева, чтобы увидеть результат.</div>
          ) : detailLoading ? (
            <div className="wp-history-result-empty">Загружаем результат…</div>
          ) : (
            <>
              <div className="wp-history-result-head">
                <div>
                  <div className="wp-history-result-kicker">Результат</div>
                  <h2>{selectedRun ? titleOf(selectedRun.workflowId) : 'Результат'}</h2>
                  <p>
                    {selectedRun?.startedAt ? formatRunWhen(selectedRun.startedAt) : ''}
                    {selectedStatus
                      ? ` · ${HISTORY_STATUS_LABELS[selectedStatus] || selectedStatus}`
                      : ''}
                  </p>
                </div>
                {selectedRun ? (
                  <button
                    className="btn-ghost"
                    type="button"
                    onClick={() => onOpenRun(selectedRun.workflowId, titleOf(selectedRun.workflowId), selectedRun.runId)}
                  >
                    Открыть запуск
                  </button>
                ) : null}
              </div>
              <div className="wp-history-result-body">
                {planMeetings.length > 0 && (
                  <div className="wf-result-calendar">
                    <MiniCalendar meetings={planMeetings} />
                  </div>
                )}
                {cleaned.text ? (
                  <MarkdownBody text={cleaned.text} />
                ) : planMeetings.length > 0 ? null : (
                  <p className="wp-history-empty">{files.length ? 'Текста результата нет.' : cleaned.emptyHint}</p>
                )}
                <section className="wf-file-section">
                  <h4>Файлы агента</h4>
                  {files.length === 0 ? (
                    <div className="wf-files-empty">Агент не приложил файлы к этому запуску.</div>
                  ) : (
                    <ul className="wf-files">
                      {files.map((file) => (
                        <li key={file.id || file.name}>
                          <button
                            className="wf-file-card history-file-btn"
                            type="button"
                            onClick={() => {
                              if (file.downloadUrl) void api.download(file.downloadUrl, file.name)
                            }}
                          >
                            <img className="files-type-icon" src={fileTypeIconSrc(file.name)} alt="" />
                            <div className="wf-file-copy">
                              <span className="wf-file-name" title={file.name}>
                                {file.name}
                              </span>
                              {formatSize(file.sizeBytes) ? (
                                <span className="wf-file-meta">{formatSize(file.sizeBytes)}</span>
                              ) : null}
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
