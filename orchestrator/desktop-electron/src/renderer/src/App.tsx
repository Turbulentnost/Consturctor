import { useEffect, useRef, useState, type ReactNode } from 'react'
import { APP_TITLE, PAGE_LABELS, Sidebar, type PageKey, type SidebarNavItem } from './components/Sidebar'
import { UserMenu } from './components/UserMenu'
import { LoginPage } from './pages/LoginPage'
import { MessengerPage } from './pages/MessengerPage'
import { api } from './api/client'
import { agentClient } from './api/agent'
import { clearAvatarCache, loadUserAvatar } from './api/avatars'
import { ApiError, type ChatThread, type LoginResult, type UserProfile } from './api/types'
import {
  clearComCredentials,
  comCredentials,
  clearSession,
  hasComPassword,
  loadSession,
  rememberPreference,
  restoreComCredentials,
  saveSession,
  setComCredentials,
  setDevGatewayCredentials,
  syncComProfileFromUser,
  getComCredentialsRevision
} from './store/session'
import { formatGatewayToolError, shouldForceReLogin } from './workplace/onecSessionHints'
import { fetchMyErpTasksOData } from './workplace/fetchMyErpTasksOData'
import { erpActorFio } from './workplace/userContext'
import { AgentRunPage } from './pages/AgentRunPage'
import { AgentHistoryPage } from './pages/AgentHistoryPage'
import { AgentSchedulePage } from './pages/AgentSchedulePage'
import { AgentPassportPage, type PassportTab } from './pages/AgentPassportPage'
import { FilesPage } from './pages/FilesPage'
import { OrchGridShell } from './layout/OrchGridShell'
import { PageSearchProvider } from './layout/pageSearchContext'
import { GlobalSearchProvider } from './layout/globalSearch'
import type { WorkplaceTabKey } from './layout/tabRegistry'
import { ProcessesGridTab } from './tabs/grid/ProcessesGridTab'
import { TasksGridTab } from './tabs/grid/TasksGridTab'
import { MailGridTab } from './tabs/grid/MailGridTab'
import { DocflowGridTab } from './tabs/grid/DocflowGridTab'
import { CreateOneCTaskPage } from './tabs/grid/CreateOneCTaskPage'
import { CreatePlatformTaskPage } from './tabs/grid/CreatePlatformTaskPage'
import { MeetingsGridTab } from './tabs/grid/MeetingsGridTab'
import { KnowledgeGridTab } from './tabs/grid/KnowledgeGridTab'
import { TodayGridTab } from './tabs/grid/TodayGridTab'
import { KpiGridTab } from './tabs/grid/KpiGridTab'
import { DecisionsGridTab } from './tabs/grid/DecisionsGridTab'
import { HistoryGridTab } from './tabs/grid/HistoryGridTab'
import { ExtensionsHubTab } from './tabs/grid/ExtensionsHubTab'
import { ExtensionsProvider, useExtensions } from './extensions/ExtensionsProvider'
import { EXTENSION_MODULES, extensionModuleForPage } from './extensions/extensionModules'
import { RunProvider, useRuns } from './store/runs'
import { isInFlightRunStatus, liveEntryMatchesRun } from './store/liveRun'
import { ChatDock } from './workplace/ChatDock'
import { isPersonalAgentWorkflowId, personalAgentWorkflowId } from './workplace/personalAgent'
import { DiagnosticsPage, SettingsTab, TicketsPage } from './workplace/WorkplaceTabs'
import { GridDataRefreshProvider } from './workplace/GridDataRefreshContext'
import { WorkplacePeriodProvider } from './workplace/workplacePeriod'
import { clearGridCacheForUser } from './workplace/gridDataCache'
import { ORCH_OPEN_TAB, type WorkplaceTabIntent } from './workplace/workplaceNav'
import { SpecV04SourcesProvider } from './workplace/SpecV04SourcesProvider'
import {
  ComCredentialsRevisionProvider,
  useBumpComCredentialsRevision,
  useComCredentialsRevision
} from './workplace/ComCredentialsRevisionContext'
import { OverviewPage } from './admin/pages/OverviewPage'
import { HistoryPage } from './admin/pages/HistoryPage'
import { LaunchCalendarPage } from './admin/pages/LaunchCalendarPage'
import { KpiAdminPage } from './admin/pages/KpiAdminPage'
import { UsersPage } from './admin/pages/UsersPage'
import { AiAgentsPage } from './admin/pages/AiAgentsPage'
import { KnowledgeBasePage } from './admin/pages/KnowledgeBasePage'
import { SettingsPage } from './admin/pages/SettingsPage'
import { FinanceEmployeesPage } from './admin/pages/FinanceEmployeesPage'
import { FinanceUploadPage } from './admin/pages/FinanceUploadPage'
import { FinanceImportHistoryPage } from './admin/pages/FinanceImportHistoryPage'
import { FinanceSalarySourceSwitch } from './admin/components/FinanceSalarySourceSwitch'
import { resolveAdminPanel } from './admin/adminPanels'

