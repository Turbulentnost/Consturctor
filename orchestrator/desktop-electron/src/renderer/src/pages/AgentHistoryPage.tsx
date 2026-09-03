import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowFileItem } from '../api/types'
import { AgentFeed, buildFeedItems } from '../components/agentfeed'
import { MarkdownBody } from '../components/agentfeed/MarkdownBody'
import { MiniCalendar, meetingsFromEvents } from '../components/agentfeed/MiniCalendar'
import { useRuns } from '../store/runs'
import { isInFlightRunStatus, isLiveRunState } from '../store/liveRun'
import { cleanRunResult } from '../utils/cleanRunResult'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { durationLabel } from '../workplace/runTiming'
import { formatSize } from './filesGrouping'
import {
  eventsForHistoryRun,
  filesForHistoryRun,
  formatRunWhen,
  historyResultText,
  historySourceLabel,
  historyStatusLabel,
  historyStatusTone
} from './historyDetail'

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
    void Promise.all([api.getAgentRunDetail(workflowId, selected), api.listWorkflowFiles(workflowId)])
      .then(([detail, allFiles]) => {
        if (!alive) return
        const stored = (detail.item.answer || detail.item.summary || '').trim()
        const text = historyResultText(stored, detail.events)
        setAnswer(text)
        setEvents(detail.events)
        setFiles(filesForHistoryRun(allFiles, selected, text, detail.events))
        setRuns((current) =>
          current.map((item) => (item.runId === detail.item.runId ? { ...item, ...detail.item } : item))
        )
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
  const feedEvents = useMemo(
    () => eventsForHistoryRun(events, selectedRun, answer),
    [events, selectedRun, answer]
  )
  const feedItems = useMemo(() => buildFeedItems(feedEvents), [feedEvents])
  const cleaned = useMemo(
    () => cleanRunResult({ answer, events, status: selectedRun?.status || '' }),
    [answer, events, selectedRun]
  )
  const planMeetings = useMemo(() => meetingsFromEvents(events), [events])
  const showLiveFeed = Boolean(
    live &&
      isLiveRunState(live.state) &&
      (isInFlightRunStatus(selectedRun?.status || '') ||
        !selected ||
        !live.backendRunId ||
        live.backendRunId === selected)
  )
  const sourceLabel = selectedRun ? historySourceLabel(selectedRun) : ''
  const agentTime = selectedRun ? durationLabel(selectedRun.agentWorkMs || 0) : ''
  const humanTime = selectedRun ? durationLabel(selectedRun.humanWaitMs || 0) : ''

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
          {runs.map((run) => (
            <button
              key={run.runId}
              className={
                selected === run.runId ? 'agent-side-card history-run active' : 'agent-side-card history-run'
              }
              onClick={() => setSelected(run.runId)}
              style={{ textAlign: 'left', cursor: 'pointer', width: '100%' }}
            >
              <div className={`history-status is-${historyStatusTone(run.status)}`}>
                {historyStatusLabel(run.status)}
              </div>
              <div className="history-summary" style={{ fontSize: 12 }}>
                {formatRunWhen(run.startedAt)}
                {run.source ? ` · ${historySourceLabel(run)}` : ''}
              </div>
              {run.triggerReason ? (
                <div className="history-run-reason">{run.triggerReason}</div>
              ) : null}
            </button>
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
                onHitl={(requestId, approved) => liveStore.respondHitl(workflowId, requestId, approved)}
                onSkip={() => liveStore.skip(workflowId)}
              />
            </div>
          ) : detailLoading ? (
            <div className="wf-files-empty">Загружаем результат…</div>
          ) : !selected ? (
            <div className="wf-files-empty">Выберите запуск, чтобы увидеть результат.</div>
          ) : (
            <div className="history-result">
              <div className="files-tabs history-result-tabs">
                <button
                  className={pane === 'result' ? 'active' : ''}
                  type="button"
                  onClick={() => setPane('result')}
                >
                  Результат
                </button>
                <button
                  className={pane === 'events' ? 'active' : ''}
                  type="button"
                  onClick={() => setPane('events')}
                >
                  Ход работы
                </button>
              </div>
              {selectedRun ? (
                <div className="history-run-meta">
                  <span>
                    {historyStatusLabel(selectedRun.status)}
                    {selectedRun.startedAt ? ` · ${formatRunWhen(selectedRun.startedAt)}` : ''}
                  </span>
                  <span>{sourceLabel}</span>
                  {selectedRun.finishedAt ? <span>конец: {formatRunWhen(selectedRun.finishedAt)}</span> : null}
                  {selectedRun.agentWorkMs > 0 || selectedRun.openSegment === 'agent' ? (
                    <span>работа агента: {agentTime}</span>
                  ) : null}
                  {selectedRun.humanWaitMs > 0 || selectedRun.openSegment === 'human' ? (
                    <span>ответ человека: {humanTime}</span>
                  ) : null}
                </div>
              ) : null}
              {pane === 'events' ? (
                <section className="wf-result-card">
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
