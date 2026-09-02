import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, BoardAgent, CalendarEvent, WorkflowBoard } from '../api/types'
import { RunCalendar } from '../components/agents/RunCalendar'
import {
  humanWhen,
  parseIso,
  shiftAnchor,
  STATUS_STYLE,
  windowFor,
  type CalendarView
} from '../utils/calendar'

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

function statusLabel(status: string): string {
  return STATUS_STYLE[status]?.label || status || '—'
}

function clip(text: string): string {
  return (text || '').replace(/\s+/g, ' ').trim()
}

export function HistoryWorkplace({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [flash, setFlash] = useState('')
  const [view, setView] = useState<CalendarView>('week')
  const [anchor, setAnchor] = useState<Date>(new Date())
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const reloadRef = useRef<(nextView?: CalendarView, nextAnchor?: Date) => Promise<void>>(
    async () => undefined
  )

  const agents = useMemo(
    () => board.agents.filter((item) => item.kind === 'workflow'),
    [board.agents]
  )

  async function reload(nextView = view, nextAnchor = anchor): Promise<void> {
    const win = windowFor(nextView, nextAnchor)
    try {
      const nextBoard = await api.getWorkflowBoard({ window_from: win.from, window_to: win.to })
      setBoard(nextBoard)
      const workflowAgents = nextBoard.agents.filter((item) => item.kind === 'workflow')
      const lists = await Promise.all(
        workflowAgents.map((agent) => api.listAgentRuns(agent.id).catch(() => [] as AgentRunHistoryItem[]))
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function notice(text: string): void {
    setFlash(text)
    window.setTimeout(() => setFlash(''), 4000)
  }

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

  function titleOf(workflowId: string): string {
    return agents.find((item) => item.id === workflowId)?.title || 'ИИ-агент'
  }

  async function onScheduleRun(workflowId: string, iso: string): Promise<void> {
    try {
      await api.createTimedTrigger(workflowId, iso, 'Плановый запуск')
      await reload()
      notice('Запуск запланирован')
    } catch (err) {
      notice(err instanceof Error ? err.message : 'Не удалось запланировать запуск')
    }
  }

  const showcase = runs.slice(0, 8)
  const selectedAgent: BoardAgent | undefined = agents.find((item) => item.id === selectedAgentId)

  return (
    <div className="wp-page wp-history">
      <div className="wp-head">
        <div>
          <div className="wp-head-title-row">
            <h1 className="page-title">История</h1>
            <span className="orch-badge">{loading ? 'загрузка' : `${runs.length} прогонов`}</span>
          </div>
          <div className="wp-sub">Календарь запусков и результаты последних прогонов</div>
        </div>
      </div>
      {flash ? <div className="wp-toast">{flash}</div> : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}

      <div className="wp-history-layout">
        <section className="wp-card wp-showcase">
          <div className="wp-showcase-head">
            <div>
              <h2>Результаты последних прогонов</h2>
              <p>Готовый ответ агента, без календаря — его можно открыть целиком.</p>
            </div>
          </div>
          {loading && !showcase.length ? <p>Загружаем прогоны с сервера…</p> : null}
          {!loading && !showcase.length ? <p>Прогонов ещё не было.</p> : null}
          <div className="wp-showcase-grid">
            {showcase.map((item) => {
              const started = parseIso(item.startedAt)
              const text = clip(item.summary || item.answer || 'Текст результата ещё не пришёл.')
              return (
                <button
                  key={item.runId}
                  className="wp-showcase-card"
                  type="button"
                  onClick={() => onOpenRun(item.workflowId, titleOf(item.workflowId), item.runId)}
                >
                  <div className="wp-showcase-meta">
                    <span className="wp-code">{titleOf(item.workflowId)}</span>
                    <span className={`wp-pill wp-pill-${item.status === 'ok' ? 'done' : item.status === 'error' ? 'needs_decision' : item.status === 'canceled' || item.status === 'cancelled' ? 'paused' : 'running'}`}>
                      {statusLabel(item.status)}
                    </span>
                  </div>
                  <strong>{started ? humanWhen(started) : 'без даты'}</strong>
                  <p>{text}</p>
                </button>
              )
            })}
          </div>
        </section>

        <div className="wp-history-cal">
          <RunCalendar
            view={view}
            anchor={anchor}
            agents={agents}
            events={board.events as CalendarEvent[]}
            agentFilter={selectedAgentId}
            onView={changeView}
            onShift={shift}
            onToday={goToday}
            onAgentFilter={setSelectedAgentId}
            onEventClick={(workflowId, runId) => onOpenRun(workflowId, titleOf(workflowId), runId)}
            onOpenGroup={(items) => {
              if (items[0]) onOpenRun(items[0].workflowId, items[0].title, items[0].runId)
            }}
            onScheduleRun={(workflowId, iso) => void onScheduleRun(workflowId, iso)}
          />
          {selectedAgent ? (
            <p className="wp-step-note">Фильтр календаря: {selectedAgent.title}. Сбросьте его в фильтрах календаря.</p>
          ) : null}
        </div>
      </div>
    </div>
  )
}
