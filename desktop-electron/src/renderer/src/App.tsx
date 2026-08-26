import { useEffect, useRef, useState } from 'react'
import { Sidebar, type PageKey } from './components/Sidebar'
import { UserMenu } from './components/UserMenu'
import { LoginPage } from './pages/LoginPage'
import { CreatePage } from './pages/CreatePage'
import { AgentsPage } from './pages/AgentsPage'
import { FilesPage } from './pages/FilesPage'
import { KpiPage, DashboardPage } from './pages/SimplePages'
import { ReviewPage } from './pages/ReviewPage'
import { RegulationChatPage } from './pages/RegulationChatPage'
import { RoleMatchPage } from './pages/RoleMatchPage'
import { ReadinessPage } from './pages/ReadinessPage'
import { SuggestionsPage } from './pages/SuggestionsPage'
import { PassportPage } from './pages/PassportPage'
import { AgentStudioPage } from './pages/AgentStudioPage'
import { AgentRunPage } from './pages/AgentRunPage'
import { AgentSchedulePage, type ScheduleSpec } from './pages/AgentSchedulePage'
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
  QuestionChatSession,
  RegulationCreationSession,
  RegulationParseResult,
  RoleMatchResult,
  UserProfile,
  ChatThread
} from './api/types'
import { clearSession, loadSession, saveSession } from './store/session'

