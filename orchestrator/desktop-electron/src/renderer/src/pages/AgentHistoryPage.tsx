import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowFileItem } from '../api/types'
import { AgentFeed, buildFeedItems } from '../components/agentfeed'
import { MarkdownBody } from '../components/agentfeed/MarkdownBody'
import { MiniCalendar, meetingsFromResult, type MiniMeeting } from '../components/agentfeed/MiniCalendar'
import { useRuns } from '../store/runs'
import { isInFlightRunStatus, isLiveRunState } from '../store/liveRun'
import { cleanRunResult } from '../utils/cleanRunResult'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import {
  formatRunTime,
  formatRunWhen,
  groupRunsByDay,
  HISTORY_STATUS_LABELS,
  historyRunStatus
} from '../utils/historyDisplay'
import { filesForHistoryRun } from '../utils/historyFiles'
import { formatSize } from './filesGrouping'

interface AgentHistoryPageProps {
  workflowId: string
  title: string
  initialRunId?: string
  onBack: () => void
  onOpenLive?: () => void
}

export function AgentHistoryPage({
  workflowId,
  title,
  initialRunId,
  onBack,
  onOpenLive
}: AgentHistoryPageProps): React.JSX.Element {
  const liveStore = useRuns()
  const live = liveStore.entries[workflowId]
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [selected, setSelected] = useState<string>(initialRunId || '')
  const [answer, setAnswer] = useState('')
  const [events, setEvents] = useState<AgentRunnerEvent[]>([])
  const [pane, setPane] = useState<'result' | 'events'>('result')
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    void api
      .listAgentRuns(workflowId)
      .then((list) => {
        if (!alive) return
        setRuns(list)
        if (list.length) {
          const preferred =
            (initialRunId && list.some((item) => item.runId === initialRunId) && initialRunId) ||
            list[0].runId
          setSelected(preferred)
        }
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось загрузить историю')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [workflowId])

  useEffect(() => {
    if (!selected) {
      setAnswer('')
      setEvents([])
      setFiles([])
      return
    }
    let alive = true
    setDetailLoading(true)
    setPane('result')
    void Promise.all([
      api.getAgentRunDetail(workflowId, selected),
      api.listWorkflowFiles(workflowId)
    ])
      .then(([detail, allFiles]) => {
        if (!alive) return
        const text = (detail.item.answer || detail.item.summary || '').trim()
        setAnswer(text)
        setEvents(detail.events)
        setFiles(filesForHistoryRun(allFiles, selected, text, detail.events))
      })
      .catch(() => {
        if (!alive) return
        setAnswer('')
        setEvents([])
        setFiles([])
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [workflowId, selected])

  const selectedRun = runs.find((item) => item.runId === selected)
  const groups = useMemo(() => groupRunsByDay(runs), [runs])
  const cleaned = useMemo(
    () => cleanRunResult({ answer, events, status: selectedRun ? historyRunStatus(selectedRun) : '' }),
    [answer, events, selectedRun]
  )
  const feedItems = useMemo(() => buildFeedItems(events), [events])
  const planMeetings = useMemo<MiniMeeting[]>(() => {
    let found: MiniMeeting[] = []
    for (const ev of events) {
      const type = String(ev.type || '').toLowerCase()
      if (type !== 'tool_call' && type !== 'tool_result') continue
      if (String((ev as { tool?: string }).tool || '') !== 'calendar.show_meetings') continue
      const parsed = meetingsFromResult((ev as { result?: unknown }).result)
      if (parsed.length) found = parsed
    }
    return found
  }, [events])
  const showLiveFeed = Boolean(
    live &&
      isLiveRunState(live.state) &&
      (isInFlightRunStatus(selectedRun?.status || '') ||
        !selected ||
        !live.backendRunId ||
        live.backendRunId === selected)
  )

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>История запусков</h2>
          <p>{title}</p>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-side" style={{ width: 300 }}>
          {loading && <div className="agent-side-card">Загрузка…</div>}
          {error && <div className="feed-system error">{error}</div>}
          {!loading && !runs.length && !error && (
            <div className="agent-side-card">
              <p>Пока нет запусков этого агента.</p>
            </div>
          )}
          {groups.map((group) => (
            <div key={group.key} className="history-day">
              <div className="history-day-label">{group.label}</div>
              {group.items.map((run) => (
                <button
                  key={run.runId}
                  className={
                    selected === run.runId ? 'agent-side-card history-run active' : 'agent-side-card history-run'
                  }
                  onClick={() => setSelected(run.runId)}
                  style={{ textAlign: 'left', cursor: 'pointer', width: '100%' }}
                >
                  <div className="history-status">
                    {HISTORY_STATUS_LABELS[historyRunStatus(run)] || 'Отменён'}
                  </div>
                  <div className="history-summary" style={{ fontSize: 12 }}>
                    {formatRunTime(run.startedAt) || formatRunWhen(run.startedAt)}
                  </div>
                </button>
              ))}
            </div>
          ))}
        </div>

        <div className="agent-studio-main">
          {showLiveFeed && live ? (
            <div className="wf-feed-wrap">
              {onOpenLive && (
                <div className="history-live-bar">
                  <span>Агент выполняется — ход событий обновляется вживую.</span>
                  <button className="btn-primary" type="button" onClick={onOpenLive}>
                    Перейти
                  </button>
                </div>
              )}
              <AgentFeed
                items={live.state.items}
                status={live.state.status}
                running={live.state.running}
                pendingQuestion={live.state.pendingQuestion}
                pendingHitl={live.state.pendingHitl}
                emptyHint="Агент уже работает. Шаги появятся здесь по мере выполнения."
                allowQuestionFiles
                onAnswer={(requestId, value, filePaths) =>
                  liveStore.answer(workflowId, requestId, value, filePaths)
                }
                onHitl={(requestId, approved) =>
                  liveStore.respondHitl(workflowId, requestId, approved)
                }
                onSkip={() => liveStore.skip(workflowId)}
              />
            </div>
          ) : detailLoading ? (
            <div className="wf-files-empty">Загружаем результат…</div>
          ) : !selected ? (
            <div className="wf-files-empty">Выберите запуск, чтобы увидеть результат.</div>
          ) : (
            <div className="history-result">
              {pane === 'events' ? (
                <section className="wf-result-card">
                  <div className="wf-result-head">
                    <div className="wf-result-title">Ход работы</div>
                    <button
                      type="button"
                      className="btn-ghost wf-result-action"
                      onClick={() => setPane('result')}
                    >
                      К результату
                    </button>
                  </div>
                  <div className="wf-feed-wrap history-feed">
                    <AgentFeed
                      items={feedItems}
                      status={selectedRun?.status || ''}
                      running={false}
                      pendingQuestion={null}
                      pendingHitl={null}
                      emptyHint="Нет записей хода работы для этого запуска."
                      onAnswer={() => undefined}
                      onHitl={() => undefined}
                      onSkip={() => undefined}
                    />
                  </div>
                </section>
              ) : (
                <section className="wf-result-card">
                  <div className="wf-result-head">
                    <div className="wf-result-title">Результат</div>
                    <button
                      type="button"
                      className="btn-ghost wf-result-action"
                      onClick={() => setPane('events')}
                    >
                      Ход работы
                    </button>
                  </div>
                  {planMeetings.length > 0 && (
                    <div className="wf-result-calendar">
                      <MiniCalendar meetings={planMeetings} />
                    </div>
                  )}
                  {cleaned.text ? (
                    <MarkdownBody text={cleaned.text} />
                  ) : planMeetings.length > 0 ? null : (
                    <p>{files.length ? 'Текста результата нет.' : cleaned.emptyHint || 'Нет текста результата'}</p>
                  )}
                </section>
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
          )}
        </div>
      </div>
    </div>
  )
}
