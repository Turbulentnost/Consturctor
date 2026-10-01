import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type PositionKpiBuildSession } from '../api/types'
import { AgentFeed } from '../components/agentfeed'
import { useAgentSession } from '../components/agentfeed/useAgentSession'
import { isAskQuestion } from '../components/agentfeed/questionArgs'
import type { FeedItem, ToolItem } from '../components/agentfeed/types'
import wallpaperUrl from '../assets/chat/wallpaper.png'
import logoUrl from '../assets/logo.png'

const STAGES = [
  { id: 'clarifying', label: 'Источники данных' },
  { id: 'coding', label: 'Код и тесты' },
  { id: 'connected', label: 'Подключено' }
] as const

const STAGE_RANK: Record<string, number> = {
  clarifying: 0,
  coding: 1,
  testing: 1,
  connected: 2,
  error: 0
}

function attachmentsOf(structured: Record<string, unknown>): string[] {
  const raw = structured.attachments
  if (!Array.isArray(raw)) return []
  return raw.map((item) => String(item || '')).filter(Boolean)
}

function quickAnswers(structured: Record<string, unknown>): string[] {
  const raw = structured.quickAnswers
  if (!Array.isArray(raw)) return []
  return raw.map((item) => String(item || '')).filter(Boolean)
}

function lastTool(items: FeedItem[]): ToolItem | undefined {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i]
    if (item.kind === 'tool') return item
  }
  return undefined
}

function isKpiNarration(text: string): boolean {
  const value = (text || '').trim()
  if (!value || value.length > 900) return false
  const folded = value.toLowerCase()
  if (/вес\s*\d|score_|generated\//.test(folded)) return false
  return /сначала прочитаю|параллельно посмотрю|office\.read_file|посмотрю как в проекте|посмотрю контракт|проверяю файлы в рабочей папке/.test(
    folded
  )
}

function isNoiseStatus(text: string): boolean {
  const value = (text || '').trim()
  if (!value) return true
  if (value.length > 90) return true
  if (/^инструменты constructor/i.test(value)) return true
  if (/askQuestion|web_search|outlook\.|onec\./.test(value) && value.includes(',')) return true
  return false
}

function kpiRowsFromText(text: string): { name: string; weight: string }[] {
  const rows: { name: string; weight: string }[] = []
  for (const line of (text || '').split('\n')) {
    const match = line.match(
      /^\s*(?:\d+[\).]|[-*•])\s*(.+?)(?:\s*[—\-–]\s*|\s+)(?:вес\s*)?(\d{1,3})\s*%/i
    )
    if (!match) continue
    const name = match[1].replace(/[—\-–]\s*$/, '').trim()
    if (name.length < 3) continue
    rows.push({ name, weight: match[2] })
  }
  return rows
}

function isKpiListText(text: string): boolean {
  return kpiRowsFromText(text).length >= 2
}

function dedupeKpiFeed(items: FeedItem[]): FeedItem[] {
  let seenList = false
  const out: FeedItem[] = []
  for (const item of items) {
    if (item.kind === 'tool' && isAskQuestion(item.tool)) continue
    const text = item.kind === 'message' || item.kind === 'result' ? item.text : ''
    if (text && isKpiListText(text)) {
      if (seenList) continue
      seenList = true
    }
    out.push(item)
  }
  return out
}

function liveBuildBanner(
  items: FeedItem[],
  opts: { busy: boolean; running: boolean; status: string; waiting: boolean }
): { text: string; kind: 'run' | 'wait' } | null {
  if (opts.waiting) return { text: 'Нужен ваш ответ', kind: 'wait' }
  if (opts.busy) return { text: 'Готовлю задание агенту…', kind: 'run' }
  if (!opts.running) return null
  if (/проверяю тесты|тесты прошли|подключаю kpi|тесты не прошли|пишу модул/i.test(opts.status)) {
    return { text: opts.status, kind: 'run' }
  }
  const live = [...items].reverse().find((item): item is ToolItem => item.kind === 'tool' && !item.done)
  const liveTool = (live?.tool || '').toLowerCase()
  if (liveTool.startsWith('onec.') || liveTool.startsWith('outlook.')) {
    return { text: 'Сверяю источник на живых данных…', kind: 'run' }
  }
  if (live) return { text: 'Агент работает…', kind: 'run' }
  const done = lastTool(items)
  const tool = (done?.tool || '').toLowerCase()
  if (tool.includes('write') || tool === 'code.write_python') return { text: 'Пишу модуль KPI…', kind: 'run' }
  if (tool.includes('shell') || tool === 'code.run_python') return { text: 'Прогоняю тесты…', kind: 'run' }
  if (!isNoiseStatus(opts.status)) return { text: opts.status, kind: 'run' }
  return { text: 'Пишу модули расчёта…', kind: 'run' }
}

