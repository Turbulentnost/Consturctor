import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, WorkflowFileItem } from '../api/types'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { formatSize } from './filesGrouping'

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
  const [answer, setAnswer] = useState('')
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
      setAnswer('')
      setFiles([])
      return
    }
    let alive = true
    setDetailLoading(true)
    void Promise.all([
      api.getAgentRunDetail(workflowId, selected),
      api.listWorkflowFiles(workflowId, selected)
    ])
      .then(([detail, allFiles]) => {
        if (!alive) return
        setAnswer((detail.item.answer || detail.item.summary || '').trim())
        setFiles(
          allFiles.filter(
            (file) => file.source === 'agent' && (!file.runId || file.runId === selected)
          )
        )
      })
      .catch(() => {
        if (!alive) return
        setAnswer('')
        setFiles([])
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
            </button>
          ))}
        </div>

        <div className="agent-studio-main">
          {detailLoading ? (
            <div className="wf-files-empty">Загружаем результат…</div>
          ) : !selected ? (
            <div className="wf-files-empty">Выберите запуск, чтобы увидеть результат.</div>
          ) : (
            <div className="history-result">
              <section className="wf-result-card">
                <div className="wf-result-title">Результат</div>
                <p>{answer || 'Нет текста результата'}</p>
              </section>
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
