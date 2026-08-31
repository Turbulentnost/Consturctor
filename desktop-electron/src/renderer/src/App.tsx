import { useEffect, useRef, useState } from 'react'
import { Sidebar, type PageKey } from './components/Sidebar'
import { UserMenu } from './components/UserMenu'
import { LoginPage } from './pages/LoginPage'
import { CreatePage } from './pages/CreatePage'
import { AgentsPage } from './pages/AgentsPage'
import { FilesPage } from './pages/FilesPage'
import { KpiPage } from './pages/SimplePages'
import { OrchestratorPage } from './pages/OrchestratorPage'
import { ReviewPage } from './pages/ReviewPage'
import { RegulationChatPage } from './pages/RegulationChatPage'
import { visibleAssistantText } from './utils/regulationChat'
import { RoleMatchPage } from './pages/RoleMatchPage'
import { ReadinessPage } from './pages/ReadinessPage'
import { SuggestionsPage } from './pages/SuggestionsPage'
import { PassportPage } from './pages/PassportPage'
import { AgentStudioPage } from './pages/AgentStudioPage'
import { RunBannerCarousel, type BannerEntry } from './components/RunBannerCarousel'
import { useFormation } from './components/agentfeed'
import { useRuns, deriveLatestOutput } from './store/runs'
import { isInFlightRunStatus, isLiveRunState } from './store/liveRun'
import { AgentRunPage } from './pages/AgentRunPage'
import { AgentSchedulePage } from './pages/AgentSchedulePage'
import { AgentKpiPreviewPage } from './pages/AgentKpiPreviewPage'
import { AgentHistoryPage } from './pages/AgentHistoryPage'
import { MessengerPage } from './pages/MessengerPage'
import { agentClient } from './api/agent'
import { api, notesFromPassport, suggestionsFromRoleMatch } from './api/client'
import { clearAvatarCache, loadUserAvatar } from './api/avatars'
import type {
  AgentDraft,
  AgentSuggestion,
  LoginResult,
  PassportSession,
  RegulationCreationSession,
  RegulationParseResult,
  RoleMatchResult,
  ScheduleDraft,
  UserProfile,
  ChatThread,
  DirectoryUser
} from './api/types'
import {
  clearComCredentials,
  clearSession,
  comCredentials,
  loadSession,
  saveSession,
  setComCredentials
} from './store/session'

type View =
  | { kind: 'tab'; key: PageKey }
  | { kind: 'review'; result: RegulationParseResult }
  | { kind: 'regchat' }
  | { kind: 'rolematch' }
  | { kind: 'readiness' }
  | { kind: 'suggestions' }
  | { kind: 'passport' }
  | { kind: 'studio'; workflowId: string; title: string }
  | { kind: 'agentrun'; workflowId: string; title: string; autoStart?: boolean }
  | { kind: 'schedule'; workflowId: string; title: string }
  | { kind: 'kpi'; workflowId: string; title: string; draft: ScheduleDraft }
  | { kind: 'history'; workflowId: string; title: string; runId?: string }
  | { kind: 'chat'; thread: ChatThread }
  | { kind: 'loading'; title: string; subtitle: string }
  | { kind: 'soon'; title: string; note: string }

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

function isOpenRegulationDraft(session: RegulationCreationSession | null): boolean {
  if (!session?.draftId) return false
  if (session.resultRegulation || session.resultDocumentPath) return false
  return session.status !== 'finalized' && session.status !== 'closed'
}

function regulationDraftPreview(session: RegulationCreationSession | null): string {
  if (!session) return ''
  for (let i = session.messages.length - 1; i >= 0; i -= 1) {
    const item = session.messages[i]
    if (item.role !== 'assistant') continue
    const text = visibleAssistantText(item.content)
    if (text) return text
  }
  return ''
}

function lastRegulationQuestion(
  session: RegulationCreationSession | null
): { messageId: string; text: string } | null {
  if (!session || !isOpenRegulationDraft(session)) return null
  for (let i = session.messages.length - 1; i >= 0; i -= 1) {
    const item = session.messages[i]
    if (item.role !== 'assistant') continue
    const text = visibleAssistantText(item.content).replace(/\s+/g, ' ').trim()
    if (!text) return null
    return { messageId: item.messageId || `assistant-${i}`, text }
  }
  return null
}

