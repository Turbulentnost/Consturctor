import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type {
  AppHealth,
  ChatThread,
  SupportTicketItem,
  ToolStatus,
  UserProfile,
  WorkflowHealthInfo
} from '../api/types'
import { HistoryWorkplace } from './HistoryWorkplace'
import { TICKET_STATUS_LABEL } from './labels'
import { TodayWorkplace } from './WorkplaceBoard'
import { humanWhen, parseIso, windowFor } from '../utils/calendar'

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
        <div className="wp-head-title-row">
          <h1 className="page-title">{title}</h1>
          {badge ? <span className="orch-badge">{badge}</span> : null}
          {count != null && <span className="wp-count">{count}</span>}
        </div>
      </div>
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

export function TodayTab({
  user,
  onOpenDecisions,
  onOpenMetrics,
  onOpenPassport,
  onRun
}: {
  user: UserProfile
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpenPassport: (workflowId: string, title: string, tab?: 'info' | 'files' | 'results') => void
  onRun: (workflowId: string, title: string) => void
}): React.JSX.Element {
  return (
    <TodayWorkplace
      userId={user.id || ''}
      userFio={user.fio || ''}
      onOpenDecisions={onOpenDecisions}
      onOpenMetrics={onOpenMetrics}
      onOpenPassport={onOpenPassport}
      onRun={onRun}
    />
  )
}

export { DecisionsTab } from './DecisionsWorkplace'

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
        <h2>Обновления</h2>
        <p>Одно обновление ставит и Constructor, и Orchestrator.</p>
        <div className="wp-actions">
          <button
            className="btn-primary"
            type="button"
            onClick={() => {
              void window.api.installUpdate?.()
            }}
          >
            Проверить и установить
          </button>
        </div>
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
