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
import { parseIso } from '../utils/calendar'

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

type StatusFilter = '' | 'ok' | 'error' | 'canceled' | 'started'
type PeriodKey = 'today' | 'week' | 'month' | 'all'
type SortKey = 'newest' | 'oldest'
type EventTypeKey = 'schedule' | 'event' | 'manual' | 'chat' | 'hitl'

function dayKey(stamp: Date): string {
  return `${stamp.getFullYear()}-${String(stamp.getMonth() + 1).padStart(2, '0')}-${String(stamp.getDate()).padStart(2, '0')}`
}

function todayKey(): string {
  return dayKey(new Date())
}

const PERIOD_LABELS: Record<PeriodKey, string> = {
  today: 'Сегодня',
  week: '7 дней',
  month: '30 дней',
  all: 'Весь период'
}

const EVENT_TYPE_LABELS: Record<EventTypeKey, string> = {
  schedule: 'Расписание',
  event: 'Событие',
  manual: 'Вручную',
  chat: 'Чат',
  hitl: 'Решение человека'
}

const INITIATOR_LABELS: Record<string, string> = {
  schedule: 'Расписание',
  chat: 'Чат',
  manual: 'Пользователь',
  event: 'Событие',
  system: 'Система'
}

function runEventType(run: AgentRunHistoryItem): EventTypeKey {
  const source = (run.source || '').toLowerCase()
  const kind = (run.triggerKind || '').toLowerCase()
  if (source === 'chat' || kind === 'chat') return 'chat'
  if (source === 'manual' || kind === 'manual') return 'manual'
  if (source === 'event' || kind === 'event') return 'event'
  if (source.includes('hitl') || kind.includes('hitl')) return 'hitl'
  return 'schedule'
}

function runInitiator(run: AgentRunHistoryItem): string {
  const source = (run.source || '').toLowerCase()
  if (source === 'chat') return 'chat'
  if (source === 'manual') return 'manual'
  if (source === 'event') return 'event'
  if (source === 'schedule' || run.triggerKind) return 'schedule'
  return 'system'
}

function runDurationSec(run: AgentRunHistoryItem): number | null {
  const total = Number(run.agentWorkMs || 0) + Number(run.humanWaitMs || 0)
  if (total > 0) return Math.round(total / 1000)
  const start = parseIso(run.startedAt)
  const end = parseIso(run.finishedAt)
  if (start && end && end >= start) return Math.round((end.getTime() - start.getTime()) / 1000)
  return null
}

function inPeriod(run: AgentRunHistoryItem, period: PeriodKey, today: string): boolean {
  if (period === 'all') return true
  const stamp = parseIso(run.startedAt || run.finishedAt)
  if (!stamp) return false
  const key = dayKey(stamp)
  if (period === 'today') return key === today
  const days = period === 'week' ? 7 : 30
  const start = parseIso(`${today}T12:00:00`) || new Date()
  start.setDate(start.getDate() - (days - 1))
  return stamp >= start
}

