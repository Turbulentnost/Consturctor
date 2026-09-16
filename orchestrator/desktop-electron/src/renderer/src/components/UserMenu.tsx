import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { InboxNotification, UserProfile } from '../api/types'
import logoUrl from '../assets/logo.png'
import { userGivenName } from '../workplace/userContext'
import { NotificationInbox } from './NotificationInbox'

interface UserMenuProps {
  user: UserProfile
  avatarUrl: string | null
  unread: number
  onUnreadChange: (count: number) => void
  onLogout: () => void
  showLogout: boolean
  onOpenAgent?: (workflowId: string, runId: string, title?: string, body?: string) => void
  onStopRun?: (workflowId: string, runId?: string) => void
  isRunLive?: (workflowId: string, runId?: string) => boolean
  onOpenSettings?: () => void
  onGoToSettings?: () => void
  canSwitchAdminView?: boolean
  onSwitchAdminView?: (mode: 'admin' | 'user') => void
  profileAfterAvatar?: boolean
  variant?: 'default' | 'admin'
}

export function UserMenu({
  user,
  avatarUrl,
  unread,
  onUnreadChange,
  onLogout,
  showLogout,
  onOpenAgent,
  onStopRun,
  isRunLive,
  onOpenSettings,
  onGoToSettings,
  canSwitchAdminView = false,
  onSwitchAdminView,
  profileAfterAvatar = false,
  variant = 'default'
}: UserMenuProps): React.JSX.Element {
  const [menuOpen, setMenuOpen] = useState(false)
  const [inboxOpen, setInboxOpen] = useState(false)
  const [items, setItems] = useState<InboxNotification[]>([])
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const adminLayout = variant === 'admin'

  useEffect(() => {
    function onDocClick(e: MouseEvent): void {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setMenuOpen(false)
        setInboxOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  useEffect(() => {
    function onOpenFromSettings(): void {
      setMenuOpen(false)
      setInboxOpen(true)
      setLoading(true)
      void (async () => {
        try {
          const list = await api.listNotifications()
          setItems(list)
          if (list.some((item) => item.unread) || unread > 0) {
            await api.markAllNotificationsRead()
            setItems((current) => current.map((item) => ({ ...item, unread: false })))
            onUnreadChange(0)
          }
        } catch {
          setItems([])
        } finally {
          setLoading(false)
        }
      })()
    }
    window.addEventListener('orchestrator:open-notifications', onOpenFromSettings)
    return () => window.removeEventListener('orchestrator:open-notifications', onOpenFromSettings)
  }, [unread, onUnreadChange])

  async function openInbox(): Promise<void> {
    const next = !inboxOpen
    setInboxOpen(next)
    setMenuOpen(false)
    if (!next) return
    setLoading(true)
    try {
      const list = await api.listNotifications()
      setItems(list)
      if (list.some((item) => item.unread) || unread > 0) {
        await api.markAllNotificationsRead()
        setItems((current) => current.map((item) => ({ ...item, unread: false })))
        onUnreadChange(0)
      }
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  async function clearAll(): Promise<void> {
    const previous = items
    setItems([])
    onUnreadChange(0)
    try {
      await api.clearNotifications()
    } catch {
      setItems(previous)
    }
  }

  function openItem(item: InboxNotification): void {
    setInboxOpen(false)
    const isLiveNotification = item.id.startsWith('live:')
    if (!isLiveNotification) {
      setItems((current) => current.map((entry) => (entry.id === item.id ? { ...entry, unread: false } : entry)))
      void api.markNotificationRead(item.id).catch(() => undefined)
    }
    if (item.workflowId && onOpenAgent) {
      onOpenAgent(item.workflowId, item.runId || '', item.title, item.body)
    }
  }

  async function clearOne(id: string): Promise<void> {
    const previous = items
    setItems((current) => current.filter((item) => item.id !== id))
    try {
      await api.deleteNotification(id)
    } catch {
      setItems(previous)
    }
  }

  function toggleProfileMenu(): void {
    setMenuOpen((value) => !value)
    setInboxOpen(false)
  }

  function openSettings(): void {
    setMenuOpen(false)
    ;(onOpenSettings || onGoToSettings)?.()
  }

  function switchAdminView(mode: 'admin' | 'user'): void {
    setMenuOpen(false)
    onSwitchAdminView?.(mode)
  }

  const positionLine = user.position.trim()
  const whoBlock = (
    <div className="who">
      <div className="name" title={user.fio}>
        {profileAfterAvatar ? userGivenName(user.fio) : user.fio}
      </div>
      {positionLine ? (
        <div className="pos" title={positionLine}>
          {positionLine}
        </div>
      ) : null}
    </div>
  )

  const notifyBlock = (
    <div className="notify-wrap">
      <button className="icon-btn" title="Уведомления" onClick={() => void openInbox()}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M6 9a6 6 0 1112 0c0 4.5 1.2 6 2 6.8.3.3.1.9-.4.9H4.4c-.5 0-.7-.6-.4-.9C4.8 15 6 13.5 6 9z"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinejoin="round"
          />
          <path d="M9.5 19a2.5 2.5 0 005 0" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
        {unread > 0 && <span className="badge">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {inboxOpen && (
        <NotificationInbox
          items={items}
          loading={loading}
          onClearAll={() => void clearAll()}
          onClearOne={(id) => void clearOne(id)}
          onOpen={openItem}
          onStop={(item) => {
            if (!item.workflowId) return
            onStopRun?.(item.workflowId, item.runId)
          }}
          canStop={(item) => Boolean(item.workflowId && isRunLive?.(item.workflowId, item.runId))}
        />
      )}
    </div>
  )

  if (adminLayout) {
    return (
      <div className="user-menu user-menu--admin" ref={ref}>
        {notifyBlock}
        <div className="user-menu__profile-wrap">
          <button type="button" className="user-menu__profile-btn" onClick={toggleProfileMenu}>
            <span className="avatar">
              <img className="avatar-img" src={avatarUrl || logoUrl} alt={user.fio} />
              <span className={`avatar-status ${user.activityStatus || 'online'}`} />
            </span>
            <span className="who">
              <span className="name">{user.fio}</span>
              <span className="pos">{user.position || 'Системный администратор'}</span>
            </span>
            <svg className="user-menu__chevron" viewBox="0 0 16 16" aria-hidden>
              <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
            </svg>
          </button>
          {menuOpen ? (
            <div className="user-dropdown user-dropdown--admin">
              <button type="button" className="user-dropdown-item" onClick={openSettings}>
                Перейти в настройки
              </button>
              {canSwitchAdminView ? (
                <button type="button" className="user-dropdown-item" onClick={() => switchAdminView('user')}>
                  Войти как пользователь
                </button>
              ) : null}
              {showLogout ? (
                <button type="button" className="user-dropdown-logout" onClick={onLogout}>
                  Выйти
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    )
  }

  const avatarBlock = (
    <div style={{ position: 'relative' }}>
      <button className="avatar" onClick={toggleProfileMenu}>
        <img className="avatar-img" src={avatarUrl || logoUrl} alt={user.fio} />
        <span className={`avatar-status ${user.activityStatus || 'online'}`} />
      </button>
      {menuOpen ? (
        <div className="user-dropdown">
          <div className="user-dropdown-dept">{user.department || 'Без подразделения'}</div>
          {onOpenSettings || onGoToSettings ? (
            <button type="button" className="user-dropdown-item" onClick={openSettings}>
              Настройки
            </button>
          ) : null}
          {canSwitchAdminView ? (
            <button type="button" className="user-dropdown-item" onClick={() => switchAdminView('admin')}>
              Войти как администратор
            </button>
          ) : null}
          {showLogout ? (
            <button className="user-dropdown-logout" onClick={onLogout}>
              Выйти
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )

  return (
    <div className={`user-menu${profileAfterAvatar ? ' user-menu-profile-after-avatar' : ''}`} ref={ref}>
      {notifyBlock}
      {!profileAfterAvatar ? whoBlock : null}
      {avatarBlock}
      {profileAfterAvatar ? whoBlock : null}
    </div>
  )
}
