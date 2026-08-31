import { useEffect, useState } from 'react'
import { FioSuggest } from './FioSuggest'
import { api, parseChatMessage } from '../api/client'
import { previewText } from '../api/chatCodec'
import { loadUserAvatar } from '../api/avatars'
import type { ChatMessage, ChatThread, DirectoryUser } from '../api/types'
import logoUrl from '../assets/logo.png'
import iconCreate from '../assets/nav-create.png'
import iconAgents from '../assets/nav-agents.png'
import iconFiles from '../assets/nav-files.png'
import iconKpi from '../assets/nav-kpi.png'
import iconOrchestrator from '../assets/nav-orchestrator.svg'
import iconSearch from '../assets/search.png'

export type PageKey = 'create' | 'agents' | 'files' | 'kpi' | 'orchestrator'

interface NavItem {
  key: PageKey
  label: string
  icon: string
}

type UpdateState = 'idle' | 'available' | 'downloading' | 'installing' | 'error'

interface UpdateStatus {
  state: UpdateState
  currentVersion: string
  availableVersion: string
  percent: number
  error: string
}

const IDLE_UPDATE: UpdateStatus = {
  state: 'idle',
  currentVersion: '',
  availableVersion: '',
  percent: 0,
  error: ''
}

const ITEMS: NavItem[] = [
  { key: 'create', label: 'Создать', icon: iconCreate },
  { key: 'agents', label: 'Мои агенты', icon: iconAgents },
  { key: 'files', label: 'Файлы', icon: iconFiles },
  { key: 'kpi', label: 'KPI агента', icon: iconKpi },
  { key: 'orchestrator', label: 'KPI сотрудника', icon: iconOrchestrator }
]

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
  const [update, setUpdate] = useState<UpdateStatus>(IDLE_UPDATE)

  useEffect(() => {
    let alive = true
    void window.api.getUpdateStatus?.().then((payload) => {
      if (alive && payload) setUpdate(payload)
    })
    const unsubscribe = window.api.onUpdateStatus?.((payload) => {
      setUpdate(payload)
    })
    return () => {
      alive = false
      unsubscribe?.()
    }
  }, [])

  useEffect(() => {
    let alive = true
    const load = async (): Promise<void> => {
      const items = await api.listChatThreads()
      if (alive) setPeers(items)
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
      const raw =
        payload.message && typeof payload.message === 'object'
          ? payload.message
          : payload
      const incoming = parseChatMessage({
        ...(raw as Record<string, unknown>),
        mine: String((raw as Record<string, unknown>).sender_id ?? '') === currentUserId
      })
      const threadId = String(payload.thread_id ?? incoming.threadId ?? '')
      if (!threadId) return
      const preview = lastMessagePreview(incoming)
      const mine = incoming.mine || incoming.senderId === currentUserId
      setPeers((current) => {
        let found = false
        const next = current.map((peer) => {
          if (!sameThread(peer, threadId, incoming.senderId)) return peer
          found = true
          const open = Boolean(activeThreadId) && (peer.id === activeThreadId || peer.peerId === activeThreadId)
          return {
            ...peer,
            preview,
            lastMessageAt: incoming.createdAt || peer.lastMessageAt,
            unread: mine || open ? 0 : peer.unread + 1
          }
        })
        return found ? next : current
      })
    })
    return () => unsubscribe?.()
  }, [activeThreadId, currentUserId])

  useEffect(() => {
    let alive = true
    void Promise.all(
      peers.map(async (peer) => {
        const url = await loadUserAvatar({
          id: peer.peerId,
          avatarUrl: peer.avatarUrl
        })
        return [peer.id, url] as const
      })
    ).then((rows) => {
      if (!alive) return
      const next: Record<string, string> = {}
      for (const [id, url] of rows) {
        if (url) next[id] = url
      }
      setPeerAvatars(next)
    })
    return () => {
      alive = false
    }
  }, [peers.map((peer) => `${peer.id}:${peer.peerId}:${peer.avatarUrl || ''}`).join('|')])

  function expandForSearch(): void {
    if (collapsed) setCollapsed(false)
  }

  return (
    <aside className={collapsed ? 'sidebar collapsed' : 'sidebar'}>
      <div className="sidebar-brand">
        <img className="sidebar-logo" src={logoUrl} alt="turbobot" />
        {!collapsed && <div className="sidebar-title">turbobot</div>}
      </div>

      <div
        className="sidebar-search"
        onClick={expandForSearch}
        title={collapsed ? 'ФИО' : undefined}
      >
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
              <img
                className={isActive ? 'nav-icon-img' : 'nav-icon-img inactive'}
                src={item.icon}
                alt=""
              />
              {!collapsed && <span className="nav-label">{item.label}</span>}
            </button>
          )
        })}
      </nav>

      {(update.state === 'available' ||
        update.state === 'downloading' ||
        update.state === 'installing' ||
        update.state === 'error') && (
        <div className="sidebar-update">
          {update.state === 'downloading' || update.state === 'installing' ? (
            <div
              className={
                update.percent > 0
                  ? 'sidebar-update-progress'
                  : 'sidebar-update-progress indeterminate'
              }
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={update.percent}
              title={update.state === 'installing' ? 'Установка обновления' : 'Загрузка обновления'}
            >
              <i
                className="sidebar-update-progress-bar"
                style={update.percent > 0 ? { width: `${update.percent}%` } : undefined}
              />
              {!collapsed && (
                <span className="sidebar-update-progress-label">
                  {update.state === 'installing'
                    ? 'Установка...'
                    : update.percent > 0
                      ? `${update.percent}%`
                      : 'Загрузка...'}
                </span>
              )}
            </div>
          ) : (
            <button
              className="sidebar-update-btn"
              title={update.error || 'Установить обновление'}
              onClick={() => {
                void window.api.installUpdate?.()
              }}
            >
              {!collapsed && <span>Установить обновление</span>}
              {collapsed && <span className="sidebar-update-mark">!</span>}
            </button>
          )}
        </div>
      )}

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
                {peerAvatars[peer.id] ? (
                  <img src={peerAvatars[peer.id]} alt="" />
                ) : (
                  initials(peer.title)
                )}
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
