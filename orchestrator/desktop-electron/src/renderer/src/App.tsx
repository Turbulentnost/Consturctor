import { useEffect, useRef, useState } from 'react'
import { Sidebar, type PageKey } from './components/Sidebar'
import { UserMenu } from './components/UserMenu'
import { LoginPage } from './pages/LoginPage'
import { MessengerPage } from './pages/MessengerPage'
import { api } from './api/client'
import { agentClient } from './api/agent'
import { clearAvatarCache, loadUserAvatar } from './api/avatars'
import type { ChatThread, DirectoryUser, LoginResult, UserProfile } from './api/types'
import {
  clearComCredentials,
  comCredentials,
  clearSession,
  loadSession,
  saveSession,
  setComCredentials
} from './store/session'
import { AgentRunPage } from './pages/AgentRunPage'
import { AgentHistoryPage } from './pages/AgentHistoryPage'
import { AgentSchedulePage } from './pages/AgentSchedulePage'
import { AgentPassportPage, type PassportTab } from './pages/AgentPassportPage'
import { ProcessesWorkplace } from './workplace/ProcessesWorkplace'
import { FilesPage } from './pages/FilesPage'
import { KpiPage } from './pages/KpiPage'
import { RunBannerCarousel, type BannerEntry } from './components/RunBannerCarousel'
import { useRuns, deriveLatestOutput } from './store/runs'
import { isInFlightRunStatus, isLiveRunState } from './store/liveRun'
import { ChatDock } from './workplace/ChatDock'
import { isPersonalAgentWorkflowId } from './workplace/personalAgent'
import {
  DecisionsTab,
  DiagnosticsPage,
  HistoryTab,
  SettingsTab,
  TicketsPage,
  TodayTab
} from './workplace/WorkplaceTabs'

function decodeJwtPart(part: string): string {
  const normalized = part.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  try {
    return decodeURIComponent(
      atob(padded)
        .split('')
        .map((ch) => `%${ch.charCodeAt(0).toString(16).padStart(2, '0')}`)
        .join('')
    )
  } catch {
    return ''
  }
}

function isOrchestratorToken(token: string): boolean {
  const parts = token.split('.')
  if (parts.length < 2) return false
  const payloadRaw = decodeJwtPart(parts[1] || '')
  if (!payloadRaw) return false
  try {
    const payload = JSON.parse(payloadRaw) as Record<string, unknown>
    const cid = String(payload.cid || payload.client || '').trim().toLowerCase()
    return cid === 'orchestrator'
  } catch {
    return false
  }
}

type View =
  | { kind: 'tab'; key: PageKey }
  | { kind: 'chat'; thread: ChatThread }
  | { kind: 'tickets' }
  | { kind: 'diagnostics' }
  | { kind: 'files'; workflowId?: string; title?: string }
  | { kind: 'passport'; workflowId: string; title: string; tab?: PassportTab }
  | { kind: 'agentrun'; workflowId: string; title: string; autoStart?: boolean }
  | { kind: 'history'; workflowId: string; title: string; runId?: string }
  | { kind: 'schedule'; workflowId: string; title: string }