const ADMIN_TAB_KEYS: PageKey[] = [
  'overview',
  'history',
  'launch_calendar',
  'kpi',
  'users',
  'ai_agents',
  'knowledge_base',
  'finance_employees',
  'finance_upload',
  'finance_import_history',
  'settings'
]

const WORKPLACE_TAB_KEYS: WorkplaceTabKey[] = [
  'today',
  'processes',
  'tasks',
  'mail',
  'docflow',
  'meetings',
  'decisions',
  'kpi',
  'history',
  'knowledge',
  'extensions',
  'task_create',
  'platform_task_create',
  ...EXTENSION_MODULES.map((item) => item.pageKey as WorkplaceTabKey)
]

type View =
  | { kind: 'tab'; key: PageKey }
  | { kind: 'chat'; thread: ChatThread }
  | { kind: 'tickets' }
  | { kind: 'diagnostics' }
  | { kind: 'files'; workflowId?: string; title?: string }
  | { kind: 'passport'; workflowId: string; title: string; tab?: PassportTab }
  | { kind: 'agentrun'; workflowId: string; title: string; autoStart?: boolean; initialMessage?: string; appContext?: string }
  | { kind: 'history'; workflowId: string; title: string; runId?: string }
  | { kind: 'schedule'; workflowId: string; title: string; published?: boolean }

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

const RESTORE_DEADLINE_MS = 60_000
const RESTORE_RETRY_MS = 2_000

/** Only an explicit auth rejection ends the saved session; an unreachable backend is retried. */
async function restoreProfile(cancelled: () => boolean): Promise<UserProfile | null> {
  const deadline = Date.now() + RESTORE_DEADLINE_MS
  while (!cancelled()) {
    try {
      return await api.me(8_000)
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        clearSession(true)
        return null
      }
      if (Date.now() >= deadline) return null
      await new Promise((resolve) => window.setTimeout(resolve, RESTORE_RETRY_MS))
    }
  }
  return null
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

function isAdminTabKey(key: PageKey): boolean {
  return ADMIN_TAB_KEYS.includes(key)
}

function isWorkplaceTabKey(key: PageKey): key is WorkplaceTabKey {
  return (WORKPLACE_TAB_KEYS as PageKey[]).includes(key)
}

function windowTitle(view: View, signedIn: boolean): string {
  if (!signedIn) return APP_TITLE
  if (view.kind === 'tab') return `${PAGE_LABELS[view.key]} — ${APP_TITLE}`
  if (view.kind === 'chat') return `${view.thread.title || 'Чат'} — ${APP_TITLE}`
  if (view.kind === 'tickets') return `Заявки — ${APP_TITLE}`
  if (view.kind === 'diagnostics') return `Диагностика — ${APP_TITLE}`
  if (view.kind === 'files') return `${view.title ? `${view.title}: файлы` : 'Файлы'} — ${APP_TITLE}`
  if (view.kind === 'passport') return `Паспорт: ${view.title || 'агент'} — ${APP_TITLE}`
  if (view.kind === 'agentrun') return `${view.title || 'Запуск'} — ${APP_TITLE}`
  if (view.kind === 'history') return `История: ${view.title || 'агент'} — ${APP_TITLE}`
  if (view.kind === 'schedule') return `Расписание: ${view.title || 'агент'} — ${APP_TITLE}`
  return APP_TITLE
}

function DebugSourcesLifetime(): null {
  useEffect(() => {
    // #region agent log
    fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H2',location:'App.tsx:DebugSourcesLifetime',message:'sources provider mount',data:{},timestamp:Date.now()})}).catch(()=>{})
    // #endregion
    return () => {
      // #region agent log
      fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H2',location:'App.tsx:DebugSourcesLifetime',message:'sources provider unmount',data:{},timestamp:Date.now()})}).catch(()=>{})
      // #endregion
    }
  }, [])
  return null
}

export function App(): React.JSX.Element {
  return (
    <RunProvider>
      <ComCredentialsRevisionProvider>
        <AppShell />
      </ComCredentialsRevisionProvider>
    </RunProvider>
  )
}

function WithExtensionNav({
  children
}: {
  children: (pinnedExtensionNav: SidebarNavItem[]) => ReactNode
}): React.JSX.Element {
  const { pinnedNav } = useExtensions()
  return <>{children(pinnedNav)}</>
}

