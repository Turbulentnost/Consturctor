import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Folder, FolderPlus, GripVertical, Pencil, Trash2, X } from 'lucide-react'
import { GlobalSearchSuggest } from './GlobalSearchSuggest'
import { api, parseChatMessage } from '../api/client'
import { previewText } from '../api/chatCodec'
import { loadUserAvatar } from '../api/avatars'
import type { ChatMessage, ChatThread } from '../api/types'
import logoUrl from '../assets/logo.png'
import iconSearch from '../assets/search.png'
import { NavIcon } from '../layout/navIcons'
import { useSpecV04SourcesContext } from '../workplace/SpecV04SourcesProvider'
import {
  addSidebarFolder,
  deleteSidebarFolder,
  folderIdFromNode,
  loadSidebarLayout,
  moveSidebarTab,
  normalizeSidebarLayout,
  renameSidebarFolder,
  saveSidebarLayout,
  tabKeyFromNode,
  toggleSidebarFolder,
  type SidebarLayout,
  type SidebarScope
} from './sidebarFolders'

export type AdminPageKey =
  | 'overview'
  | 'launch_calendar'
  | 'users'
  | 'ai_agents'
  | 'knowledge_base'
  | 'finance_employees'
  | 'finance_upload'
  | 'finance_import_history'

export type UserPageKey =
  | 'today'
  | 'processes'
  | 'tasks'
  | 'projects'
  | 'mail'
  | 'docflow'
  | 'meetings'
  | 'decisions'
  | 'knowledge'
  | 'extensions'
  | 'assignments_registry'
  | 'agent_library'
  | 'task_create'
  | 'platform_task_create'

export type SharedPageKey = 'kpi' | 'history' | 'settings'
export type PageKey = AdminPageKey | UserPageKey | SharedPageKey

export const APP_TITLE = 'Оркестратор'

export const PAGE_LABELS: Record<PageKey, string> = {
  overview: 'Обзор',
  launch_calendar: 'Календарь запуска',
  users: 'Пользователи',
  ai_agents: 'ИИ-агенты',
  knowledge_base: 'База знаний',
  finance_employees: 'Сотрудники',
  finance_upload: 'Загрузить',
  finance_import_history: 'История',
  today: 'Сегодня',
  processes: 'Процессы',
  tasks: 'Задачи',
  projects: 'Turboproject',
  mail: 'Письма',
  docflow: 'Документооборот',
  meetings: 'Совещания',
  decisions: 'Решения',
  knowledge: 'База знаний',
  extensions: 'Расширения',
  assignments_registry: 'Реестр поручений',
  agent_library: 'Библиотека агентов',
  task_create: 'Создание задачи',
  platform_task_create: 'Задача в платформе',
  kpi: 'KPI',
  history: 'История',
  settings: 'Настройки'
}

const ADMIN_ITEMS: { key: PageKey; label: string }[] = [
  { key: 'overview', label: PAGE_LABELS.overview },
  { key: 'history', label: PAGE_LABELS.history },
  { key: 'launch_calendar', label: PAGE_LABELS.launch_calendar },
  { key: 'kpi', label: PAGE_LABELS.kpi },
  { key: 'users', label: PAGE_LABELS.users },
  { key: 'ai_agents', label: PAGE_LABELS.ai_agents },
  { key: 'knowledge_base', label: PAGE_LABELS.knowledge_base },
  { key: 'finance_employees', label: PAGE_LABELS.finance_employees },
  { key: 'finance_upload', label: PAGE_LABELS.finance_upload },
  { key: 'finance_import_history', label: PAGE_LABELS.finance_import_history },
  { key: 'settings', label: PAGE_LABELS.settings }
]