export function PositionKpiBuildPage({
  position,
  buildId,
  onReady,
  onBack
}: {
  position: string
  buildId?: string
  onReady: () => void
  onBack: () => void
}): React.JSX.Element {
  const [session, setSession] = useState<PositionKpiBuildSession | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const startedSdk = useRef('')
  const sessionRef = useRef<PositionKpiBuildSession | null>(null)
  const agent = useAgentSession({
    onResult: () => {
      const id = sessionRef.current?.buildId
      if (!id) return
      void api.getPositionKpiBuild(id).then(setSession).catch(() => undefined)
    },
    onError: (message) => setError(message)
  })
  sessionRef.current = session

  useEffect(() => {
    let alive = true
    setBusy(true)
    const boot = buildId
      ? api.getPositionKpiBuild(buildId)
      : api.startPositionKpiBuild(position)
    void boot
      .then((next) => {
        if (alive) setSession(next)
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof ApiError ? err.message : 'Не удалось открыть чат методики')
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [buildId, position])

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [session?.messages, agent.items, busy, agent.running])

  const canStartSdk =
    Boolean(session?.buildId) &&
    Boolean(session?.sdkPrompt) &&
    session?.status !== 'connected' &&
    session?.status !== 'error'

  useEffect(() => {
    if (!canStartSdk || !session) return
    if (startedSdk.current === session.buildId) return
    if (agent.running) return
    startedSdk.current = session.buildId
    agent.start({
      kind: 'kpi_module',
      buildId: session.buildId,
      workflowId: `kpi-build-${session.buildId}`,
      prompt: session.sdkPrompt,
      filePaths: []
    })
  }, [agent, canStartSdk, session])

  useEffect(() => {
    const question = agent.pendingQuestion
    if (!question) return
    const blob = `${question.question} ${question.options.join(' ')}`.toLowerCase()
    if (!/когда запускать|триггер агента|каденс планёр|outlook не является/.test(blob)) return
    agent.answer(
      question.requestId,
      'Конструктор вызывается один раз. Модули KPI сохранить на бэкенд. Расписание не нужно.'
    )
  }, [agent.answer, agent.pendingQuestion])

  function continueBuild(): void {
    if (!session?.buildId || agent.running) return
    agent.start({
      kind: 'kpi_module',
      buildId: session.buildId,
      workflowId: `kpi-build-${session.buildId}`,
      prompt: session.sdkPrompt,
      filePaths: []
    })
  }

  async function send(message: string): Promise<void> {
    if (!session?.buildId) return
    const text = message.trim()
    if (!text) return
    setBusy(true)
    setError('')
    setInput('')
    try {
      let next = session
      const pending = agent.pendingQuestion
      if (pending && text) {
        agent.answer(pending.requestId, text)
      }
      if (text && !pending) {
        next = await api.sendPositionKpiBuildTurn(session.buildId, text)
        agent.pushUserMessage(text)
      }
      setSession(next)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Не удалось отправить')
    } finally {
      setBusy(false)
    }
  }

  const rank = STAGE_RANK[session?.status || 'clarifying'] ?? 0
  const ready = session?.status === 'connected'
  const visible = (session?.messages || []).filter((item) => {
    if (item.role !== 'assistant' && item.role !== 'user') return false
    if (item.structured?.stage === 'sdk_finish') return false
    if (item.structured?.stage === 'kickoff') return true
    if (item.role === 'assistant' && isKpiListText(item.content)) return false
    return true
  })
  const waiting = Boolean(agent.pendingQuestion || agent.pendingHitl)
  const feedItems = dedupeKpiFeed(
    agent.items.filter((item) => item.kind !== 'message' || !isKpiNarration(item.text))
  )
  const banner = liveBuildBanner(agent.items, {
    busy,
    running: agent.running,
    status: agent.status,
    waiting
  })
  const composerLocked = Boolean(busy || (agent.running && !waiting))
  const positionMissing = (session?.messages || []).some(
    (item) => item.structured?.stage === 'not_found'
  )
  const incomplete = Boolean(
    !ready &&
      !positionMissing &&
      !agent.running &&
      !waiting &&
      !busy &&
      session
  )

  return (
    <div className="regchat-page kpi-build-page">
      <div className="regchat-head">
        <div className="regchat-head-top">
          <button className="btn-ghost" onClick={onBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 24 }}>
            Модули расчёта KPI
          </h1>
        </div>
        <div className="regchat-subtitle">
          {[session?.subjectFio, session?.position || position].filter(Boolean).join(' · ') ||
            'Методика Finance'}
        </div>
        <ol className="kpi-build-stages">
          {STAGES.map((stage, index) => (
            <li key={stage.id} className={index <= rank ? 'is-active' : ''}>
              {stage.label}
            </li>
          ))}
        </ol>
      </div>

      <div className="regchat-feed-wrap">
        <div className="regchat-feed-bg" style={{ backgroundImage: `url(${wallpaperUrl})` }} aria-hidden />
        <div className="regchat-scroll" ref={scrollRef}>
          {visible.length === 0 && !busy ? (
            <div className="regchat-hint">
              KPI утверждены Finance. Агент сразу пишет модули расчёта: по одному на показатель,
              с тестами, и подключает их к ежедневному подсчёту.
            </div>
          ) : null}
          {visible.map((message) => {
            const isUser = message.role === 'user'
            const names = attachmentsOf(message.structured)
            const quicks = quickAnswers(message.structured)
            return (
              <div key={message.messageId} className={isUser ? 'regchat-row user' : 'regchat-row ai'}>
                {!isUser ? (
                  <div className="regchat-avatar">
                    <img src={logoUrl} alt="" />
                  </div>
                ) : null}
                <div className="regchat-bubble-col">
                  <div className={isUser ? 'regchat-bubble user' : 'regchat-bubble ai'}>
                    {message.content ? <div className="regchat-bubble-text">{message.content}</div> : null}
                    {names.length ? (
                      <div className="regchat-attach-list">
                        {names.map((name) => (
                          <span key={name} className="regchat-attach-chip">
                            {name}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  {!isUser && quicks.length && !busy
                    ? quicks.map((answer) => (
                        <button
                          key={answer}
                          className="regchat-quick-chip"
                          onClick={() => void send(answer)}
                        >
                          {answer}
                        </button>
                      ))
                    : null}
                </div>
              </div>
            )
          })}
          <AgentFeed
            items={feedItems}
            status={agent.status}
            running={agent.running}
            pendingQuestion={agent.pendingQuestion}
            pendingHitl={agent.pendingHitl}
            emptyHint=""
            allowQuestionFiles={false}
            hideRunningStatus
            onAnswer={(requestId, value, filePaths) => agent.answer(requestId, value, filePaths)}
            onHitl={agent.respondHitl}
            onSkip={agent.skip}
          />
          {banner ? (
            <div className="regchat-row ai">
              <div className="regchat-avatar">
                <img src={logoUrl} alt="" />
              </div>
              <div className={`kpi-build-live${banner.kind === 'wait' ? ' is-wait' : ''}`}>
                {banner.kind === 'run' ? <span className="agent-feed-spinner" /> : null}
                <span>{banner.text}</span>
              </div>
            </div>
          ) : null}
          {incomplete ? (
            <div className="regchat-row ai">
              <div className="regchat-avatar">
                <img src={logoUrl} alt="" />
              </div>
              <div className="kpi-build-live is-wait">
                <span>Модуль уже в рабочей папке. Продолжить — прогоним тесты и подключим KPI.</span>
                <button className="regchat-quick-chip" type="button" onClick={continueBuild}>
                  Продолжить
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="status-line" style={{ color: 'var(--error)' }}>
          {error}
        </div>
      ) : null}

      {ready ? (
        <div className="chat-ready">
          <div>Методика подключена. Можно вернуться к KPI должности.</div>
          <button className="btn-primary" style={{ maxWidth: 260 }} onClick={onReady}>
            К показателям
          </button>
        </div>
      ) : (
        <div className="regchat-composer">
          <div className="regchat-input-row">
            <textarea
              value={input}
              placeholder={
                waiting
                  ? 'Выберите вариант выше или напишите ответ…'
                  : 'Ответьте на вопрос агента…'
              }
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  if (!composerLocked) void send(input)
                }
              }}
              disabled={composerLocked}
              rows={2}
            />
            <button
              className="btn-primary"
              style={{ width: 120 }}
              onClick={() => void send(input)}
              disabled={composerLocked}
            >
              Отправить
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
