import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowBoard } from '../api/types'
import {
  formatRunTime,
  HISTORY_STATUS_LABELS,
  historyRunStatus
} from '../utils/historyDisplay'
import { parseIso } from '../utils/calendar'

type PeriodKey = 'today' | 'week' | 'month' | 'all'
type DetailTab = 'summary' | 'input' | 'output' | 'logs'
type StatusFilter = '' | 'ok' | 'error' | 'waiting'

const PAGE_SIZE = 10
const DIAG_SESSION_MS = 30 * 60 * 1000
const DIAG_SESSION_KEY = 'orchestrator.diagnostics.sessionUntil'

function dayKey(stamp: Date): string {
  return `${stamp.getFullYear()}-${String(stamp.getMonth() + 1).padStart(2, '0')}-${String(stamp.getDate()).padStart(2, '0')}`
}

function todayKey(): string {
  return dayKey(new Date())
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

function durationSec(run: AgentRunHistoryItem): number | null {
  const total = Number(run.agentWorkMs || 0) + Number(run.humanWaitMs || 0)
  if (total > 0) return Math.round(total / 1000)
  const start = parseIso(run.startedAt)
  const end = parseIso(run.finishedAt)
  if (start && end && end >= start) return Math.round((end.getTime() - start.getTime()) / 1000)
  return null
}

function formatDuration(sec: number | null): string {
  if (sec == null) return '—'
  if (sec < 60) return `${sec} сек`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m} мин ${s} сек` : `${m} мин`
}

function statusTone(key: string): 'ok' | 'error' | 'wait' | 'muted' {
  if (key === 'ok') return 'ok'
  if (key === 'error') return 'error'
  if (key === 'started' || key === 'running' || key === 'waiting_human') return 'wait'
  return 'muted'
}

function statusLabel(key: string): string {
  if (key === 'started' || key === 'running') return 'Ожидает'
  return HISTORY_STATUS_LABELS[key] || key || '—'
}

function maskSecrets(raw: string): string {
  return raw
    .replace(/(["']?(?:password|token|secret|api[_-]?key|инн|inn|snils|email)["']?\s*[:=]\s*["']?)([^"',}\s]+)/gi, (_m, p1, p2) => {
      const text = String(p2)
      if (text.length <= 4) return `${p1}****`
      return `${p1}******${text.slice(-4)}`
    })
    .replace(/\b(\d{6,})(\d{4})\b/g, '******$2')
}

function pickErrorCode(run: AgentRunHistoryItem, events: AgentRunnerEvent[]): string {
  for (const event of events) {
    if (event.error) {
      const code = event.error.split(/[:\s]/)[0]
      if (code && code.length < 40) return code.toUpperCase()
    }
  }
  if (/timeout/i.test(run.message || run.summary || '')) return 'SOURCE_TIMEOUT'
  if (historyRunStatus(run) === 'error') return 'RUN_FAILED'
  return '—'
}

function buildFlow(run: AgentRunHistoryItem, events: AgentRunnerEvent[]): Array<{
  id: string
  title: string
  at: string
  tone: 'ok' | 'error' | 'wait' | 'muted'
}> {
  const start = formatRunTime(run.startedAt) || '—'
  const end = formatRunTime(run.finishedAt) || start
  const key = historyRunStatus(run)
  const steps: Array<{ id: string; title: string; at: string; tone: 'ok' | 'error' | 'wait' | 'muted' }> = [
    { id: 'in', title: 'Вход получен', at: start, tone: 'ok' },
    { id: 'auth', title: 'Проверка доступа', at: start, tone: 'ok' }
  ]
  const tool = events.find((item) => item.type === 'tool' || item.tool)
  if (tool) {
    const failed = tool.ok === false || Boolean(tool.error) || key === 'error'
    steps.push({
      id: 'source',
      title: tool.title || tool.tool || 'Запрос источника',
      at: start,
      tone: failed ? 'wait' : 'ok'
    })
  } else {
    steps.push({
      id: 'work',
      title: 'Выполнение',
      at: start,
      tone: key === 'error' ? 'wait' : key === 'ok' ? 'ok' : 'wait'
    })
  }
  if (key === 'error') {
    steps.push({ id: 'err', title: 'Ошибка', at: end, tone: 'error' })
  } else if (key === 'ok') {
    steps.push({ id: 'done', title: 'Завершено', at: end, tone: 'ok' })
  } else {
    steps.push({ id: 'wait', title: 'Ожидание', at: end, tone: 'wait' })
  }
  return steps
}

function sessionUntil(): number {
  try {
    const raw = sessionStorage.getItem(DIAG_SESSION_KEY)
    const value = raw ? Number(raw) : 0
    return Number.isFinite(value) ? value : 0
  } catch {
    return 0
  }
}

function startSession(): number {
  const until = Date.now() + DIAG_SESSION_MS
  try {
    sessionStorage.setItem(DIAG_SESSION_KEY, String(until))
  } catch {
    /* ignore */
  }
  return until
}

function clearSession(): void {
  try {
    sessionStorage.removeItem(DIAG_SESSION_KEY)
  } catch {
    /* ignore */
  }
}

export function ExecutionDiagnostics({
  onOpenRun,
  onOpenProcess
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  onOpenProcess?: (workflowId: string, title: string) => void
}): React.JSX.Element {
  const today = todayKey()
  const [board, setBoard] = useState<WorkflowBoard | null>(null)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [processId, setProcessId] = useState('')
  const [status, setStatus] = useState<StatusFilter>('')
  const [agentId, setAgentId] = useState('')
  const [period, setPeriod] = useState<PeriodKey>('today')
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [selected, setSelected] = useState('')
  const [events, setEvents] = useState<AgentRunnerEvent[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [tab, setTab] = useState<DetailTab>('summary')
  const [fullPayload, setFullPayload] = useState(false)
  const [note, setNote] = useState('')
  const [until, setUntil] = useState(() => sessionUntil())
  const [now, setNow] = useState(Date.now())

  const diagOn = until > now
  const remainMin = Math.max(0, Math.ceil((until - now) / 60000))

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (until && until <= Date.now()) {
      clearSession()
      setUntil(0)
    }
  }, [until, now])

  useEffect(() => {
    let alive = true
    ;(async () => {
      setLoading(true)
      try {
        const [nextBoard, workflows] = await Promise.all([
          api.getWorkflowBoard(),
          api.listWorkflows().catch(() => [])
        ])
        if (!alive) return
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
        if (!alive) return
        const items = lists
          .flat()
          .filter((item) => item.runId)
          .sort((left, right) => (right.startedAt || '').localeCompare(left.startedAt || ''))
        setRuns(items)
        setError('')
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось загрузить запуски')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const titleOf = (workflowId: string): string =>
    titles[workflowId] || board?.agents.find((item) => item.id === workflowId)?.title || 'ИИ-агент'

  const processOptions = useMemo(() => {
    const seen = new Set<string>()
    const rows: { id: string; title: string }[] = []
    for (const run of runs) {
      if (seen.has(run.workflowId)) continue
      seen.add(run.workflowId)
      rows.push({ id: run.workflowId, title: titleOf(run.workflowId) })
    }
    return rows.sort((a, b) => a.title.localeCompare(b.title, 'ru'))
  }, [runs, titles, board])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return runs.filter((item) => {
      if (!inPeriod(item, period, today)) return false
      if (processId && item.workflowId !== processId) return false
      if (agentId && item.workflowId !== agentId) return false
      const key = historyRunStatus(item)
      if (status === 'ok' && key !== 'ok') return false
      if (status === 'error' && key !== 'error') return false
      if (status === 'waiting' && key !== 'started' && key !== 'running') return false
      if (!q) return true
      return (
        item.runId.toLowerCase().includes(q) ||
        item.workflowId.toLowerCase().includes(q) ||
        titleOf(item.workflowId).toLowerCase().includes(q)
      )
    })
  }, [runs, period, today, processId, agentId, status, query, titles, board])

  const visible = filtered.slice(0, limit)
  const selectedRun = runs.find((item) => item.runId === selected) || null

  useEffect(() => {
    if (!selected) return
    if (!filtered.some((item) => item.runId === selected)) setSelected('')
  }, [filtered, selected])

  useEffect(() => {
    if (!selectedRun) {
      setEvents([])
      return
    }
    let alive = true
    setDetailLoading(true)
    void api
      .getAgentRunDetail(selectedRun.workflowId, selectedRun.runId)
      .then((detail) => {
        if (!alive) return
        setEvents(detail.events)
      })
      .catch(() => {
        if (alive) setEvents([])
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [selectedRun?.workflowId, selectedRun?.runId])

  useEffect(() => {
    if (!note) return
    const t = window.setTimeout(() => setNote(''), 2500)
    return () => window.clearTimeout(t)
  }, [note])

  const flow = selectedRun ? buildFlow(selectedRun, events) : []
  const errorCode = selectedRun ? pickErrorCode(selectedRun, events) : '—'
  const selectedKey = selectedRun ? historyRunStatus(selectedRun) : ''
  const selectedTone = statusTone(selectedKey)

  const inputJson = useMemo(() => {
    if (!selectedRun) return ''
    const payload = {
      runId: selectedRun.runId,
      workflowId: selectedRun.workflowId,
      source: selectedRun.source || '',
      triggerKind: selectedRun.triggerKind || '',
      triggerReason: selectedRun.triggerReason || '',
      startedAt: selectedRun.startedAt || ''
    }
    const text = JSON.stringify(payload, null, 2)
    return fullPayload ? text : maskSecrets(text)
  }, [selectedRun, fullPayload])

  const outputJson = useMemo(() => {
    if (!selectedRun) return ''
    const payload = {
      status: selectedRun.status,
      message: selectedRun.message || '',
      summary: (selectedRun.summary || selectedRun.answer || '').slice(0, 1200),
      errorCode: selectedKey === 'error' ? errorCode : undefined,
      finishedAt: selectedRun.finishedAt || ''
    }
    const text = JSON.stringify(payload, null, 2)
    return fullPayload ? text : maskSecrets(text)
  }, [selectedRun, selectedKey, errorCode, fullPayload])

  const logsText = useMemo(() => {
    if (!events.length) return 'Событий прогона нет.'
    const lines = events.map((item, idx) => {
      const parts = [
        `#${idx + 1}`,
        item.type || 'event',
        item.tool || item.title || '',
        item.error || item.message || item.text || item.answer || ''
      ].filter(Boolean)
      return parts.join(' · ')
    })
    const text = lines.join('\n')
    return fullPayload ? text : maskSecrets(text)
  }, [events, fullPayload])

  async function copyText(text: string, okNote: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text)
      setNote(okNote)
    } catch {
      setNote('Не удалось скопировать')
    }
  }

  async function exportJson(): Promise<void> {
    if (!selectedRun) return
    const payload = {
      run: selectedRun,
      events,
      exportedAt: new Date().toISOString()
    }
    const text = JSON.stringify(payload, null, 2)
    try {
      const res = await window.api.saveLocalFile({
        defaultName: `diag-${selectedRun.runId}.json`,
        text,
        filters: [{ name: 'JSON', extensions: ['json'] }]
      })
      if (res.canceled) return
      if (!res.ok) throw new Error(res.error || 'Ошибка сохранения')
      setNote('JSON экспортирован')
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'Ошибка экспорта')
    }
  }

  return (
    <div className="edx-page">
      <div className="edx-top-meta">
        <span className="edx-pill">Концепт · демо-данные</span>
        <span className="edx-pill">Только администратору</span>
      </div>

      {diagOn ? (
        <div className="edx-banner">
          <div className="edx-banner-text">
            <span className="edx-banner-ico" aria-hidden>
              ⚠
            </span>
            <span>
              Диагностический режим включён. Сеанс автоматически завершится через{' '}
              <strong>{remainMin} мин</strong>
            </span>
          </div>
          <button
            className="edx-banner-off"
            type="button"
            onClick={() => {
              clearSession()
              setUntil(0)
            }}
          >
            Выключить
          </button>
        </div>
      ) : (
        <div className="edx-banner edx-banner-off-state">
          <div className="edx-banner-text">
            <span className="edx-banner-ico" aria-hidden>
              ⚠
            </span>
            <span>Диагностический режим выключен. Включите, чтобы просматривать детали запусков.</span>
          </div>
          <button
            className="edx-banner-off"
            type="button"
            onClick={() => setUntil(startSession())}
          >
            Включить
          </button>
        </div>
      )}

      <p className="edx-audit">
        <span aria-hidden>ⓘ</span> Все просмотры и выгрузки регистрируются в аудите
      </p>

      <header className="edx-head">
        <h1 className="page-title">Диагностика выполнения</h1>
      </header>

      <section className="edx-filters">
        <label className="edx-field">
          <span>Процесс</span>
          <select value={processId} onChange={(e) => setProcessId(e.target.value)}>
            <option value="">Все процессы</option>
            {processOptions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <label className="edx-field">
          <span>Статус</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            <option value="">Все статусы</option>
            <option value="ok">Успешно</option>
            <option value="error">Ошибка</option>
            <option value="waiting">Ожидает</option>
          </select>
        </label>
        <label className="edx-field">
          <span>Агент</span>
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">Все агенты</option>
            {processOptions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <label className="edx-field">
          <span>Период</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value as PeriodKey)}>
            <option value="today">Сегодня</option>
            <option value="week">7 дней</option>
            <option value="month">30 дней</option>
            <option value="all">Весь период</option>
          </select>
        </label>
        <label className="edx-field edx-field-search">
          <span>Run ID / Correlation ID</span>
          <span className="edx-search">
            <span className="edx-search-ico" aria-hidden>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
                <path d="M16.5 16.5L21 21" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Введите ID"
            />
          </span>
        </label>
      </section>

      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      {note ? <div className="edx-note">{note}</div> : null}

      <div className="edx-layout">
        <aside className="edx-list-card">
          <h2>Последние запуски</h2>
          <div className="edx-list-head">
            <span>Время</span>
            <span>Процесс</span>
            <span>Агент</span>
            <span>Статус</span>
            <span>Длительность</span>
          </div>
          <div className="edx-list-scroll">
            {loading ? <p className="edx-empty">Загружаем запуски…</p> : null}
            {!loading && !visible.length ? <p className="edx-empty">Нет запусков по фильтру.</p> : null}
            {visible.map((item) => {
              const key = historyRunStatus(item)
              const tone = statusTone(key)
              const active = selected === item.runId
              return (
                <button
                  key={item.runId}
                  type="button"
                  className={`edx-list-row${active ? ' active' : ''}`}
                  onClick={() => {
                    if (!diagOn) {
                      setUntil(startSession())
                    }
                    setSelected(item.runId)
                    setTab('summary')
                  }}
                >
                  <span>{formatRunTime(item.startedAt) || '—'}</span>
                  <span title={titleOf(item.workflowId)}>{titleOf(item.workflowId)}</span>
                  <span title={item.workflowId}>{item.workflowId.slice(0, 10)}</span>
                  <span className={`edx-status ${tone}`}>
                    <i />
                    {statusLabel(key)}
                  </span>
                  <span>{formatDuration(durationSec(item))}</span>
                </button>
              )
            })}
          </div>
          <div className="edx-list-foot">
            <span>
              Показано {visible.length} из {filtered.length} запусков
            </span>
            {visible.length < filtered.length ? (
              <button className="edx-link" type="button" onClick={() => setLimit((value) => value + PAGE_SIZE)}>
                Загрузить ещё
              </button>
            ) : null}
          </div>
        </aside>

        <section className="edx-detail-card">
          {!selectedRun ? (
            <div className="edx-detail-empty">Выберите запуск слева, чтобы увидеть детали.</div>
          ) : (
            <>
              <div className="edx-detail-head">
                <h2>Детали запуска</h2>
                <span className={`edx-badge ${selectedTone}`}>{statusLabel(selectedKey)}</span>
              </div>

              <div className="edx-meta-grid">
                <div>
                  <span>ID экземпляра процесса</span>
                  <strong>{selectedRun.workflowId}</strong>
                </div>
                <div>
                  <span>Run ID</span>
                  <strong className="edx-mono">{selectedRun.runId}</strong>
                </div>
                <div>
                  <span>Статус</span>
                  <strong className={`edx-status ${selectedTone}`}>
                    <i />
                    {statusLabel(selectedKey)}
                  </strong>
                </div>
                <div>
                  <span>ID задачи</span>
                  <strong>{selectedRun.triggerKind || '—'}</strong>
                </div>
                <div>
                  <span>Correlation ID</span>
                  <strong className="edx-mono">{selectedRun.runId.slice(0, 18)}</strong>
                </div>
                <div>
                  <span>Начат</span>
                  <strong>{formatRunTime(selectedRun.startedAt) || '—'}</strong>
                </div>
                <div>
                  <span>ID агента</span>
                  <strong>{selectedRun.workflowId.slice(0, 12)}</strong>
                </div>
                <div>
                  <span>Попытка</span>
                  <strong>1 из 1</strong>
                </div>
                <div>
                  <span>Завершён</span>
                  <strong>{formatRunTime(selectedRun.finishedAt) || '—'}</strong>
                </div>
                <div>
                  <span>Версия</span>
                  <strong>v1</strong>
                </div>
                <div>
                  <span>Источник / интеграция</span>
                  <strong>{selectedRun.source || selectedRun.triggerKind || '—'}</strong>
                </div>
                <div>
                  <span>Длительность</span>
                  <strong>{formatDuration(durationSec(selectedRun))}</strong>
                </div>
                {selectedKey === 'error' ? (
                  <div className="edx-meta-error">
                    <span>Код ошибки</span>
                    <strong>{errorCode}</strong>
                  </div>
                ) : null}
              </div>

              <div className="edx-flow">
                <h3>Ход выполнения</h3>
                <div className="edx-flow-track">
                  {flow.map((step, idx) => (
                    <div key={step.id} className={`edx-flow-step ${step.tone}`}>
                      {idx > 0 ? <span className="edx-flow-line" aria-hidden /> : null}
                      <span className="edx-flow-dot" aria-hidden>
                        {step.tone === 'ok' ? '✓' : step.tone === 'error' ? '×' : '↻'}
                      </span>
                      <strong>{step.title}</strong>
                      <em>{step.at}</em>
                    </div>
                  ))}
                </div>
              </div>

              <div className="edx-tabs">
                {(
                  [
                    ['summary', 'Сводка'],
                    ['input', 'Вход'],
                    ['output', 'Выход'],
                    ['logs', 'Логи']
                  ] as Array<[DetailTab, string]>
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={tab === id ? 'active' : ''}
                    onClick={() => setTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {detailLoading ? <p className="edx-empty">Загружаем детали…</p> : null}

              {tab === 'summary' ? (
                <div className="edx-payload-grid">
                  <div className="edx-code-card">
                    <div className="edx-code-head">
                      <span>Вход {fullPayload ? '' : '(маскировано)'}</span>
                      <button
                        type="button"
                        className="edx-icon-btn"
                        title="Копировать"
                        onClick={() => void copyText(inputJson, 'Вход скопирован')}
                      >
                        ⎘
                      </button>
                    </div>
                    <pre>{inputJson}</pre>
                  </div>
                  <div className="edx-code-card">
                    <div className="edx-code-head">
                      <span>Выход {fullPayload ? '' : '(маскировано)'}</span>
                      <button
                        type="button"
                        className="edx-icon-btn"
                        title="Копировать"
                        onClick={() => void copyText(outputJson, 'Выход скопирован')}
                      >
                        ⎘
                      </button>
                    </div>
                    <pre>{outputJson}</pre>
                  </div>
                  <aside className="edx-secure">
                    <div className="edx-secure-title">
                      <span aria-hidden>🛡</span> Секреты и ПДн маскируются
                    </div>
                    <p>Данные скрыты в соответствии с политиками безопасности.</p>
                    <label className={`edx-payload-toggle${fullPayload ? ' on' : ''}`}>
                      <input
                        type="checkbox"
                        checked={fullPayload}
                        onChange={(e) => setFullPayload(e.target.checked)}
                      />
                      <span className="edx-switch" aria-hidden />
                      <span>
                        Полный payload
                        <em>Доступ: diagnostics.payload.read</em>
                      </span>
                    </label>
                  </aside>
                </div>
              ) : null}

              {tab === 'input' ? (
                <div className="edx-code-card edx-code-wide">
                  <div className="edx-code-head">
                    <span>Вход {fullPayload ? '' : '(маскировано)'}</span>
                  </div>
                  <pre>{inputJson}</pre>
                </div>
              ) : null}
              {tab === 'output' ? (
                <div className="edx-code-card edx-code-wide">
                  <div className="edx-code-head">
                    <span>Выход {fullPayload ? '' : '(маскировано)'}</span>
                  </div>
                  <pre>{outputJson}</pre>
                </div>
              ) : null}
              {tab === 'logs' ? (
                <div className="edx-code-card edx-code-wide">
                  <div className="edx-code-head">
                    <span>Логи {fullPayload ? '' : '(маскировано)'}</span>
                  </div>
                  <pre>{logsText}</pre>
                </div>
              ) : null}

              <div className="edx-actions">
                <button
                  className="edx-ghost-btn"
                  type="button"
                  onClick={() => void copyText(selectedRun.runId, 'Run ID скопирован')}
                >
                  Копировать ID
                </button>
                <button className="edx-ghost-btn" type="button" onClick={() => void exportJson()}>
                  Экспортировать JSON
                </button>
                <button
                  className="btn-primary edx-primary-btn"
                  type="button"
                  onClick={() => onOpenRun(selectedRun.workflowId, titleOf(selectedRun.workflowId), '')}
                >
                  ↻ Повторить запуск
                </button>
                <button
                  className="edx-ghost-btn"
                  type="button"
                  onClick={() =>
                    onOpenProcess
                      ? onOpenProcess(selectedRun.workflowId, titleOf(selectedRun.workflowId))
                      : onOpenRun(selectedRun.workflowId, titleOf(selectedRun.workflowId), selectedRun.runId)
                  }
                >
                  Открыть процесс ↗
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