function clipToastBody(text: string, max = 180): string {
  if (text.length <= max) return text
  return `${text.slice(0, max - 1).trim()}...`
}

export function App(): React.JSX.Element {
  const [booting, setBooting] = useState(true)
  const [user, setUser] = useState<UserProfile | null>(null)
  const [showLogout, setShowLogout] = useState(true)
  const [view, setView] = useState<View>({ kind: 'tab', key: 'create' })
  const [unread, setUnread] = useState(0)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [regulation, setRegulation] = useState<RegulationParseResult | null>(null)
  const [roleMatch, setRoleMatch] = useState<RoleMatchResult | null>(null)
  const [draft, setDraft] = useState<AgentDraft | null>(null)
  const [suggestions, setSuggestions] = useState<AgentSuggestion[]>([])
  const [suggestion, setSuggestion] = useState<AgentSuggestion | null>(null)
  const [passport, setPassport] = useState<PassportSession | null>(null)
  const [passportError, setPassportError] = useState('')
  const [busy, setBusy] = useState(false)
  const kickedRef = useRef(false)
  const seenHitlRef = useRef<Set<string>>(new Set())
  const seenRegQuestionRef = useRef<Set<string>>(new Set())
  const [windowFocused, setWindowFocused] = useState(() =>
    typeof document === 'undefined' ? true : document.hasFocus()
  )
  const [chatRefreshAt, setChatRefreshAt] = useState(0)
  const [regChat, setRegChat] = useState<RegulationCreationSession | null>(null)
  const [regChatBusy, setRegChatBusy] = useState(false)
  const formation = useFormation()
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
          api.setToken(stored.accessToken)
          try {
            const profile = await api.me(8_000)
            setUser(profile)
          } catch {
            clearSession(true)
            api.setToken(null)
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
    if (!user) return
    let alive = true
    void api
      .getActiveRegulationCreation()
      .then((session) => {
        if (!alive || !session) return
        setRegChat((prev) => prev ?? session)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [user])

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
      const text =
        (payload.message || '').trim() ||
        'Выполнен вход на другом устройстве. Этот сеанс завершён.'
      window.alert(text)
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
    if (token) {
      void window.api.startNotifications?.(token)
    }
    const creds = comCredentials()
    void agentClient
      .ready(token, { login: creds.login || user.fio, password: creds.password })
      .catch(() => undefined)
  }, [user?.id])

  useEffect(() => {
    if (!user) return
    let alive = true
    const refresh = async (): Promise<void> => {
      const count = await api.unreadNotificationCount()
      if (alive) setUnread(count)
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

  useEffect(() => {
    if (!user) return
    void runs.hydrateLive()
    const unsubscribe = window.api.onBoardUpdated?.(() => {
      void runs.hydrateLive()
    })
    const timer = window.setInterval(() => {
      void runs.hydrateLive()
    }, 15000)
    return () => {
      unsubscribe?.()
      window.clearInterval(timer)
    }
  }, [user?.id])

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

  // A clicked OS toast (incoming notification) opens the related agent
  // or the regulation-creation chat that asked the question.
  useEffect(() => {
    const unsubscribe = window.api.onNotificationOpen?.((payload) => {
      if (payload?.draftId) {
        setView({ kind: 'regchat' })
        return
      }
      const workflowId = payload?.workflowId || ''
      if (workflowId) void openAgentRun(workflowId, payload?.runId || '')
    })
    return () => unsubscribe?.()
  }, [])

  useEffect(() => {
    const unsubscribe = window.api.onNotificationHitl?.((payload) => {
      const workflowId = payload?.workflowId || ''
      const requestId = payload?.requestId || ''
      if (!workflowId || !requestId) return
      seenHitlRef.current.add(requestId)
      runs.acknowledgeHitl(workflowId, requestId, Boolean(payload.approved))
    })
    return () => unsubscribe?.()
  }, [runs])

  // The main process toasts incoming notifications; refresh the bell badge.
  useEffect(() => {
    if (!user) return
    const unsubscribe = window.api.onInboxChanged?.(() => {
      void api.unreadNotificationCount().then(setUnread).catch(() => undefined)
    })
    return () => unsubscribe?.()
  }, [user])

  // When a tool needs approval while you are not watching that agent, raise a
  // Windows toast with Accept / Reject. Do not mark the request as shown while
  // the user is still on the page, otherwise leaving the page silences it.
  useEffect(() => {
    const activeWorkflowId =
      view.kind === 'agentrun' || view.kind === 'history' || view.kind === 'studio'
        ? view.workflowId
        : ''
    for (const entry of Object.values(runs.entries)) {
      const hitl = entry.state.pendingHitl
      if (!hitl?.requestId) continue
      if (seenHitlRef.current.has(hitl.requestId)) continue
      const watchingThisAgent = windowFocused && activeWorkflowId === entry.workflowId
      if (watchingThisAgent) continue
      seenHitlRef.current.add(hitl.requestId)
      void window.api.showNotification?.({
        title: 'Агент ждёт подтверждения',
        body: `${entry.title || 'ИИ-агент'}: ${hitl.title || hitl.tool}`,
        workflowId: entry.workflowId,
        runId: entry.state.activeRunId || entry.backendRunId || '',
        requestId: hitl.requestId
      })
    }
  }, [runs.entries, view, windowFocused])

  // Each new interview question during regulation creation raises a Windows
  // toast so the user knows the chat is waiting for an answer.
  useEffect(() => {
    if (!regChat || regChatBusy) return
    const question = lastRegulationQuestion(regChat)
    if (!question) return
    const key = `${regChat.draftId}:${question.messageId}`
    if (seenRegQuestionRef.current.has(key)) return
    seenRegQuestionRef.current.add(key)
    void window.api.showNotification?.({
      title: 'Система ждёт вашего ответа на сообщение',
      body: clipToastBody(question.text),
      draftId: regChat.draftId
    })
  }, [regChat, regChatBusy])

  function onLoggedIn(result: LoginResult, remember: boolean, password = ''): void {
    if (user && user.id !== result.user.id) {
      formation.cancel()
      formation.clear()
      runs.clearAll()
      setRegChat(null)
      setRegChatBusy(false)
    }
    api.setToken(result.accessToken || null)
    setComCredentials(result.user.fio, password)
    if (remember && result.accessToken) {
      saveSession({ accessToken: result.accessToken, fio: result.user.fio })
    } else {
      clearSession(true)
    }
    setUser(result.user)
    setView({ kind: 'tab', key: 'create' })
    if (result.accessToken) {
      void api.me().then(setUser).catch(() => undefined)
    }
  }

  async function resetToLogin(): Promise<void> {
    void window.api.stopNotifications?.()
    formation.cancel()
    formation.clear()
    runs.clearAll()
    setRegChat(null)
    setRegChatBusy(false)
    clearSession(true)
    clearComCredentials()
    api.setToken(null)
    clearAvatarCache()
    setAvatarUrl(null)
    setRegulation(null)
    setRoleMatch(null)
    setDraft(null)
    setSuggestions([])
    setSuggestion(null)
    setPassport(null)
    setPassportError('')
    setView({ kind: 'tab', key: 'create' })
    setUser(null)
  }

  function onLogout(): void {
    void resetToLogin()
  }

  function fail(title: string, err: unknown): void {
    setBusy(false)
    setView({
      kind: 'soon',
      title,
      note: err instanceof Error ? err.message : String(err)
    })
  }

  function openChat(thread: ChatThread): void {
    setView({ kind: 'chat', thread })
    setChatRefreshAt(Date.now())
  }

  async function openChatByFio(fio: string, picked?: DirectoryUser): Promise<void> {
    const name = (picked?.fio || fio).trim()
    if (!name) return
    const me = user
    if (me && (picked?.id === me.id || name.toLowerCase() === me.fio.trim().toLowerCase())) {
      return
    }
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
        fail('Чат', new Error('Пользователь не найден'))
        return
      }
      const known = findExistingChat(threads, match.fio, match.id)
      if (known) {
        openChat(known)
        return
      }
      try {
        await api.openDirectChat(match.id)
      } catch {
        /* still open a local dialog */
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
    } catch (err) {
      fail('Чат', err)
    }
  }

  async function startRegulationChat(opts?: { fresh?: boolean }): Promise<void> {
    setView({
      kind: 'loading',
      title: opts?.fresh ? 'Создаём чат регламента' : 'Открываем черновик регламента',
      subtitle: opts?.fresh
        ? 'Готовим профиль стиля и первый вопрос.'
        : 'Загружаем сохранённые ответы и историю вопросов.'
    })
    try {
      if (!opts?.fresh && regChat && isOpenRegulationDraft(regChat)) {
        try {
          const latest = await api.getRegulationCreationSession(regChat.draftId)
          setRegChat(latest)
        } catch {
          /* keep the in-memory draft */
        }
        setView({ kind: 'regchat' })
        return
      }
      const session = opts?.fresh
        ? await api.startRegulationCreation({ fresh: true })
        : (await api.getActiveRegulationCreation()) || (await api.startRegulationCreation())
      setRegChat(session)
      setView({ kind: 'regchat' })
    } catch (err) {
      fail('Не удалось начать', err)
    }
  }

  async function extractFunctions(result: RegulationParseResult): Promise<void> {
    let position = (user?.position || '').trim()
    let department = (user?.department || '').trim()
    if (!position) {
      position = window.prompt('Должность не найдена в профиле. Укажите должность:')?.trim() || ''
    }
    if (!department) {
      department =
        window.prompt('Подразделение не найдено в профиле. Укажите подразделение:')?.trim() || ''
    }
    if (!position || !department) return
    setView({
      kind: 'loading',
      title: 'Cursor Agent выделяет функциональные блоки',
      subtitle: 'Передаём полный распознанный регламент агенту. Это может занять несколько минут.'
    })
    try {
      const extracted = await api.extractRegulationFunctions(result.regulationId, position, department)
      setRoleMatch(extracted)
      setView({ kind: 'rolematch' })
    } catch (err) {
      fail('Поиск фрагментов по должности', err)
    }
  }

  async function finishRoleMatch(): Promise<void> {
    if (!regulation || !roleMatch) return
    setBusy(true)
    setView({
      kind: 'loading',
      title: 'Создаём черновик ИИ-агента',
      subtitle: 'Сохраняем подтверждённые функции и готовим уточняющие вопросы.'
    })
    try {
      const created = await api.createAgentDraft(regulation.regulationId, roleMatch.runId)
      const items = created.agentSuggestions.length
        ? created.agentSuggestions
        : suggestionsFromRoleMatch(roleMatch)
      setDraft({ ...created, agentSuggestions: items })
      setBusy(false)
      setView({ kind: 'readiness' })
    } catch (err) {
      fail('Готовность регламента', err)
    }
  }

  async function openAgentRun(
    workflowId: string,
    runId: string,
    autoStart = false
  ): Promise<void> {
    let title = ''
    try {
      const record = await api.getWorkflow(workflowId)
      title = record.title
    } catch {
      /* fall back to a generic title */
    }
    const live = runs.entries[workflowId]
    if (live && isLiveRunState(live.state)) {
      setView({
        kind: 'agentrun',
        workflowId,
        title: title || live.title,
        autoStart: false
      })
      return
    }
    if (runId) {
      try {
        const detail = await api.getAgentRunDetail(workflowId, runId)
        if (isInFlightRunStatus(detail.item.status)) {
          runs.noteRunning(workflowId, title, runId)
          void runs.attachHistoryFeed(workflowId)
          setView({ kind: 'agentrun', workflowId, title, autoStart: false })
          return
        }
      } catch {
        /* open history of this finished run */
      }
      setView({ kind: 'history', workflowId, title, runId })
      return
    }
    setView({ kind: 'agentrun', workflowId, title, autoStart })
  }

  async function continueDraft(draftId: string): Promise<void> {
    setView({
      kind: 'loading',
      title: 'Открываем черновик',
      subtitle: 'Загружаем выделенные функции и готовим список ИИ-агентов.'
    })
    try {
      const loaded = await api.getAgentDraft(draftId)
      setDraft(loaded)
      const items = loaded.agentSuggestions ?? []
      setSuggestions(items)
      if (loaded.status === 'ready' && items.length) {
        setView({ kind: 'suggestions' })
      } else {
        setView({ kind: 'readiness' })
      }
    } catch (err) {
      fail('Не удалось открыть черновик', err)
    }
  }

  function completeReadiness(nextDraft: AgentDraft): void {
    setDraft(nextDraft)
    setSuggestions(
      nextDraft.agentSuggestions.length
        ? nextDraft.agentSuggestions
        : roleMatch
          ? suggestionsFromRoleMatch(roleMatch)
          : []
    )
    setView({ kind: 'suggestions' })
  }

  async function formDraftSuggestion(draftId: string, agentId: string): Promise<void> {
    setView({
      kind: 'loading',
      title: 'Готовим паспорт ИИ-агента',
      subtitle: 'Загружаем выбранную функцию из черновика.'
    })
    try {
      const loaded = await api.getAgentDraft(draftId)
      setDraft(loaded)
      const items = loaded.agentSuggestions ?? []
      setSuggestions(items)
      const picked = items.find((item) => item.agentId === agentId) ?? items[0]
      if (!picked) {
        setView({ kind: 'suggestions' })
        return
      }
      await openPassport(picked)
    } catch (err) {
      fail('Не удалось открыть черновик', err)
    }
  }

  async function openPassport(item: AgentSuggestion): Promise<void> {
    setSuggestion(item)
    setPassport(null)
    setPassportError('')
    setView({ kind: 'passport' })
    setBusy(true)
    try {
      const session = await api.draftPassportFromSuggestion(item, draft?.draftId || '', item.agentId)
      setPassport(session)
    } catch (err) {
      setPassportError(err instanceof Error ? err.message : 'Не удалось собрать паспорт')
    } finally {
      setBusy(false)
    }
  }

  async function answerPassport(answers: Record<string, string>): Promise<void> {
    if (!passport || !suggestion) return
    setBusy(true)
    setPassportError('')
    try {
      const updated = await api.completePassport(
        passport,
        answers,
        suggestion,
        draft?.draftId || passport.draftId,
        suggestion.agentId
      )
      setPassport(updated)
    } catch (err) {
      setPassportError(err instanceof Error ? err.message : 'Не удалось обновить паспорт')
    } finally {
      setBusy(false)
    }
  }

  async function startWorkflowFromPassport(): Promise<void> {
    if (!passport) return
    const title = (passport.passport?.name || passport.bpName || 'ИИ-агент').trim()
    setView({
      kind: 'loading',
      title: 'Создаём агента',
      subtitle: 'Готовим рабочее пространство и запускаем проектирование через локальный Cursor SDK.'
    })
    setBusy(true)
    try {
      const created = await api.createWorkflow(
        notesFromPassport(passport),
        draft?.draftId || passport.draftId || ''
      )
      setView({ kind: 'studio', workflowId: created.id, title: created.title || title })
    } catch (err) {
      fail('Ошибка создания агента', err)
    } finally {
      setBusy(false)
    }
  }

  if (booting) {
    return (
      <div className="app-root boot-screen">
        <div className="spinner spinner-on-dark" />
        <div className="boot-label">Загрузка Constructor...</div>
      </div>
    )
  }

  if (!user) {
    return <LoginPage onLoggedIn={onLoggedIn} />
  }

  const activeKey: PageKey | null =
    view.kind === 'tab'
      ? view.key
      : view.kind === 'chat'
        ? null
        : view.kind === 'history' ||
            view.kind === 'agentrun' ||
            view.kind === 'studio' ||
            view.kind === 'schedule' ||
            view.kind === 'kpi'
          ? 'agents'
          : 'create'

  function renderCreatePage(): React.JSX.Element {
    return (
      <CreatePage
        onRegulationParsed={(result) => {
          setRegulation(result)
          setView({ kind: 'review', result })
        }}
        onStartRegulationChat={() => void startRegulationChat()}
        hasRegulationDraft={isOpenRegulationDraft(regChat)}
        regulationDraftBusy={regChatBusy}
        onResumeRegulationDraft={() => void startRegulationChat()}
        onRestartRegulationDraft={() => void startRegulationChat({ fresh: true })}
      />
    )
  }

  function renderContent(): React.JSX.Element {
    if (view.kind === 'chat') {
      return (
        <MessengerPage
          thread={view.thread}
          me={user!}
          onThreadChange={(thread) => setView({ kind: 'chat', thread })}
          onOpenAgent={(workflowId) => void openAgentRun(workflowId, '')}
        />
      )
    }
    if (view.kind === 'loading') {
      return (
        <div className="center-state">
          <div className="spinner" />
          <div style={{ fontSize: 22, fontWeight: 600, color: 'var(--main-text)' }}>{view.title}</div>
          <div>{view.subtitle}</div>
        </div>
      )
    }
    if (view.kind === 'soon') {
      return (
        <div>
          <h1 className="page-title">{view.title}</h1>
          <div className="placeholder-card">{view.note}</div>
          <button
            className="btn-primary"
            style={{ maxWidth: 200, marginTop: 20 }}
            onClick={() => setView({ kind: 'tab', key: 'create' })}
          >
            На главную
          </button>
        </div>
      )
    }
    if (view.kind === 'review') {
      return (
        <ReviewPage
          result={view.result}
          onBack={() => setView({ kind: 'tab', key: 'create' })}
          onContinue={() => extractFunctions(view.result)}
          continueBusy={busy}
        />
      )
    }
    if (view.kind === 'rolematch' && roleMatch) {
      return (
        <RoleMatchPage
          result={roleMatch}
          regulation={regulation}
          busy={busy}
          onBack={() =>
            regulation
              ? setView({ kind: 'review', result: regulation })
              : setView({ kind: 'tab', key: 'create' })
          }
          onDecide={async (matchId, status) => {
            if (!regulation || !roleMatch) {
              throw new Error('Нет данных регламента или проверки функций')
            }
            setBusy(true)
            try {
              const updated = await api.decideRoleMatch(
                regulation.regulationId,
                roleMatch.runId,
                matchId,
                status
              )
              setRoleMatch(updated)
            } finally {
              setBusy(false)
            }
          }}
          onFinish={finishRoleMatch}
        />
      )
    }
    if (view.kind === 'readiness' && draft) {
      return (
        <ReadinessPage
          draft={draft}
          busy={busy}
          onBack={() => setView({ kind: 'rolematch' })}
          onComplete={completeReadiness}
        />
      )
    }
    if (view.kind === 'suggestions') {
      return (
        <SuggestionsPage
          suggestions={suggestions}
          busy={busy}
          onBack={() => setView({ kind: 'readiness' })}
          onCreate={openPassport}
        />
      )
    }
    if (view.kind === 'passport' && suggestion) {
      return (
        <PassportPage
          suggestion={suggestion}
          session={passport}
          error={passportError}
          busy={busy}
          onBack={() => setView({ kind: 'suggestions' })}
          onAnswer={answerPassport}
          onFinish={startWorkflowFromPassport}
        />
      )
    }
    if (view.kind === 'studio') {
      return (
        <AgentStudioPage
          workflowId={view.workflowId}
          title={view.title}
          formation={formation}
          onBack={() => setView({ kind: 'tab', key: 'agents' })}
          onGoSchedule={(workflowId, title) => setView({ kind: 'schedule', workflowId, title })}
        />
      )
    }
    if (view.kind === 'agentrun') {
      return (
        <AgentRunPage
          workflowId={view.workflowId}
          title={view.title}
          autoStart={view.autoStart}
          onBack={() => setView({ kind: 'tab', key: 'agents' })}
          onOpenHistory={(workflowId, title) => setView({ kind: 'history', workflowId, title })}
        />
      )
    }
    if (view.kind === 'schedule') {
      return (
        <AgentSchedulePage
          workflowId={view.workflowId}
          title={view.title}
          onBack={() => setView({ kind: 'studio', workflowId: view.workflowId, title: view.title })}
          onNext={(draft) =>
            setView({ kind: 'kpi', workflowId: view.workflowId, title: view.title, draft })
          }
        />
      )
    }
    if (view.kind === 'kpi') {
      return (
        <AgentKpiPreviewPage
          workflowId={view.workflowId}
          title={view.title}
          draft={view.draft}
          onBack={() => setView({ kind: 'schedule', workflowId: view.workflowId, title: view.title })}
          onPublished={() => setView({ kind: 'tab', key: 'agents' })}
        />
      )
    }
    if (view.kind === 'history') {
      return (
        <AgentHistoryPage
          workflowId={view.workflowId}
          title={view.title}
          initialRunId={view.runId}
          onBack={() => setView({ kind: 'tab', key: 'agents' })}
          onOpenLive={() =>
            setView({ kind: 'agentrun', workflowId: view.workflowId, title: view.title })
          }
        />
      )
    }
    if (view.kind !== 'tab') {
      return renderCreatePage()
    }
    switch (view.key) {
      case 'create':
        return renderCreatePage()
      case 'agents':
        return (
          <AgentsPage
            onCreateAgent={() => setView({ kind: 'tab', key: 'create' })}
            onOpenRun={(workflowId, runId, autoStart) =>
              void openAgentRun(workflowId, runId, autoStart)
            }
            onFormDraftSuggestion={formDraftSuggestion}
            onContinueDraft={continueDraft}
          />
        )
      case 'files':
        return (
          <FilesPage
            ownerName={user?.fio || ''}
            onOpenRun={(workflowId, runId) => void openAgentRun(workflowId, runId)}
          />
        )
      case 'kpi':
        return <KpiPage />
      case 'orchestrator':
        return <OrchestratorPage user={user!} />
      default:
        return renderCreatePage()
    }
  }

  const bannerEntries: BannerEntry[] = []
  if (
    formation.inProgress &&
    !(view.kind === 'studio' && view.workflowId === formation.workflowId)
  ) {
    bannerEntries.push({
      id: `formation:${formation.workflowId}`,
      title: formation.title,
      output: formation.latestOutput,
      running: formation.running,
      awaiting: formation.awaiting,
      mode: 'formation',
      onOpen: () =>
        setView({ kind: 'studio', workflowId: formation.workflowId, title: formation.title })
    })
  }
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
      onOpen: () =>
        setView({ kind: 'agentrun', workflowId: entry.workflowId, title: entry.title })
    })
  }
  if (regChat && isOpenRegulationDraft(regChat) && view.kind !== 'regchat') {
    bannerEntries.push({
      id: `regchat:${regChat.draftId}`,
      title: 'Создание регламента',
      output: regChatBusy
        ? 'Готовлю вопрос...'
        : regulationDraftPreview(regChat) || 'Ответьте на вопрос ИИ',
      running: regChatBusy,
      awaiting: !regChatBusy,
      mode: 'formation',
      onOpen: () => setView({ kind: 'regchat' })
    })
  }

  return (
    <div className="app-root">
      <Sidebar
        active={activeKey}
        activeThreadId={view.kind === 'chat' ? view.thread.id : ''}
        currentUserId={user?.id || ''}
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
              onLogout={onLogout}
              showLogout={showLogout}
              onOpenAgent={(workflowId, runId) => void openAgentRun(workflowId, runId)}
            />
          </div>
          {view.kind === 'regchat' ? null : <RunBannerCarousel entries={bannerEntries} />}
          {regChat ? (
            <div
              className={view.kind === 'regchat' ? 'regchat-host' : 'regchat-host is-parked'}
              hidden={view.kind !== 'regchat'}
            >
              <RegulationChatPage
                session={regChat}
                onSessionChange={setRegChat}
                onBusyChange={setRegChatBusy}
                onStopped={() => {
                  setRegChat(null)
                  setRegChatBusy(false)
                  setView({ kind: 'tab', key: 'create' })
                }}
                banner={
                  view.kind === 'regchat' ? <RunBannerCarousel entries={bannerEntries} /> : undefined
                }
                onReady={async (session) => {
                  let result = session.resultRegulation
                  if (!result?.regulationId) {
                    const latest = await api.getRegulationCreationSession(session.draftId)
                    setRegChat(latest)
                    result = latest.resultRegulation
                  }
                  if (result?.regulationId) {
                    setRegulation(result)
                    setView({ kind: 'review', result })
                    return
                  }
                  throw new Error(
                    'Карточка регламента не собралась. Скачайте файл из чата или нажмите «Создать принудительно».'
                  )
                }}
                onBack={() => setView({ kind: 'tab', key: 'create' })}
              />
            </div>
          ) : null}
          {view.kind === 'regchat' ? null : renderContent()}
        </div>
      </main>
    </div>
  )
}
