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
  { id: 'awaiting_file', label: 'Документ' },
  { id: 'extracting', label: 'Разбор KPI' },
  { id: 'clarifying', label: 'Уточнения' },
  { id: 'coding', label: 'Код и тесты' },
  { id: 'connected', label: 'Подключено' }
] as const

const STAGE_RANK: Record<string, number> = {
  awaiting_file: 0,
  extracting: 1,
  clarifying: 2,
  coding: 3,
  testing: 3,
  connected: 4,
  error: 2
}

interface PendingFile {
  path: string
  name: string
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
  if (opts.busy) return { text: 'Загружаю методику…', kind: 'run' }
  if (!opts.running) return null
  if (/проверяю тесты|тесты прошли|подключаю kpi|тесты не прошли/i.test(opts.status)) {
    return { text: opts.status, kind: 'run' }
  }
  const live = [...items].reverse().find((item): item is ToolItem => item.kind === 'tool' && !item.done)
  if (live?.tool === 'office.read_file') return { text: 'Прикладываю положение в чат…', kind: 'run' }
  if (live?.tool === 'excel.list_files') return { text: 'Смотрю файлы агента…', kind: 'run' }
  if (live) return { text: 'Агент работает…', kind: 'run' }
  const done = lastTool(items)
  const tool = (done?.tool || '').toLowerCase()
  if (tool === 'office.read_file') return { text: 'Выписываю KPI должности…', kind: 'run' }
  if (tool === 'excel.list_files') return { text: 'Разбираю методику…', kind: 'run' }
  if (tool.includes('write') || tool === 'code.write_python') return { text: 'Пишу модуль KPI…', kind: 'run' }
  if (tool.includes('shell') || tool === 'code.run_python') return { text: 'Прогоняю тесты…', kind: 'run' }
  if (/положение (в чате|приложено)|прикладываю положение/i.test(opts.status)) {
    return { text: 'Выписываю KPI должности…', kind: 'run' }
  }
  if (!isNoiseStatus(opts.status)) return { text: opts.status, kind: 'run' }
  return { text: 'Выписываю KPI должности…', kind: 'run' }
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
  const [attachments, setAttachments] = useState<PendingFile[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const startedSdk = useRef('')
  const lastFilePaths = useRef<string[]>([])
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

  const needsChoice = Boolean(session?.extracted?.needs_position_choice)
  const attachedHere = lastFilePaths.current.length > 0
  const canStartSdk =
    Boolean(session?.buildId) &&
    attachedHere &&
    !needsChoice &&
    session?.status !== 'connected' &&
    session?.status !== 'awaiting_file'

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
      filePaths: lastFilePaths.current
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
      filePaths: lastFilePaths.current
    })
  }

  async function pickFiles(): Promise<void> {
    const paths = await window.api.openFile({
      title: 'Выберите методику расчёта',
      filters: [{ name: 'Документы', extensions: ['pdf', 'docx', 'xlsx', 'md', 'txt'] }],
      properties: ['openFile', 'multiSelections']
    })
    setAttachments((prev) => {
      const seen = new Set(prev.map((item) => item.path))
      const next = [...prev]
      for (const path of paths) {
        if (seen.has(path)) continue
        next.push({ path, name: path.split(/[\\/]/).pop() || path })
      }
      return next
    })
  }

  async function send(message: string, files: PendingFile[]): Promise<void> {
    if (!session?.buildId) return
    const text = message.trim()
    if (!text && !files.length) return
    setBusy(true)
    setError('')
    setInput('')
    setAttachments([])
    try {
      let next = session
      if (files.length) {
        lastFilePaths.current = files.map((item) => item.path)
        next = await api.uploadPositionKpiBuildFiles(
          session.buildId,
          files.map((item) => item.path)
        )
      }
      const pending = agent.pendingQuestion
      if (pending && (text || files.length)) {
        agent.answer(pending.requestId, text || 'файл', files.map((item) => item.path))
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

  const rank = STAGE_RANK[session?.status || 'awaiting_file'] ?? 0
  const ready = session?.status === 'connected'
  const visible = (session?.messages || []).filter((item) => {
    if (item.role !== 'assistant' && item.role !== 'user') return false
    if (item.structured?.stage === 'sdk_finish') return false
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
      session &&
      session.status !== 'awaiting_file'
  )

  return (
    <div className="regchat-page kpi-build-page">
      <div className="regchat-head">
        <div className="regchat-head-top">
          <button className="btn-ghost" onClick={onBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 24 }}>
            Методика KPI
          </h1>
        </div>
        <div className="regchat-subtitle">
          {session?.position || position
            ? `Должность: ${session?.position || position}`
            : 'Загрузите положение о мотивации'}
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
              Приложите PDF с системой мотивации. Прочитаем без обложки, найдём KPI вашей
              должности, уточним план и факт, затем сохраним модули в kpi.
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
                          onClick={() => void send(answer, [])}
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
            embed
            allowQuestionFiles
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
          {attachments.length ? (
            <div className="regchat-pending">
              {attachments.map((file) => (
                <span key={file.path} className="regchat-pending-chip">
                  {file.name}
                  <button
                    className="regchat-pending-remove"
                    onClick={() => setAttachments((prev) => prev.filter((item) => item.path !== file.path))}
                    aria-label="Убрать файл"
                  >
                    {'\u00D7'}
                  </button>
                </span>
              ))}
            </div>
          ) : null}
          <div className="regchat-input-row">
            <button
              className="regchat-attach-btn"
              onClick={() => void pickFiles()}
              disabled={composerLocked}
              title="Приложить файлы"
            >
              {'\uD83D\uDCCE'}
            </button>
            <textarea
              value={input}
              placeholder={
                waiting
                  ? 'Выберите вариант выше или напишите ответ…'
                  : 'Ответьте на вопрос или приложите PDF методики…'
              }
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  if (!composerLocked) void send(input, attachments)
                }
              }}
              disabled={composerLocked}
              rows={2}
            />
            <button
              className="btn-primary"
              style={{ width: 120 }}
              onClick={() => void send(input, attachments)}
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
