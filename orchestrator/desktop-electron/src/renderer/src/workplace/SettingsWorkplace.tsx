import { useEffect, useMemo, useState } from 'react'
import type { UserProfile } from '../api/types'
import { api } from '../api/client'

type SettingsSection = 'general' | 'notifications' | 'access' | 'diagnostics' | 'integrations'

type SendWhen = 'immediate' | '60m' | 'off'
type Escalate = '30m' | 'none' | 'owner'

interface EventChannelRow {
  id: string
  title: string
  icon: 'clock' | 'warn-clock' | 'alert' | 'gear' | 'pause'
  inApp: boolean
  email: boolean
  emailOptional?: boolean
  when: SendWhen
  escalate: Escalate
}

interface NotifyPrefs {
  events: EventChannelRow[]
  popupCritical: boolean
  quietHours: string
  groupRepeats: boolean
  mode: 'comfortable' | 'compact'
  showSender: boolean
  showTime: boolean
  highlightUnread: boolean
}

const TABS: { id: SettingsSection; label: string }[] = [
  { id: 'general', label: 'Общие' },
  { id: 'notifications', label: 'Уведомления' },
  { id: 'access', label: 'Права доступа' },
  { id: 'diagnostics', label: 'Диагностика' },
  { id: 'integrations', label: 'Интеграции' }
]

const DEFAULT_EVENTS: EventChannelRow[] = [
  {
    id: 'decision_new',
    title: 'Новое решение ожидает подтверждения',
    icon: 'clock',
    inApp: true,
    email: true,
    when: 'immediate',
    escalate: '30m'
  },
  {
    id: 'decision_soon',
    title: 'Приближается срок решения',
    icon: 'warn-clock',
    inApp: true,
    email: true,
    emailOptional: true,
    when: '60m',
    escalate: 'none'
  },
  {
    id: 'decision_overdue',
    title: 'Нарушен срок решения',
    icon: 'alert',
    inApp: true,
    email: true,
    when: 'immediate',
    escalate: '30m'
  },
  {
    id: 'process_error',
    title: 'Ошибка процесса или агента',
    icon: 'gear',
    inApp: true,
    email: true,
    when: 'immediate',
    escalate: 'owner'
  },
  {
    id: 'process_pause',
    title: 'Процесс приостановлен / возобновлён',
    icon: 'pause',
    inApp: true,
    email: false,
    emailOptional: true,
    when: 'immediate',
    escalate: 'none'
  }
]

const DEFAULT_PREFS: NotifyPrefs = {
  events: DEFAULT_EVENTS,
  popupCritical: true,
  quietHours: '22-08',
  groupRepeats: true,
  mode: 'comfortable',
  showSender: true,
  showTime: true,
  highlightUnread: true
}

function prefsKey(userId: string): string {
  return `orchestrator.settings.notify.${(userId || 'local').trim() || 'local'}`
}

function loadPrefs(userId: string): NotifyPrefs {
  try {
    const raw = localStorage.getItem(prefsKey(userId))
    if (!raw) return structuredClone(DEFAULT_PREFS)
    const data = JSON.parse(raw) as Partial<NotifyPrefs>
    const eventsById = new Map((data.events || []).map((row) => [row.id, row]))
    return {
      ...DEFAULT_PREFS,
      ...data,
      events: DEFAULT_EVENTS.map((row) => ({ ...row, ...eventsById.get(row.id) })),
      quietHours: data.quietHours || DEFAULT_PREFS.quietHours,
      mode: data.mode === 'compact' ? 'compact' : 'comfortable'
    }
  } catch {
    return structuredClone(DEFAULT_PREFS)
  }
}

function savePrefs(userId: string, prefs: NotifyPrefs): void {
  try {
    localStorage.setItem(prefsKey(userId), JSON.stringify(prefs))
  } catch {
    /* ignore */
  }
}