type View =
  | { kind: 'tab'; key: PageKey }
  | { kind: 'review'; result: RegulationParseResult }
  | { kind: 'regchat'; session: RegulationCreationSession }
  | { kind: 'rolematch' }
  | { kind: 'readiness' }
  | { kind: 'suggestions' }
  | { kind: 'passport' }
  | { kind: 'studio'; workflowId: string; title: string }
  | { kind: 'agentrun'; workflowId: string; title: string }
  | { kind: 'schedule'; workflowId: string; title: string }
  | { kind: 'kpi'; workflowId: string; title: string; schedule: ScheduleSpec }
  | { kind: 'history'; workflowId: string; title: string }
  | { kind: 'chat'; thread: ChatThread }
  | { kind: 'loading'; title: string; subtitle: string }
  | { kind: 'soon'; title: string; note: string }

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
  const [chat, setChat] = useState<QuestionChatSession | null>(null)
  const [suggestions, setSuggestions] = useState<AgentSuggestion[]>([])
  const [suggestion, setSuggestion] = useState<AgentSuggestion | null>(null)
  const [passport, setPassport] = useState<PassportSession | null>(null)
  const [passportError, setPassportError] = useState('')
  const [busy, setBusy] = useState(false)
  const kickedRef = useRef(false)
  const [chatRefreshAt, setChatRefreshAt] = useState(0)

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
      return
    }
    const token = api.getToken()
    if (token) {
      void window.api.startNotifications?.(token)
      void agentClient.ready(token).catch(() => undefined)
    }
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

  function onLoggedIn(result: LoginResult, remember: boolean): void {
    api.setToken(result.accessToken || null)
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
    await api.terminateRegulationCreationSessions()
    clearSession(true)
    api.setToken(null)
    clearAvatarCache()
    setAvatarUrl(null)
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

  async function openChatByFio(fio: string): Promise<void> {
    const name = fio.trim()
    if (!name) return
    try {
      const threads = await api.listChatThreads()
      const existing = threads.find((item) => item.title.toLowerCase() === name.toLowerCase())
      if (existing) {
        openChat(existing)
        return
      }
      const users = await api.listDirectoryUsers(name)
      const match =
        users.find((item) => item.fio.toLowerCase() === name.toLowerCase() && item.id) ||
        users.find((item) => item.id)
      if (!match?.id) {
        fail('Чат', new Error('Пользователь не найден'))
        return
      }
      const known = threads.find((item) => item.peerId === match.id)
      if (known) {
        openChat(known)
        return
      }
      await api.openDirectChat(match.id)
      const next = (await api.listChatThreads()).find((item) => item.peerId === match.id)
      openChat(
        next || {
          id: match.id,
          kind: 'dm',
          title: match.fio,
          position: match.position,
          preview: '',
          lastMessageAt: '',
          unread: 0,
          pinned: false,
          peerId: match.id,
          activityStatus: match.activityStatus,
          online: match.online,
          ticketStatus: '',
          avatarUrl: null
        }
      )
    } catch (err) {
      fail('Чат', err)
    }
  }

  async function startRegulationChat(): Promise<void> {
    setView({
      kind: 'loading',
      title: 'Создаём чат регламента',
      subtitle: 'Готовим профиль стиля и первый вопрос.'
    })
    try {
      const session = await api.startRegulationCreation()
      setView({ kind: 'regchat', session })
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

  async function firstChatForDraft(next: AgentDraft): Promise<QuestionChatSession | null> {
    const readiness = next.readiness
    const question = readiness?.questions.find((item) => !item.answered)
    try {
      const latest = await api.latestQuestionChat(next.draftId)
      if (latest.status !== 'answered') return latest
      if (!question) return latest
    } catch {
      /* no latest chat */
    }
    if (!question) return null
    return api.createQuestionChat(next.draftId, question.questionId)
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
      const ensured = await api.ensureDraftReadiness(created.draftId)
      const unanswered = (ensured.readiness?.questions ?? []).some((item) => !item.answered)
      if (!unanswered) {
        const ready = await api.updateAgentDraftStatus(ensured.draftId, 'ready')
        setDraft(ready)
        setSuggestions(
          ready.agentSuggestions.length ? ready.agentSuggestions : suggestionsFromRoleMatch(roleMatch)
        )
        setBusy(false)
        setView({ kind: 'suggestions' })
        return
      }
      const nextChat = await firstChatForDraft(ensured)
      setDraft(ensured)
      setChat(nextChat)
      setBusy(false)
      setView({ kind: 'readiness' })
    } catch (err) {
      fail('Готовность регламента', err)
    }
  }

  async function sendReadinessMessage(questionId: string, message: string): Promise<void> {
    if (!draft) return
    setBusy(true)
    try {
      let nextChat = await api.sendQuestionChatMessage(draft.draftId, questionId, message)
      const nextDraft = await api.getAgentDraft(draft.draftId)
      if (nextChat.status === 'answered') {
        nextChat = (await firstChatForDraft(nextDraft)) || nextChat
      }
      setDraft(nextDraft)
      setChat(nextChat)
      if (!(nextDraft.readiness?.questions ?? []).some((item) => !item.answered)) {
        const ready = await api.updateAgentDraftStatus(nextDraft.draftId, 'ready')
        setDraft(ready)
        setSuggestions(
          ready.agentSuggestions.length
            ? ready.agentSuggestions
            : roleMatch
              ? suggestionsFromRoleMatch(roleMatch)
              : []
        )
        setView({ kind: 'suggestions' })
      }
    } catch (err) {
      fail('Готовность регламента', err)
    } finally {
      setBusy(false)
    }
  }

  async function openAgentRun(workflowId: string, runId: string): Promise<void> {
    let title = ''
    try {
      const record = await api.getWorkflow(workflowId)
      title = record.title
    } catch {
      /* fall back to a generic title */
    }
    if (runId) {
      setView({ kind: 'history', workflowId, title })
    } else {
      setView({ kind: 'agentrun', workflowId, title })
    }
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
      if (items.length) {
        setView({ kind: 'suggestions' })
      } else {
        setChat(await firstChatForDraft(loaded))
        setView({ kind: 'readiness' })
      }
    } catch (err) {
      fail('Не удалось открыть черновик', err)
    }
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
      const created = await api.createWorkflow(notesFromPassport(passport))
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

  const activeKey: PageKey | null = view.kind === 'tab' ? view.key : view.kind === 'chat' ? null : 'create'

  function renderContent(): React.JSX.Element {
    if (view.kind === 'chat') {
      return (
        <MessengerPage
          thread={view.thread}
          me={user!}
          onThreadChange={(thread) => setView({ kind: 'chat', thread })}
          onOpenAgent={(workflowId, title) => setView({ kind: 'history', workflowId, title })}
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
    if (view.kind === 'regchat') {
      return (
        <RegulationChatPage
          session={view.session}
          onSessionChange={(session) => setView({ kind: 'regchat', session })}
          onReady={(session) => {
            if (session.resultRegulation) {
              setRegulation(session.resultRegulation)
              setView({ kind: 'review', result: session.resultRegulation })
            }
          }}
          onBack={() => setView({ kind: 'tab', key: 'create' })}
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
          chat={chat}
          busy={busy}
          onBack={() => setView({ kind: 'rolematch' })}
          onSend={sendReadinessMessage}
          onSkipToAgents={() => {
            setSuggestions(
              draft.agentSuggestions.length
                ? draft.agentSuggestions
                : roleMatch
                  ? suggestionsFromRoleMatch(roleMatch)
                  : []
            )
            setView({ kind: 'suggestions' })
          }}
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
          onNext={(schedule) =>
            setView({ kind: 'kpi', workflowId: view.workflowId, title: view.title, schedule })
          }
        />
      )
    }
    if (view.kind === 'kpi') {
      return (
        <AgentKpiPreviewPage
          workflowId={view.workflowId}
          title={view.title}
          schedule={view.schedule}
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
          onBack={() => setView({ kind: 'tab', key: 'agents' })}
        />
      )
    }
    if (view.kind !== 'tab') {
      return (
        <CreatePage
          onRegulationParsed={(result) => {
            setRegulation(result)
            setView({ kind: 'review', result })
          }}
          onStartRegulationChat={startRegulationChat}
        />
      )
    }
    switch (view.key) {
      case 'create':
        return (
          <CreatePage
            onRegulationParsed={(result) => {
              setRegulation(result)
              setView({ kind: 'review', result })
            }}
            onStartRegulationChat={startRegulationChat}
          />
        )
      case 'agents':
        return (
          <AgentsPage
            onCreateAgent={() => setView({ kind: 'tab', key: 'create' })}
            onOpenRun={(workflowId, runId) => void openAgentRun(workflowId, runId)}
            onFormDraftSuggestion={formDraftSuggestion}
            onContinueDraft={continueDraft}
          />
        )
      case 'files':
        return <FilesPage />
      case 'kpi':
        return <KpiPage />
      case 'dashboard':
        return <DashboardPage />
      default:
        return <CreatePage onRegulationParsed={() => {}} onStartRegulationChat={startRegulationChat} />
    }
  }

  return (
    <div className="app-root">
      <Sidebar
        active={activeKey}
        activeThreadId={view.kind === 'chat' ? view.thread.id : ''}
        onNavigate={(key) => setView({ kind: 'tab', key })}
        onOpenThread={openChat}
        onOpenFio={(fio) => void openChatByFio(fio)}
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
            />
          </div>
          {renderContent()}
        </div>
      </main>
    </div>
  )
}