function fioKey(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function fioEquals(left: string, right: string): boolean {
  const a = fioKey(left)
  const b = fioKey(right)
  return Boolean(a) && Boolean(b) && (a === b || a.startsWith(b) || b.startsWith(a))
}

function findExistingChat(threads: ChatThread[], name: string, peerId?: string): ChatThread | undefined {
  if (peerId) {
    const byPeer = threads.find((item) => item.kind !== 'support' && item.peerId === peerId)
    if (byPeer) return byPeer
  }
  return threads.find((item) => item.kind !== 'support' && fioEquals(item.title, name))
}

export function App(): React.JSX.Element {
  const [booting, setBooting] = useState(true)
  const [user, setUser] = useState<UserProfile | null>(null)
  const [showLogout, setShowLogout] = useState(true)
  const [view, setView] = useState<View>({ kind: 'tab', key: 'today' })
  const [unread, setUnread] = useState(0)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [toast, setToast] = useState('')
  const kickedRef = useRef(false)
  const [chatRefreshAt, setChatRefreshAt] = useState(0)
  const runs = useRuns()

  useEffect(() => {
    let done = false
    const finish = (): void => {
      if (done) return
      done = true
      setBooting(false)
    }
    const watchdog = window.setTimeout(finish, 10_000)
    ;(async () => {
      try {
        const config = await window.api.getConfig()
        setShowLogout(!config.testUser)
        const stored = loadSession()
        if (stored?.accessToken) {
          if (!isOrchestratorToken(stored.accessToken)) {
            clearSession(true)
          } else {
            api.setToken(stored.accessToken)
            try {
              const profile = await api.me(8_000)
              setUser(profile)
            } catch {
              clearSession(true)
              api.setToken(null)
            }
          }
        }
      } catch {
        /* show login even if config or restore fails */
      } finally {
        window.clearTimeout(watchdog)
        finish()
      }
    })()
    return () => {
      window.clearTimeout(watchdog)
      done = true
    }
  }, [])

  useEffect(() => {
    if (!user) {
      setAvatarUrl(null)
      return
    }
    let alive = true
    void loadUserAvatar(user).then((url) => {
      if (alive) setAvatarUrl(url)
    })
    return () => {
      alive = false
    }
  }, [user])

  useEffect(() => {
    const subscribe = window.api.onSessionKicked
    if (!subscribe) return
    return subscribe((payload) => {
      if (kickedRef.current) return
      kickedRef.current = true
      window.alert(
        (payload.message || '').trim() || 'Выполнен вход на другом устройстве. Этот сеанс завершён.'
      )
      void resetToLogin()
    })
  }, [])

  useEffect(() => {
    if (!user) {
      kickedRef.current = false
      void window.api.stopNotifications?.()
      void agentClient.ready(null, { login: '', password: '' }).catch(() => undefined)
      return
    }
    const token = api.getToken()
    if (token) void window.api.startNotifications?.(token)
    const creds = comCredentials()
    void agentClient
      .ready(token, { login: creds.login || user.fio, password: creds.password || '' })
      .catch(() => undefined)
  }, [user?.id])

  useEffect(() => {
    if (!user) return
    let alive = true
    const refresh = async (): Promise<void> => {
      try {
        const count = await api.unreadNotificationCount()
        if (alive) setUnread(count)
      } catch {
        if (alive) setUnread(0)
      }
    }
    void refresh()
    const timer = setInterval(refresh, 20000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [user])

  useEffect(() => {
    const unsubscribe = window.api.onChatEvent?.(() => {
      setChatRefreshAt(Date.now())
    })
    return () => unsubscribe?.()
  }, [])

  function onLoggedIn(result: LoginResult, remember: boolean, password = ''): void {
    api.setToken(result.accessToken || null)
    setComCredentials(result.user.fio, password)
    void agentClient
      .ready(result.accessToken || null, { login: result.user.fio, password })
      .catch(() => undefined)
    if (remember && result.accessToken) {
      saveSession({ accessToken: result.accessToken, fio: result.user.fio })
    } else {
      clearSession(true)
    }
    setUser(result.user)
    setView({ kind: 'tab', key: 'today' })
    if (result.accessToken) {
      void api.me().then(setUser).catch(() => undefined)
    }
  }

  async function resetToLogin(): Promise<void> {
    void window.api.stopNotifications?.()
    clearSession(true)
    clearComCredentials()
    api.setToken(null)
    clearAvatarCache()
    setAvatarUrl(null)
    setView({ kind: 'tab', key: 'today' })
    setUser(null)
  }

  function flash(text: string): void {
    setToast(text)
    window.setTimeout(() => setToast(''), 2400)
  }

  function openChat(thread: ChatThread): void {
    setView({ kind: 'chat', thread })
    setChatRefreshAt(Date.now())
  }

  async function openChatByFio(fio: string, picked?: DirectoryUser): Promise<void> {
    const name = (picked?.fio || fio).trim()
    if (!name) return
    const me = user
    if (me && (picked?.id === me.id || name.toLowerCase() === me.fio.trim().toLowerCase())) return
    try {
      const threads = await api.listChatThreads()
      const existing = findExistingChat(threads, name, picked?.id)
      if (existing) {
        openChat(existing)
        return
      }
      let match = picked && picked.id ? picked : null
      if (!match?.id) {
        const users = await api.listDirectoryUsers(name)
        match =
          users.find((item) => fioEquals(item.fio, name) && item.id && item.id !== me?.id) ||
          users.find((item) => item.id && item.id !== me?.id) ||
          null
      }
      if (!match?.id) {
        openChat({
          id: `dm:local-${name}`,
          kind: 'dm',
          title: name,
          position: picked?.position || '',
          preview: '',
          lastMessageAt: '',
          unread: 0,
          pinned: false,
          peerId: picked?.id || '',
          activityStatus: 'offline',
          online: false,
          ticketStatus: '',
          avatarUrl: picked?.avatarUrl || null
        })
        return
      }
      try {
        await api.openDirectChat(match.id)
      } catch {
        /* local dialog */
      }
      const next = (await api.listChatThreads()).find((item) => item.peerId === match.id)
      openChat(
        next || {
          id: `dm:${match.id}`,
          kind: 'dm',
          title: match.fio || name,
          position: match.position,
          preview: '',
          lastMessageAt: '',
          unread: 0,
          pinned: false,
          peerId: match.id,
          activityStatus: match.activityStatus,
          online: match.online,
          ticketStatus: '',
          avatarUrl: match.avatarUrl
        }
      )
    } catch {
      openChat({
        id: `dm:local-${name}`,
        kind: 'dm',
        title: name,
        position: '',
        preview: '',
        lastMessageAt: '',
        unread: 0,
        pinned: false,
        peerId: '',
        activityStatus: 'offline',
        online: false,
        ticketStatus: '',
        avatarUrl: null
      })
    }
  }

  function openSupport(): void {
    openChat({
      id: 'support',
      kind: 'support',
      title: 'Техническая поддержка',
      position: 'Закреплённый разработчик',
      preview: '',
      lastMessageAt: '',
      unread: 0,
      pinned: true,
      peerId: '',
      activityStatus: 'online',
      online: true,
      ticketStatus: 'new',
      avatarUrl: null
    })
    flash('Обращение зарегистрировано в журнале заявок')
  }

  function openAgentFiles(workflowId: string, title = ''): void {
    const wid = (workflowId || '').trim()
    if (!wid) {
      setView({ kind: 'files' })
      return
    }
    setView({ kind: 'files', workflowId: wid, title: title || '' })
  }

  if (booting) {
    return (
      <div className="app-root boot-screen">
        <div className="spinner spinner-on-dark" />
        <div className="boot-label">Загрузка Orchestrator...</div>
      </div>
    )
  }

  if (!user) {
    return <LoginPage onLoggedIn={onLoggedIn} />
  }
  const activeUser = user

  const activeKey: PageKey | null =
    view.kind === 'tab'
      ? view.key
      : view.kind === 'chat'
        ? null
        : view.kind === 'agentrun' || view.kind === 'history' || view.kind === 'schedule' || view.kind === 'passport'
          ? 'processes'
          : 'settings'

  async function openAgentRun(workflowId: string, runId = '', autoStart = false, title = ''): Promise<void> {
    if (!workflowId) {
      flash('У карточки нет id агента на сервере')
      return
    }
    if (isPersonalAgentWorkflowId(workflowId)) {
      setView({ kind: 'agentrun', workflowId, title: title || 'Базовый агент', autoStart: false })
      return
    }
    const nextTitle = title || 'ИИ-агент'
    const live = runs.entries[workflowId]
    if (live && isLiveRunState(live.state)) {
      setView({ kind: 'agentrun', workflowId, title: nextTitle || live.title, autoStart: false })
      return
    }
    if (runId) {
      // Открываем историю сразу, чтобы кнопка "Открыть прогон" реагировала
      // мгновенно даже при медленном backend. Детали проверим в фоне.
      setView({ kind: 'history', workflowId, title: nextTitle, runId })
      void (async () => {
        try {
          const [record, detail] = await Promise.all([
            api.getWorkflow(workflowId).catch(() => null),
            api.getAgentRunDetail(workflowId, runId)
          ])
          const resolvedTitle = record?.title || nextTitle
          if (isInFlightRunStatus(detail.item.status)) {
            runs.noteRunning(workflowId, resolvedTitle, runId)
            void runs.attachHistoryFeed(workflowId)
            setView({ kind: 'agentrun', workflowId, title: resolvedTitle, autoStart: false })
          } else {
            setView({ kind: 'history', workflowId, title: resolvedTitle, runId })
          }
        } catch {
          /* keep already opened history page */
        }
      })()
      return
    }
    setView({ kind: 'agentrun', workflowId, title: nextTitle || 'ИИ-агент', autoStart })
  }

  function renderContent(): React.JSX.Element {
    if (view.kind === 'chat') {
      return (
        <MessengerPage
          thread={view.thread}
          me={user!}
          onThreadChange={(thread) => setView({ kind: 'chat', thread })}
          onOpenAgent={() => setView({ kind: 'tab', key: 'processes' })}
        />
      )
    }
    if (view.kind === 'tickets') {
      return (
        <TicketsPage
          user={user!}
          onBack={() => setView({ kind: 'tab', key: 'settings' })}
          onOpenThread={openChat}
        />
      )
    }
    if (view.kind === 'diagnostics') {
      return (
        <DiagnosticsPage
          onBack={() => setView({ kind: 'tab', key: 'settings' })}
          onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)}
        />
      )
    }
    if (view.kind === 'files') {
      return (
        <FilesPage
          ownerName={user?.fio || ''}
          initialWorkflowId={view.workflowId || ''}
          initialAgentTitle={view.title || ''}
          onOpenRun={(workflowId, runId) => void openAgentRun(workflowId, runId)}
        />
      )
    }
    if (view.kind === 'agentrun') {
      return (
        <AgentRunPage
          workflowId={view.workflowId}
          title={view.title}
          autoStart={view.autoStart}
          onBack={() => setView({ kind: 'tab', key: 'processes' })}
          onOpenHistory={(workflowId, title) => setView({ kind: 'history', workflowId, title })}
        />
      )
    }
    if (view.kind === 'passport') {
      return (
        <AgentPassportPage
          workflowId={view.workflowId}
          title={view.title}
          initialTab={view.tab || 'info'}
          onBack={() => setView({ kind: 'tab', key: 'today' })}
          onRun={(workflowId, title) => void openAgentRun(workflowId, '', true, title)}
          onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)}
        />
      )
    }
    if (view.kind === 'history') {
      return (
        <AgentHistoryPage
          workflowId={view.workflowId}
          title={view.title}
          initialRunId={view.runId}
          onBack={() => setView({ kind: 'tab', key: 'processes' })}
          onOpenLive={() =>
            setView({ kind: 'agentrun', workflowId: view.workflowId, title: view.title })
          }
        />
      )
    }
    if (view.kind === 'schedule') {
      return (
        <AgentSchedulePage
          workflowId={view.workflowId}
          title={view.title}
          onBack={() => setView({ kind: 'tab', key: 'processes' })}
          onNext={() => setView({ kind: 'tab', key: 'processes' })}
        />
      )
    }
    switch (view.key) {
      case 'processes':
        return (
          <ProcessesWorkplace
            userId={activeUser.id || ''}
            userFio={activeUser.fio || ''}
            onOpen={(workflowId, title, tab) => setView({ kind: 'passport', workflowId, title, tab: tab || 'info' })}
            onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)}
            onFiles={(workflowId, title) => openAgentFiles(workflowId, title)}
            onHistory={(workflowId, title) => setView({ kind: 'history', workflowId, title })}
            onSchedule={(workflowId, title) => setView({ kind: 'schedule', workflowId, title })}
          />
        )
      case 'decisions':
        return (
          <DecisionsTab
            onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', Boolean(!runId), title)}
          />
        )
      case 'metrics':
        return <KpiPage />
      case 'history':
        return (
          <HistoryTab
            onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)}
          />
        )
      case 'settings':
        return (
          <SettingsTab
            user={activeUser}
            onDiagnostics={() => setView({ kind: 'diagnostics' })}
            onTickets={() => setView({ kind: 'tickets' })}
            onFiles={() => setView({ kind: 'files' })}
            onSupport={openSupport}
          />
        )
      default:
        return (
          <TodayTab
            user={activeUser}
            onOpenDecisions={() => setView({ kind: 'tab', key: 'decisions' })}
            onOpenMetrics={() => setView({ kind: 'tab', key: 'metrics' })}
            onOpenPassport={(workflowId, title, tab) => setView({ kind: 'passport', workflowId, title, tab })}
            onRun={(workflowId, title) => void openAgentRun(workflowId, '', true, title)}
          />
        )
    }
  }

  const bannerEntries: BannerEntry[] = []
  for (const entry of Object.values(runs.entries)) {
    const active =
      entry.state.running || Boolean(entry.state.pendingQuestion) || Boolean(entry.state.pendingHitl)
    if (!active) continue
    if (view.kind === 'agentrun' && view.workflowId === entry.workflowId) continue
    bannerEntries.push({
      id: `run:${entry.workflowId}`,
      title: entry.title,
      output: deriveLatestOutput(entry.state.items),
      running: entry.state.running,
      awaiting: Boolean(entry.state.pendingQuestion || entry.state.pendingHitl),
      mode: 'run',
      onOpen: () => setView({ kind: 'agentrun', workflowId: entry.workflowId, title: entry.title })
    })
  }

  return (
    <div className="app-root">
      <Sidebar
        active={activeKey}
        activeThreadId={view.kind === 'chat' ? view.thread.id : ''}
        currentUserId={user.id || ''}
        onNavigate={(key) => setView({ kind: 'tab', key })}
        onOpenThread={openChat}
        onOpenFio={(fio, picked) => void openChatByFio(fio, picked)}
        refreshAt={chatRefreshAt}
      />
      <main className="content">
        <div className={view.kind === 'chat' ? 'content-inner messenger-mode' : 'content-inner'}>
          <div className="app-page-header">
            <UserMenu
              user={user}
              avatarUrl={avatarUrl}
              unread={unread}
              onUnreadChange={setUnread}
              onLogout={() => void resetToLogin()}
              showLogout={showLogout}
              onOpenAgent={(workflowId, runId) => void openAgentRun(workflowId, runId)}
            />
          </div>
          {toast && <div className="wp-toast">{toast}</div>}
          <RunBannerCarousel entries={bannerEntries} />
          {renderContent()}
        </div>
      </main>
      <ChatDock onOpenThread={openChat} onOpenSupport={openSupport} />
    </div>
  )
}