function EventIcon({ kind }: { kind: EventChannelRow['icon'] }): React.JSX.Element {
  const color =
    kind === 'clock'
      ? '#1565c0'
      : kind === 'warn-clock'
        ? '#c77800'
        : kind === 'alert' || kind === 'gear'
          ? '#c62828'
          : '#6b7380'
  return (
    <span className="set-event-ico" style={{ color }} aria-hidden>
      {kind === 'clock' || kind === 'warn-clock' ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.8" />
          <path d="M12 8v4l2.5 1.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      ) : kind === 'alert' ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 4l9 16H3L12 4z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          <path d="M12 10v4M12 16.5v.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      ) : kind === 'gear' ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M12 3v2.5M12 18.5V21M4.9 6.5l1.8 1.8M17.3 15.7l1.8 1.8M3 12h2.5M18.5 12H21M4.9 17.5l1.8-1.8M17.3 8.3l1.8-1.8"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <rect x="6" y="5" width="4" height="14" rx="1" stroke="currentColor" strokeWidth="1.8" />
          <rect x="14" y="5" width="4" height="14" rx="1" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      )}
    </span>
  )
}

function Switch({
  checked,
  onChange,
  disabled,
  label
}: {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  label?: string
}): React.JSX.Element {
  return (
    <label className={`set-switch${disabled ? ' is-disabled' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={label}
      />
      <span className="set-switch-track" aria-hidden>
        <span className="set-switch-thumb" />
      </span>
    </label>
  )
}

export function SettingsWorkplace({
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
  const [section, setSection] = useState<SettingsSection>('notifications')
  const [prefs, setPrefs] = useState<NotifyPrefs>(() => loadPrefs(user.id))
  const [draft, setDraft] = useState<NotifyPrefs>(() => loadPrefs(user.id))
  const [unread, setUnread] = useState(0)
  const [savedNote, setSavedNote] = useState('')
  const [toolLines, setToolLines] = useState<string[]>([])

  useEffect(() => {
    const next = loadPrefs(user.id)
    setPrefs(next)
    setDraft(next)
  }, [user.id])

  useEffect(() => {
    void api.unreadNotificationCount().then(setUnread).catch(() => setUnread(0))
  }, [])

  useEffect(() => {
    let alive = true
    void Promise.all([
      api.getToolStatus('onec').catch(() => null),
      api.getToolStatus('imap').catch(() => null),
      api.getToolStatus('turboproject').catch(() => null)
    ]).then((rows) => {
      if (!alive) return
      const labels: Record<string, string> = {
        onec: '1С',
        imap: 'Почта (IMAP)',
        turboproject: 'Turbo Project'
      }
      setToolLines(
        rows
          .filter((item): item is NonNullable<typeof item> => item != null)
          .map((item) =>
            `${labels[item.name] || item.name}: ${item.configured ? `подключен · ${item.mode}` : 'не настроен'}`
          )
      )
    })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!savedNote) return
    const t = window.setTimeout(() => setSavedNote(''), 2800)
    return () => window.clearTimeout(t)
  }, [savedNote])

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(prefs), [draft, prefs])

  function patchEvent(id: string, patch: Partial<EventChannelRow>): void {
    setDraft((prev) => ({
      ...prev,
      events: prev.events.map((row) => (row.id === id ? { ...row, ...patch } : row))
    }))
  }

  function saveChanges(): void {
    savePrefs(user.id, draft)
    setPrefs(draft)
    setSavedNote('Изменения сохранены')
  }

  function restoreDefaults(): void {
    const next = structuredClone(DEFAULT_PREFS)
    setDraft(next)
  }

  function openNotificationCenter(): void {
    window.dispatchEvent(new CustomEvent('orchestrator:open-notifications'))
  }

  return (
    <div className="wp-page set-page">
      <nav className="set-tabs" aria-label="Разделы настроек">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={section === tab.id ? 'active' : ''}
            onClick={() => setSection(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {section === 'general' ? (
        <div className="set-body">
          <header className="set-head">
            <div>
              <h1 className="page-title">Общие</h1>
              <p className="set-sub">Профиль, обновления и рабочие файлы</p>
            </div>
          </header>
          <section className="set-card">
            <h2>Профиль</h2>
            <p className="set-muted">
              {user.fio}
              {user.department ? ` · ${user.department}` : ''}
              {user.position ? ` · ${user.position}` : ''}
            </p>
            <p className="set-muted">
              {user.isSupport ? 'Есть права технической поддержки' : 'Обычный сотрудник'}
            </p>
          </section>
          <section className="set-card">
            <h2>Обновления</h2>
            <p className="set-muted">Одно обновление ставит и Constructor, и Orchestrator.</p>
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
          <section className="set-card">
            <h2>Файлы агентов</h2>
            <p className="set-muted">
              Файлы агентов, KPI и прогоны те же. Создать нового агента можно только в Constructor.
            </p>
            <div className="wp-actions">
              <button className="btn-primary" type="button" onClick={onFiles}>
                Открыть файлы
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {section === 'notifications' ? (
        <div className="set-body set-body-notify">
          <header className="set-head set-head-notify">
            <div>
              <h1 className="page-title">Уведомления</h1>
              <p className="set-sub">События, каналы и пороги</p>
            </div>
            <div className="set-channel-cards">
              <article className="set-channel-card">
                <span className="set-channel-ico" aria-hidden>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M6 9a6 6 0 0112 0c0 7 3 7 3 9H3c0-2 3-2 3-9"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                    <path d="M10 20a2 2 0 004 0" stroke="currentColor" strokeWidth="1.8" />
                  </svg>
                </span>
                <div>
                  <strong>Внутрисистемные</strong>
                  <span>обязательный канал</span>
                </div>
              </article>
              <article className="set-channel-card">
                <span className="set-channel-ico" aria-hidden>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
                    <path d="M4 7l8 6 8-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                </span>
                <div>
                  <strong>Email</strong>
                  <span>настраивается</span>
                </div>
              </article>
            </div>
          </header>

          {savedNote ? <div className="set-toast">{savedNote}</div> : null}
          <p className="set-hint">
            Непрочитанных в колокольчике: <strong>{unread}</strong>
          </p>

          <section className="set-card set-events-card">
            <div className="set-events-head">
              <span>Событие</span>
              <span>В интерфейсе</span>
              <span>Email</span>
              <span>Когда отправлять</span>
              <span>Эскалация</span>
            </div>
            {draft.events.map((row) => (
              <div key={row.id} className="set-events-row">
                <div className="set-event-title">
                  <EventIcon kind={row.icon} />
                  <span>{row.title}</span>
                </div>
                <div className="set-events-cell">
                  <Switch
                    checked={row.inApp}
                    label="В интерфейсе"
                    onChange={(next) => patchEvent(row.id, { inApp: next })}
                  />
                </div>
                <div className="set-events-cell set-events-email">
                  <Switch
                    checked={row.email}
                    label="Email"
                    onChange={(next) => patchEvent(row.id, { email: next })}
                  />
                  {row.emailOptional ? <em>(опционально)</em> : null}
                </div>
                <div className="set-events-cell">
                  <select
                    className="set-select"
                    value={row.when}
                    onChange={(e) => patchEvent(row.id, { when: e.target.value as SendWhen })}
                  >
                    <option value="immediate">Сразу</option>
                    <option value="60m">За 60 мин</option>
                    <option value="off">Не отправлять</option>
                  </select>
                </div>
                <div className="set-events-cell">
                  <select
                    className="set-select"
                    value={row.escalate}
                    onChange={(e) => patchEvent(row.id, { escalate: e.target.value as Escalate })}
                  >
                    <option value="30m">Через 30 мин</option>
                    <option value="none">Нет</option>
                    <option value="owner">Владельцу процесса</option>
                  </select>
                </div>
              </div>
            ))}
          </section>

          <div className="set-bottom-grid">
            <section className="set-card">
              <h2>Поведение уведомлений</h2>
              <div className="set-behavior-list">
                <label className="set-behavior-row">
                  <span>Показывать всплывающие уведомления для критических событий</span>
                  <Switch
                    checked={draft.popupCritical}
                    onChange={(next) => setDraft((prev) => ({ ...prev, popupCritical: next }))}
                  />
                </label>
                <div className="set-behavior-row set-behavior-quiet">
                  <div>
                    <span>Тихие часы</span>
                    <p className="set-quiet-hint">
                      <span aria-hidden>ⓘ</span> Критические ошибки доставляются всегда
                    </p>
                  </div>
                  <select
                    className="set-select"
                    value={draft.quietHours}
                    onChange={(e) => setDraft((prev) => ({ ...prev, quietHours: e.target.value }))}
                  >
                    <option value="off">Выключены</option>
                    <option value="22-08">22:00 – 08:00</option>
                    <option value="21-07">21:00 – 07:00</option>
                    <option value="23-09">23:00 – 09:00</option>
                  </select>
                </div>
                <label className="set-behavior-row">
                  <span>Объединять повторяющиеся события</span>
                  <Switch
                    checked={draft.groupRepeats}
                    onChange={(next) => setDraft((prev) => ({ ...prev, groupRepeats: next }))}
                  />
                </label>
                <div className="set-behavior-row">
                  <span>Вид карточек в центре</span>
                  <select
                    className="set-select"
                    value={draft.mode}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        mode: e.target.value === 'compact' ? 'compact' : 'comfortable'
                      }))
                    }
                  >
                    <option value="comfortable">Обычный</option>
                    <option value="compact">Компактный</option>
                  </select>
                </div>
                <label className="set-behavior-row">
                  <span>Показывать автора</span>
                  <Switch
                    checked={draft.showSender}
                    onChange={(next) => setDraft((prev) => ({ ...prev, showSender: next }))}
                  />
                </label>
                <label className="set-behavior-row">
                  <span>Показывать дату и время</span>
                  <Switch
                    checked={draft.showTime}
                    onChange={(next) => setDraft((prev) => ({ ...prev, showTime: next }))}
                  />
                </label>
                <label className="set-behavior-row">
                  <span>Выделять непрочитанные</span>
                  <Switch
                    checked={draft.highlightUnread}
                    onChange={(next) => setDraft((prev) => ({ ...prev, highlightUnread: next }))}
                  />
                </label>
              </div>
              <button className="set-link" type="button" onClick={openNotificationCenter}>
                Открыть центр уведомлений
                <span aria-hidden>↗</span>
              </button>
            </section>

            <section className="set-card set-mvp-card">
              <h2>Границы MVP</h2>
              <ul className="set-mvp-list">
                <li className="ok">
                  <span>✓</span> Внутрисистемные уведомления
                </li>
                <li className="ok">
                  <span>✓</span> Email
                </li>
                <li className="ok">
                  <span>✓</span> Встроенный чат
                </li>
                <li className="no">
                  <span>×</span> Мобильные push
                </li>
                <li className="no">
                  <span>×</span> SMS
                </li>
                <li className="no">
                  <span>×</span> Внешние мессенджеры
                </li>
              </ul>
            </section>
          </div>

          <footer className="set-footer">
            <div className="set-footer-actions">
              <button className="btn-primary set-save-btn" type="button" onClick={saveChanges} disabled={!dirty}>
                <span aria-hidden>✓</span>
                Сохранить изменения
              </button>
              <button className="set-ghost-btn" type="button" onClick={restoreDefaults}>
                <span aria-hidden>↻</span>
                Восстановить значения по умолчанию
              </button>
            </div>
            <div className="set-footer-meta">
              <span className="set-admin-lock">
                <span className="set-admin-lock-ico" aria-hidden>
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
                Только для администраторов
              </span>
              <button className="set-link" type="button" onClick={() => setSection('access')}>
                Матрица прав <span aria-hidden>↗</span>
              </button>
              <button className="set-link" type="button" onClick={onDiagnostics}>
                Диагностический режим <span aria-hidden>↗</span>
              </button>
            </div>
          </footer>
        </div>
      ) : null}

      {section === 'access' ? (
        <div className="set-body">
          <header className="set-head">
            <div>
              <h1 className="page-title">Права доступа</h1>
              <p className="set-sub">Роли, матрица и сопровождение</p>
            </div>
          </header>
          <section className="set-card">
            <h2>Текущая роль</h2>
            <p className="set-muted">
              {user.isSupport ? 'Техническая поддержка / администратор сопровождения' : 'Сотрудник'}
            </p>
            <p className="set-muted">
              Изменение прав выполняется на стороне ERP / каталога пользователей. Здесь — обзор и переходы.
            </p>
          </section>
          <section className="set-card">
            <h2>Матрица прав (обзор)</h2>
            <div className="set-matrix">
              <div className="set-matrix-row set-matrix-head">
                <span>Действие</span>
                <span>Сотрудник</span>
                <span>Владелец процесса</span>
                <span>Админ</span>
              </div>
              {[
                ['Просмотр журнала', '✓', '✓', '✓'],
                ['Подтверждение решений', 'свои', 'по процессу', 'все'],
                ['Настройка уведомлений', '—', 'частично', '✓'],
                ['Диагностика / заявки', 'свои', 'свои', '✓']
              ].map((row) => (
                <div key={row[0]} className="set-matrix-row">
                  {row.map((cell) => (
                    <span key={cell}>{cell}</span>
                  ))}
                </div>
              ))}
            </div>
          </section>
          <section className="set-card">
            <h2>Сопровождение</h2>
            <div className="wp-actions">
              <button className="btn-primary" type="button" onClick={onSupport}>
                Чат поддержки
              </button>
              <button className="btn-ghost" type="button" onClick={onTickets}>
                Журнал заявок
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {section === 'diagnostics' ? (
        <div className="set-body">
          <header className="set-head">
            <div>
              <h1 className="page-title">Диагностика</h1>
              <p className="set-sub">Состояние backend, инструментов и проблемных прогонов</p>
            </div>
          </header>
          <section className="set-card">
            <h2>Полный отчёт</h2>
            <p className="set-muted">
              Откройте диагностический режим, чтобы снять health backend, статусы 1С / почты / Turbo и список
              проблемных прогонов.
            </p>
            <div className="wp-actions">
              <button className="btn-primary" type="button" onClick={onDiagnostics}>
                Открыть диагностику
              </button>
            </div>
          </section>
          {toolLines.length ? (
            <section className="set-card">
              <h2>Краткий статус инструментов</h2>
              <ul className="set-tool-list">
                {toolLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : null}

      {section === 'integrations' ? (
        <div className="set-body">
          <header className="set-head">
            <div>
              <h1 className="page-title">Интеграции</h1>
              <p className="set-sub">Каналы доставки и внешние системы</p>
            </div>
          </header>
          <section className="set-card">
            <h2>Каналы уведомлений</h2>
            <ul className="set-mvp-list">
              <li className="ok">
                <span>✓</span> Внутрисистемные — включены всегда
              </li>
              <li className="ok">
                <span>✓</span> Email — настраивается на вкладке «Уведомления»
              </li>
              <li className="ok">
                <span>✓</span> Встроенный чат поддержки
              </li>
              <li className="no">
                <span>×</span> Push / SMS / мессенджеры — вне MVP
              </li>
            </ul>
          </section>
          <section className="set-card">
            <h2>Внешние системы</h2>
            {toolLines.length ? (
              <ul className="set-tool-list">
                {toolLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              <p className="set-muted">Статусы инструментов пока недоступны.</p>
            )}
            <div className="wp-actions">
              <button className="btn-ghost" type="button" onClick={onDiagnostics}>
                Проверить в диагностике
              </button>
              <button className="btn-ghost" type="button" onClick={onFiles}>
                Файлы агентов
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  )
}