function escapeCsv(value: string): string {
  const text = String(value || '').replace(/\r?\n/g, ' ')
  if (/[",;]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

function buildHistoryCsv(rows: Array<Record<string, string>>): string {
  if (!rows.length) return 'runId;workflow;status;startedAt;finishedAt;source\n'
  const keys = Object.keys(rows[0])
  return [keys.join(';'), ...rows.map((row) => keys.map((key) => escapeCsv(row[key] || '')).join(';'))].join(
    '\n'
  )
}

export function HistoryWorkplace({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const today = todayKey()
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [period, setPeriod] = useState<PeriodKey>('today')
  const [agentId, setAgentId] = useState('')
  const [eventTypes, setEventTypes] = useState<EventTypeKey[]>([])
  const [initiator, setInitiator] = useState('')
  const [status, setStatus] = useState<StatusFilter>('')
  const [sort, setSort] = useState<SortKey>('newest')
  const [extraOpen, setExtraOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [exportNote, setExportNote] = useState('')
  const [draftCorrelation, setDraftCorrelation] = useState('')
  const [draftVersion, setDraftVersion] = useState('')
  const [draftDurationMin, setDraftDurationMin] = useState('')
  const [draftDurationMax, setDraftDurationMax] = useState('')
  const [correlationId, setCorrelationId] = useState('')
  const [agentVersion, setAgentVersion] = useState('')
  const [durationMin, setDurationMin] = useState('')
  const [durationMax, setDurationMax] = useState('')
  const [selected, setSelected] = useState('')
  const [answer, setAnswer] = useState('')
  const [events, setEvents] = useState<AgentRunnerEvent[]>([])
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const [detailMeetings, setDetailMeetings] = useState<AgentRunHistoryItem['calendarMeetings']>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const liveStore = useRuns()
  const reloadRef = useRef<() => Promise<void>>(async () => undefined)
  const extraRef = useRef<HTMLDivElement | null>(null)
  const exportRef = useRef<HTMLDivElement | null>(null)
  const eventTypeRef = useRef<HTMLDivElement | null>(null)
  const [eventTypeOpen, setEventTypeOpen] = useState(false)

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

  const extraActiveCount = useMemo(() => {
    let count = 0
    if (correlationId.trim()) count += 1
    if (agentVersion.trim()) count += 1
    if (durationMin.trim() || durationMax.trim()) count += 1
    return count
  }, [correlationId, agentVersion, durationMin, durationMax])

  useEffect(() => {
    if (!extraOpen && !exportOpen && !eventTypeOpen) return
    const onDoc = (event: MouseEvent): void => {
      const target = event.target as Node
      if (extraOpen && !extraRef.current?.contains(target)) setExtraOpen(false)
      if (exportOpen && !exportRef.current?.contains(target)) setExportOpen(false)
      if (eventTypeOpen && !eventTypeRef.current?.contains(target)) setEventTypeOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [extraOpen, exportOpen, eventTypeOpen])

  useEffect(() => {
    if (!exportNote) return
    const timer = window.setTimeout(() => setExportNote(''), 3500)
    return () => window.clearTimeout(timer)
  }, [exportNote])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const minSec = durationMin.trim() ? Number(durationMin) : null
    const maxSec = durationMax.trim() ? Number(durationMax) : null
    const rows = runs.filter((item) => {
      if (!inPeriod(item, period, today)) return false
      if (agentId && item.workflowId !== agentId) return false
      if (eventTypes.length && !eventTypes.includes(runEventType(item))) return false
      if (initiator && runInitiator(item) !== initiator) return false
      const key = historyRunStatus(item)
      if (status === 'canceled' && key !== 'canceled' && key !== 'cancelled') return false
      if (status === 'started' && key !== 'started' && key !== 'running') return false
      if (status === 'ok' && key !== 'ok') return false
      if (status === 'error' && key !== 'error') return false
      if (correlationId.trim() && !item.runId.toLowerCase().includes(correlationId.trim().toLowerCase())) {
        return false
      }
      if (agentVersion.trim()) {
        const blob = `${item.summary || ''} ${item.message || ''}`.toLowerCase()
        if (!blob.includes(agentVersion.trim().toLowerCase())) return false
      }
      const duration = runDurationSec(item)
      if (minSec != null && Number.isFinite(minSec) && (duration == null || duration < minSec)) return false
      if (maxSec != null && Number.isFinite(maxSec) && (duration == null || duration > maxSec)) return false
      if (!q) return true
      const title = titleOf(item.workflowId).toLowerCase()
      return title.includes(q) || item.runId.toLowerCase().includes(q) || item.workflowId.toLowerCase().includes(q)
    })
    rows.sort((left, right) => {
      const cmp = (right.startedAt || '').localeCompare(left.startedAt || '')
      return sort === 'newest' ? cmp : -cmp
    })
    return rows
  }, [
    runs,
    query,
    period,
    today,
    agentId,
    eventTypes,
    initiator,
    status,
    correlationId,
    agentVersion,
    durationMin,
    durationMax,
    sort,
    agents,
    titles
  ])

  const groups = useMemo(() => groupRunsByDay(visible), [visible])

  function resetFilters(): void {
    setQuery('')
    setPeriod('today')
    setAgentId('')
    setEventTypes([])
    setInitiator('')
    setStatus('')
    setSort('newest')
    setCorrelationId('')
    setAgentVersion('')
    setDurationMin('')
    setDurationMax('')
    setDraftCorrelation('')
    setDraftVersion('')
    setDraftDurationMin('')
    setDraftDurationMax('')
    setExtraOpen(false)
  }

  function applyExtraFilters(): void {
    setCorrelationId(draftCorrelation.trim())
    setAgentVersion(draftVersion.trim())
    setDurationMin(draftDurationMin.trim())
    setDurationMax(draftDurationMax.trim())
    setExtraOpen(false)
  }

  function resetExtraDraft(): void {
    setDraftCorrelation('')
    setDraftVersion('')
    setDraftDurationMin('')
    setDraftDurationMax('')
  }

  function toggleEventType(key: EventTypeKey): void {
    setEventTypes((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
    )
  }

  async function runExport(kind: 'xlsx' | 'csv' | 'pdf'): Promise<void> {
    if (exportBusy) return
    setExportBusy(true)
    setExportOpen(false)
    try {
      const stamp = new Date().toISOString().slice(0, 10)
      const rows = visible.map((item) => ({
        runId: item.runId,
        workflow: titleOf(item.workflowId),
        workflowId: item.workflowId,
        status: HISTORY_STATUS_LABELS[historyRunStatus(item)] || item.status,
        startedAt: item.startedAt || '',
        finishedAt: item.finishedAt || '',
        source: item.source || '',
        triggerKind: item.triggerKind || '',
        summary: (item.summary || item.answer || '').slice(0, 500)
      }))
      if (kind === 'pdf') {
        setExportNote('PDF — после MVP')
        return
      }
      const text = buildHistoryCsv(rows)
      const res = await window.api.saveLocalFile({
        defaultName: `zhurnal-${stamp}.${kind === 'xlsx' ? 'csv' : 'csv'}`,
        text,
        filters: [{ name: kind === 'xlsx' ? 'CSV (таблица)' : 'CSV', extensions: ['csv'] }]
      })
      if (res.canceled) return
      if (!res.ok) throw new Error(res.error || 'Ошибка сохранения')
      setExportNote(kind === 'xlsx' ? 'Журнал сохранён (CSV-таблица)' : 'CSV сохранён')
    } catch (err) {
      setExportNote(err instanceof Error ? err.message : 'Ошибка экспорта')
    } finally {
      setExportBusy(false)
    }
  }

  const chips = [
    {
      id: 'period',
      label: period !== 'today' ? `Период: ${PERIOD_LABELS[period]}` : '',
      onClear: () => setPeriod('today')
    },
    {
      id: 'process',
      label: agentId ? `Процесс: ${titleOf(agentId)}` : '',
      onClear: () => setAgentId('')
    },
    {
      id: 'result',
      label: status ? `Результат: ${HISTORY_STATUS_LABELS[status] || status}` : '',
      onClear: () => setStatus('')
    },
    {
      id: 'events',
      label: eventTypes.length
        ? `Тип события: ${eventTypes.map((item) => EVENT_TYPE_LABELS[item]).join(', ')}`
        : '',
      onClear: () => setEventTypes([])
    },
    {
      id: 'initiator',
      label: initiator ? `Инициатор: ${INITIATOR_LABELS[initiator] || initiator}` : '',
      onClear: () => setInitiator('')
    },
    {
      id: 'q',
      label: query ? `Поиск: ${query}` : '',
      onClear: () => setQuery('')
    },
    {
      id: 'corr',
      label: correlationId ? `Correlation ID: ${correlationId}` : '',
      onClear: () => {
        setCorrelationId('')
        setDraftCorrelation('')
      }
    },
    {
      id: 'version',
      label: agentVersion ? `Версия: ${agentVersion}` : '',
      onClear: () => {
        setAgentVersion('')
        setDraftVersion('')
      }
    },
    {
      id: 'duration',
      label:
        durationMin || durationMax
          ? `Длительность: ${durationMin || '…'}–${durationMax || '…'} с`
          : '',
      onClear: () => {
        setDurationMin('')
        setDurationMax('')
        setDraftDurationMin('')
        setDraftDurationMax('')
      }
    },
    {
      id: 'sort',
      label: sort !== 'newest' ? 'Сортировка: Сначала старые' : '',
      onClear: () => setSort('newest')
    }
  ].filter((item) => Boolean(item.label))

  useEffect(() => {
    if (!selected) return
    if (!visible.some((item) => item.runId === selected)) {
      setSelected('')
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
          <h1 className="page-title">Единый журнал событий, задач и решений</h1>
          <div className="wp-sub">
            Запуски по дням. Справа только результат: план совещаний и итог, без хода работы агента.
          </div>
        </div>
        <span className="orch-badge">{loading ? 'загрузка' : `${visible.length} прогонов`}</span>
      </div>
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      {exportNote ? <div className="hist-export-note">{exportNote}</div> : null}

      <section className="hist-filters">
        <div className="hist-filters-primary">
          <label className="hist-field">
            <span>Период (обязательно)</span>
            <select className="hist-select" value={period} onChange={(e) => setPeriod(e.target.value as PeriodKey)}>
              {(Object.keys(PERIOD_LABELS) as PeriodKey[]).map((key) => (
                <option key={key} value={key}>
                  {PERIOD_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="hist-field">
            <span>Процесс</span>
            <select className="hist-select" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
              <option value="">Все</option>
              {agentOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <div className="hist-field hist-field-multi" ref={eventTypeRef}>
            <span>Тип события</span>
            <button
              className="hist-select hist-select-btn"
              type="button"
              onClick={() => setEventTypeOpen((value) => !value)}
            >
              <span>{eventTypes.length ? `Выбрано: ${eventTypes.length}` : 'Все'}</span>
              {eventTypes.length ? <em className="hist-multi-badge">+{eventTypes.length}</em> : null}
              <span className="hist-caret" aria-hidden>
                ▾
              </span>
            </button>
            {eventTypeOpen ? (
              <div className="hist-multi-menu" role="listbox">
                {(Object.keys(EVENT_TYPE_LABELS) as EventTypeKey[]).map((key) => (
                  <label key={key} className="hist-multi-option">
                    <input
                      type="checkbox"
                      checked={eventTypes.includes(key)}
                      onChange={() => toggleEventType(key)}
                    />
                    <span>{EVENT_TYPE_LABELS[key]}</span>
                  </label>
                ))}
              </div>
            ) : null}
          </div>
          <label className="hist-field">
            <span>Инициатор</span>
            <select className="hist-select" value={initiator} onChange={(e) => setInitiator(e.target.value)}>
              <option value="">Все</option>
              {Object.entries(INITIATOR_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="hist-field">
            <span>Результат</span>
            <select
              className="hist-select"
              value={status}
              onChange={(e) => setStatus(e.target.value as StatusFilter)}
            >
              <option value="">Все</option>
              <option value="ok">Успешно</option>
              <option value="error">Ошибка</option>
              <option value="canceled">Отменён</option>
              <option value="started">Выполняется</option>
            </select>
          </label>
          <div className="hist-export" ref={exportRef}>
            <button
              className="hist-ghost-btn hist-export-btn"
              type="button"
              disabled={exportBusy}
              onClick={() => setExportOpen((value) => !value)}
            >
              <span className="hist-export-ico" aria-hidden>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              {exportBusy ? 'Экспорт…' : 'Экспорт'}
              <span className="hist-caret" aria-hidden>
                ▾
              </span>
            </button>
            {exportOpen ? (
              <div className="hist-export-menu" role="menu">
                <button type="button" role="menuitem" onClick={() => void runExport('xlsx')}>
                  <span>XLSX — журнал с фильтрами</span>
                  <em className="kpi-export-badge">Рекомендуется</em>
                </button>
                <button type="button" role="menuitem" onClick={() => void runExport('csv')}>
                  <span>CSV — исходные события</span>
                </button>
                <button type="button" role="menuitem" onClick={() => void runExport('pdf')}>
                  <span>PDF — отчёт</span>
                  <em className="kpi-export-badge muted">После MVP</em>
                </button>
                <p className="hist-export-hint">Выгрузка регистрируется в аудите</p>
              </div>
            ) : null}
          </div>
        </div>

        <div className="hist-filters-secondary">
          <label className="hist-search">
            <span className="hist-search-ico" aria-hidden>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
                <path d="M16.5 16.5L21 21" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Найти по названию или ID"
            />
          </label>
          <label className="hist-sort">
            <span className="hist-sort-ico" aria-hidden>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <path
                  d="M8 6h12M8 12h8M8 18h4M4 6v.01M4 12v.01M4 18v.01"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </span>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="newest">Сначала новые</option>
              <option value="oldest">Сначала старые</option>
            </select>
          </label>
          <div className="hist-extra" ref={extraRef}>
            <button
              className="hist-ghost-btn"
              type="button"
              onClick={() => {
                setDraftCorrelation(correlationId)
                setDraftVersion(agentVersion)
                setDraftDurationMin(durationMin)
                setDraftDurationMax(durationMax)
                setExtraOpen((value) => !value)
              }}
            >
              <span className="hist-extra-ico" aria-hidden>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M4 6h16M7 12h10M10 18h4"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
              Доп. фильтры
              {extraActiveCount > 0 ? <em className="hist-extra-badge">{extraActiveCount}</em> : null}
            </button>
            {extraOpen ? (
              <div className="hist-extra-menu">
                <div className="hist-extra-admin">
                  <span className="hist-extra-lock" aria-hidden>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                      <rect x="5" y="11" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.8" />
                      <path
                        d="M8 11V8a4 4 0 118 0v3"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                      />
                    </svg>
                  </span>
                  <span>Только администратору</span>
                </div>
                <label className="hist-field">
                  <span>Correlation ID</span>
                  <input
                    className="hist-input"
                    value={draftCorrelation}
                    onChange={(e) => setDraftCorrelation(e.target.value)}
                    placeholder="Часть run id"
                  />
                </label>
                <label className="hist-field">
                  <span>Версия агента</span>
                  <select
                    className="hist-select"
                    value={draftVersion}
                    onChange={(e) => setDraftVersion(e.target.value)}
                  >
                    <option value="">Любая</option>
                    <option value="v1">v1</option>
                    <option value="v2">v2</option>
                    <option value="latest">latest</option>
                  </select>
                </label>
                <div className="hist-field">
                  <span>Длительность</span>
                  <div className="hist-duration">
                    <input
                      className="hist-input"
                      value={draftDurationMin}
                      onChange={(e) => setDraftDurationMin(e.target.value)}
                      placeholder="Мин, с"
                      inputMode="numeric"
                    />
                    <span>—</span>
                    <input
                      className="hist-input"
                      value={draftDurationMax}
                      onChange={(e) => setDraftDurationMax(e.target.value)}
                      placeholder="Макс, с"
                      inputMode="numeric"
                    />
                  </div>
                </div>
                <div className="hist-extra-actions">
                  <button className="wp-reset-link" type="button" onClick={resetExtraDraft}>
                    Сбросить
                  </button>
                  <button className="btn-primary hist-apply-btn" type="button" onClick={applyExtraFilters}>
                    Применить
                  </button>
                </div>
              </div>
            ) : null}
          </div>
          <div className="hist-chips">
            {chips.map((chip) => (
              <button key={chip.id} type="button" className="wp-chip wp-chip-btn" onClick={chip.onClear}>
                {chip.label}
                <span aria-hidden>×</span>
              </button>
            ))}
            {chips.length ? (
              <button className="wp-reset-link" type="button" onClick={resetFilters}>
                Сбросить
              </button>
            ) : null}
          </div>
        </div>
      </section>

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
