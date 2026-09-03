import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent } from '../api/types'
import { FilterBar } from './FilterBar'
import { useWorkplaceData } from './WorkplaceBoard'
import { humanWhen, parseIso } from '../utils/calendar'
import { MiniCalendar, meetingsFromEvents, type MiniMeeting } from '../components/agentfeed/MiniCalendar'
import { cleanRunResult } from '../utils/cleanRunResult'
import { useRuns } from '../store/runs'
import {
  extractToolDecisions,
  isDecisionTool,
  toolIntent,
  type ToolDecisionItem
} from './decisionTools'

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function dayKey(stamp: Date): string {
  return `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}`
}

function todayKey(): string {
  return dayKey(new Date())
}

function inRange(stamp: Date | null, fromDay: string, toDay: string): boolean {
  if (!stamp) return false
  const key = dayKey(stamp)
  const start = fromDay <= toDay ? fromDay : toDay
  const end = fromDay <= toDay ? toDay : fromDay
  return key >= start && key <= end
}

function runStamp(run: AgentRunHistoryItem): Date | null {
  return parseIso(run.finishedAt || run.startedAt || '')
}

function formatRange(fromDay: string, toDay: string): string {
  if (fromDay === toDay) {
    if (fromDay === todayKey()) return 'сегодня'
    return fromDay
  }
  return `${fromDay} — ${toDay}`
}

function isOpenRun(status: string): boolean {
  const key = (status || '').trim().toLowerCase()
  return key === 'started' || key === 'running'
}

function toolStatusLabel(item: ToolDecisionItem): string {
  if (item.status === 'pending') return 'Ждёт подтверждения'
  if (item.status === 'rejected') return 'Отклонено'
  if (item.status === 'confirmed') return 'Подтверждено'
  if (!item.result || /не был выполнен|не сохранился/i.test(item.result)) return 'Не выполнен'
  return 'Выполнено'
}

function runStatusLabel(status: string): string {
  const key = (status || '').trim().toLowerCase()
  if (key === 'ok' || key === 'done' || key === 'completed') return 'готово'
  if (key === 'error' || key === 'failed') return 'ошибка'
  if (key === 'canceled' || key === 'cancelled') return 'отменён'
  if (key === 'started' || key === 'running') return 'выполняется'
  return status || 'готово'
}