const USER_ITEMS: { key: PageKey; label: string }[] = [
  { key: 'today', label: PAGE_LABELS.today },
  { key: 'processes', label: PAGE_LABELS.processes },
  { key: 'tasks', label: PAGE_LABELS.tasks },
  { key: 'mail', label: PAGE_LABELS.mail },
  { key: 'docflow', label: PAGE_LABELS.docflow },
  { key: 'meetings', label: PAGE_LABELS.meetings },
  { key: 'decisions', label: PAGE_LABELS.decisions },
  { key: 'kpi', label: PAGE_LABELS.kpi },
  { key: 'history', label: PAGE_LABELS.history },
  { key: 'knowledge', label: PAGE_LABELS.knowledge },
  { key: 'extensions', label: '+ Расширения' },
  { key: 'settings', label: PAGE_LABELS.settings }
]

export type SidebarNavItem = { key: PageKey; label: string; extension?: boolean }

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
  return Boolean(peer.id.startsWith('dm:') && peer.peerId && (peer.peerId === senderId || peer.peerId === threadId))
}

type UpdateState = 'idle' | 'available' | 'downloading' | 'installing' | 'error'

interface UpdateStatus {
  state: UpdateState
  currentVersion: string
  availableVersion: string
  percent: number
  error: string
  source: string
  devMode: boolean
}

const IDLE_UPDATE: UpdateStatus = {
  state: 'idle',
  currentVersion: '',
  availableVersion: '',
  percent: 0,
  error: '',
  source: '',
  devMode: false
}

interface SidebarProps {
  active: PageKey | null
  light?: boolean
  showAdminNav?: boolean
  adminPageKeys?: PageKey[]
  adminTitle?: string
  activeThreadId?: string
  currentUserId?: string
  onNavigate: (key: PageKey) => void
  onOpenThread: (thread: ChatThread) => void
  refreshAt?: number
  /** Pinned extension tabs (inserted before «+ Расширения»). */
  pinnedExtensionNav?: SidebarNavItem[]
  navScope?: SidebarScope
}

