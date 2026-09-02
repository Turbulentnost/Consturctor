import { useEffect, useState } from 'react'
import { FioSuggest } from './FioSuggest'
import { api, parseChatMessage } from '../api/client'
import { previewText } from '../api/chatCodec'
import { loadUserAvatar } from '../api/avatars'
import type { ChatMessage, ChatThread, DirectoryUser } from '../api/types'
import logoUrl from '../assets/logo.png'
import iconSearch from '../assets/search.png'

export type PageKey =
  | 'today'
  | 'processes'
  | 'calendar'
  | 'decisions'
  | 'metrics'
  | 'history'
  | 'settings'

interface NavItem {
  key: PageKey
  label: string
}

const ITEMS: NavItem[] = [
  { key: 'today', label: 'Сегодня' },
  { key: 'processes', label: 'Процессы' },
  { key: 'calendar', label: 'Календарь' },
  { key: 'decisions', label: 'Решения' },
  { key: 'metrics', label: 'Показатели' },
  { key: 'history', label: 'История' },
  { key: 'settings', label: 'Настройки' }
]

function NavIcon({ page }: { page: PageKey }): React.JSX.Element {
  if (page === 'today') {
    return (
      <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="4" y="5" width="16" height="15" rx="3" />
        <path d="M8 3v4M16 3v4M4 10h16" strokeLinecap="round" />
      </svg>
    )
  }
  if (page === 'processes') {
    return (
      <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="3.2" />
        <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M5.9 5.9l1.5 1.5M16.6 16.6l1.5 1.5M18.1 5.9l-1.5 1.5M7.4 16.6l-1.5 1.5" strokeLinecap="round" />
      </svg>
    )
  }
  if (page === 'decisions') {
    return (
      <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M7 7h10M7 12h10M7 17h6" strokeLinecap="round" />
        <rect x="4" y="4" width="16" height="16" rx="3" />
      </svg>
    )
  }
  if (page === 'metrics') {
    return (
      <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M5 19V9M12 19V5M19 19v-7" strokeLinecap="round" />
        <path d="M4 19.5h16" strokeLinecap="round" />
      </svg>
    )
  }
  if (page === 'calendar') {
    return (
      <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="4" y="5" width="16" height="15" rx="3" />
        <path d="M8 3v4M16 3v4M4 10h16" strokeLinecap="round" />
        <path d="M8 14h2M12 14h2M16 14h2M8 17h2M12 17h2" strokeLinecap="round" />
      </svg>
    )
  }
  if (page === 'history') {
    return (
      <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 12a8 8 0 1 0 2.3-5.7" strokeLinecap="round" />
        <path d="M4 5v4h4M12 8v4l3 2" strokeLinecap="round" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" className="nav-icon-svg" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.6v2.1M12 18.3v2.1M3.6 12h2.1M18.3 12h2.1M5.9 5.9l1.5 1.5M16.6 16.6l1.5 1.5M18.1 5.9l-1.5 1.5M7.4 16.6l-1.5 1.5" strokeLinecap="round" />
    </svg>
  )
}

function initials(fio: string): string {
  const parts = (fio || '').replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function shortFio(fio: string): string {
  const parts = (fio || '').replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return ''
  const rest = parts.slice(1).map((part) => `${part[0].toUpperCase()}.`)
  return [parts[0], ...rest].join(' ')
}

function oneLine(text: string): string {
  return (text || '').replace(/\s+/g, ' ').trim()
}

function lastMessagePreview(value: string | ChatMessage): string {
  if (typeof value === 'string') return oneLine(previewText(value))
  const text = oneLine(value.text)
  if (text) return text
  if (value.agent) return oneLine(`Агент: ${value.agent.title || 'ИИ-агент'}`)
  const file = value.attachments[0]
  return file ? oneLine(file.filename || 'Файл') : ''
}

function sameThread(peer: ChatThread, threadId: string, senderId = ''): boolean {
  if (threadId && peer.id === threadId) return true
  if (peer.kind === 'support' && (peer.id === 'support' || peer.id === threadId)) return true
  if (peer.id.startsWith('dm:') && peer.peerId && (peer.peerId === senderId || peer.peerId === threadId)) {
    return true
  }
  return false
}

interface SidebarProps {
  active: PageKey | null
  activeThreadId?: string
  currentUserId?: string
  onNavigate: (key: PageKey) => void
  onOpenThread: (thread: ChatThread) => void
  onOpenFio: (fio: string, user?: DirectoryUser) => void
  refreshAt?: number
}

export function Sidebar({
  active,
  activeThreadId = '',
  currentUserId = '',
  onNavigate,
  onOpenThread,
  onOpenFio,
  refreshAt = 0
}: SidebarProps): React.JSX.Element {
  const [collapsed, setCollapsed] = useState(false)
  const [fio, setFio] = useState('')
  const [peers, setPeers] = useState<ChatThread[]>([])
  const [peerAvatars, setPeerAvatars] = useState<Record<string, string>>({})

  useEffect(() => {
    let alive = true
    const load = async (): Promise<void> => {
      try {
        const items = await api.listChatThreads()
        if (alive) setPeers(items)
      } catch {
        if (alive) setPeers([])
      }
    }
    void load()
    const timer = window.setInterval(() => {
      void load()
    }, 20000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [refreshAt])

  useEffect(() => {
    const unsubscribe = window.api.onChatEvent?.((payload) => {
      const kind = String(payload.type || '')
      if (kind === 'chat_receipt') {
        const threadId = String(payload.thread_id ?? '')
        const readerId = String(payload.reader_id ?? '')
        if (!threadId || (currentUserId && readerId && readerId !== currentUserId)) return
        setPeers((current) =>
          current.map((peer) => (sameThread(peer, threadId) ? { ...peer, unread: 0 } : peer))
        )
        return
      }
      if (kind !== 'chat_message') return
      const raw = payload.message
      const parsed = parseChatMessage(raw)
      const threadId = String(payload.thread_id ?? parsed?.id ?? '')
      if (!threadId) return
      setPeers((current) => {
        const idx = current.findIndex((peer) => sameThread(peer, threadId, String(payload.sender_id ?? '')))
        if (idx < 0) return current
        const next = [...current]
        const preview = parsed ? lastMessagePreview(parsed) : lastMessagePreview(String(raw || ''))
        next[idx] = { ...next[idx], preview, unread: next[idx].unread + 1 }
        return next
      })
    })
    return () => unsubscribe?.()
  }, [currentUserId])

  useEffect(() => {
    let alive = true
    void Promise.all(
      peers.map(async (peer) => {
        const url = await loadUserAvatar({
          id: peer.peerId || peer.id,
          avatarUrl: peer.avatarUrl
        })
        return [peer.id, url] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const map: Record<string, string> = {}
      for (const [id, url] of pairs) {
        if (url) map[id] = url
      }
      setPeerAvatars(map)
    })
    return () => {
      alive = false
    }
  }, [peers])

  function expandForSearch(): void {
    if (collapsed) setCollapsed(false)
  }

  return (
    <aside className={collapsed ? 'sidebar collapsed' : 'sidebar'}>
      <div className="sidebar-brand">
        <img className="sidebar-logo" src={logoUrl} alt="Orchestrator" />
        {!collapsed && <div className="sidebar-title">Orchestrator</div>}
      </div>

      <div className="sidebar-search" onClick={expandForSearch} title={collapsed ? 'ФИО' : undefined}>
        <img className="sidebar-search-icon" src={iconSearch} alt="" />
        {!collapsed && (
          <FioSuggest
            value={fio}
            onChange={setFio}
            onSelect={(value, user) => {
              setFio('')
              onOpenFio(value, user)
            }}
            placeholder="ФИО"
            inputClassName="sidebar-search-input"
            variant="dark"
          />
        )}
      </div>

      <nav className="nav">
        {ITEMS.map((item) => {
          const isActive = item.key === active
          return (
            <button
              key={item.key}
              className={isActive ? 'nav-item active' : 'nav-item'}
              onClick={() => onNavigate(item.key)}
              title={item.label}
            >
              <span className="nav-icon" aria-hidden>
                <NavIcon page={item.key} />
              </span>
              {!collapsed && <span className="nav-label">{item.label}</span>}
            </button>
          )
        })}
      </nav>

      <div className="sidebar-divider" />

      <div className="sidebar-peers">
        {peers.map((peer) => {
          const isActive = peer.id === activeThreadId || (peer.peerId !== '' && peer.peerId === activeThreadId)
          const preview = lastMessagePreview(peer.preview)
          const unread = peer.unread > 0 && !isActive
          return (
            <button
              key={peer.id}
              className={isActive ? 'sidebar-peer active' : 'sidebar-peer'}
              title={preview ? `${peer.title}\n${preview}` : peer.title}
              onClick={() => {
                if (collapsed) setCollapsed(false)
                setPeers((current) =>
                  current.map((item) => (item.id === peer.id ? { ...item, unread: 0 } : item))
                )
                onOpenThread({ ...peer, unread: 0 })
              }}
            >
              <span className="sidebar-peer-avatar">
                {peerAvatars[peer.id] ? <img src={peerAvatars[peer.id]} alt="" /> : initials(peer.title)}
              </span>
              {!collapsed && (
                <span className="sidebar-peer-meta">
                  <span className="sidebar-peer-name">{shortFio(peer.title)}</span>
                  <span className="sidebar-peer-preview">{preview}</span>
                </span>
              )}
              {unread && <i className="sidebar-peer-dot" aria-hidden />}
            </button>
          )
        })}
      </div>

      <button
        className="collapse-btn"
        onClick={() => setCollapsed((v) => !v)}
        title={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
      >
        {collapsed ? '\u203A' : '\u2039'}
      </button>
    </aside>
  )
}
