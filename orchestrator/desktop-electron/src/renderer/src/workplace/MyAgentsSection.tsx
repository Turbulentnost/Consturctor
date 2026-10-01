import { useCallback, useEffect, useMemo, useState } from 'react'
import { FileText, History, MessageSquare, Pause, Play, RefreshCw, Square } from 'lucide-react'
import { api } from '../api/client'
import type { WorkflowListItem } from '../api/types'
import { useRuns } from '../store/runs'
import { isLiveRunState } from '../store/liveRun'
import { isPersonalAgentWorkflowId } from './personalAgent'
import './myAgents.css'

type StatusFilter = 'all' | 'active' | 'paused'

interface MyAgentsSectionProps {
  onOpen: (workflowId: string, title: string) => void
  onPassport: (workflowId: string, title: string) => void
  onHistory: (workflowId: string, title: string) => void
}

function phaseLabel(phase: string): string {
  return phase === 'done' ? 'Опубликован' : 'В разработке'
}

function formatUpdated(value: string | undefined): string {
  if (!value) return ''
  const stamp = new Date(value)
  if (Number.isNaN(stamp.getTime())) return ''
  return stamp.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function MyAgentsSection({ onOpen, onPassport, onHistory }: MyAgentsSectionProps): React.JSX.Element {
  const runs = useRuns()
  const [agents, setAgents] = useState<WorkflowListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StatusFilter>('all')

  const load = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError('')
    try {
      const rows = await api.listWorkflows()
      setAgents(rows.filter((row) => !isPersonalAgentWorkflowId(row.id)))
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Не удалось загрузить агентов')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return agents.filter((agent) => {
      if (filter === 'active' && agent.paused) return false
      if (filter === 'paused' && !agent.paused) return false
      return !needle || agent.title.toLowerCase().includes(needle)
    })
  }, [agents, filter, query])

  const pausedCount = agents.filter((agent) => agent.paused).length

  async function setPaused(agent: WorkflowListItem, paused: boolean): Promise<void> {
    setBusyId(agent.id)
    setError('')
    try {
      if (paused) {
        if (isRunning(agent.id)) runs.cancel(agent.id)
        await api.stopWorkflowAutoRun(agent.id)
      } else {
        await api.resumeWorkflowAutoRun(agent.id)
      }
      setAgents((current) =>
        current.map((row) => (row.id === agent.id ? { ...row, paused, autoRun: paused ? false : row.autoRun } : row))
      )
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Не удалось изменить состояние агента')
    } finally {
      setBusyId('')
    }
  }

  function isRunning(workflowId: string): boolean {
    const entry = runs.entries[workflowId]
    return Boolean(entry && isLiveRunState(entry.state))
  }

  function statusOf(agent: WorkflowListItem): { label: string; tone: string } {
    const entry = runs.entries[agent.id]
    if (entry?.state.pendingHitl || entry?.state.pendingQuestion) return { label: 'Ждёт подтверждения', tone: 'wait' }
    if (isRunning(agent.id)) return { label: 'Выполняется', tone: 'run' }
    if (agent.paused) return { label: 'Остановлен', tone: 'paused' }
    if (agent.autoRun) return { label: 'Активен · по расписанию', tone: 'on' }
    return { label: 'Активен · вручную', tone: 'idle' }
  }

  return (
    <div className="set-body">
      <header className="set-head">
        <div>
          <h1 className="page-title">Мои агенты</h1>
          <p className="set-sub">
            Все ваши агенты: {agents.length}, остановлено: {pausedCount}. Остановка отключает расписание и
            триггеры, агент и его данные сохраняются.
          </p>
        </div>
        <button className="my-agents-btn" type="button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} aria-hidden /> {loading ? 'Обновляем…' : 'Обновить'}
        </button>
      </header>

      <div className="my-agents-toolbar">
        <input
          className="my-agents-search"
          type="search"
          placeholder="Поиск по названию"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="my-agents-filter" role="group" aria-label="Фильтр по состоянию">
          {(
            [
              ['all', 'Все'],
              ['active', 'Активные'],
              ['paused', 'Остановленные']
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`my-agents-btn${filter === id ? ' is-active' : ''}`}
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error ? <p className="my-agents-error">{error}</p> : null}

      <section className="set-card my-agents-card">
        {loading && !agents.length ? <p className="set-muted">Загружаем агентов…</p> : null}
        {!loading && !visible.length ? (
          <p className="set-muted">{agents.length ? 'Ничего не найдено.' : 'У вас пока нет агентов.'}</p>
        ) : null}
        {visible.map((agent) => {
          const status = statusOf(agent)
          const running = isRunning(agent.id)
          const busy = busyId === agent.id
          const title = agent.title || 'Без названия'
          return (
            <div key={agent.id} className={`my-agents-row${agent.paused ? ' is-paused' : ''}`}>
              <div className="my-agents-main">
                <button type="button" className="my-agents-title" onClick={() => onOpen(agent.id, title)}>
                  {title}
                </button>
                <span className="my-agents-meta">
                  {phaseLabel(agent.phase)}
                  {formatUpdated(agent.updatedAt) ? ` · изменён ${formatUpdated(agent.updatedAt)}` : ''}
                </span>
              </div>
              <span className={`my-agents-status tone-${status.tone}`}>{status.label}</span>
              <div className="my-agents-actions">
                <button className="my-agents-btn is-active" type="button" onClick={() => onOpen(agent.id, title)}>
                  <MessageSquare size={14} aria-hidden /> Открыть
                </button>
                <button className="my-agents-btn" type="button" onClick={() => onPassport(agent.id, title)}>
                  <FileText size={14} aria-hidden /> Паспорт
                </button>
                <button className="my-agents-btn" type="button" onClick={() => onHistory(agent.id, title)}>
                  <History size={14} aria-hidden /> История
                </button>
                {running ? (
                  <button className="my-agents-btn" type="button" onClick={() => runs.cancel(agent.id)}>
                    <Square size={14} aria-hidden /> Прервать запуск
                  </button>
                ) : null}
                <button
                  className={`my-agents-btn${agent.paused ? '' : ' is-danger'}`}
                  type="button"
                  disabled={busy}
                  onClick={() => void setPaused(agent, !agent.paused)}
                >
                  {agent.paused ? <Play size={14} aria-hidden /> : <Pause size={14} aria-hidden />}
                  {busy ? '…' : agent.paused ? 'Возобновить' : 'Остановить'}
                </button>
              </div>
            </div>
          )
        })}
      </section>
    </div>
  )
}