export function Sidebar({
  active,
  light = false,
  showAdminNav = false,
  adminPageKeys = [],
  adminTitle = 'Администрирование',
  activeThreadId = '',
  currentUserId = '',
  onNavigate,
  onOpenThread,
  refreshAt = 0,
  pinnedExtensionNav = [],
  navScope
}: SidebarProps): React.JSX.Element {
  const [collapsed, setCollapsed] = useState(false)
  const [peers, setPeers] = useState<ChatThread[]>([])
  const [peerAvatars, setPeerAvatars] = useState<Record<string, string>>({})
  const [update, setUpdate] = useState<UpdateStatus>(IDLE_UPDATE)
  const [checking, setChecking] = useState(false)
  const { newOneCTaskKeys } = useSpecV04SourcesContext()
  const navBadges: Partial<Record<PageKey, number>> = { tasks: newOneCTaskKeys.size }
  const items = useMemo((): SidebarNavItem[] => {
    if (showAdminNav) {
      const allowed = new Set(adminPageKeys)
      return ADMIN_ITEMS.filter((item) => allowed.has(item.key))
    }
    const pinnedKeys = new Set(pinnedExtensionNav.map((item) => item.key))
    const core = USER_ITEMS.filter((item) => item.key !== 'extensions' && !pinnedKeys.has(item.key))
    const settings = USER_ITEMS.find((item) => item.key === 'settings')
    const extensionsHub = USER_ITEMS.find((item) => item.key === 'extensions')
    return [
      ...core.filter((item) => item.key !== 'settings'),
      ...pinnedExtensionNav,
      ...(extensionsHub ? [extensionsHub] : []),
      ...(settings ? [settings] : [])
    ]
  }, [showAdminNav, adminPageKeys, pinnedExtensionNav])
  const effectiveNavScope: SidebarScope = navScope ?? (showAdminNav ? 'admin:default' : 'user')
  const availableNavKeys = useMemo(() => items.map((item) => item.key), [items])
  const availableNavKey = availableNavKeys.join('\u0001')
  const [navLayout, setNavLayout] = useState<SidebarLayout>(() =>
    loadSidebarLayout(currentUserId, effectiveNavScope, availableNavKeys)
  )
  const [folderEditor, setFolderEditor] = useState<'new' | string | null>(null)
  const [folderDraft, setFolderDraft] = useState('')
  const [draggedTab, setDraggedTab] = useState<PageKey | null>(null)
  const [dropFolderId, setDropFolderId] = useState<string | null>(null)
  const pointerDragRef = useRef<{
    key: PageKey
    pointerId: number
    startX: number
    startY: number
    moved: boolean
  } | null>(null)
  const itemByKey = useMemo(() => new Map(items.map((item) => [item.key, item])), [items])

  useEffect(() => {
    const next = loadSidebarLayout(currentUserId, effectiveNavScope, availableNavKeys)
    setNavLayout(next)
    saveSidebarLayout(currentUserId, effectiveNavScope, next)
    setFolderEditor(null)
    setDraggedTab(null)
    setDropFolderId(null)
  }, [currentUserId, effectiveNavScope, availableNavKey])

  const persistNavLayout = (next: SidebarLayout): void => {
    const normalized = normalizeSidebarLayout(next, availableNavKeys)
    setNavLayout(normalized)
    saveSidebarLayout(currentUserId, effectiveNavScope, normalized)
  }

  const beginFolderCreate = (): void => {
    if (collapsed) setCollapsed(false)
    setFolderDraft('')
    setFolderEditor('new')
  }

  const beginFolderRename = (folderId: string, currentName: string): void => {
    if (collapsed) setCollapsed(false)
    setFolderDraft(currentName)
    setFolderEditor(folderId)
  }

  const submitFolderEditor = (): void => {
    const name = folderDraft.trim()
    if (!name || !folderEditor) return
    persistNavLayout(
      folderEditor === 'new'
        ? addSidebarFolder(navLayout, name)
        : renameSidebarFolder(navLayout, folderEditor, name)
    )
    setFolderEditor(null)
    setFolderDraft('')
  }

  const removeFolder = (folderId: string, folderName: string): void => {
    if (!window.confirm(`Удалить папку «${folderName}»? Вкладки вернутся в общий список.`)) return
    persistNavLayout(deleteSidebarFolder(navLayout, folderId))
    if (folderEditor === folderId) setFolderEditor(null)
  }

  const finishTabDrag = (): void => {
    pointerDragRef.current = null
    setDraggedTab(null)
    setDropFolderId(null)
  }

  const dropTab = (targetFolderId: string | null, key = draggedTab || ''): void => {
    if (!itemByKey.has(key as PageKey)) return
    persistNavLayout(moveSidebarTab(navLayout, key, targetFolderId))
    finishTabDrag()
  }

  const beginPointerTabDrag = (event: React.PointerEvent<HTMLElement>, key: PageKey): void => {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    pointerDragRef.current = {
      key,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      moved: false
    }
    setDraggedTab(key)
  }

  const updatePointerTabDrag = (event: React.PointerEvent<HTMLElement>): void => {
    const drag = pointerDragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 4) return
    drag.moved = true
    const target = document.elementFromPoint(event.clientX, event.clientY) as HTMLElement | null
    const folder = target?.closest<HTMLElement>('[data-nav-folder-id]')
    if (folder?.dataset.navFolderId) setDropFolderId(folder.dataset.navFolderId)
    else if (target?.closest('[data-nav-root]')) setDropFolderId('__root__')
    else setDropFolderId(null)
  }

  const endPointerTabDrag = (event: React.PointerEvent<HTMLElement>): void => {
    const drag = pointerDragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const target = document.elementFromPoint(event.clientX, event.clientY) as HTMLElement | null
    const folder = target?.closest<HTMLElement>('[data-nav-folder-id]')
    if (drag.moved && folder?.dataset.navFolderId) {
      dropTab(folder.dataset.navFolderId, drag.key)
      return
    }
    if (drag.moved && target?.closest('[data-nav-root]')) {
      dropTab(null, drag.key)
      return
    }
    finishTabDrag()
  }

  const renderNavTab = (item: SidebarNavItem, nested = false): React.JSX.Element => {
    const isActive = item.key === active
    const isExtensionModule = 'extension' in item && Boolean(item.extension)
    const isExtensionsHub = item.key === 'extensions'
    const badge = showAdminNav ? 0 : navBadges[item.key] ?? 0
    const badgeText = badge > 99 ? '99+' : String(badge)
    return (
      <div
        key={item.key}
        className={['nav-tab-row', nested ? 'nav-tab-row-nested' : '', draggedTab === item.key ? 'dragging' : '']
          .filter(Boolean)
          .join(' ')}
      >
        <button
          type="button"
          className={[
            'nav-item',
            isActive ? 'active' : '',
            isExtensionsHub ? 'nav-item-extensions-hub' : '',
            isExtensionModule ? 'nav-item-extension-module' : ''
          ]
            .filter(Boolean)
            .join(' ')}
          onClick={() => onNavigate(item.key)}
          title={badge > 0 ? `${item.label}: новых задач 1С — ${badge}` : item.label}
        >
          <span className="nav-icon" aria-hidden>
            <NavIcon page={item.key} />
          </span>
          {!collapsed && <span className="nav-label">{item.label}</span>}
          {badge > 0 ? (
            <em className="nav-badge" aria-label={`Новых: ${badge}`}>
              {badgeText}
            </em>
          ) : null}
        </button>
        {!collapsed ? (
          <span
            className="nav-drag-handle"
            role="button"
            tabIndex={0}
            aria-label={`Переместить вкладку «${item.label}»`}
            title="Перетащите вкладку в папку или общий список"
            onPointerDown={(event) => beginPointerTabDrag(event, item.key)}
            onPointerMove={updatePointerTabDrag}
            onPointerUp={endPointerTabDrag}
            onPointerCancel={finishTabDrag}
            onClick={(event) => event.stopPropagation()}
          >
            <GripVertical size={15} strokeWidth={2} aria-hidden />
          </span>
        ) : null}
      </div>
    )
  }

  const runCheck = (): void => {
    if (checking) return
    setChecking(true)
    void window.api
      .checkUpdate?.()
      .then((payload) => {
        if (payload) setUpdate(payload)
      })
      .finally(() => setChecking(false))
  }

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
      try {
        const loaded = await api.listChatThreads()
        if (alive) setPeers(loaded)
      } catch {
        if (alive) setPeers([])
      }
    }
    void load()
    const timer = window.setInterval(() => {
      void load()
    }, 120_000)
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
        setPeers((current) => current.map((peer) => (sameThread(peer, threadId) ? { ...peer, unread: 0 } : peer)))
        return
      }
      if (kind !== 'chat_message') return
      const parsed = parseChatMessage(payload.message)
      const threadId = String(payload.thread_id ?? parsed?.id ?? '')
      if (!threadId) return
      setPeers((current) => {
        const idx = current.findIndex((peer) => sameThread(peer, threadId, String(payload.sender_id ?? '')))
        if (idx < 0) return current
        const next = [...current]
        next[idx] = {
          ...next[idx],
          preview: parsed ? lastMessagePreview(parsed) : lastMessagePreview(String(payload.message || '')),
          unread: next[idx].unread + 1
        }
        return next
      })
    })
    return () => unsubscribe?.()
  }, [currentUserId])

  const peoplePeers = peers.filter((peer) => peer.kind !== 'support')
  const peerAvatarKey = peoplePeers
    .map((peer) => `${peer.id}\u0000${peer.peerId || peer.id}\u0000${peer.avatarUrl || ''}`)
    .join('\u0001')
  useEffect(() => {
    let alive = true
    const entries = peerAvatarKey ? peerAvatarKey.split('\u0001') : []
    void Promise.all(
      entries.map(async (entry) => {
        const [threadId, userId, avatarUrl] = entry.split('\u0000')
        const url = await loadUserAvatar({ id: userId, avatarUrl })
        return [threadId, url] as const
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
  }, [peerAvatarKey])

  function expandForSearch(): void {
    if (collapsed) setCollapsed(false)
  }

  return (
    <aside className={['sidebar', collapsed ? 'collapsed' : '', light ? 'light' : ''].filter(Boolean).join(' ')}>
      <div className="sidebar-brand">
        <img className="sidebar-logo" src={logoUrl} alt={APP_TITLE} />
        {!collapsed && showAdminNav ? (
          <div className="sidebar-brand-text">
            <div className="sidebar-title">{APP_TITLE}</div>
            <div className="sidebar-subtitle">{adminTitle}</div>
          </div>
        ) : null}
        {!collapsed && !showAdminNav ? (
          <div className="sidebar-title">
            <strong>Оркестратор</strong>
            <span>должности</span>
          </div>
        ) : null}
      </div>

      <div className="sidebar-search" onClick={expandForSearch} title={collapsed ? 'Поиск' : undefined}>
        <img className="sidebar-search-icon" src={iconSearch} alt="" />
        {!collapsed && (
          <GlobalSearchSuggest
            placeholder="Поиск"
            inputClassName="sidebar-search-input"
          />
        )}
      </div>

      <div className="nav-toolbar">
        <button
          type="button"
          className="nav-folder-add"
          onClick={beginFolderCreate}
          title="Создать папку вкладок"
          aria-label="Создать папку вкладок"
        >
          <FolderPlus size={17} strokeWidth={2} aria-hidden />
          {!collapsed ? <span>Новая папка</span> : null}
        </button>
      </div>

      <nav
        className={draggedTab ? 'nav nav-dragging' : 'nav'}
        data-nav-root
      >
        {folderEditor === 'new' ? (
          <div className="nav-folder-editor">
            <Folder size={17} aria-hidden />
            <input
              autoFocus
              value={folderDraft}
              maxLength={64}
              placeholder="Название папки"
              aria-label="Название новой папки"
              onChange={(event) => setFolderDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submitFolderEditor()
                if (event.key === 'Escape') setFolderEditor(null)
              }}
            />
            <button type="button" onClick={submitFolderEditor} disabled={!folderDraft.trim()} aria-label="Сохранить папку">
              <Check size={15} aria-hidden />
            </button>
            <button type="button" onClick={() => setFolderEditor(null)} aria-label="Отменить создание">
              <X size={15} aria-hidden />
            </button>
          </div>
        ) : null}

        {draggedTab ? (
          <div
            className={`nav-root-drop-zone${dropFolderId === '__root__' ? ' is-over' : ''}`}
          >
            В общий список
          </div>
        ) : null}

        {navLayout.root.map((nodeId) => {
          const tabKey = tabKeyFromNode(nodeId)
          if (tabKey !== null) {
            const item = itemByKey.get(tabKey as PageKey)
            return item ? renderNavTab(item) : null
          }
          const folderId = folderIdFromNode(nodeId)
          const folder = navLayout.folders.find((item) => item.id === folderId)
          if (!folder) return null
          const containsActive = active !== null && folder.tabKeys.includes(active)
          const isEditing = folderEditor === folder.id
          return (
            <div
              key={nodeId}
              className={[
                'nav-folder',
                containsActive ? 'has-active' : '',
                dropFolderId === folder.id ? 'is-drop-target' : ''
              ]
                .filter(Boolean)
                .join(' ')}
              data-nav-folder-id={folder.id}
            >
              {isEditing ? (
                <div className="nav-folder-editor">
                  <Folder size={17} aria-hidden />
                  <input
                    autoFocus
                    value={folderDraft}
                    maxLength={64}
                    aria-label={`Новое название папки «${folder.name}»`}
                    onChange={(event) => setFolderDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') submitFolderEditor()
                      if (event.key === 'Escape') setFolderEditor(null)
                    }}
                  />
                  <button type="button" onClick={submitFolderEditor} disabled={!folderDraft.trim()} aria-label="Сохранить название">
                    <Check size={15} aria-hidden />
                  </button>
                  <button type="button" onClick={() => setFolderEditor(null)} aria-label="Отменить переименование">
                    <X size={15} aria-hidden />
                  </button>
                </div>
              ) : (
                <div className="nav-folder-row">
                  <button
                    type="button"
                    className="nav-folder-toggle"
                    aria-expanded={collapsed ? undefined : folder.expanded}
                    title={folder.name}
                    onClick={() => {
                      if (collapsed) setCollapsed(false)
                      else persistNavLayout(toggleSidebarFolder(navLayout, folder.id))
                    }}
                  >
                    <span className="nav-folder-chevron" aria-hidden>
                      {folder.expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </span>
                    <Folder size={17} aria-hidden />
                    {!collapsed ? <span className="nav-folder-name">{folder.name}</span> : null}
                  </button>
                  {!collapsed ? (
                    <span className="nav-folder-actions">
                      <button
                        type="button"
                        onClick={() => beginFolderRename(folder.id, folder.name)}
                        title="Переименовать папку"
                        aria-label={`Переименовать папку «${folder.name}»`}
                      >
                        <Pencil size={13} aria-hidden />
                      </button>
                      <button
                        type="button"
                        onClick={() => removeFolder(folder.id, folder.name)}
                        title="Удалить папку"
                        aria-label={`Удалить папку «${folder.name}»`}
                      >
                        <Trash2 size={13} aria-hidden />
                      </button>
                    </span>
                  ) : null}
                </div>
              )}
              {!collapsed && folder.expanded ? (
                <div className="nav-folder-children">
                  {folder.tabKeys.map((key) => {
                    const item = itemByKey.get(key as PageKey)
                    return item ? renderNavTab(item, true) : null
                  })}
                  {!folder.tabKeys.length ? <span className="nav-folder-empty">Перетащите вкладку сюда</span> : null}
                </div>
              ) : null}
            </div>
          )
        })}
      </nav>

      <div className="sidebar-update">
        {!collapsed ? (
          <p className="sidebar-update-meta">
            {update.currentVersion ? `v${update.currentVersion}` : 'Версия —'}
            {update.availableVersion && update.availableVersion !== update.currentVersion
              ? ` → ${update.availableVersion}`
              : ''}
          </p>
        ) : null}
        {update.error && !collapsed ? <p className="sidebar-update-error">{update.error}</p> : null}
        {update.state === 'downloading' || update.state === 'installing' ? (
          <div
            className={update.percent > 0 ? 'sidebar-update-progress' : 'sidebar-update-progress indeterminate'}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={update.percent}
          >
            <i className="sidebar-update-progress-bar" style={update.percent > 0 ? { width: `${update.percent}%` } : undefined} />
            {!collapsed && (
              <span className="sidebar-update-progress-label">
                {update.state === 'installing' ? 'Установка...' : update.percent > 0 ? `${update.percent}%` : 'Загрузка...'}
              </span>
            )}
          </div>
        ) : update.state === 'available' && !update.devMode ? (
          <button
            className="sidebar-update-btn"
            title={update.error || 'Установить обновление Конструктора и Оркестратора'}
            onClick={() => void window.api.installUpdate?.()}
          >
            {!collapsed && <span>Обновить обе программы</span>}
            {collapsed && <span className="sidebar-update-mark">!</span>}
          </button>
        ) : null}
        <button
          type="button"
          className="sidebar-update-check"
          disabled={checking || update.state === 'downloading' || update.state === 'installing'}
          title="Проверить обновление приложения (не перезагрузка данных сеток)"
          onClick={runCheck}
        >
          {collapsed ? '↻' : checking ? 'Проверяем…' : 'Проверить обновление'}
        </button>
      </div>

      <div className="sidebar-divider" />
      <div className="sidebar-peers">
        {peoplePeers.map((peer) => {
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
                setPeers((current) => current.map((item) => (item.id === peer.id ? { ...item, unread: 0 } : item)))
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

      <button className="collapse-btn" onClick={() => setCollapsed((value) => !value)} title={collapsed ? 'Развернуть меню' : 'Свернуть меню'}>
        {collapsed ? '\u203A' : '\u2039'}
      </button>
    </aside>
  )
}