function AppShell(): React.JSX.Element {
  const [booting, setBooting] = useState(true)
  const [user, setUser] = useState<UserProfile | null>(null)
  const [showLogout, setShowLogout] = useState(true)
  const [view, setView] = useState<View>({ kind: 'tab', key: 'overview' })
  const [lastTab, setLastTab] = useState<PageKey>('overview')
  const [adminViewMode, setAdminViewMode] = useState<'admin' | 'user'>('user')
  const [unread, setUnread] = useState(0)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [toast, setToast] = useState('')
  /** JWT restored from localStorage but 1C password is only in memory after login form. */
  const [requireComLogin, setRequireComLogin] = useState(false)
  const kickedRef = useRef(false)
  const comCredsRevision = useComCredentialsRevision()
  const bumpComCredentialsRevision = useBumpComCredentialsRevision()
  const [chatRefreshAt, setChatRefreshAt] = useState(0)
  const [windowFocused, setWindowFocused] = useState(() => document.hasFocus())
  const seenHitlRef = useRef<Set<string>>(new Set())
  const seenRunNotifyRef = useRef<Map<string, 'started' | 'finished'>>(new Map())
  const [tabIntent, setTabIntent] = useState<WorkplaceTabIntent | null>(null)
  const runs = useRuns()
  useEffect(() => {
    document.title = booting ? APP_TITLE : windowTitle(view, Boolean(user))
  }, [booting, user, view])

  useEffect(() => {
    let done = false
    let disposed = false
    const finish = (): void => {
      if (done) return
      done = true
      setBooting(false)
    }
    const watchdog = window.setTimeout(finish, 4_000)
    ;(async () => {
      try {
        const config = await window.api.getConfig()
        setShowLogout(!config.testUser)
        const dev = config.devGatewaySecrets
        if (dev) {
          setDevGatewayCredentials({
            fio: dev.fio,
            nameMail: dev.nameMail,
            password: dev.password
          })
          bumpComCredentialsRevision()
        }
        const secret = await window.api.getComSecret?.().catch(() => null)
        if (secret?.password) {
          restoreComCredentials(secret, { persist: rememberPreference() })
          bumpComCredentialsRevision()
        }
        const stored = loadSession()
        if (stored?.accessToken) {
          if (!isOrchestratorToken(stored.accessToken)) {
            clearSession(true)
          } else {
            // The local backend may still be starting: keep the splash instead of the login form.
            window.clearTimeout(watchdog)
            api.setToken(stored.accessToken)
            const profile = await restoreProfile(() => disposed)
            if (disposed) return
            if (profile) {
              setUser(profile)
              // Password comes from login (safeStorage / sidecar), not from JWT.
              setModeForUser(profile)
            } else {
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
      disposed = true
    }
  }, [])

  useEffect(() => {
    if (!user || hasComPassword()) return
    let alive = true
    void window.api
      .getComSecret?.()
      .then((secret) => {
        if (!alive || !secret?.password) return
        if (restoreComCredentials(secret, { persist: rememberPreference() })) {
          bumpComCredentialsRevision()
        }
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [user?.id, comCredsRevision, bumpComCredentialsRevision])

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
      window.alert((payload.message || '').trim() || 'Выполнен вход на другом устройстве. Этот сеанс завершён.')
      void resetToLogin()
    })
  }, [])

  useEffect(() => {
    api.setUnauthorizedHandler((message, status) => {
      if (!shouldForceReLogin(message, status)) return
      if (kickedRef.current) return
      kickedRef.current = true
      const hint = formatGatewayToolError(message, status)
      void resetToLogin().then(() => {
        setRequireComLogin(true)
        if (hint) flash(hint)
      })
    })
    return () => api.setUnauthorizedHandler(null)
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
    const beforeRevision = getComCredentialsRevision()
    syncComProfileFromUser(user)
    if (getComCredentialsRevision() !== beforeRevision) {
      bumpComCredentialsRevision()
    }
    const creds = comCredentials()
    void agentClient
      .ready(token, {
        login: creds.login || user.fio,
        password: creds.password || ''
      })
      .catch(() => undefined)
  }, [user?.id ?? '', user?.nameMail ?? '', user?.fio ?? '', comCredsRevision, bumpComCredentialsRevision])

  useEffect(() => {
    if (!import.meta.env.DEV || !user) {
      delete window.__ORCH_DEV__
      return
    }
    window.__ORCH_DEV__ = {
      fetchMyErpTasksOData: (limit?: number) =>
        fetchMyErpTasksOData(user, erpActorFio(user), { limit })
    }
    return () => {
      delete window.__ORCH_DEV__
    }
  }, [user])

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
    const unsub = window.api.onInboxChanged?.(() => {
      void refresh()
      void runs.hydrateLive()
    })
    return () => {
      alive = false
      clearInterval(timer)
      unsub?.()
    }
  }, [user, runs.hydrateLive])

  useEffect(() => {
    const unsubscribe = window.api.onChatEvent?.(() => setChatRefreshAt(Date.now()))
    return () => unsubscribe?.()
  }, [])

  useEffect(() => {
    const onFocus = (): void => setWindowFocused(true)
    const onBlur = (): void => setWindowFocused(false)
    window.addEventListener('focus', onFocus)
    window.addEventListener('blur', onBlur)
    return () => {
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('blur', onBlur)
    }
  }, [])

  useEffect(() => {
    const onOpenTab = (event: Event): void => {
      const detail = (event as CustomEvent<{ key?: string; intent?: WorkplaceTabIntent }>).detail || {}
      const key = String(detail.key || '')
      if (!key) return
      const panel = resolveAdminPanel(user)
      const isAllowedAdminPage = panel?.pages.includes(key as PageKey) ?? false
      if ((WORKPLACE_TAB_KEYS as string[]).includes(key) || isAllowedAdminPage) {
        setTabIntent(detail.intent ?? null)
        setLastTab(key as PageKey)
        setView({ kind: 'tab', key: key as PageKey })
      }
    }
    window.addEventListener(ORCH_OPEN_TAB, onOpenTab)
    return () => window.removeEventListener(ORCH_OPEN_TAB, onOpenTab)
  }, [user])

  useEffect(() => {
    const stopUnsub = window.api.onNotificationStop?.((payload) => {
      const workflowId = payload?.workflowId || ''
      if (workflowId) runs.cancel(workflowId)
    })
    const unsubscribe = window.api.onNotificationOpen?.((payload) => {
      if (payload?.openDecisions || payload?.requestId) {
        setLastTab('decisions')
        setView({ kind: 'tab', key: 'decisions' })
        return
      }
      const workflowId = payload?.workflowId || ''
      if (workflowId) void openAgentRun(workflowId, payload?.runId || '', false)
    })
    return () => {
      stopUnsub?.()
      unsubscribe?.()
    }
  }, [runs])

  useEffect(() => {
    const watchingDecisions = view.kind === 'tab' && view.key === 'decisions'
    for (const entry of Object.values(runs.entries)) {
      const hitl = entry.state.pendingHitl
      const question = entry.state.pendingQuestion
      const requestId = hitl?.requestId || question?.requestId || ''
      if (!requestId || seenHitlRef.current.has(requestId)) continue
      const watchingThisAgent =
        (view.kind === 'agentrun' || view.kind === 'history' || view.kind === 'passport') &&
        view.workflowId === entry.workflowId
      if (windowFocused && (watchingDecisions || watchingThisAgent)) continue
      seenHitlRef.current.add(requestId)
      void window.api.showNotification?.({
        title: 'Агент ожидает подтверждения',
        body: `${entry.title || 'ИИ-агент'}: ${hitl?.title || question?.question || 'нужно подтверждение'}`,
        workflowId: entry.workflowId,
        runId: entry.state.activeRunId || entry.backendRunId || '',
        requestId,
        openDecisions: true
      })
    }
  }, [runs.entries, view, windowFocused])

  useEffect(() => {
    for (const entry of Object.values(runs.entries)) {
      const runId = entry.backendRunId || entry.state.activeRunId || entry.workflowId
      if (!runId) continue
      const live = Boolean(entry.state.running || entry.state.pendingHitl || entry.state.pendingQuestion)
      const prev = seenRunNotifyRef.current.get(runId)
      if (live && prev !== 'started' && prev !== 'finished') {
        seenRunNotifyRef.current.set(runId, 'started')
        void window.api.showNotification?.({
          title: 'Запуск начался',
          body: `Агент «${entry.title || 'агент'}»: запуск начался.`,
          workflowId: entry.workflowId,
          runId: entry.backendRunId || ''
        })
      }
      if (!live && prev === 'started') {
        seenRunNotifyRef.current.set(runId, 'finished')
        void window.api.showNotification?.({
          title: 'Запуск закончен',
          body: `Агент «${entry.title || 'агент'}» завершил запуск.`,
          workflowId: entry.workflowId,
          runId: entry.backendRunId || '',
        })
      }
    }
  }, [runs.entries])
  function setModeForUser(profile: UserProfile): void {
    const panel = resolveAdminPanel(profile)
    const mode = panel ? 'admin' : 'user'
    const key: PageKey = panel?.defaultTab ?? 'today'
    setAdminViewMode(mode)
    setLastTab(key)
    setView({ kind: 'tab', key })
  }

  function onLoggedIn(result: LoginResult, remember: boolean, password = '', typedLogin = ''): void {
    api.setToken(result.accessToken || null)
    setComCredentials(typedLogin || result.user.fio, password, result.user.nameMail, {
      persist: remember
    })
    bumpComCredentialsRevision()
    setRequireComLogin(false)
    void agentClient
      .ready(result.accessToken || null, {
        login: typedLogin || result.user.fio,
        password
      })
      .catch(() => undefined)
    if (remember && result.accessToken) {
      saveSession({ accessToken: result.accessToken, fio: result.user.fio })
    } else {
      clearSession(true)
    }
    setUser(result.user)
    setModeForUser(result.user)
    if (result.accessToken) {
      void api
        .me()
        .then((profile) => {
          setUser(profile)
          setModeForUser(profile)
        })
        .catch(() => undefined)
    }
  }

  async function resetToLogin(): Promise<void> {
    const uid = (user?.id || '').trim()
    if (uid) clearGridCacheForUser(uid)
    void window.api.stopNotifications?.()
    runs.clearAll()
    clearSession(true)
    clearComCredentials()
    api.setToken(null)
    clearAvatarCache()
    setAvatarUrl(null)
    setView({ kind: 'tab', key: 'overview' })
    setLastTab('overview')
    setAdminViewMode('user')
    setUser(null)
    setRequireComLogin(false)
  }

  function onLogout(): void {
    void resetToLogin()
  }

  function switchAdminView(mode: 'admin' | 'user'): void {
    const panel = resolveAdminPanel(user)
    const nextMode = mode === 'admin' && panel ? 'admin' : 'user'
    setAdminViewMode(nextMode)
    const key: PageKey = nextMode === 'admin' ? panel!.defaultTab : 'today'
    setLastTab(key)
    setView({ kind: 'tab', key })
  }

  function flash(text: string): void {
    setToast(text)
    window.setTimeout(() => setToast(''), 2400)
  }

  function openChat(thread: ChatThread): void {
    setView({ kind: 'chat', thread })
    setChatRefreshAt(Date.now())
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

  if (booting) {
    return (
      <div className="app-root boot-screen">
        <div className="spinner spinner-on-dark" />
        <div className="boot-label">Загрузка оркестратора...</div>
      </div>
    )
  }

  if (!user || requireComLogin) {
    return (
      <LoginPage
        onLoggedIn={onLoggedIn}
        banner={
          requireComLogin
            ? 'Сеанс восстановлен по токену. Введите пароль 1С — без него erp_pm и COM недоступны.'
            : undefined
        }
      />
    )
  }

  const activeUser = user
  const activeAdminPanel = resolveAdminPanel(activeUser)
  const isAdminMode = Boolean(activeAdminPanel && adminViewMode === 'admin')
  const activeKey: PageKey | null =
    view.kind === 'tab'
      ? view.key
      : view.kind === 'chat'
        ? null
        : isAdminMode && (view.kind === 'agentrun' || view.kind === 'history' || view.kind === 'schedule' || view.kind === 'passport')
          ? 'ai_agents'
          : lastTab

  async function openAgentRun(workflowId: string, runId = '', _autoStart = false, title = ''): Promise<void> {
    if (!workflowId) {
      flash('У карточки нет id агента на сервере')
      return
    }
    if (isPersonalAgentWorkflowId(workflowId)) {
      setView({ kind: 'agentrun', workflowId, title: title || 'Оркестратор', autoStart: false })
      return
    }
    const nextTitle = title || 'ИИ-агент'
    const live = runs.entries[workflowId]
    if (liveEntryMatchesRun(live, runId)) {
      setView({ kind: 'agentrun', workflowId, title: nextTitle || live.title, autoStart: false })
      return
    }
    if (runId) {
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
    setView({ kind: 'agentrun', workflowId, title: nextTitle || 'ИИ-агент', autoStart: false })
  }

  function openFromInbox(workflowId: string, runId = '', title = '', body = ''): void {
    if (/ожидает подтверждения/i.test(title)) {
      setLastTab('decisions')
      setView({ kind: 'tab', key: 'decisions' })
      return
    }
    const fromBody = /Агент «([^»]+)»/.exec(body || '')?.[1] || ''
    const agentTitle = fromBody || (/запуск/i.test(title) ? '' : title)
    const nextTitle = agentTitle || runs.entries[workflowId]?.title || 'ИИ-агент'
    if (/запуск начался|начат плановый запуск/i.test(title)) {
      setView({ kind: 'agentrun', workflowId, title: nextTitle, autoStart: false })
      if (runId) {
        runs.noteRunning(workflowId, nextTitle, runId)
        void runs.attachHistoryFeed(workflowId)
      }
      return
    }
    if (/запуск закончен/i.test(title) && runId) {
      if (liveEntryMatchesRun(runs.entries[workflowId], runId)) {
        setView({ kind: 'agentrun', workflowId, title: nextTitle, autoStart: false })
        return
      }
      setLastTab('history')
      setView({ kind: 'history', workflowId, title: nextTitle, runId })
      void api
        .getWorkflow(workflowId)
        .then((record) => {
          if (record?.title) {
            setView({ kind: 'history', workflowId, title: record.title, runId })
          }
        })
        .catch(() => undefined)
      return
    }
    void openAgentRun(workflowId, runId, false, agentTitle)
  }

  function askOrchestratorFromTab(message: string, appContext: string): void {
    const workflowId = personalAgentWorkflowId(activeUser.id || '')
    setView({
      kind: 'agentrun',
      workflowId,
      title: 'Оркестратор',
      autoStart: false,
      initialMessage: message,
      appContext
    })
  }

  function askOrchestratorFromDock(message: string): void {
    const tabKey = view.kind === 'tab' ? view.key : lastTab
    const label = tabKey ? PAGE_LABELS[tabKey] || tabKey : ''
    askOrchestratorFromTab(message, label ? `Вкладка «${label}»` : 'Рабочее место')
  }

  function renderAdminContent(): React.JSX.Element {
    if (view.kind === 'chat') {
      return (
        <MessengerPage
          thread={view.thread}
          me={activeUser}
          onThreadChange={(thread) => setView({ kind: 'chat', thread })}
          onOpenAgent={() => setView({ kind: 'tab', key: 'ai_agents' })}
        />
      )
    }
    if (view.kind === 'tickets') {
      return <TicketsPage user={activeUser} onBack={() => setView({ kind: 'tab', key: 'settings' })} onOpenThread={openChat} />
    }
    if (view.kind === 'diagnostics') {
      return <DiagnosticsPage onBack={() => setView({ kind: 'tab', key: 'settings' })} onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)} />
    }
    if (view.kind === 'files') {
      return <FilesPage ownerName={activeUser.fio || ''} initialWorkflowId={view.workflowId || ''} initialAgentTitle={view.title || ''} onOpenRun={(workflowId, runId) => void openAgentRun(workflowId, runId)} />
    }
    if (view.kind === 'agentrun') {
      return <AgentRunPage workflowId={view.workflowId} title={view.title} autoStart={view.autoStart} initialMessage={view.initialMessage} appContext={view.appContext} onBack={() => setView({ kind: 'tab', key: lastTab })} onOpenHistory={(workflowId, title) => setView({ kind: 'history', workflowId, title })} />
    }
    if (view.kind === 'passport') {
      return <AgentPassportPage workflowId={view.workflowId} title={view.title} initialTab={view.tab || 'info'} onBack={() => setView({ kind: 'tab', key: 'overview' })} onRun={(workflowId, title) => void openAgentRun(workflowId, '', true, title)} onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)} />
    }
    if (view.kind === 'history') {
      return (
        <AgentHistoryPage
          key={`${view.workflowId}:${view.runId || ''}`}
          workflowId={view.workflowId}
          title={view.title}
          initialRunId={view.runId}
          onBack={() => setView({ kind: 'tab', key: lastTab })}
          onOpenLive={() => setView({ kind: 'agentrun', workflowId: view.workflowId, title: view.title })}
        />
      )
    }
    if (view.kind === 'schedule') {
      return <AgentSchedulePage workflowId={view.workflowId} title={view.title} published={Boolean(view.published)} onBack={() => setView({ kind: 'tab', key: lastTab })} onNext={() => setView({ kind: 'tab', key: lastTab })} />
    }
    if (!isAdminTabKey(view.key) || !activeAdminPanel?.pages.includes(view.key)) {
      const fallback = activeAdminPanel?.defaultTab ?? 'today'
      if (fallback === 'today') return renderUserContent()
      if (fallback === 'finance_employees') return <FinanceEmployeesPage />
      return <OverviewPage />
    }
    switch (view.key) {
      case 'overview':
        return <OverviewPage />
      case 'history':
        return <HistoryPage />
      case 'launch_calendar':
        return <LaunchCalendarPage />
      case 'kpi':
        return <KpiAdminPage />
      case 'users':
        return <UsersPage />
      case 'ai_agents':
        return <AiAgentsPage />
      case 'knowledge_base':
        return <KnowledgeBasePage />
      case 'settings':
        return <SettingsPage />
      case 'finance_employees':
        return <FinanceEmployeesPage />
      case 'finance_upload':
        return <FinanceUploadPage />
      case 'finance_import_history':
        return <FinanceImportHistoryPage />
      default:
        return activeAdminPanel?.defaultTab === 'finance_employees' ? <FinanceEmployeesPage /> : <OverviewPage />
    }
  }

  function renderWorkplaceGridTab(key: WorkplaceTabKey): React.JSX.Element {
    switch (key) {
      case 'processes':
        return <ProcessesGridTab user={activeUser} navProcessTab={tabIntent?.processTab} onOpen={(workflowId, title) => setView({ kind: 'passport', workflowId, title, tab: 'info' })} onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)} />
      case 'tasks':
        return <TasksGridTab user={activeUser} navTaskFilter={tabIntent?.taskFilter} />
      case 'mail':
        return <MailGridTab user={activeUser} onAskOrchestrator={askOrchestratorFromTab} />
      case 'docflow':
        return <DocflowGridTab user={activeUser} />
      case 'task_create':
        return <CreateOneCTaskPage user={activeUser} />
      case 'platform_task_create':
        return <CreatePlatformTaskPage user={activeUser} />
      case 'meetings':
        return <MeetingsGridTab user={activeUser} />
      case 'decisions':
        return <DecisionsGridTab user={activeUser} onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', Boolean(!runId), title)} />
      case 'kpi':
        return <KpiGridTab user={activeUser} onOpenProcesses={() => setView({ kind: 'tab', key: 'processes' })} onOpenDecisions={() => setView({ kind: 'tab', key: 'decisions' })} />
      case 'knowledge':
        return <KnowledgeGridTab user={activeUser} />
      case 'history':
        return <HistoryGridTab onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)} />
      case 'extensions':
        return (
          <ExtensionsHubTab
            user={activeUser}
            onNotify={flash}
            onOpenExtension={(pageKey) => {
              setLastTab(pageKey)
              setView({ kind: 'tab', key: pageKey })
            }}
          />
        )
      case 'today':
      default: {
        const extensionTab = extensionModuleForPage(key)
        if (extensionTab) {
          return (
            <>
              {extensionTab.renderTab({
                user: activeUser,
                onAskOrchestrator: askOrchestratorFromTab,
                onRunAgent: (workflowId, title, message) =>
                  setView({ kind: 'agentrun', workflowId, title, autoStart: false, initialMessage: message }),
                onNavigate: (pageKey) => {
                  setLastTab(pageKey)
                  setView({ kind: 'tab', key: pageKey })
                },
                onOpenPassport: (workflowId, title, tab) =>
                  setView({ kind: 'passport', workflowId, title, tab })
              })}
            </>
          )
        }
        return (
          <TodayGridTab
            user={activeUser}
            onAskOrchestrator={askOrchestratorFromTab}
            onOpenDecisions={() => setView({ kind: 'tab', key: 'decisions' })}
            onOpenMetrics={() => setView({ kind: 'tab', key: 'kpi' })}
            onOpenPassport={(workflowId, title, tab) => setView({ kind: 'passport', workflowId, title, tab })}
            onRun={(workflowId, title) => void openAgentRun(workflowId, '', true, title)}
            onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)}
          />
        )
      }
    }
  }

  function renderUserFullscreen(): React.JSX.Element {
    if (view.kind === 'chat') {
      return <MessengerPage thread={view.thread} me={activeUser} onThreadChange={(thread) => setView({ kind: 'chat', thread })} onOpenAgent={() => setView({ kind: 'tab', key: 'processes' })} />
    }
    if (view.kind === 'tickets') {
      return <TicketsPage user={activeUser} onBack={() => setView({ kind: 'tab', key: 'settings' })} onOpenThread={openChat} />
    }
    if (view.kind === 'diagnostics') {
      return <DiagnosticsPage onBack={() => setView({ kind: 'tab', key: 'settings' })} onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)} />
    }
    if (view.kind === 'files') {
      return <FilesPage ownerName={activeUser.fio || ''} initialWorkflowId={view.workflowId || ''} initialAgentTitle={view.title || ''} onOpenRun={(workflowId, runId) => void openAgentRun(workflowId, runId)} />
    }
    if (view.kind === 'agentrun') {
      return <AgentRunPage workflowId={view.workflowId} title={view.title} autoStart={view.autoStart} initialMessage={view.initialMessage} appContext={view.appContext} onBack={() => setView({ kind: 'tab', key: lastTab })} onOpenHistory={(workflowId, title) => setView({ kind: 'history', workflowId, title })} />
    }
    if (view.kind === 'passport') {
      return <AgentPassportPage workflowId={view.workflowId} title={view.title} initialTab={view.tab || 'info'} onBack={() => setView({ kind: 'tab', key: 'today' })} onRun={(workflowId, title) => void openAgentRun(workflowId, '', true, title)} onOpenRun={(workflowId, title, runId) => void openAgentRun(workflowId, runId || '', false, title)} />
    }
    if (view.kind === 'history') {
      return (
        <AgentHistoryPage
          key={`${view.workflowId}:${view.runId || ''}`}
          workflowId={view.workflowId}
          title={view.title}
          initialRunId={view.runId}
          onBack={() => setView({ kind: 'tab', key: lastTab })}
          onOpenLive={() => setView({ kind: 'agentrun', workflowId: view.workflowId, title: view.title })}
        />
      )
    }
    if (view.kind === 'schedule') {
      return <AgentSchedulePage workflowId={view.workflowId} title={view.title} published={Boolean(view.published)} onBack={() => setView({ kind: 'tab', key: lastTab })} onNext={() => setView({ kind: 'tab', key: lastTab })} />
    }
    return (
      <SettingsTab
        user={activeUser}
        onDiagnostics={() => setView({ kind: 'diagnostics' })}
        onTickets={() => setView({ kind: 'tickets' })}
        onFiles={() => setView({ kind: 'files' })}
        onSupport={openSupport}
      />
    )
  }

  function renderUserContent(): React.JSX.Element {
    if (view.kind === 'tab' && isWorkplaceTabKey(view.key)) {
      return renderWorkplaceGridTab(view.key)
    }
    return renderUserFullscreen()
  }

  const workplaceGrid = !isAdminMode && view.kind === 'tab' && isWorkplaceTabKey(view.key)
  const workplaceShellKey: WorkplaceTabKey | null =
    workplaceGrid && view.kind === 'tab' && isWorkplaceTabKey(view.key) ? view.key : null
  const content = isAdminMode ? renderAdminContent() : renderUserContent()

  return (
    <ExtensionsProvider user={activeUser}>
      <GridDataRefreshProvider userId={activeUser.id}>
        <WorkplacePeriodProvider>
        <SpecV04SourcesProvider user={activeUser} comCredsRevision={comCredsRevision}>
          <DebugSourcesLifetime />
          <GlobalSearchProvider
            onChoose={(target) => {
              setAdminViewMode('user')
              setTabIntent({ searchTarget: target })
              setLastTab(target.pageKey)
              setView({ kind: 'tab', key: target.pageKey })
            }}
          >
          <WithExtensionNav>
            {(pinnedExtensionNav) =>
              workplaceShellKey ? (
          <div className="app-root orch-app-root">
            <PageSearchProvider tabKey={workplaceShellKey}>
            <OrchGridShell
              activeKey={workplaceShellKey}
              pinnedExtensionNav={pinnedExtensionNav}
              gridClassName={
                workplaceShellKey === 'today'
                  ? 'orch-grid-today'
                  : workplaceShellKey === 'kpi'
                    ? 'orch-grid-kpi'
                    : workplaceShellKey === 'assignments_registry'
                      ? 'orch-grid-registry'
                      : workplaceShellKey === 'history'
                        ? 'orch-grid-history'
                        : workplaceShellKey === 'extensions'
                          ? 'orch-grid-extensions'
                          : workplaceShellKey === 'agent_library'
                            ? 'orch-grid-agent-library'
                            : workplaceShellKey === 'processes'
                              ? 'orch-grid-processes'
                              : workplaceShellKey === 'docflow' ||
                                  workplaceShellKey === 'task_create' ||
                                  workplaceShellKey === 'platform_task_create'
                                ? 'orch-grid-docflow'
                                : ''
              }
              user={activeUser}
              avatarUrl={avatarUrl}
              unread={unread}
              onUnreadChange={setUnread}
              onLogout={onLogout}
              showLogout={showLogout}
              lightSidebar={workplaceShellKey === 'today'}
              activeThreadId=""
              chatRefreshAt={chatRefreshAt}
              onNavigate={(key) => {
                setTabIntent(null)
                setLastTab(key)
                setView({ kind: 'tab', key })
              }}
              onOpenThread={openChat}
              searchTarget={tabIntent?.searchTarget}
              onOpenSettings={() => setView({ kind: 'tab', key: 'settings' })}
              onOpenAgent={openFromInbox}
              onStopRun={(workflowId, runId) => runs.cancel(workflowId, runId)}
              isRunLive={() => true}
              canSwitchAdminView={Boolean(activeAdminPanel)}
              onSwitchAdminView={switchAdminView}
              toast={toast ? <div className="wp-toast">{toast}</div> : null}
            >
              {renderWorkplaceGridTab(workplaceShellKey)}
            </OrchGridShell>
            </PageSearchProvider>
            <ChatDock onAskOrchestrator={askOrchestratorFromDock} onOpenSupport={openSupport} />
          </div>
              ) : (
          <div className="app-root">
            <Sidebar
              active={activeKey}
              light={false}
              showAdminNav={isAdminMode}
              adminPageKeys={activeAdminPanel?.pages}
              adminTitle={activeAdminPanel?.title}
              navScope={activeAdminPanel ? `admin:${activeAdminPanel.key}` : 'user'}
              pinnedExtensionNav={pinnedExtensionNav}
              activeThreadId={view.kind === 'chat' ? view.thread.id : ''}
              currentUserId={activeUser.id || ''}
              onNavigate={(key) => {
                if (isAdminMode && !activeAdminPanel?.pages.includes(key)) return
                if (!isAdminMode && !isWorkplaceTabKey(key) && key !== 'settings') return
                setTabIntent(null)
                setLastTab(key)
                setView({ kind: 'tab', key })
              }}
              onOpenThread={openChat}
              refreshAt={chatRefreshAt}
            />
            <main className={isAdminMode ? 'content' : 'content orch-legacy-fullpage'}>
              <div className={view.kind === 'chat' ? 'content-inner messenger-mode' : 'content-inner'}>
                <div className="app-page-header">
                  {isAdminMode && activeAdminPanel?.key === 'finance' ? <FinanceSalarySourceSwitch /> : null}
                  <UserMenu
                    user={activeUser}
                    avatarUrl={avatarUrl}
                    unread={unread}
                    onUnreadChange={setUnread}
                    onLogout={onLogout}
                    showLogout={showLogout}
                    onOpenAgent={openFromInbox}
                    onStopRun={(workflowId, runId) => runs.cancel(workflowId, runId)}
                    isRunLive={() => true}
                    onOpenSettings={() => setView({ kind: 'tab', key: 'settings' })}
                    canSwitchAdminView={Boolean(activeAdminPanel)}
                    onSwitchAdminView={switchAdminView}
                    variant={isAdminMode ? 'admin' : 'default'}
                  />
                </div>
                {toast && <div className="wp-toast">{toast}</div>}
                {content}
              </div>
            </main>
            <ChatDock onAskOrchestrator={askOrchestratorFromDock} onOpenSupport={openSupport} />
          </div>
              )
            }
          </WithExtensionNav>
          </GlobalSearchProvider>
        </SpecV04SourcesProvider>
        </WorkplacePeriodProvider>
      </GridDataRefreshProvider>
    </ExtensionsProvider>
  )
}
