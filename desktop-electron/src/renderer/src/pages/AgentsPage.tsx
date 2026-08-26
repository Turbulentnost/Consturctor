import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  AgentDraft,
  AgentRunHistoryItem,
  AgentSuggestion,
  BoardAgent,
  WorkflowBoard
} from '../api/types'
import {
  activeWord,
  agentsWord,
  humanWhen,
  nextRunTile,
  parseIso,
  runsWord,
  shiftAnchor,
  windowFor,
  type CalendarView
} from '../utils/calendar'
import { StatTile } from '../components/agents/StatTile'
import { AgentCard } from '../components/agents/AgentCard'
import { DraftCard } from '../components/agents/DraftCard'
import { RunCalendar } from '../components/agents/RunCalendar'
import statAgents from '../assets/stat-agents.png'
import statActive from '../assets/stat-active.png'
import statRuns from '../assets/stat-runs.png'
import statNext from '../assets/stat-next.png'

type StatusFilter = 'active' | 'draft' | 'all' | 'paused' | 'errors'

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

function normalizeTitle(value: string): string {
  return (value || '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
}

interface AgentsPageProps {
  onCreateAgent: () => void
  onOpenRun: (workflowId: string, runId: string) => void
  onFormDraftSuggestion: (draftId: string, agentId: string) => void
  onContinueDraft: (draftId: string) => void
}

export function AgentsPage({
  onCreateAgent,
  onOpenRun,
  onFormDraftSuggestion,
  onContinueDraft
}: AgentsPageProps): React.JSX.Element {
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [drafts, setDrafts] = useState<AgentDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [search, setSearch] = useState('')
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [view, setView] = useState<CalendarView>('week')
  const [anchor, setAnchor] = useState<Date>(new Date())
  const [funnelOpen, setFunnelOpen] = useState(false)
  const [history, setHistory] = useState<{ title: string; items: AgentRunHistoryItem[] } | null>(null)
  const funnelRef = useRef<HTMLDivElement>(null)
  const tickRef = useRef(0)
  const [, forceTick] = useState(0)

  const workflowAgents = useMemo(
    () => board.agents.filter((item) => item.kind === 'workflow'),
    [board]
  )

  async function reload(nextView = view, nextAnchor = anchor): Promise<void> {
    const win = windowFor(nextView, nextAnchor)
    try {
      const [nextBoard, nextDrafts] = await Promise.all([
        api.getWorkflowBoard({ window_from: win.from, window_to: win.to }),
        api.listAgentDrafts()
      ])
      setBoard(nextBoard)
      setDrafts(nextDrafts)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Refresh relative stat wording every 30s.
  useEffect(() => {
    const timer = setInterval(() => {
      tickRef.current += 1
      forceTick(tickRef.current)
    }, 30000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!funnelOpen) return
    function onDocClick(evt: MouseEvent): void {
      if (funnelRef.current && !funnelRef.current.contains(evt.target as Node)) setFunnelOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [funnelOpen])

  function changeView(nextView: CalendarView): void {
    setView(nextView)
    void reload(nextView, anchor)
  }

  function shift(step: number): void {
    const next = shiftAnchor(view, anchor, step)
    setAnchor(next)
    void reload(view, next)
  }

  function goToday(): void {
    const next = new Date()
    setAnchor(next)
    void reload(view, next)
  }

  function suggestionsFor(agent: BoardAgent): AgentSuggestion[] {
    const draftId = (agent.draftId || agent.id || '').trim()
    const draft = drafts.find((item) => item.draftId === draftId)
    if (!draft) return []
    return (draft.agentSuggestions || []).filter((item) => item.title || item.description)
  }

  const createdTitles = useMemo(() => {
    const titles = new Set<string>()
    for (const item of workflowAgents) {
      if (item.title.trim()) titles.add(normalizeTitle(item.title))
    }
    return titles
  }, [workflowAgents])

  function matchesSearch(agent: BoardAgent): boolean {
    const needle = search.trim().toLowerCase()
    if (!needle) return true
    if (agent.title.toLowerCase().includes(needle)) return true
    if (agent.description.toLowerCase().includes(needle)) return true
    if (agent.kind !== 'draft') return false
    return suggestionsFor(agent).some(
      (item) =>
        item.title.toLowerCase().includes(needle) ||
        item.description.toLowerCase().includes(needle)
    )
  }

  const visibleAgents = useMemo(() => {
    let items = [...board.agents]
    if (statusFilter === 'active') items = items.filter((item) => item.status === 'active')
    else if (statusFilter === 'paused') items = items.filter((item) => item.status === 'paused')
    else if (statusFilter === 'errors')
      items = items.filter(
        (item) => item.status === 'needs_attention' || item.lastRunStatus === 'error'
      )
    else if (statusFilter === 'draft') items = items.filter((item) => item.kind === 'draft')
    if (search.trim()) items = items.filter(matchesSearch)
    return items
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board, statusFilter, search, drafts])

  function selectAgent(id: string): void {
    setSelectedAgentId((prev) => (prev === id ? '' : id))
  }

  function flash(message: string): void {
    setActionMsg(message)
    window.setTimeout(() => setActionMsg(''), 4000)
  }

  async function runAction(fn: () => Promise<void>, okMessage: string): Promise<void> {
    try {
      await fn()
      await reload()
      flash(okMessage)
    } catch (err) {
      flash(err instanceof Error ? err.message : 'Не удалось выполнить действие')
    }
  }

  function onPause(id: string): void {
    void runAction(() => api.stopWorkflowAutoRun(id), 'Агент приостановлен')
  }

  function onResume(id: string): void {
    void runAction(() => api.resumeWorkflowAutoRun(id), 'Автозапуск возобновлён')
  }

  function onSchedule(id: string): void {
    void runAction(async () => {
      await api.proposeScheduleDraft(id)
    }, 'Черновик расписания создан')
  }

  function onDelete(id: string): void {
    const agent = board.agents.find((item) => item.id === id)
    if (!window.confirm(`Удалить агента "${agent?.title || 'ИИ-агент'}"?`)) return
    void runAction(() => api.deleteWorkflow(id), 'Агент удалён')
  }

  function onDeleteDraft(draftId: string): void {
    if (!window.confirm('Удалить черновик?')) return
    void runAction(async () => {
      await api.updateAgentDraftStatus(draftId, 'archived')
    }, 'Черновик удалён')
  }

  function onScheduleRun(workflowId: string, iso: string): void {
    void runAction(
      () => api.createTimedTrigger(workflowId, iso, 'Плановый запуск'),
      'Запуск запланирован'
    )
  }

  async function onHistory(id: string, title: string): Promise<void> {
    setHistory({ title, items: [] })
    try {
      const items = await api.listAgentRuns(id)
      setHistory({ title, items })
    } catch (err) {
      flash(err instanceof Error ? err.message : 'Не удалось загрузить историю')
      setHistory(null)
    }
  }

  const totalAgents = workflowAgents.length
  const stats = board.stats

  return (
    <div className="agents-page">
      <div className="agents-header">
        <div>
          <h1 className="page-title">Мои агенты</h1>
          <p className="page-subtitle">Управляйте агентами и контролируйте их запуски</p>
        </div>
        <button className="btn-primary agents-create-btn" onClick={onCreateAgent}>
          +&nbsp;&nbsp;Создать агента
        </button>
      </div>

      <div className="agents-stats">
        <StatTile icon={statAgents} text={`${totalAgents} ${agentsWord(totalAgents)}`} />
        <StatTile icon={statActive} text={`${stats.activeAgents} ${activeWord(stats.activeAgents)}`} />
        <StatTile icon={statRuns} text={`${stats.runsToday} ${runsWord(stats.runsToday)} сегодня`} />
        <StatTile icon={statNext} text={nextRunTile(stats.nextRunAt)} />
      </div>

      {actionMsg && <div className="agents-flash">{actionMsg}</div>}

      <div className="agents-layout">
        <div className="agents-pane">
          <div className="agents-count">Агенты&nbsp;&nbsp;·&nbsp;&nbsp;{visibleAgents.length}</div>
          <div className="agents-search-row">
            <input
              className="agents-search"
              placeholder="Поиск агента"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="agents-funnel" ref={funnelRef}>
              <button
                className={
                  statusFilter === 'paused' || statusFilter === 'errors'
                    ? 'agents-funnel-btn on'
                    : 'agents-funnel-btn'
                }
                title="Фильтр: приостановленные и с ошибками"
                onClick={() => setFunnelOpen((v) => !v)}
              >
                <svg width="16" height="16" viewBox="0 0 36 36" fill="none">
                  <path
                    d="M9 10 H27 L21 19 V27 L15 29 V19 Z"
                    fill="currentColor"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              {funnelOpen && (
                <div className="agents-funnel-menu">
                  <button
                    onClick={() => {
                      setStatusFilter('paused')
                      setFunnelOpen(false)
                    }}
                  >
                    Приостановленные
                  </button>
                  <button
                    onClick={() => {
                      setStatusFilter('errors')
                      setFunnelOpen(false)
                    }}
                  >
                    С ошибками
                  </button>
                  <div className="card-menu-sep" />
                  <button
                    onClick={() => {
                      setStatusFilter('active')
                      setFunnelOpen(false)
                    }}
                  >
                    Сбросить
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="agents-tabs">
            {(
              [
                ['active', 'Активные'],
                ['draft', 'Черновики'],
                ['all', 'Все']
              ] as [StatusFilter, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                className={statusFilter === key ? 'agents-chip active' : 'agents-chip'}
                onClick={() => setStatusFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="agents-list">
            {loading ? (
              <div className="agents-empty">Загрузка...</div>
            ) : error ? (
              <div className="agents-empty">{error}</div>
            ) : visibleAgents.length === 0 ? (
              <div className="agents-empty">Нет агентов по текущему фильтру.</div>
            ) : (
              visibleAgents.map((agent) =>
                agent.kind === 'draft' ? (
                  <DraftCard
                    key={agent.id}
                    agent={agent}
                    suggestions={suggestionsFor(agent)}
                    createdTitles={createdTitles}
                    onContinue={onContinueDraft}
                    onFormSuggestion={onFormDraftSuggestion}
                    onDelete={onDeleteDraft}
                  />
                ) : (
                  <AgentCard
                    key={agent.id}
                    agent={agent}
                    selected={agent.id === selectedAgentId}
                    onSelect={selectAgent}
                    onRun={(id) => onOpenRun(id, '')}
                    onOpen={(id) => onOpenRun(id, '')}
                    onHistory={(id, title) => void onHistory(id, title)}
                    onSchedule={onSchedule}
                    onPause={onPause}
                    onResume={onResume}
                    onDelete={onDelete}
                  />
                )
              )
            )}
          </div>
        </div>

        <RunCalendar
          view={view}
          anchor={anchor}
          agents={workflowAgents}
          events={board.events}
          agentFilter={selectedAgentId}
          onView={changeView}
          onShift={shift}
          onToday={goToday}
          onAgentFilter={setSelectedAgentId}
          onEventClick={onOpenRun}
          onOpenGroup={(items) => {
            if (items.length) onOpenRun(items[0].workflowId, items[0].runId || '')
          }}
          onScheduleRun={onScheduleRun}
        />
      </div>

      {history && (
        <div className="modal-overlay" onClick={() => setHistory(null)}>
          <div className="modal-card history-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">История запусков — {history.title}</div>
            {history.items.length === 0 ? (
              <div className="modal-note">Запусков пока не было.</div>
            ) : (
              <div className="history-list">
                {history.items.map((item) => {
                  const started = parseIso(item.startedAt)
                  return (
                    <div key={item.runId} className="history-row">
                      <span className="history-when">
                        {started ? humanWhen(started) : 'без даты'}
                      </span>
                      <span className="history-status">{item.status || '—'}</span>
                      {item.summary && <span className="history-summary">{item.summary}</span>}
                    </div>
                  )
                })}
              </div>
            )}
            <div className="modal-actions">
              <button className="btn-light" onClick={() => setHistory(null)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
