import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  AgentRunHistoryItem,
  AppHealth,
  ChatThread,
  SupportTicketItem,
  ToolStatus,
  UserProfile,
  WorkflowFileItem,
  WorkflowHealthInfo
} from '../api/types'
import { FilterBar } from './FilterBar'
import { HistoryWorkplace } from './HistoryWorkplace'
import { STATUS_LABEL, TICKET_STATUS_LABEL, type ProcessStatus } from './labels'
import { TodayWorkplace, useWorkplaceData } from './WorkplaceBoard'
import { humanWhen, parseIso, windowFor } from '../utils/calendar'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'

type NotificationViewMode = 'comfortable' | 'compact'

interface NotificationViewSettings {
  mode: NotificationViewMode
  showSender: boolean
  showTime: boolean
  highlightUnread: boolean
}

function notificationSettingsKey(userId: string): string {
  return `orchestrator.notifications.view.${(userId || 'local').trim() || 'local'}`
}

function loadNotificationSettings(userId: string): NotificationViewSettings {
  const fallback: NotificationViewSettings = {
    mode: 'comfortable',
    showSender: true,
    showTime: true,
    highlightUnread: true
  }
  try {
    const raw = localStorage.getItem(notificationSettingsKey(userId))
    if (!raw) return fallback
    const data = JSON.parse(raw) as Partial<NotificationViewSettings>
    const mode: NotificationViewMode = data.mode === 'compact' ? 'compact' : 'comfortable'
    return {
      mode,
      showSender: data.showSender !== false,
      showTime: data.showTime !== false,
      highlightUnread: data.highlightUnread !== false
    }
  } catch {
    return fallback
  }
}

function saveNotificationSettings(userId: string, settings: NotificationViewSettings): void {
  try {
    localStorage.setItem(notificationSettingsKey(userId), JSON.stringify(settings))
  } catch {
    /* ignore local storage errors */
  }
}

function Head({
  title,
  count,
  badge
}: {
  title: string
  count?: number
  badge?: string
}): React.JSX.Element {
  return (
    <div className="wp-head">
      <div>
        <h1 className="page-title">{title}</h1>
      </div>
      {badge ? <span className="orch-badge">{badge}</span> : null}
      {count != null && <span className="wp-count">{count}</span>}
    </div>
  )
}

function ticketToThread(item: SupportTicketItem): ChatThread {
  return {
    id: item.threadId || 'support',
    kind: 'support',
    title: item.authorFio || 'Техническая поддержка',
    position: item.authorPosition,
    preview: item.preview,
    lastMessageAt: item.queuedAt,
    unread: 0,
    pinned: true,
    peerId: item.authorId,
    activityStatus: '',
    online: false,
    ticketStatus: item.status,
    avatarUrl: null
  }
}

function compactDecisionSummary(run: AgentRunHistoryItem | null): string {
  if (!run) return 'Результат не содержит краткого текста. Откройте материалы для деталей.'
  const raw = String(run.summary || run.answer || '')
    .replace(/\s+/g, ' ')
    .replace(/\bTESTS:\s*(PASS|FAIL)\b/gi, '')
    .trim()
  if (!raw) return 'Результат не содержит краткого текста. Откройте материалы для деталей.'
  const parts = raw.split(/(?<=[.!?])\s+/).filter(Boolean)
  let text = parts[0] || raw
  if (text.length < 80 && parts.length > 1) text = `${parts[0]} ${parts[1]}`
  if (text.length > 260) text = `${text.slice(0, 259).trimEnd()}…`
  return text
}

export function TodayTab({
  user,
  onOpenDecisions,
  onOpenMetrics,
  onOpen,
  onRun,
  onOpenFiles
}: {
  user: UserProfile
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpen: (workflowId: string, title: string) => void
  onRun: (workflowId: string, title: string) => void
  onOpenFiles: (workflowId: string, title: string) => void
}): React.JSX.Element {
  return (
    <TodayWorkplace
      userId={user.id || ''}
      userFio={user.fio || ''}
      onOpenDecisions={onOpenDecisions}
      onOpenMetrics={onOpenMetrics}
      onOpen={onOpen}
      onRun={onRun}
      onOpenFiles={onOpenFiles}
    />
  )
}

