import { useEffect, useState } from 'react'
import { FioSuggest } from './FioSuggest'
import { api } from '../api/client'
import { loadUserAvatar } from '../api/avatars'
import type { ChatThread } from '../api/types'
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

const ITEMS: NavItem[] = [
  { key: 'create', label: 'Создать', icon: iconCreate },
  { key: 'agents', label: 'Мои агенты', icon: iconAgents },
  { key: 'files', label: 'Файлы', icon: iconFiles },
  { key: 'kpi', label: 'KPI агента', icon: iconKpi },
  { key: 'orchestrator', label: 'Оркестратор', icon: iconOrchestrator }
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

interface SidebarProps {
  active: PageKey | null
  activeThreadId?: string
  onNavigate: (key: PageKey) => void
  onOpenThread: (thread: ChatThread) => void
  onOpenFio: (fio: string) => void
  refreshAt?: number
}

export function Sidebar({
  active,
  activeThreadId = '',
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
  }, [peers])

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
            onSelect={(value) => {
              setFio(value)
              onOpenFio(value)
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

      <div className="sidebar-divider" />

      <div className="sidebar-peers">
        {peers.map((peer) => {
          const isActive = peer.id === activeThreadId || (peer.peerId !== '' && peer.peerId === activeThreadId)
          return (
            <button
              key={peer.id}
              className={isActive ? 'sidebar-peer active' : 'sidebar-peer'}
              title={peer.title}
              onClick={() => {
                if (collapsed) setCollapsed(false)
                onOpenThread(peer)
              }}
            >
              <span className="sidebar-peer-avatar">
                {peerAvatars[peer.id] ? (
                  <img src={peerAvatars[peer.id]} alt="" />
                ) : (
                  initials(peer.title)
                )}
                {peer.unread > 0 && <i className="sidebar-peer-unread">{peer.unread > 9 ? '9+' : peer.unread}</i>}
              </span>
              {!collapsed && <span className="sidebar-peer-name">{shortFio(peer.title)}</span>}
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
