import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem } from '../api/types'
import { AgentFeed, buildFeedItems, type FeedItem } from '../components/agentfeed'

interface AgentHistoryPageProps {
  workflowId: string
  title: string
  onBack: () => void
}

function formatWhen(value: string): string {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('ru-RU')
  } catch {
    return value
  }
}

const STATUS_LABELS: Record<string, string> = {
  ok: 'Успешно',
  error: 'Ошибка',
  running: 'Выполняется',
  cancelled: 'Отменён'
}

export function AgentHistoryPage({ workflowId, title, onBack }: AgentHistoryPageProps): React.JSX.Element {
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [selected, setSelected] = useState<string>('')
  const [items, setItems] = useState<FeedItem[]>([])
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
        if (list.length) setSelected(list[0].runId)
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
      setItems([])
      return
    }
    let alive = true
    setDetailLoading(true)
    void api
      .getAgentRunDetail(workflowId, selected)
      .then((detail) => {
        if (!alive) return
        setItems(buildFeedItems(detail.events))
      })
      .catch(() => {
        if (alive) setItems([])
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [workflowId, selected])

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
              <div className="history-status">{STATUS_LABELS[run.status] || run.status || 'Запуск'}</div>
              <div className="history-summary" style={{ fontSize: 12 }}>
                {formatWhen(run.startedAt)}
              </div>
              {run.summary && (
                <div className="history-summary" style={{ marginTop: 4 }}>
                  {run.summary.slice(0, 120)}
                </div>
              )}
            </button>
          ))}
        </div>

        <div className="agent-studio-main">
          <AgentFeed
            items={items}
            status=""
            running={detailLoading}
            pendingQuestion={null}
            pendingHitl={null}
            emptyHint={detailLoading ? 'Загружаем ход выполнения…' : 'Выберите запуск, чтобы увидеть ход выполнения.'}
            onAnswer={() => undefined}
            onHitl={() => undefined}
            onSkip={() => undefined}
          />
        </div>
      </div>
    </div>
  )
}
