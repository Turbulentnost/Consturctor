import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowBoard } from '../api/types'
import { historyResultText } from '../pages/historyDetail'
import { formatKpiRangeLabel, KpiRangePicker } from '../pages/KpiRangePicker'
import { cleanRunResult } from '../utils/cleanRunResult'
import {
  formatRunTime,
  formatRunWhen,
  HISTORY_STATUS_LABELS,
  historyRunStatus,
  statusPillClass
} from '../utils/historyDisplay'
import { parseIso } from '../utils/calendar'

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

type StatusFilter = '' | 'ok' | 'error' | 'canceled' | 'started'
type SortKey = 'newest' | 'oldest'
type EventTypeKey = 'schedule' | 'event' | 'manual' | 'chat' | 'hitl'

function dayKey(stamp: Date): string {
  return `${stamp.getFullYear()}-${String(stamp.getMonth() + 1).padStart(2, '0')}-${String(stamp.getDate()).padStart(2, '0')}`
}

function todayKey(): string {
  return dayKey(new Date())
}

const EVENT_TYPE_LABELS: Record<EventTypeKey, string> = {
  schedule: 'Расписание',
  event: 'Событие',
  manual: 'Вручную',
  chat: 'Чат',
  hitl: 'Решение человека'
}

const INITIATOR_LABELS: Record<string, string> = {
  employee: 'Сотрудник',
  agent: 'ИИ-агент',
  schedule: 'Расписание',
  system: 'Система'
}

function runEventType(run: AgentRunHistoryItem): EventTypeKey {
  const source = (run.source || '').toLowerCase()
  const kind = (run.triggerKind || '').toLowerCase()
  if (source === 'chat' || kind === 'chat') return 'chat'
  if (source === 'manual' || kind === 'manual') return 'manual'
  if (source === 'event' || kind === 'event') return 'event'
  if (source.includes('hitl') || kind.includes('hitl') || source.includes('human')) return 'hitl'
  return 'schedule'
}

function runInitiator(run: AgentRunHistoryItem): string {
  const source = (run.source || '').toLowerCase()
  const kind = (run.triggerKind || '').toLowerCase()
  if (source === 'manual' || source === 'chat' || kind === 'manual' || kind === 'chat') return 'employee'
  if (source === 'schedule' || kind === 'schedule') return 'schedule'
  if (source === 'event') return 'system'
  return 'agent'
}

