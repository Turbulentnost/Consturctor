import { useEffect, useLayoutEffect, useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'
import { apiGet, apiPost } from '../api/client'
import type {
  AgentApproval,
  AgentQuestion,
  PlatformConfig,
  PlatformSession,
  PlatformSessionDetail,
  SessionEvent
} from '../api/types'
import {
  ArrowUpIcon,
  BotIcon,
  ChecklistIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  LayersIcon,
  PaperclipIcon,
  PlayIcon,
  StopIcon
} from '../components/Icons'
import { MarkdownView } from '../components/MarkdownView'
import { AgentInsights } from './AgentInsights'
import { SESSION_STATUS, modelLabel } from '../platformLabels'
import {
  ExploreGroup,
  SubagentMeta,
  ToolCard,
  isExploreEvent,
  isHiddenTool,
  isQuestionEvent,
  isWaitingQuestion,
  readSubagent,
  type SubagentLink
} from './SessionTools'
import { QuestionForm } from './SessionQuestion'
import { ApprovalForm, ApprovalLine } from './SessionApproval'
import { ProgressBar } from './SessionProgress'
import {
  ComposerFiles,
  MAX_FILES,
  MessageFiles,
  pendingFrom,
  toUpload,
  type PendingFile
} from './SessionAttachments'
export type AgentWorkspace = { kind: 'create'; configId: string } | { kind: 'session'; sessionId: string }

const RUNNING_POLL_MS = 700
const IDLE_POLL_MS = 4000
const MAX_INPUT_HEIGHT = 240
const LONG_INSTRUCTION = 700
const STICK_TO_BOTTOM_PX = 80
const QUESTION_GRACE_MS = 4000

interface AgentSessionProps {
  target: AgentWorkspace
  configs: PlatformConfig[]
  onBack: () => void
  backLabel?: string
  onOpened: (sessionId: string) => void
  showProgress: boolean
  onShowProgress: (show: boolean) => void
}

// Скрытый ход работы: сообщения человека, вопросы, разрешения, план, ошибки и итоговый
// текст каждого завершённого хода — без размышлений, инструментов и промежуточных реплик.
function resultsOnly(visible: SessionEvent[], running: boolean): SessionEvent[] {
  const lastTurn = visible.reduce((max, event) => Math.max(max, event.turn), 0)
  const finalText = new Map<number, number>()
  for (const event of visible) if (event.type === 'assistant' && event.text.trim()) finalText.set(event.turn, event.seq)
  return visible.filter((event) => {
    if (event.type === 'assistant') return finalText.get(event.turn) === event.seq && !(running && event.turn === lastTurn)
    if (event.type === 'tool') return isQuestionEvent(event)
    return event.type !== 'thinking'
  })
}

type FeedBlock = { kind: 'event'; event: SessionEvent } | { kind: 'explore'; items: SessionEvent[] }

// Подряд идущие чтения, поиски и вызовы MCP одного хода сворачиваются в одну группу,
// размышления между ними уходят внутрь. Список дел показываем только в последнем состоянии хода.
function buildBlocks(visible: SessionEvent[]): FeedBlock[] {
  const lastTodos = new Map<number, number>()
  for (const event of visible) {
    if (event.type === 'tool' && event.name === 'updateTodos') lastTodos.set(event.turn, event.seq)
  }
  const blocks: FeedBlock[] = []
  let group: SessionEvent[] | null = null
  let pending: SessionEvent[] = []
  const close = (): void => {
    if (group) blocks.push({ kind: 'explore', items: group })
    for (const event of pending) blocks.push({ kind: 'event', event })
    group = null
    pending = []
  }
  for (const event of visible) {
    if (event.type === 'tool' && event.name === 'updateTodos' && lastTodos.get(event.turn) !== event.seq) continue
    if (event.type === 'tool' && (event.name === 'createPlan' || isHiddenTool(event))) continue
    if (event.type === 'tool' && isExploreEvent(event)) {
      if (group && group[0].turn === event.turn) {
        group.push(...pending, event)
        pending = []
      } else {
        close()
        group = [event]
      }
    } else if (event.type === 'thinking' && group) {
      pending.push(event)
    } else {
      close()
      blocks.push({ kind: 'event', event })
    }
  }
  close()
  return blocks
}

function Feed({
  sessionId,
  events,
  progress,
  running,
  footer,
  subagents
}: {
  sessionId: string
  events: SessionEvent[]
  progress: boolean
  running: boolean
  footer?: ReactNode
  subagents?: SubagentLink
}): React.JSX.Element {
  const all = events.filter((event) => event.type !== 'status')
  const visible = progress ? all : resultsOnly(all, running)
  const last = visible[visible.length - 1]

  return (
    <div className="sess-feed">
      {buildBlocks(visible).map((block) => {
        if (block.kind === 'explore') {
          return (
            <ExploreGroup
              key={`g${block.items[0].seq}`}
              items={block.items}
              active={running}
              live={running && block.items.includes(last)}
            />
          )
        }
        const event = block.event
        if (event.type === 'user') {
          const isInstruction = event.turn === 1
          const label = event.label || (isInstruction ? 'Инструкция' : '')
          if (label && event.text.length > LONG_INSTRUCTION) {
            return (
              <details key={event.seq} className="sess-instruction">
                <summary>
                  <span>
                    {event.label || 'Инструкция агента'}
                    {event.attachments?.length ? ` · вложений: ${event.attachments.length}` : ''}
                  </span>
                  <ChevronDownIcon size={14} />
                </summary>
                {event.attachments?.length ? <MessageFiles sessionId={sessionId} files={event.attachments} /> : null}
                <MarkdownView text={event.text} />
              </details>
            )
          }
          return (
            <div key={event.seq} className="sess-user">
              {label ? <span className="sess-user-label">{label}</span> : null}
              {event.attachments?.length ? <MessageFiles sessionId={sessionId} files={event.attachments} /> : null}
              {event.text ? <p>{event.text}</p> : null}
            </div>
          )
        }
        if (event.type === 'thinking') {
          const live = running && event === last
          return (
            <details key={event.seq} className={live ? 'sess-thinking live' : 'sess-thinking'}>
              <summary>{live ? 'Размышляет…' : 'Размышления'}</summary>
              <p>{event.text}</p>
            </details>
          )
        }
        if (event.type === 'tool') return <ToolCard key={event.seq} event={event} active={running} subagents={subagents} />
        if (event.type === 'approval') return <ApprovalLine key={event.seq} event={event} />
        if (event.type === 'plan') {
          return (
            <details key={event.seq} className="sess-plan" open>
              <summary>
                <ChecklistIcon size={15} />
                <span className="sess-plan-title">{event.name ? `План · ${event.name}` : 'План'}</span>
                <span className="sess-plan-note">сохранён как инструкция агента</span>
                <ChevronDownIcon size={14} />
              </summary>
              <MarkdownView text={event.text} />
            </details>
          )
        }
        if (event.type === 'error') {
          return (
            <p key={event.seq} className="sess-error">
              {event.text}
            </p>
          )
        }
        return (
          <div key={event.seq} className="sess-assistant">
            <MarkdownView text={event.text} />
          </div>
        )
      })}
      {footer}
    </div>
  )
}

const STICK_SUBAGENT_PX = 60

function SubagentPanel({
  sessionId,
  task,
  events,
  running,
  onBack
}: {
  sessionId: string
  task: SessionEvent | null
  events: SessionEvent[]
  running: boolean
  onBack: () => void
}): React.JSX.Element {
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const info = task ? readSubagent(task, running) : null
  const live = running && info?.state === 'running'

  useEffect(() => {
    stickRef.current = true
  }, [task?.call_id])

  useLayoutEffect(() => {
    const box = scrollRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [events, task?.call_id])

  const prompt: SessionEvent[] =
    task && info?.prompt
      ? [
          {
            seq: 0,
            rev: 0,
            turn: task.turn,
            type: 'user',
            text: info.prompt,
            name: '',
            status: '',
            call_id: '',
            args: '',
            result: '',
            label: 'Задание подагента'
          }
        ]
      : []
  let note = ''
  if (info && !events.length) {
    note =
      info.state === 'running'
        ? 'Подагент запускается…'
        : 'Ход подагента не записан: он работал до того, как платформа начала сохранять его шаги.'
  } else if (info?.state === 'stopped') {
    note = 'Подагент остановлен.'
  }

  return (
    <aside className="glass-panel sub-panel" aria-label="Ход подагента">
      <header className="sub-head">
        <button type="button" className="agent-back" onClick={onBack}>
          <ChevronLeftIcon size={16} />
          Производительность
        </button>
        {info ? <SubagentMeta info={info} /> : null}
      </header>
      {info ? (
        <div className="sub-title">
          <BotIcon size={15} />
          <strong title={info.description}>{info.description || 'Подагент'}</strong>
          {info.model ? <span className="sess-config-model">{info.model}</span> : null}
        </div>
      ) : null}
      <div
        className="sess-scroll sub-scroll"
        ref={scrollRef}
        onScroll={(event) => {
          const box = event.currentTarget
          stickRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < STICK_SUBAGENT_PX
        }}
      >
        {info ? (
          <Feed
            sessionId={sessionId}
            events={[...prompt, ...events]}
            progress
            running={live}
            footer={
              <>
                {info.error ? <p className="sess-error">{info.error}</p> : null}
                {note ? <p className="sess-note">{note}</p> : null}
              </>
            }
          />
        ) : null}
      </div>
    </aside>
  )
}

export function AgentSession({
  target,
  configs,
  onBack,
  backLabel = 'К агентам',
  onOpened,
  showProgress,
  onShowProgress
}: AgentSessionProps): React.JSX.Element {
  const sessionId = target.kind === 'session' ? target.sessionId : null
  const [session, setSession] = useState<PlatformSession | null>(null)
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [loadError, setLoadError] = useState('')
  const [prompt, setPrompt] = useState('')
  const [files, setFiles] = useState<PendingFile[]>([])
  const [dragging, setDragging] = useState(false)
  const [sending, setSending] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [notice, setNotice] = useState('')
  const [wake, setWake] = useState(0)
  const [remote, setRemote] = useState<PlatformSessionDetail['remote'] | null>(null)
  const [question, setQuestion] = useState<AgentQuestion | null>(null)
  const [approval, setApproval] = useState<AgentApproval | null>(null)
  const [lateQuestion, setLateQuestion] = useState<string | null>(null)
  // Ход работы «один раз»: только в этом окне сессии, поверх общей настройки.
  const [progressOnce, setProgressOnce] = useState<boolean | null>(null)
  // call_id подагента, открытого справа вместо производительности.
  const [openAgent, setOpenAgent] = useState<string | null>(null)
  // Пока панель уезжает, в ней остаётся последний подагент.
  const shownAgentRef = useRef<string | null>(null)
  // Опрос, ушедший до ответа, ещё вернёт этот вопрос — не показываем его снова.
  const answeredRef = useRef(new Set<string>())
  const revRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const pickerRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef<PendingFile[]>([])
  filesRef.current = files

  const configId = target.kind === 'create' ? target.configId : session?.config_id
  const config = configs.find((item) => item.id === configId) ?? null
  const running = session?.status === 'running'
  // Вопрос ставит MCP-сервер сразу, а поток SDK доносит текст до вызова ask_user с задержкой:
  // форму показываем, когда вызов дошёл до ленты (или поток так и не догнал за QUESTION_GRACE_MS).
  const lastTurn = events.length ? events[events.length - 1].turn : 0
  const questionCalled = events.some((event) => event.turn === lastTurn && isWaitingQuestion(event))
  const asking = running && !remote && question && (questionCalled || lateQuestion === question.id) ? question : null
  const permitting = running && !remote ? approval : null
  if (stopping && !running) setStopping(false)
  const progress = progressOnce ?? showProgress
  const canAttach = Boolean(config?.attachments)
  const planned = Boolean(config?.plan_instruction)
  const canRerun =
    planned &&
    session !== null &&
    !running &&
    session.source === 'custom' &&
    (session.plan_turn === 0 || Boolean(session.plan))

  useEffect(
    () => () => {
      for (const item of filesRef.current) if (item.preview) URL.revokeObjectURL(item.preview)
    },
    []
  )

  // Electron открывает брошенный мимо поля ввода файл вместо приложения.
  useEffect(() => {
    const block = (event: globalThis.DragEvent): void => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault()
    }
    window.addEventListener('dragover', block)
    window.addEventListener('drop', block)
    return () => {
      window.removeEventListener('dragover', block)
      window.removeEventListener('drop', block)
    }
  }, [])

  function addFiles(list: File[]): void {
    if (!list.length) return
    if (!canAttach) {
      setNotice('Эта конфигурация не принимает вложения')
      return
    }
    const room = MAX_FILES - filesRef.current.length
    const { added, rejected } = pendingFrom(list.slice(0, Math.max(room, 0)))
    if (list.length > room) rejected.push(`Не больше ${MAX_FILES} вложений за сообщение`)
    setNotice(rejected.join(' · '))
    if (added.length) setFiles((current) => [...current, ...added])
  }

  function removeFile(id: string): void {
    setFiles((current) => {
      const gone = current.find((item) => item.id === id)
      if (gone?.preview) URL.revokeObjectURL(gone.preview)
      return current.filter((item) => item.id !== id)
    })
  }

  function clearFiles(): void {
    for (const item of filesRef.current) if (item.preview) URL.revokeObjectURL(item.preview)
    setFiles([])
  }

  function onDrop(event: DragEvent<HTMLFormElement>): void {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    setDragging(false)
    addFiles([...event.dataTransfer.files])
  }

  useEffect(() => {
    revRef.current = 0
    setSession(null)
    setEvents([])
    setRemote(null)
    setQuestion(null)
    setApproval(null)
    setProgressOnce(null)
    setOpenAgent(null)
    shownAgentRef.current = null
    setLoadError('')
    stickRef.current = true
  }, [sessionId])

  const questionId = question?.id
  useEffect(() => {
    if (!questionId) return
    const timer = window.setTimeout(() => setLateQuestion(questionId), QUESTION_GRACE_MS)
    return () => window.clearTimeout(timer)
  }, [questionId])

  useEffect(() => {
    if (!sessionId) return
    let alive = true
    let timer = 0
    const tick = async (): Promise<void> => {
      let delay = IDLE_POLL_MS
      try {
        const data = await apiGet<PlatformSessionDetail>(
          `/api/v1/platform/sessions/${encodeURIComponent(sessionId)}?since=${revRef.current}`
        )
        if (!alive) return
        revRef.current = data.session.rev
        setSession(data.session)
        setRemote(data.remote ?? null)
        const asked = data.question && !answeredRef.current.has(data.question.id) ? data.question : null
        setQuestion((current) => (current?.id === asked?.id ? current : asked))
        const pending = data.approval && !answeredRef.current.has(data.approval.id) ? data.approval : null
        setApproval((current) => (current?.id === pending?.id ? current : pending))
        setLoadError('')
        if (data.events.length) {
          setEvents((current) => {
            const bySeq = new Map(current.map((event) => [event.seq, event]))
            for (const event of data.events) bySeq.set(event.seq, event)
            return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
          })
        }
        if (data.session.status === 'running') delay = RUNNING_POLL_MS
      } catch (reason) {
        if (alive) setLoadError(reason instanceof Error ? reason.message : 'Не удалось загрузить сессию')
      }
      if (alive) timer = window.setTimeout(() => void tick(), delay)
    }
    void tick()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [sessionId, wake])

  useLayoutEffect(() => {
    const box = scrollRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [events, session?.status])

  useEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.style.height = 'auto'
    input.style.height = `${Math.min(input.scrollHeight, MAX_INPUT_HEIGHT)}px`
  }, [prompt])

  useEffect(() => {
    inputRef.current?.focus({ preventScroll: true })
  }, [target.kind])

  const hasContent = Boolean(prompt.trim()) || (target.kind === 'session' && files.length > 0)
  const canSend = hasContent && !sending && !running && (target.kind === 'session' || Boolean(config?.runnable))

  async function send(): Promise<void> {
    if (!canSend) return
    const text = prompt.trim()
    setSending(true)
    setNotice('')
    try {
      const attachments = await Promise.all(files.map(toUpload))
      if (target.kind === 'create') {
        const created = await apiPost<PlatformSession>('/api/v1/platform/sessions', {
          source: 'custom',
          config_id: target.configId,
          prompt: text,
          attachments
        })
        setPrompt('')
        clearFiles()
        onOpened(created.id)
      } else {
        const updated = await apiPost<PlatformSession>(
          `/api/v1/platform/sessions/${encodeURIComponent(target.sessionId)}/messages`,
          { prompt: text, attachments }
        )
        setPrompt('')
        clearFiles()
        setSession(updated)
        stickRef.current = true
        setWake((value) => value + 1)
      }
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'Не удалось отправить')
    } finally {
      setSending(false)
    }
  }

  async function rerun(): Promise<void> {
    if (!session) return
    setSending(true)
    setNotice('')
    try {
      const created = await apiPost<PlatformSession>(
        `/api/v1/platform/agents/${encodeURIComponent(session.agent_id)}/runs`,
        {}
      )
      onOpened(created.id)
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'Не удалось запустить агента')
    } finally {
      setSending(false)
    }
  }

  async function stop(): Promise<void> {
    if (target.kind !== 'session' || stopping) return
    setStopping(true)
    try {
      await apiPost(`/api/v1/platform/sessions/${encodeURIComponent(target.sessionId)}/cancel`, {})
      setWake((value) => value + 1)
    } catch (reason) {
      setStopping(false)
      setNotice(reason instanceof Error ? reason.message : 'Не удалось остановить агента')
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send()
    }
  }

  const mainEvents = events.filter((event) => !event.parent)
  if (openAgent) shownAgentRef.current = openAgent
  const shownAgent = shownAgentRef.current
  const subagentTask = shownAgent
    ? (mainEvents.find((event) => event.type === 'tool' && event.call_id === shownAgent) ?? null)
    : null
  const subagentEvents = shownAgent ? events.filter((event) => event.parent === shownAgent) : []
  const subagentLink: SubagentLink = {
    open: openAgent,
    onOpen: (callId) => setOpenAgent((current) => (current === callId ? null : callId))
  }

  const lastShown = [...mainEvents].reverse().find((event) => event.type !== 'status')
  const workingText = stopping
    ? 'Останавливаю агента…'
    : permitting
    ? 'Агент ждёт разрешения'
    : asking
      ? 'Агент ждёт вашего ответа'
      : !lastShown || lastShown.type === 'user'
        ? [...events].reverse().find((event) => event.type === 'status')?.text || 'Запускаем агента…'
        : 'Агент работает…'

  const title =
    target.kind === 'create' ? 'Новый ИИ-агент' : session?.agent_title || (loadError ? 'Сессия' : 'Загружаем…')
  const placeholder =
    target.kind === 'create'
      ? planned
        ? 'Опишите задачу — агент составит по ней план, и план станет его инструкцией'
        : 'Опишите задачу агента — промпт сохранится как его инструкция'
      : running
        ? 'Агент работает — дождитесь ответа или остановите'
        : 'Продолжить диалог с агентом'

  return (
    <div className="agent-stage sess-page">
      <div className="agent-stage-bar">
        <button type="button" className="agent-back" onClick={onBack}>
          <ChevronLeftIcon size={16} />
          {backLabel}
        </button>
        <h2 title={title}>{title}</h2>
        {canRerun ? (
          <button
            type="button"
            className="agent-back sess-rerun"
            disabled={sending}
            title="Новый запуск по плану: в промпт уйдёт история этого прогона"
            onClick={() => void rerun()}
          >
            <PlayIcon size={14} />
            Запустить снова
          </button>
        ) : null}
        {session ? (
          <span className={`session-badge ${session.status}`}>
            {permitting ? 'Ждёт разрешения' : asking ? 'Ждёт ответа' : SESSION_STATUS[session.status]}
          </span>
        ) : null}
      </div>

      <div className="sess-split">
        <section className="sess-main" aria-label="Ход работы агента">
          <div className="sess-config">
            <span className="owner-agent-icon">
              <LayersIcon size={16} />
            </span>
            <span className="sess-config-text">
              <span className="sess-config-label">Конфигурация запуска</span>
              <strong>{config?.title || session?.config_title || configId || '—'}</strong>
            </span>
            {config?.model ? (
              <span className="sess-config-model">{modelLabel(config.model, config.model_params)}</span>
            ) : null}
            {session ? (
              <span className="sess-config-model">
                {session.ephemeral
                  ? 'Без сохранения'
                  : session.source === 'constructor'
                    ? 'Агент Constructor'
                    : 'Свой агент'}
              </span>
            ) : null}
          </div>

          {session && events.length ? (
            <ProgressBar
              running={running}
              text={workingText}
              waiting={Boolean(asking || permitting)}
              shown={progress}
              always={showProgress}
              onOnce={(show) => {
                setProgressOnce(show === showProgress ? null : show)
                stickRef.current = true
              }}
              onAlways={(show) => {
                setProgressOnce(null)
                onShowProgress(show)
                stickRef.current = true
              }}
            />
          ) : null}

          <div
            className="sess-scroll"
            ref={scrollRef}
            onScroll={(event) => {
              const box = event.currentTarget
              stickRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < STICK_TO_BOTTOM_PX
            }}
          >
            {target.kind === 'create' ? (
              <div className="agent-runs-empty sess-empty">
                <BotIcon size={24} />
                <strong>Опишите, что должен сделать агент</strong>
                <p>
                  {planned
                    ? 'Сначала агент в режиме plan составит план — он станет инструкцией и сразу выполнится.'
                    : `Промпт станет инструкцией агента. ${config?.description || ''}`}
                </p>
                {config && !config.runnable ? (
                  <p className="agent-error">{config.error || 'Эту конфигурацию нельзя запустить.'}</p>
                ) : null}
              </div>
            ) : session ? (
              <Feed
                sessionId={session.id}
                events={mainEvents}
                progress={progress}
                running={running}
                subagents={subagentLink}
                footer={
                  <>
                    {session.status === 'error' && session.error && !mainEvents.some((event) => event.type === 'error') ? (
                      <p className="sess-error">{session.error}</p>
                    ) : null}
                    {session.status === 'cancelled' ? <p className="sess-note">Агент остановлен.</p> : null}
                  </>
                }
              />
            ) : loadError ? (
              <p className="sess-error">{loadError}</p>
            ) : null}
          </div>

          {remote ? (
            <p className="sess-readonly">
              Запуск {remote.author ? `пользователя ${remote.author} ` : ''}
              {remote.host ? (
                <>
                  с компьютера <strong>{remote.host}</strong>
                </>
              ) : (
                'с другого компьютера'
              )}{' '}
              — только просмотр: диалог продолжают на том устройстве.
            </p>
          ) : permitting && sessionId ? (
            <ApprovalForm
              key={permitting.id}
              sessionId={sessionId}
              approval={permitting}
              onDecided={() => {
                answeredRef.current.add(permitting.id)
                setApproval(null)
                stickRef.current = true
                setWake((value) => value + 1)
              }}
              onStop={() => void stop()}
            />
          ) : asking && sessionId ? (
            <QuestionForm
              key={asking.id}
              sessionId={sessionId}
              question={asking}
              onAnswered={() => {
                answeredRef.current.add(asking.id)
                setQuestion(null)
                stickRef.current = true
                setWake((value) => value + 1)
              }}
              onStop={() => void stop()}
            />
          ) : (
          <form
            className={[
              'composer sess-composer',
              files.length ? 'has-files' : '',
              dragging ? 'dragging' : ''
            ].join(' ')}
            onSubmit={(event) => {
              event.preventDefault()
              void send()
            }}
            onDragOver={(event) => {
              if (!canAttach || !event.dataTransfer.types.includes('Files')) return
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
            }}
            onDrop={onDrop}
          >
            {files.length ? <ComposerFiles files={files} onRemove={removeFile} /> : null}
            {canAttach ? (
              <>
                <button
                  type="button"
                  className="icon-button"
                  title="Прикрепить фото или файл (можно вставить из буфера или перетащить)"
                  aria-label="Прикрепить фото или файл"
                  disabled={sending || files.length >= MAX_FILES}
                  onClick={() => pickerRef.current?.click()}
                >
                  <PaperclipIcon />
                </button>
                <input
                  ref={pickerRef}
                  type="file"
                  multiple
                  hidden
                  onChange={(event) => {
                    addFiles([...(event.target.files ?? [])])
                    event.target.value = ''
                  }}
                />
              </>
            ) : null}
            <textarea
              ref={inputRef}
              rows={1}
              value={prompt}
              placeholder={dragging ? 'Отпустите, чтобы прикрепить' : placeholder}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={onKeyDown}
              onPaste={(event) => {
                const pasted = [...event.clipboardData.files]
                if (!pasted.length || !canAttach) return
                event.preventDefault()
                addFiles(pasted)
              }}
            />
            {running ? (
              <button
                type="button"
                className="send sess-stop"
                disabled={stopping}
                onClick={() => void stop()}
                aria-label="Остановить агента"
              >
                <StopIcon size={16} />
              </button>
            ) : (
              <button
                type="submit"
                className="send"
                disabled={!canSend}
                aria-label={target.kind === 'create' ? 'Запустить агента' : 'Отправить'}
              >
                <ArrowUpIcon />
              </button>
            )}
          </form>
          )}
          {notice ? <p className="sess-notice">{notice}</p> : null}
        </section>
        <div className={openAgent ? 'sess-side subagent' : 'sess-side'}>
          <div className="sess-side-pane insights" inert={Boolean(openAgent)}>
            <AgentInsights sessionId={sessionId} running={running} turns={session?.turns ?? 0} remote={!!remote} />
          </div>
          {sessionId ? (
            <div className="sess-side-pane agent" inert={!openAgent}>
              {shownAgent ? (
                <SubagentPanel
                  sessionId={sessionId}
                  task={subagentTask}
                  events={subagentEvents}
                  running={running}
                  onBack={() => setOpenAgent(null)}
                />
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