export function DecisionsTab({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const today = todayKey()
  const [query, setQuery] = useState('')
  const [fromDay, setFromDay] = useState(today)
  const [toDay, setToDay] = useState(today)
  const [duePanelOpen, setDuePanelOpen] = useState(false)
  const [dueAnchor, setDueAnchor] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [tools, setTools] = useState<ToolDecisionItem[]>([])
  const [results, setResults] = useState<
    Array<{
      workflowId: string
      agentName: string
      runId: string
      at: string
      text: string
      status: string
      meetings: MiniMeeting[]
    }>
  >([])
  const { agents, loading, error } = useWorkplaceData()
  const runs = useRuns()
  const agentsRef = useRef(agents)
  agentsRef.current = agents

  const agentKey = useMemo(() => agents.map((item) => item.workflowId).join('|'), [agents])

  useEffect(() => {
    let alive = true
    setLoadingDetails(true)
    void (async () => {
      const collectedTools: ToolDecisionItem[] = []
      const collectedResults: Array<{
        workflowId: string
        agentName: string
        runId: string
        at: string
        text: string
        status: string
        meetings: MiniMeeting[]
      }> = []
      const jobs = agentsRef.current.slice(0, 40).map(async (agent) => {
        const history = await api.listAgentRuns(agent.workflowId).catch(() => [] as AgentRunHistoryItem[])
        const matched = history
          .filter((run) => inRange(runStamp(run), fromDay, toDay))
          .slice(0, 5)
        for (const run of matched) {
          const detail = await api.getAgentRunDetail(agent.workflowId, run.runId).catch(() => null)
          const events: AgentRunnerEvent[] = detail?.events || []
          const at = run.finishedAt || run.startedAt || ''
          collectedTools.push(
            ...extractToolDecisions(events, {
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: run.runId,
              at,
              runClosed: !isOpenRun(run.status)
            })
          )
          const cleaned = cleanRunResult({
            answer: detail?.item.answer || run.answer,
            summary: run.summary,
            events,
            status: run.status
          })
          const meetings = meetingsFromEvents(events)
          const storedMeetings = detail?.item.calendarMeetings || []
          const plan = meetings.length ? meetings : storedMeetings
          if (cleaned.text || plan.length) {
            collectedResults.push({
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: run.runId,
              at,
              text: cleaned.text,
              status: run.status,
              meetings: plan
            })
          }
        }
      })
      await Promise.all(jobs)
      if (!alive) return
      collectedTools.sort((left, right) => String(right.at).localeCompare(String(left.at)))
      collectedResults.sort((left, right) => String(right.at).localeCompare(String(left.at)))
      setTools(collectedTools)
      setResults(collectedResults)
      setLoadingDetails(false)
    })()
    return () => {
      alive = false
    }
  }, [agentKey, fromDay, toDay])

  const livePending = useMemo(() => {
    if (!inRange(new Date(), fromDay, toDay)) return []
    const items: ToolDecisionItem[] = []
    for (const entry of Object.values(runs.entries)) {
      const hitl = entry.state.pendingHitl
      if (!hitl) continue
      const tool = String(hitl.tool || '')
      if (!isDecisionTool(tool, true)) continue
      items.push({
        id: `live:${entry.workflowId}:${hitl.requestId}`,
        workflowId: entry.workflowId,
        agentName: entry.title,
        runId: entry.backendRunId || entry.state.activeRunId || '',
        tool,
        title: hitl.title || tool,
        intent: toolIntent(tool, hitl.arguments),
        result: '',
        status: 'pending',
        requestId: hitl.requestId,
        at: new Date().toISOString(),
        live: true
      })
    }
    return items
  }, [runs.entries, fromDay, toDay])

  const visibleTools = useMemo(() => {
    const q = query.trim().toLowerCase()
    const seen = new Set<string>()
    const merged: ToolDecisionItem[] = []
    for (const item of [...livePending, ...tools]) {
      const key = item.requestId
        ? `${item.workflowId}:${item.requestId}`
        : `${item.workflowId}:${item.runId}:${item.tool}:${item.status}`
      if (seen.has(key)) continue
      seen.add(key)
      if (q && !`${item.title} ${item.tool} ${item.agentName}`.toLowerCase().includes(q)) continue
      merged.push(item)
    }
    return merged
  }, [livePending, tools, query])

  const pending = visibleTools.filter((item) => item.status === 'pending')
  const history = visibleTools.filter((item) => item.status !== 'pending')
  const visibleResults = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return results
    return results.filter((item) => `${item.agentName} ${item.workflowId} ${item.text}`.toLowerCase().includes(q))
  }, [results, query])

  const dueMonthLabel = dueAnchor.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })
  const dueCells = useMemo(() => {
    const first = new Date(dueAnchor.getFullYear(), dueAnchor.getMonth(), 1)
    const weekday = (first.getDay() + 6) % 7
    const start = new Date(first)
    start.setDate(first.getDate() - weekday)
    return Array.from({ length: 42 }, (_, idx) => {
      const day = new Date(start)
      day.setDate(start.getDate() + idx)
      return day
    })
  }, [dueAnchor])

  function resetFilters(): void {
    setQuery('')
    setFromDay(today)
    setToDay(today)
  }

  function pickDay(key: string): void {
    setFromDay(key)
    setToDay(key)
    setDuePanelOpen(false)
  }

  return (
    <div className="wp-page">
      <div className="wp-head">
        <div>
          <h1 className="page-title">Решения</h1>
        </div>
      </div>
      <section className="wp-decisions-kpi">
        <article className="wp-decisions-kpi-card wait">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            !
          </div>
          <div>
            <p>Ждут подтверждения</p>
            <strong>{pending.length}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card done">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ✓
          </div>
          <div>
            <p>История за период</p>
            <strong>{history.length}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card review">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ●
          </div>
          <div>
            <p>Результаты агентов</p>
            <strong>{visibleResults.length}</strong>
          </div>
        </article>
      </section>
      <FilterBar
        query={query}
        onQuery={setQuery}
        queryPlaceholder="Агент или инструмент"
        chips={[
          { id: 'q', label: query ? `поиск: ${query}` : '' },
          { id: 'range', label: `период: ${formatRange(fromDay, toDay)}` }
        ]}
        onReset={resetFilters}
      >
        <label className="wp-range-field">
          <span>С</span>
          <input
            className="wp-date"
            type="date"
            value={fromDay}
            onChange={(event) => {
              if (event.target.value) setFromDay(event.target.value)
            }}
          />
        </label>
        <label className="wp-range-field">
          <span>По</span>
          <input
            className="wp-date"
            type="date"
            value={toDay}
            onChange={(event) => {
              if (event.target.value) setToDay(event.target.value)
            }}
          />
        </label>
        <button className="btn-ghost wp-deadline-toggle" type="button" onClick={() => setDuePanelOpen((value) => !value)}>
          День
        </button>
      </FilterBar>
      {duePanelOpen ? (
        <section className="wp-card wp-deadline-panel">
          <div className="wp-deadline-head">
            <button
              className="btn-ghost"
              type="button"
              onClick={() => setDueAnchor((prev) => new Date(prev.getFullYear(), prev.getMonth() - 1, 1))}
            >
              ←
            </button>
            <strong>{dueMonthLabel}</strong>
            <button
              className="btn-ghost"
              type="button"
              onClick={() => setDueAnchor((prev) => new Date(prev.getFullYear(), prev.getMonth() + 1, 1))}
            >
              →
            </button>
          </div>
          <div className="wp-deadline-weekdays">
            {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((name) => (
              <span key={name}>{name}</span>
            ))}
          </div>
          <div className="wp-deadline-grid">
            {dueCells.map((day) => {
              const key = dayKey(day)
              const tone = key < today ? 'past' : key > today ? 'future' : 'today'
              const outside = day.getMonth() !== dueAnchor.getMonth()
              const start = fromDay <= toDay ? fromDay : toDay
              const end = fromDay <= toDay ? toDay : fromDay
              const selected = key === fromDay || key === toDay
              const inSel = key >= start && key <= end
              return (
                <button
                  key={key}
                  type="button"
                  className={`wp-deadline-day ${tone}${outside ? ' muted' : ''}${selected ? ' selected' : ''}${
                    inSel && !selected ? ' in-range' : ''
                  }`}
                  onClick={() => pickDay(key)}
                >
                  {day.getDate()}
                </button>
              )
            })}
          </div>
        </section>
      ) : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      {loading || loadingDetails ? <article className="wp-card">Собираем подтверждения и результаты…</article> : null}
      {!loading && !loadingDetails ? (
        <div className="wp-decisions-columns">
          <section className="wp-card wp-decisions-col">
            <h2>Подтверждение инструментов</h2>
            <p>
              По умолчанию за {formatRange(fromDay, toDay)}. Только инструменты на запись или с
              подтверждением. Уже подтверждённые не нужно подтверждать снова.
            </p>
            <div className="wp-decisions-col-list">
              {!pending.length && !history.length ? (
                <article className="wp-card wp-decisions-mini">За выбранный период таких инструментов нет.</article>
              ) : null}
              {pending.map((item) => (
                <article key={item.id} className="wp-card wp-decision-rich">
                  <div className="wp-decision-rich-head">
                    <div>
                      <h3>{item.title}</h3>
                      <div className="wp-code">{item.agentName}</div>
                    </div>
                    <span className="wp-decision-state warn">{toolStatusLabel(item)}</span>
                  </div>
                  <div className="wp-decision-block">
                    <strong>Что должен сделать</strong>
                    <p>{item.intent}</p>
                  </div>
                  <div className="wp-actions wp-decision-actions">
                    {item.live && item.requestId ? (
                      <>
                        <button
                          className="btn-primary"
                          type="button"
                          onClick={() => runs.respondHitl(item.workflowId, item.requestId, true)}
                        >
                          Подтвердить
                        </button>
                        <button
                          className="btn-ghost"
                          type="button"
                          onClick={() => runs.respondHitl(item.workflowId, item.requestId, false)}
                        >
                          Отклонить
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn-primary"
                        type="button"
                        onClick={() => onOpenRun(item.workflowId, item.agentName, item.runId)}
                      >
                        Открыть прогон
                      </button>
                    )}
                  </div>
                </article>
              ))}
              {pending.length > 0 && history.length > 0 ? (
                <h3 className="wp-decisions-sub">История подтверждений</h3>
              ) : null}
              {history.map((item) => (
                <article key={item.id} className="wp-card wp-decision-rich">
                  <div className="wp-decision-rich-head">
                    <div>
                      <h3>{item.title}</h3>
                      <div className="wp-code">{item.agentName}</div>
                    </div>
                    <span className={`wp-decision-state ${item.status === 'rejected' ? 'warn' : 'ok'}`}>
                      {toolStatusLabel(item)}
                    </span>
                  </div>
                  <div className="wp-decision-block">
                    <strong>Что нужно было подтвердить</strong>
                    <p>{item.intent}</p>
                  </div>
                  <div className="wp-decision-block">
                    <strong>Результат инструмента</strong>
                    <p className="wp-decisions-result">{item.result || 'Результат не сохранился.'}</p>
                  </div>
                  <p className="wp-decision-time">{item.at ? humanWhen(parseIso(item.at) || new Date(item.at)) : ''}</p>
                </article>
              ))}
            </div>
          </section>
          <section className="wp-card wp-decisions-col">
            <h2>Результаты агентов</h2>
            <p>Итог работы, без хода выполнения.</p>
            <div className="wp-decisions-col-list">
              {!visibleResults.length ? (
                <article className="wp-card wp-decisions-mini">За выбранный период готовых результатов нет.</article>
              ) : null}
              {visibleResults.map((item) => (
                <article key={`${item.workflowId}:${item.runId}`} className="wp-card wp-decision-rich">
                  <div className="wp-decision-rich-head">
                    <div>
                      <h3>{item.agentName}</h3>
                      <div className="wp-code">{item.workflowId}</div>
                    </div>
                    <span className="wp-decision-state ok">{runStatusLabel(item.status)}</span>
                  </div>
                  <div className="wp-decision-block">
                    <strong>Результат</strong>
                    {item.meetings.length > 0 && (
                      <div className="wf-result-calendar">
                        <MiniCalendar meetings={item.meetings} />
                      </div>
                    )}
                    {item.text ? (
                      <p className="wp-decisions-result wp-decision-summary">{item.text}</p>
                    ) : null}
                  </div>
                  <p className="wp-decision-time">{item.at ? humanWhen(parseIso(item.at) || new Date(item.at)) : ''}</p>
                  <div className="wp-actions wp-decision-actions">
                    <button
                      className="btn-ghost"
                      type="button"
                      onClick={() => onOpenRun(item.workflowId, item.agentName, item.runId)}
                    >
                      Открыть материалы
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  )
}