function processCode(workflowId: string): string {
  const raw = (workflowId || '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase()
  const tail = (raw.slice(-5) || '00000').padStart(5, '0')
  return `PR-${tail}`
}

function eventTitleForRun(run: AgentRunHistoryItem): string {
  const status = historyRunStatus(run)
  const type = runEventType(run)
  if (status === 'error') return 'Ошибка агента'
  if (type === 'hitl') return status === 'ok' ? 'Решение подтверждено' : 'Ожидает подтверждения'
  if (status === 'started' || status === 'running') {
    return type === 'schedule' ? 'Запуск по расписанию' : 'Выполнение задачи'
  }
  if (type === 'schedule' && status === 'ok') return 'Задача выполнена'
  if (type === 'manual') return 'Запуск вручную'
  if (type === 'chat') return 'Запуск из чата'
  if (status === 'ok') return 'Задача выполнена'
  if (status === 'canceled' || status === 'cancelled') return 'Запуск отменён'
  return 'Событие запуска'
}

function initiatorDisplay(run: AgentRunHistoryItem, processTitle: string): string {
  const key = runInitiator(run)
  if (key === 'employee') return 'Сотрудник'
  if (key === 'schedule') return 'Расписание'
  if (key === 'system') return 'Система'
  return `ИИ-агент «${processTitle}»`
}

function runDurationSec(run: AgentRunHistoryItem): number | null {
  const total = Number(run.agentWorkMs || 0) + Number(run.humanWaitMs || 0)
  if (total > 0) return Math.round(total / 1000)
  const start = parseIso(run.startedAt)
  const end = parseIso(run.finishedAt)
  if (start && end && end >= start) return Math.round((end.getTime() - start.getTime()) / 1000)
  return null
}

function orderedDayKeys(from: string, to: string): { from: string; to: string } {
  return from <= to ? { from, to } : { from: to, to: from }
}

function inDateRange(run: AgentRunHistoryItem, from: string, to: string): boolean {
  if (!from || !to) return false
  const stamp = parseIso(run.startedAt || run.finishedAt)
  if (!stamp) return false
  const key = dayKey(stamp)
  const range = orderedDayKeys(from, to)
  return key >= range.from && key <= range.to
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
  const [rangeFrom, setRangeFrom] = useState(today)
  const [rangeTo, setRangeTo] = useState(today)
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
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
  const [detailLoading, setDetailLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(20)
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
      if (!inDateRange(item, rangeFrom, rangeTo)) return false
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
      const eventName = eventTitleForRun(item).toLowerCase()
      return (
        title.includes(q) ||
        eventName.includes(q) ||
        item.runId.toLowerCase().includes(q) ||
        item.workflowId.toLowerCase().includes(q)
      )
    })
    rows.sort((left, right) => {
      const cmp = (right.startedAt || '').localeCompare(left.startedAt || '')
      return sort === 'newest' ? cmp : -cmp
    })
    return rows
  }, [
    runs,
    query,
    rangeFrom,
    rangeTo,
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

  function resetFilters(): void {
    setQuery('')
    const key = todayKey()
    setRangeFrom(key)
    setRangeTo(key)
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
        event: eventTitleForRun(item),
        initiator: initiatorDisplay(item, titleOf(item.workflowId)),
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
      label:
        rangeFrom !== today || rangeTo !== today
          ? `Период: ${formatKpiRangeLabel(rangeFrom, rangeTo)}`
          : '',
      onClear: () => {
        setRangeFrom(today)
        setRangeTo(today)
      }
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
    setPage(1)
  }, [
    query,
    rangeFrom,
    rangeTo,
    agentId,
    eventTypes,
    initiator,
    status,
    correlationId,
    agentVersion,
    durationMin,
    durationMax,
    sort,
    pageSize
  ])

  const totalPages = Math.max(1, Math.ceil(visible.length / pageSize))
  const pageSafe = Math.min(page, totalPages)
  const pageRows = useMemo(() => {
    const start = (pageSafe - 1) * pageSize
    return visible.slice(start, start + pageSize)
  }, [visible, pageSafe, pageSize])

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
      return
    }
    const run = runs.find((item) => item.runId === selected)
    if (!run) {
      setAnswer('')
      setEvents([])
      return
    }
    let alive = true
    setDetailLoading(true)
    void api
      .getAgentRunDetail(run.workflowId, selected)
      .then((detail) => {
        if (!alive) return
        const stored = (detail.item.answer || detail.item.summary || '').trim()
        const text = historyResultText(stored, detail.events)
        setAnswer(text)
        setEvents(detail.events)
      })
      .catch(() => {
        if (!alive) return
        setAnswer('')
        setEvents([])
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
  const selectedTitle = selectedRun ? titleOf(selectedRun.workflowId) : ''
  const selectedEventTitle = selectedRun ? eventTitleForRun(selectedRun) : ''
  const selectedInitiator = selectedRun ? initiatorDisplay(selectedRun, selectedTitle) : ''
  const selectedProcessCode = selectedRun ? processCode(selectedRun.workflowId) : ''
  const showDecisionFlow = selectedRun
    ? runEventType(selectedRun) === 'hitl' || selectedEventTitle.includes('Решение')
    : false
  const pageNumbers = useMemo(() => {
    const maxButtons = 5
    const start = Math.max(1, Math.min(pageSafe - 2, totalPages - maxButtons + 1))
    const end = Math.min(totalPages, start + maxButtons - 1)
    const list: number[] = []
    for (let i = start; i <= end; i += 1) list.push(i)
    return list
  }, [pageSafe, totalPages])

  return (
    <div className="wp-page wp-history">
      <div className="wp-head">
        <div>
          <h1 className="page-title">История</h1>
          <div className="wp-sub">Единый журнал событий, задач и решений</div>
        </div>
        <span className="orch-badge">{loading ? 'загрузка' : `${visible.length} событий`}</span>
      </div>
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      {exportNote ? <div className="hist-export-note">{exportNote}</div> : null}

      <section className="hist-filters">
        <div className="hist-filters-primary">
          <div className="hist-field">
            <span>Период</span>
            <div className="hist-range-picker">
              <KpiRangePicker
                from={rangeFrom}
                to={rangeTo}
                showShortcuts={false}
                onApply={({ from, to }) => {
                  setRangeFrom(from)
                  setRangeTo(to)
                }}
              />
            </div>
          </div>
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
              <span>Все</span>
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
        <section className="hist-events-panel">
          <div className="hist-events-head">
            <h2>События</h2>
            <span className="hist-events-count">{visible.length}</span>
          </div>
          <div className="hist-events-scroll">
            {loading && !runs.length ? <p className="wp-history-empty">Загружаем журнал…</p> : null}
            {!loading && !visible.length ? (
              <p className="wp-history-empty">
                {runs.length ? 'Нет событий по текущему фильтру.' : 'Событий ещё не было.'}
              </p>
            ) : null}
            {pageRows.length ? (
              <table className="hist-events-table">
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Процесс</th>
                    <th>Событие</th>
                    <th>Инициатор</th>
                    <th>Результат</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((item) => {
                    const key = historyRunStatus(item)
                    const processTitle = titleOf(item.workflowId)
                    const active = selected === item.runId
                    return (
                      <tr
                        key={item.runId}
                        className={active ? 'active' : undefined}
                        onClick={() => setSelected(item.runId)}
                      >
                        <td className="hist-col-time">
                          <span className={`hist-dot hist-dot-${key}`} aria-hidden />
                          {formatRunTime(item.startedAt) || '—'}
                        </td>
                        <td>
                          <div className="hist-process-cell">
                            <strong>{processTitle}</strong>
                            <span>ID: {processCode(item.workflowId)}</span>
                          </div>
                        </td>
                        <td>{eventTitleForRun(item)}</td>
                        <td>{initiatorDisplay(item, processTitle)}</td>
                        <td>
                          <span className={`wp-pill ${statusPillClass(key)}`}>
                            {HISTORY_STATUS_LABELS[key] || 'Отменён'}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : null}
          </div>
          {visible.length > 0 ? (
            <div className="hist-pager">
              <span className="hist-pager-range">
                {(pageSafe - 1) * pageSize + 1}–{Math.min(pageSafe * pageSize, visible.length)} из{' '}
                {visible.length}
              </span>
              <div className="hist-pager-pages">
                <button
                  type="button"
                  className="hist-pager-btn"
                  disabled={pageSafe <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  ‹
                </button>
                {pageNumbers.map((num) => (
                  <button
                    key={num}
                    type="button"
                    className={num === pageSafe ? 'hist-pager-btn active' : 'hist-pager-btn'}
                    onClick={() => setPage(num)}
                  >
                    {num}
                  </button>
                ))}
                {pageNumbers[pageNumbers.length - 1] < totalPages ? (
                  <>
                    <span className="hist-pager-ellipsis">…</span>
                    <button type="button" className="hist-pager-btn" onClick={() => setPage(totalPages)}>
                      {totalPages}
                    </button>
                  </>
                ) : null}
                <button
                  type="button"
                  className="hist-pager-btn"
                  disabled={pageSafe >= totalPages}
                  onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                >
                  ›
                </button>
              </div>
              <label className="hist-pager-size">
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value) as (typeof PAGE_SIZE_OPTIONS)[number])}
                >
                  {PAGE_SIZE_OPTIONS.map((size) => (
                    <option key={size} value={size}>
                      {size} на странице
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
        </section>

        <aside className="hist-detail-panel">
          {!selectedRun ? (
            <div className="wp-history-result-empty">Выберите событие в таблице, чтобы открыть карточку.</div>
          ) : (
            <>
              <div className="hist-detail-head">
                <h2>{selectedEventTitle}</h2>
                <span className={`wp-pill ${statusPillClass(selectedStatus)}`}>
                  {HISTORY_STATUS_LABELS[selectedStatus] || selectedStatus || '—'}
                </span>
              </div>
              <dl className="hist-detail-meta">
                <div>
                  <dt>ID события</dt>
                  <dd>{selectedRun.runId}</dd>
                </div>
                <div>
                  <dt>Процесс</dt>
                  <dd>
                    <button
                      type="button"
                      className="hist-link"
                      onClick={() => onOpenRun(selectedRun.workflowId, selectedTitle, selectedRun.runId)}
                    >
                      {selectedTitle}
                    </button>
                    <span className="hist-meta-sub">ID: {selectedProcessCode}</span>
                  </dd>
                </div>
                <div>
                  <dt>Задача</dt>
                  <dd>RUN-{selectedRun.runId.slice(-6).toUpperCase()}</dd>
                </div>
                <div>
                  <dt>Инициатор</dt>
                  <dd>{selectedInitiator}</dd>
                </div>
                <div>
                  <dt>Время</dt>
                  <dd>{selectedRun.startedAt ? formatRunWhen(selectedRun.startedAt) : '—'}</dd>
                </div>
              </dl>

              {showDecisionFlow ? (
                <div className="hist-flow">
                  <div className="hist-flow-step muted">Ожидает подтверждения</div>
                  <span className="hist-flow-arrow" aria-hidden>
                    →
                  </span>
                  <div className={`hist-flow-step ${selectedStatus === 'ok' ? 'ok' : 'muted'}`}>
                    {selectedStatus === 'ok' ? 'Подтверждено' : 'Не подтверждено'}
                  </div>
                </div>
              ) : (
                <div className="hist-flow">
                  <div className="hist-flow-step muted">Запуск</div>
                  <span className="hist-flow-arrow" aria-hidden>
                    →
                  </span>
                  <div
                    className={`hist-flow-step ${
                      selectedStatus === 'ok' ? 'ok' : selectedStatus === 'error' ? 'error' : 'muted'
                    }`}
                  >
                    {HISTORY_STATUS_LABELS[selectedStatus] || 'В работе'}
                  </div>
                </div>
              )}

              <div className="hist-detail-comment">
                <h3>Комментарий</h3>
                {detailLoading ? (
                  <p>Загружаем детали…</p>
                ) : (
                  <p>
                    {(cleaned.text || selectedRun.summary || selectedRun.message || '').trim() ||
                      'Комментарий к событию не указан.'}
                  </p>
                )}
              </div>

              <button
                type="button"
                className="hist-decision-link"
                onClick={() => onOpenRun(selectedRun.workflowId, selectedTitle, selectedRun.runId)}
              >
                Перейти к запуску #{selectedRun.runId.slice(-8).toUpperCase()}
              </button>

              <div className="hist-detail-lock">
                <span aria-hidden>🔒</span>
                <span>Данные и payload события скрыты из соображений безопасности</span>
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