export function DecisionsTab({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const [agentFilter, setAgentFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'waiting' | 'done' | 'returned'>('all')
  const [sortBy, setSortBy] = useState<'deadline_asc' | 'deadline_desc' | 'status' | 'agent'>('deadline_asc')
  const [duePanelOpen, setDuePanelOpen] = useState(false)
  const [dueFilter, setDueFilter] = useState('')
  const [dueAnchor, setDueAnchor] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [runByAgent, setRunByAgent] = useState<Record<string, AgentRunHistoryItem | null>>({})
  const [agentFilesByRun, setAgentFilesByRun] = useState<Record<string, WorkflowFileItem[]>>({})
  const loadedRunFilesRef = useRef<Record<string, boolean>>({})
  const { agents, loading, error } = useWorkplaceData()
  const scopedAgents = useMemo(() => {
    const q = query.trim().toLowerCase()
    return agents.filter((item) => {
      if (agentFilter && item.workflowId !== agentFilter) return false
      if (q && !`${item.name} ${item.workflowId}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [agents, query, agentFilter])

  useEffect(() => {
    let alive = true
    void Promise.all(
      scopedAgents.map(async (item) => {
        const runs = await api.listAgentRuns(item.workflowId).catch(() => [] as AgentRunHistoryItem[])
        return [item.workflowId, runs[0] || null] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const next: Record<string, AgentRunHistoryItem | null> = {}
      for (const [id, run] of pairs) next[id] = run
      setRunByAgent(next)
    })
    return () => {
      alive = false
    }
  }, [scopedAgents])

  const decisionRows = useMemo(() => {
    const now = new Date()
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const sameDay = (left: Date, right: Date): boolean =>
      left.getFullYear() === right.getFullYear() &&
      left.getMonth() === right.getMonth() &&
      left.getDate() === right.getDate()
    return scopedAgents.map((agent) => {
      const run = runByAgent[agent.workflowId] || null
      const statusRaw = `${run?.status || agent.status || ''}`.toLowerCase()
      const bucket: 'waiting' | 'done' | 'returned' | 'review' =
        statusRaw.includes('return') ||
        statusRaw.includes('reject') ||
        statusRaw.includes('cancel')
          ? 'returned'
          : statusRaw.includes('wait') ||
              statusRaw.includes('hitl') ||
              statusRaw.includes('attention') ||
              statusRaw.includes('error') ||
              statusRaw.includes('fail')
            ? 'waiting'
            : statusRaw.includes('ok') ||
                statusRaw.includes('done') ||
                statusRaw.includes('success') ||
                statusRaw.includes('complete')
              ? 'done'
              : 'review'
      const needsHuman = bucket === 'waiting' || bucket === 'returned' || agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR'
      const deadlineStamp =
        parseIso(agent.boardAgent?.nextRunAt || '') ||
        parseIso(run?.startedAt || run?.finishedAt || '')
      const dateKey = deadlineStamp
        ? `${deadlineStamp.getFullYear()}-${String(deadlineStamp.getMonth() + 1).padStart(2, '0')}-${String(deadlineStamp.getDate()).padStart(2, '0')}`
        : ''
      const doneToday = bucket === 'done' && Boolean(deadlineStamp && sameDay(deadlineStamp, todayStart))
      return { agent, run, bucket, needsHuman, deadlineStamp, dateKey, doneToday }
    })
  }, [scopedAgents, runByAgent])

  const visibleRows = useMemo(() => {
    const rows = decisionRows
      .filter((row) => {
        if (statusFilter !== 'all' && row.bucket !== statusFilter) return false
        if (dueFilter && row.dateKey !== dueFilter) return false
        return true
      })
      .sort((left, right) => {
        if (sortBy === 'agent') return left.agent.name.localeCompare(right.agent.name, 'ru')
        if (sortBy === 'status') return left.bucket.localeCompare(right.bucket)
        const leftTs = left.deadlineStamp ? left.deadlineStamp.getTime() : 0
        const rightTs = right.deadlineStamp ? right.deadlineStamp.getTime() : 0
        return sortBy === 'deadline_desc' ? rightTs - leftTs : leftTs - rightTs
      })
    return rows
  }, [decisionRows, statusFilter, dueFilter, sortBy])

  const waiting = useMemo(() => visibleRows.filter((item) => item.needsHuman), [visibleRows])
  const latestResults = useMemo(() => visibleRows.filter((item) => item.run), [visibleRows])

  useEffect(() => {
    const targets = latestResults
      .map(({ agent, run }) => ({
        workflowId: agent.workflowId,
        runId: String(run?.runId || '').trim()
      }))
      .filter((item) => item.workflowId && item.runId)
      .filter((item) => !loadedRunFilesRef.current[`${item.workflowId}:${item.runId}`])
      .slice(0, 20)
    if (!targets.length) return
    let alive = true
    void Promise.all(
      targets.map(async (item) => {
        const key = `${item.workflowId}:${item.runId}`
        loadedRunFilesRef.current[key] = true
        const files = await api.listWorkflowFiles(item.workflowId, item.runId).catch(
          () => [] as WorkflowFileItem[]
        )
        const produced = files.filter((file) => {
          const source = String(file.source || '').toLowerCase()
          const origin = String(file.origin || '').toLowerCase()
          return source === 'agent' || source === 'result' || origin.includes('agent')
        })
        return [key, produced] as const
      })
    ).then((rows) => {
      if (!alive) return
      setAgentFilesByRun((prev) => {
        const next = { ...prev }
        for (const [key, files] of rows) next[key] = files
        return next
      })
    })
    return () => {
      alive = false
    }
  }, [latestResults])

  const counters = useMemo(() => {
    let waitingMine = 0
    let onReview = 0
    let confirmedToday = 0
    let returned = 0
    for (const row of decisionRows) {
      if (row.bucket === 'waiting') waitingMine += 1
      else if (row.bucket === 'review') onReview += 1
      else if (row.bucket === 'returned') returned += 1
      if (row.doneToday) confirmedToday += 1
    }
    return { waitingMine, onReview, confirmedToday, returned }
  }, [decisionRows])

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

  const chips = useMemo(() => {
    const statusLabel: Record<string, string> = {
      waiting: 'ожидают',
      done: 'готово',
      returned: 'возвращено'
    }
    return [
      { id: 'q', label: query ? `поиск: ${query}` : '' },
      {
        id: 'agent',
        label: agentFilter ? `процесс: ${(agents.find((item) => item.workflowId === agentFilter)?.name || agentFilter).slice(0, 40)}` : ''
      },
      { id: 'status', label: statusFilter !== 'all' ? `статус: ${statusLabel[statusFilter]}` : '' },
      { id: 'due', label: dueFilter ? `срок: ${dueFilter}` : '' }
    ]
  }, [query, agentFilter, statusFilter, dueFilter, agents])

  function resetFilters(): void {
    setQuery('')
    setAgentFilter('')
    setStatusFilter('all')
    setSortBy('deadline_asc')
    setDueFilter('')
  }

  return (
    <div className="wp-page">
      <Head title="Решения" />
      <section className="wp-decisions-kpi">
        <article className="wp-decisions-kpi-card wait">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            !
          </div>
          <div>
            <p>Ожидают меня</p>
            <strong>{counters.waitingMine}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card review">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ○
          </div>
          <div>
            <p>На рассмотрении</p>
            <strong>{counters.onReview}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card done">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ✓
          </div>
          <div>
            <p>Подтверждено сегодня</p>
            <strong>{counters.confirmedToday}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card returned">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ↻
          </div>
          <div>
            <p>Возвращено</p>
            <strong>{counters.returned}</strong>
          </div>
        </article>
      </section>
      <FilterBar
        query={query}
        onQuery={setQuery}
        queryPlaceholder="Агент или id"
        chips={chips}
        onReset={resetFilters}
      >
        <select className="wp-select" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}>
          <option value="">Процесс: все</option>
          {agents.map((item) => (
            <option key={item.workflowId} value={item.workflowId}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          className="wp-select"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as 'all' | 'waiting' | 'done' | 'returned')}
        >
          <option value="all">Статус: все</option>
          <option value="waiting">Ожидают</option>
          <option value="done">Готово</option>
          <option value="returned">Возвращено</option>
        </select>
        <button className="btn-ghost wp-deadline-toggle" type="button" onClick={() => setDuePanelOpen((v) => !v)}>
          Срок {dueFilter ? `· ${dueFilter}` : ''}
        </button>
        <select
          className="wp-select"
          value={sortBy}
          onChange={(event) =>
            setSortBy(event.target.value as 'deadline_asc' | 'deadline_desc' | 'status' | 'agent')
          }
        >
          <option value="deadline_asc">Сортировка: срок (ближайшие)</option>
          <option value="deadline_desc">Сортировка: срок (дальние)</option>
          <option value="status">Сортировка: статус</option>
          <option value="agent">Сортировка: агент</option>
        </select>
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
              const today = new Date()
              const dayOnly = new Date(day.getFullYear(), day.getMonth(), day.getDate())
              const todayOnly = new Date(today.getFullYear(), today.getMonth(), today.getDate())
              const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
              const tone =
                dayOnly.getTime() < todayOnly.getTime() ? 'past' : dayOnly.getTime() > todayOnly.getTime() ? 'future' : 'today'
              const outside = day.getMonth() !== dueAnchor.getMonth()
              return (
                <button
                  key={key}
                  type="button"
                  className={`wp-deadline-day ${tone}${outside ? ' muted' : ''}${dueFilter === key ? ' selected' : ''}`}
                  onClick={() => setDueFilter((prev) => (prev === key ? '' : key))}
                >
                  {day.getDate()}
                </button>
              )
            })}
          </div>
          <div className="wp-deadline-legend">
            <span className="past">Прошлые дни</span>
            <span className="today">Сегодня</span>
            <span className="future">Предстоящие</span>
          </div>
        </section>
      ) : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      {loading ? <article className="wp-card">Загружаем агентов с сервера…</article> : null}
      {!loading ? (
        <div className="wp-decisions-columns">
          <section className="wp-card wp-decisions-col">
            <h2>Требуют решения человека</h2>
            <p>Агенты со статусом ошибки или ожидания подтверждения.</p>
            <div className="wp-decisions-col-list">
              {!waiting.length ? (
                <article className="wp-card wp-decisions-mini">Сейчас нет решений, которые ждут человека.</article>
              ) : null}
              {waiting.map(({ agent, run }) => {
                const started = run?.startedAt ? parseIso(run.startedAt) : null
                return (
                  <article key={agent.id} className="wp-card wp-decisions-mini">
                    <div className="wp-code">{agent.workflowId}</div>
                    <h3>{agent.name}</h3>
                    <p>
                      {STATUS_LABEL[agent.status]} · {agent.stage}
                      {agent.due ? ` · ${agent.due}` : ''}
                    </p>
                    {run ? (
                      <p>
                        Последний прогон: {started ? humanWhen(started) : 'без даты'} · {run.status}
                      </p>
                    ) : null}
                    <div className="wp-actions">
                      <button
                        className="btn-primary"
                        type="button"
                        onClick={() => onOpenRun(agent.workflowId, agent.name, run?.runId)}
                      >
                        Открыть прогон
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          </section>

          <section className="wp-card wp-decisions-col">
            <h2>Последние результаты работы</h2>
            <p>Последний прогон каждого агента с кратким итогом.</p>
            <div className="wp-decisions-col-list">
              {!latestResults.length ? (
                <article className="wp-card wp-decisions-mini">Пока нет результатов прогонов в выбранном фильтре.</article>
              ) : null}
              {latestResults.map(({ agent, run, bucket }) => {
                const started = run?.startedAt ? parseIso(run.startedAt) : null
                const resultText = compactDecisionSummary(run || null)
                const needsAttention = bucket === 'waiting' || bucket === 'returned'
                const runKey = `${agent.workflowId}:${String(run?.runId || '').trim()}`
                const runFiles = agentFilesByRun[runKey] || []
                return (
                  <article key={`${agent.id}-latest`} className="wp-card wp-decision-rich">
                    <div className="wp-decision-rich-head">
                      <div>
                        <h3>{agent.name}</h3>
                        <div className="wp-code">{agent.workflowId}</div>
                      </div>
                      <div className="wp-decision-rich-meta">
                        <span className={`wp-decision-state ${needsAttention ? 'warn' : 'ok'}`}>
                          {run?.status || 'без статуса'}
                        </span>
                        <span>{started ? `Создано: ${humanWhen(started)}` : 'без даты'}</span>
                      </div>
                    </div>
                    <div className={`wp-decision-deadline ${needsAttention ? 'warn' : 'ok'}`}>
                      <span>{needsAttention ? 'Требуется решение' : 'Решение готово'}</span>
                      <span>{agent.due || 'Срок не задан'}</span>
                    </div>
                    <div className="wp-decision-block">
                      <strong>Краткое содержание</strong>
                      <p className="wp-decisions-result wp-decision-summary" title={resultText}>
                        {resultText}
                      </p>
                    </div>
                    <div className="wp-decision-block wp-decision-recommend">
                      <strong>Рекомендуемое решение</strong>
                      <p>
                        {needsAttention
                          ? 'Открыть прогон, проверить детали и принять решение по доработке.'
                          : 'Подтвердить результат и использовать материалы прогона.'}
                      </p>
                    </div>
                    <div className="wp-decision-block">
                      <strong>Вложения (создано агентом)</strong>
                      {runFiles.length ? (
                        <div className="wp-chip-row">
                          {runFiles.slice(0, 6).map((file) => (
                            <button
                              key={file.id || file.name}
                              className="wp-decision-chip"
                              title={file.name}
                              type="button"
                              onClick={() => {
                                if (!file.downloadUrl) return
                                void api.download(file.downloadUrl, file.name || 'file')
                              }}
                            >
                              <img src={fileTypeIconSrc(file.name || '')} alt="" />
                              <span>{file.name}</span>
                            </button>
                          ))}
                          {runFiles.length > 6 ? (
                            <span className="wp-decision-chip">+{runFiles.length - 6}</span>
                          ) : null}
                        </div>
                      ) : (
                        <p>Файлы этого прогона не найдены.</p>
                      )}
                    </div>
                    <div className="wp-decision-block">
                      <strong>Основания и источники</strong>
                      <div className="wp-chip-row">
                        <span className="wp-decision-chip">Запуск агента</span>
                        <span className="wp-decision-chip">{run?.runId || 'run неизвестен'}</span>
                        <span className="wp-decision-chip">{run?.status || 'статус неизвестен'}</span>
                      </div>
                    </div>
                    <div className="wp-actions wp-decision-actions">
                      <button
                        className="btn-primary"
                        type="button"
                        onClick={() => onOpenRun(agent.workflowId, agent.name, run?.runId)}
                      >
                        Подтвердить
                      </button>
                      <button
                        className="btn-ghost"
                        type="button"
                        onClick={() => onOpenRun(agent.workflowId, agent.name, run?.runId)}
                      >
                        Вернуть на доработку
                      </button>
                      <button
                        className="btn-ghost"
                        type="button"
                        onClick={() => onOpenRun(agent.workflowId, agent.name, run?.runId)}
                      >
                        Открыть материалы
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  )
}

export function HistoryTab({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  return <HistoryWorkplace onOpenRun={onOpenRun} />
}

export function SettingsTab({
  user,
  onDiagnostics,
  onTickets,
  onFiles,
  onSupport
}: {
  user: UserProfile
  onDiagnostics: () => void
  onTickets: () => void
  onFiles: () => void
  onSupport: () => void
}): React.JSX.Element {
  const [unread, setUnread] = useState(0)
  const [error, setError] = useState('')
  const [viewSettings, setViewSettings] = useState<NotificationViewSettings>(() =>
    loadNotificationSettings(user.id)
  )

  async function reload(): Promise<void> {
    try {
      const count = await api.unreadNotificationCount()
      setUnread(count)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить уведомления')
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  useEffect(() => {
    setViewSettings(loadNotificationSettings(user.id))
  }, [user.id])

  const updateView = (patch: Partial<NotificationViewSettings>): void => {
    setViewSettings((prev) => {
      const next = { ...prev, ...patch }
      saveNotificationSettings(user.id, next)
      return next
    })
  }

  return (
    <div className="wp-page">
      <Head title="Настройки" badge={user.position || 'аккаунт'} />
      <section className="wp-card">
        <h2>Профиль</h2>
        <p>
          {user.fio}
          {user.department ? ` · ${user.department}` : ''}
          {user.position ? ` · ${user.position}` : ''}
        </p>
        <p>{user.isSupport ? 'Есть права технической поддержки' : 'Обычный сотрудник'}</p>
      </section>
      <section className="wp-card">
        <h2>Уведомления</h2>
        <p>Непрочитанных: {unread}. Это те же уведомления, что в колокольчике сверху.</p>
        <div className="wp-notify-view">
          <div className="wp-notify-label">Вид карточек</div>
          <div className="wp-notify-controls">
            <select
              className="wp-select"
              value={viewSettings.mode}
              onChange={(event) =>
                updateView({ mode: event.target.value === 'compact' ? 'compact' : 'comfortable' })
              }
            >
              <option value="comfortable">Обычный</option>
              <option value="compact">Компактный</option>
            </select>
            <label className="wp-toggle">
              <input
                type="checkbox"
                checked={viewSettings.showSender}
                onChange={(event) => updateView({ showSender: event.target.checked })}
              />
              Показывать автора
            </label>
            <label className="wp-toggle">
              <input
                type="checkbox"
                checked={viewSettings.showTime}
                onChange={(event) => updateView({ showTime: event.target.checked })}
              />
              Показывать дату и время
            </label>
            <label className="wp-toggle">
              <input
                type="checkbox"
                checked={viewSettings.highlightUnread}
                onChange={(event) => updateView({ highlightUnread: event.target.checked })}
              />
              Выделять непрочитанные
            </label>
          </div>
        </div>
        {error ? <p>{error}</p> : null}
      </section>
      <section className="wp-card">
        <h2>Файлы агентов</h2>
        <p>Файлы агентов, KPI и прогоны те же. Создать нового агента можно только в Constructor.</p>
        <div className="wp-actions">
          <button className="btn-primary" type="button" onClick={onFiles}>
            Файлы агентов
          </button>
        </div>
      </section>
      <section className="wp-card">
        <h2>Сопровождение</h2>
        <p>Заявки и диагностика идут в тот же backend, что и чат поддержки.</p>
        <div className="wp-actions">
          <button className="btn-primary" type="button" onClick={onSupport}>
            Чат поддержки
          </button>
          <button className="btn-ghost" type="button" onClick={onTickets}>
            Журнал заявок
          </button>
          <button className="btn-ghost" type="button" onClick={onDiagnostics}>
            Диагностика
          </button>
        </div>
      </section>
    </div>
  )
}

export function TicketsPage({
  user,
  onBack,
  onOpenThread
}: {
  user: UserProfile
  onBack: () => void
  onOpenThread: (thread: ChatThread) => void
}): React.JSX.Element {
  const [items, setItems] = useState<SupportTicketItem[]>([])
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        if (user.isSupport) {
          const rows = await api.listSupportTickets('all')
          if (alive) setItems(rows)
        } else {
          const all = await api.listChatThreads()
          if (alive) setThreads(all.filter((item) => item.kind === 'support'))
        }
        if (alive) setError('')
      } catch (err) {
        if (alive) {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить заявки')
          const all = await api.listChatThreads().catch(() => [])
          if (alive) setThreads(all.filter((item) => item.kind === 'support'))
        }
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [user.isSupport])

  const count = user.isSupport ? items.length : threads.length

  return (
    <div className="wp-page">
      <button className="btn-ghost" type="button" onClick={onBack}>
        Назад к настройкам
      </button>
      <Head title="Журнал заявок" count={count} badge={user.isSupport ? 'поддержка' : 'мои обращения'} />
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      <div className="wp-list">
        {loading ? <article className="wp-card">Загружаем заявки с сервера…</article> : null}
        {!loading && !count ? (
          <article className="wp-card">Открытых заявок нет. Новое обращение создаётся через чат поддержки.</article>
        ) : null}
        {items.map((item) => (
          <article key={item.id} className="wp-card">
            <div className="wp-code">
              {item.id} · {TICKET_STATUS_LABEL[item.status] || item.status}
            </div>
            <h2>{item.authorFio || 'Обращение'}</h2>
            <p>{item.authorPosition}</p>
            <p>{item.preview || 'Нет текста'}</p>
            <p>{item.queuedAt && parseIso(item.queuedAt) ? humanWhen(parseIso(item.queuedAt) as Date) : ''}</p>
            <div className="wp-actions">
              <button className="btn-primary" type="button" onClick={() => onOpenThread(ticketToThread(item))}>
                Открыть диалог
              </button>
            </div>
          </article>
        ))}
        {threads.map((thread) => (
          <article key={thread.id} className="wp-card">
            <div className="wp-code">
              {thread.id} · {TICKET_STATUS_LABEL[thread.ticketStatus] || thread.ticketStatus || 'чат'}
            </div>
            <h2>{thread.title}</h2>
            <p>{thread.preview || 'Диалог поддержки'}</p>
            <div className="wp-actions">
              <button className="btn-primary" type="button" onClick={() => onOpenThread(thread)}>
                Открыть диалог
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}

export function DiagnosticsPage({
  onBack,
  onOpenRun
}: {
  onBack: () => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const [health, setHealth] = useState<AppHealth | null>(null)
  const [workflow, setWorkflow] = useState<WorkflowHealthInfo | null>(null)
  const [tools, setTools] = useState<ToolStatus[]>([])
  const [backendUrl, setBackendUrl] = useState('')
  const [failed, setFailed] = useState<
    { workflowId: string; title: string; runId: string; at: string; status: string }[]
  >([])
  const [period, setPeriod] = useState<'week' | 'month'>('week')
  const [reloadKey, setReloadKey] = useState(0)
  const [query, setQuery] = useState('')
  const [updatedAt, setUpdatedAt] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    const reload = async (): Promise<void> => {
      setLoading(true)
      try {
        const config = await window.api.getConfig()
        const win = windowFor(period, new Date())
        const [appHealth, wfHealth, onec, imap, turbo, board] = await Promise.all([
          api.getHealth().catch(() => null),
          api.getWorkflowHealth().catch(() => null),
          api.getToolStatus('onec').catch(() => null),
          api.getToolStatus('imap').catch(() => null),
          api.getToolStatus('turboproject').catch(() => null),
          api.getWorkflowBoard({ window_from: win.from, window_to: win.to }).catch(() => null)
        ])
        if (!alive) return
        setBackendUrl(config.backendUrl || '')
        setHealth(appHealth)
        setWorkflow(wfHealth)
        setTools([onec, imap, turbo].filter((item): item is ToolStatus => item != null))
        const rows = (board?.events || [])
          .filter((event) => {
            const status = (event.status || '').toLowerCase()
            return status === 'error' || status === 'needs_attention' || status === 'waiting_human'
          })
          .sort((left, right) => (right.startAt || '').localeCompare(left.startAt || ''))
          .slice(0, 20)
          .map((event) => ({
            workflowId: event.workflowId,
            title: event.title,
            runId: event.runId,
            at: event.startAt,
            status: event.status || ''
          }))
        setFailed(rows)
        setUpdatedAt(new Date().toISOString())
        setError('')
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось снять диагностику')
      } finally {
        if (alive) setLoading(false)
      }
    }
    void reload()
    return () => {
      alive = false
    }
  }, [period, reloadKey])

  const toolLabel: Record<string, string> = {
    onec: '1С',
    imap: 'Почта',
    turboproject: 'Turbo Project'
  }
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return failed
    return failed.filter((item) => `${item.title} ${item.workflowId} ${item.runId}`.toLowerCase().includes(q))
  }, [failed, query])
  const updatedStamp = updatedAt ? parseIso(updatedAt) : null

  return (
    <div className="wp-page wp-diag-page">
      <div className="wp-diag-toolbar">
        <button className="btn-ghost" type="button" onClick={onBack}>
          Назад к настройкам
        </button>
        <div className="wp-diag-toolbar-actions">
          <select className="wp-select" value={period} onChange={(event) => setPeriod(event.target.value as 'week' | 'month')}>
            <option value="week">Окно: неделя</option>
            <option value="month">Окно: месяц</option>
          </select>
          <input
            className="wp-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Поиск по агенту / run id"
          />
        </div>
      </div>
      <Head title="Диагностика" badge={health?.status || (loading ? 'проверка' : 'нет ответа')} />
      <div className="wp-diag-toolbar">
        <p className="wp-sub">
          {updatedStamp ? `Обновлено: ${humanWhen(updatedStamp)}` : 'Состояние ещё не снималось'}
        </p>
        <button className="btn-primary" type="button" onClick={() => setReloadKey((v) => v + 1)} disabled={loading}>
          {loading ? 'Обновляем…' : 'Обновить'}
        </button>
      </div>
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      <section className="wp-card">
        <h2>Backend</h2>
        {loading ? <p>Снимаем состояние сервера…</p> : null}
        <div className="wp-diag-grid">
          <div className="wp-diag-kv">
            <span>Адрес</span>
            <strong>{backendUrl || 'не задан'}</strong>
          </div>
          <div className="wp-diag-kv">
            <span>ERP</span>
            <strong>{health ? (health.erpReachable ? `доступен · ${health.erpServer || '—'}` : 'недоступен') : 'нет ответа'}</strong>
          </div>
          <div className="wp-diag-kv">
            <span>LLM</span>
            <strong>{health?.llmProvider || 'нет данных'}</strong>
          </div>
          <div className="wp-diag-kv">
            <span>Workflows</span>
            <strong>
              {workflow
                ? workflow.ok
                  ? `ок${workflow.who ? ` · ${workflow.who}` : ''}`
                  : workflow.message || 'ошибка'
                : 'нет ответа'}
            </strong>
          </div>
        </div>
      </section>
      <section className="wp-card">
        <h2>Инструменты</h2>
        {!tools.length && !loading ? <p>Статусы инструментов недоступны.</p> : null}
        <div className="wp-diag-tools">
          {tools.map((item) => (
            <span key={item.name} className={`wp-diag-tool ${item.configured ? 'ok' : 'off'}`}>
              {toolLabel[item.name] || item.name}: {item.configured ? `подключен · ${item.mode}` : 'не настроен'}
            </span>
          ))}
        </div>
      </section>
      <section className="wp-card">
        <h2>Проблемные прогоны</h2>
        {!filtered.length && !loading ? <p>В выбранном окне нет проблемных прогонов.</p> : null}
        <div className="wp-list">
          {filtered.map((item) => (
            <article key={`${item.workflowId}-${item.runId}-${item.at}`} className="wp-card">
              <h2>{item.title}</h2>
              <p>
                <span className="wp-code">{item.status || 'ошибка'}</span> · {item.workflowId}
                {item.at ? ` · ${humanWhen(parseIso(item.at) || new Date(item.at))}` : ''}
              </p>
              <div className="wp-actions">
                <button
                  className="btn-primary wp-diag-run-btn"
                  type="button"
                  onClick={() => onOpenRun(item.workflowId, item.title, item.runId)}
                >
                  Открыть прогон
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
