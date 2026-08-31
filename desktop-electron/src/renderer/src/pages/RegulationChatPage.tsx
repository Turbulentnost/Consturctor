import { useEffect, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import { ApiError, type AgentEvent, type RegulationCreationSession, type RegulationCreationTurn } from '../api/types'
import wallpaperUrl from '../assets/chat/wallpaper.png'
import programIcon from '../assets/logo.png'
import iconAttention from '@agent-icons/agent-attention-animated.svg?raw'
import iconCompleted from '@agent-icons/agent-completed-animated.svg?raw'
import iconWorking from '@agent-icons/agent-working-animated.svg?raw'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { extractInterviewAnswer, visibleAssistantText } from '../utils/regulationChat'

type AgentPhase = 'working' | 'attention' | 'completed'

interface RegulationChatPageProps {
  session: RegulationCreationSession
  onSessionChange: (session: RegulationCreationSession) => void
  onReady: (session: RegulationCreationSession) => void | Promise<void>
  onBack: () => void
  onBusyChange?: (busy: boolean) => void
}

interface PendingFile {
  path: string
  name: string
}

const DEFAULT_PLACEHOLDER = 'Опишите процесс или ответьте на вопрос ИИ...'
const EDIT_PLACEHOLDER = 'Измените предложенный вариант и отправьте...'
const FORCE_CREATE_PROMPT =
  'Создай регламент принудительно по текущей информации. ' +
  'Если каких-то данных не хватает, используй разумные типовые формулировки и явно отметь, что это предположение.'
const WORKING_STATUS = 'Готовлю вопрос...'
const COMPOSER_MIN_HEIGHT = 44
const COMPOSER_MAX_HEIGHT = 129

function fileCountLabel(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'файл'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'файла'
  return 'файлов'
}

function agentIcon(phase: AgentPhase): string {
  if (phase === 'working') return iconWorking
  if (phase === 'completed') return iconCompleted
  return iconAttention
}

function prepareAgentSvg(svg: string, prefix: string): string {
  const safe = prefix.replace(/[^a-zA-Z0-9_-]/g, '') || 'icon'
  return svg
    .replace(/\bid="([^"]+)"/g, `id="${safe}-$1"`)
    .replace(/url\(#([^)]+)\)/g, `url(#${safe}-$1)`)
    .replace(/\bhref="#([^"]+)"/g, `href="#${safe}-$1"`)
    .replace(/transform-origin:\s*[\d.]+px\s+[\d.]+px/g, 'transform-origin:center')
    .replace(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\n\s*\}/g, '')
    .replace('<style>', '<style>\n    * { transform-box: fill-box; }\n')
}

function AgentAvatar({
  phase,
  uid,
  frozen = false
}: {
  phase: AgentPhase
  uid: string
  frozen?: boolean
}): React.JSX.Element {
  if (frozen) {
    return (
      <div className="regchat-avatar program" aria-hidden>
        <img src={programIcon} alt="" />
      </div>
    )
  }
  return (
    <div
      className={`regchat-avatar ${phase}`}
      aria-hidden
      dangerouslySetInnerHTML={{ __html: prepareAgentSvg(agentIcon(phase), uid) }}
    />
  )
}

function quickAnswers(structured: Record<string, unknown>): string[] {
  const raw = structured.quickAnswers
  if (Array.isArray(raw)) return raw.map((x) => String(x)).filter(Boolean)
  return []
}

function safeDownloadName(name: string): string {
  const cleaned = name.replace(/[<>:"/\\|?*]+/g, ' ').replace(/\s+/g, ' ').trim()
  return (cleaned || 'Регламент.docx').slice(0, 120)
}

function resultFileName(session: RegulationCreationSession): string {
  const fromPath = session.resultDocumentPath.split(/[\\/]/).pop() || ''
  if (fromPath) return safeDownloadName(fromPath)
  const title = String(session.resultDocument?.title || '').trim()
  if (title) return safeDownloadName(`${title}.docx`)
  return 'Регламент.docx'
}

function attachmentsOf(structured: Record<string, unknown>): string[] {
  const raw = structured.attachments
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const rec = item as Record<string, unknown>
        return String(rec.shortName || rec.name || '')
      }
      return ''
    })
    .filter(Boolean)
}

function waitForRegulationSdk(
  runId: string,
  onEvent: (type: string, text: string) => void
): Promise<{ answer: string; agentId: string }> {
  return new Promise((resolve, reject) => {
    const off = agentClient.onEvent((event: AgentEvent) => {
      if (event.runId && event.runId !== runId) return
      if (event.type === 'event' && event.payload) {
        const payload = event.payload
        const text = String(payload.text || payload.message || '')
        const kind = String(payload.type || '')
        if (text) onEvent(kind, text)
      }
      if (event.type === 'result') {
        off()
        resolve({
          answer: String(event.answer || ''),
          agentId: String(event.agentId || '')
        })
        return
      }
      if (event.type === 'error') {
        const recovered = extractInterviewAnswer(event.message || '')
        off()
        if (recovered) {
          resolve({ answer: recovered, agentId: '' })
          return
        }
        reject(new Error(event.message || 'Ошибка локального агента'))
      }
    })
  })
}

function extractProposal(message: string): string {
  const text = (message || '').trim()
  if (!text) return ''
  const match = text.match(
    /Предлагаю\s+так\s*:\s*([\s\S]*?)(?:\n\s*\n\s*Оставить это или переделать\s*\??\s*$|$)/i
  )
  if (match) return match[1].replace(/\s+/g, ' ').trim()
  const parts = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length >= 2) {
    for (const part of parts.slice(1)) {
      const lower = part.toLowerCase()
      if (lower.startsWith('оставить это или переделать')) continue
      if (lower.startsWith('вопрос')) continue
      const cleaned = part.replace(/^Предлагаю\s+так\s*:\s*/i, '').trim()
      if (cleaned) return cleaned.replace(/\s+/g, ' ').trim()
    }
  }
  return ''
}

export function RegulationChatPage({
  session,
  onSessionChange,
  onReady,
  onBack,
  onBusyChange
}: RegulationChatPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [placeholder, setPlaceholder] = useState(DEFAULT_PLACEHOLDER)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [savedNote, setSavedNote] = useState('')
  const [attachments, setAttachments] = useState<PendingFile[]>([])
  const [filesOpen, setFilesOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const resumeKeyRef = useRef('')

  useEffect(() => {
    setError('')
    setSavedNote('')
    setAttachments([])
    setFilesOpen(false)
    setInput('')
    setPlaceholder(DEFAULT_PLACEHOLDER)
  }, [session.draftId])

  useEffect(() => {
    onBusyChange?.(busy)
  }, [busy, onBusyChange])

  useEffect(() => {
    if (!pinnedRef.current) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [session.messages.length, busy])

  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = '0px'
    node.style.overflowY = 'hidden'
    const content = node.scrollHeight
    node.style.height = `${Math.min(Math.max(content, COMPOSER_MIN_HEIGHT), COMPOSER_MAX_HEIGHT)}px`
    node.style.overflowY = content > COMPOSER_MAX_HEIGHT ? 'auto' : 'hidden'
  }, [input])

  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  const hasUserMessage = session.messages.some((m) => m.role === 'user')
  const resultName = resultFileName(session)
  const phase: AgentPhase = ready ? 'completed' : busy ? 'working' : 'attention'

  async function downloadResult(): Promise<void> {
    if (!ready) return
    setError('')
    setSavedNote('')
    try {
      const res = await window.api.download({
        url: `/api/v1/regulation-creation/sessions/${session.draftId}/document`,
        defaultName: resultName,
        token: api.getToken()
      })
      if (res.canceled) return
      if (!res.ok) {
        setError(res.error || 'Не удалось скачать файл регламента')
        return
      }
      setSavedNote(res.path ? `Файл сохранён: ${res.path}` : 'Файл сохранён')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скачать файл регламента')
    }
  }

  async function continueReady(): Promise<void> {
    setError('')
    try {
      await onReady(session)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Не удалось открыть регламент')
    }
  }

  function onScroll(): void {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    pinnedRef.current = distance < 80
  }

  async function send(text: string, files: PendingFile[]): Promise<void> {
    const message = text.trim()
    if ((!message && files.length === 0) || busy) return
    setInput('')
    setPlaceholder(DEFAULT_PLACEHOLDER)
    setError('')
    setBusy(true)
    pinnedRef.current = true
    const optimistic: RegulationCreationSession = {
      ...session,
      status: 'generating',
      messages: [
        ...session.messages,
        {
          messageId: 'local-pending',
          draftId: session.draftId,
          role: 'user',
          content: message || (files.length ? `Приложены файлы: ${files.map((f) => f.name).join(', ')}` : ''),
          structured: files.length ? { attachments: files.map((f) => ({ name: f.name })) } : {}
        }
      ]
    }
    onSessionChange(optimistic)
    let persisted = false
    try {
      const filePaths = files.map((f) => f.path)
      const onStreamEvent = (type: string, text: string): void => {
        if (type === 'error' && text) setError(text)
      }
      if (window.agent?.start) {
        let turn: RegulationCreationTurn
        try {
          turn = await api.persistRegulationCreationTurn(session.draftId, message, filePaths)
        } catch (err) {
          if (!(err instanceof ApiError) || (err.status !== 404 && err.status !== 405)) {
            throw err
          }
          const updated = await api.streamRegulationCreationMessage(
            session.draftId,
            message,
            filePaths,
            (event) => onStreamEvent(event.type, event.text || event.message || '')
          )
          persisted = true
          setAttachments([])
          setFilesOpen(false)
          onSessionChange(updated)
          return
        }
        persisted = true
        setAttachments([])
        setFilesOpen(false)
        onSessionChange(turn.session)
        await runSdkAndApply(turn)
      } else {
        const updated = await api.streamRegulationCreationMessage(
          session.draftId,
          message,
          filePaths,
          (event) => onStreamEvent(event.type, event.text || event.message || '')
        )
        persisted = true
        setAttachments([])
        setFilesOpen(false)
        onSessionChange(updated)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка отправки сообщения')
      if (persisted) {
        try {
          const latest = await api.getRegulationCreationSession(session.draftId)
          onSessionChange(latest)
        } catch {
          /* keep the last known session, including the user files */
        }
      } else {
        onSessionChange({ ...session, status: 'idle' })
      }
    } finally {
      setBusy(false)
    }
  }

  function handleQuick(answer: string, sourceText: string): void {
    if (/^передел/i.test(answer.trim())) {
      const proposal = extractProposal(sourceText)
      setInput(proposal)
      setPlaceholder(EDIT_PLACEHOLDER)
      requestAnimationFrame(() => {
        const el = textareaRef.current
        if (el) {
          el.focus()
          el.setSelectionRange(el.value.length, el.value.length)
        }
      })
      return
    }
    void send(answer, [])
  }

  async function pickFiles(): Promise<void> {
    if (busy) return
    const paths = await window.api.openFile({
      title: 'Выберите файлы для регламента',
      filters: [{ name: 'Документы', extensions: ['docx', 'pdf', 'md', 'txt'] }],
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    setAttachments((prev) => {
      const seen = new Set(prev.map((f) => f.path))
      const next = [...prev]
      for (const p of paths) {
        if (seen.has(p)) continue
        next.push({ path: p, name: p.split(/[\\/]/).pop() || p })
      }
      return next
    })
    setFilesOpen(true)
  }

  function removeAttachment(path: string): void {
    setAttachments((prev) => {
      const next = prev.filter((f) => f.path !== path)
      if (next.length === 0) setFilesOpen(false)
      return next
    })
  }

  const visible = session.messages.filter((m) => m.role === 'assistant' || m.role === 'user')
  const lastAssistantId = [...visible].reverse().find((item) => item.role === 'assistant')?.messageId || ''
  const lastVisible = visible[visible.length - 1]
  const pendingUserId =
    lastVisible?.role === 'user' && lastVisible.messageId !== 'local-pending'
      ? lastVisible.messageId
      : ''

  async function runSdkAndApply(turn: RegulationCreationTurn): Promise<void> {
    const runId = agentClient.start({
      kind: 'regulation_creation',
      draftId: session.draftId,
      prompt: turn.sdkPrompt,
      rules: turn.sdkRules,
      interview: turn.interview,
      resumeAgentId: turn.sdkAgentId || session.sdkAgentId
    })
    const sdk = await waitForRegulationSdk(runId, (type, text) => {
      if (type === 'error' && text) setError(text)
    })
    const answer = extractInterviewAnswer(sdk.answer) || sdk.answer
    const updated = await api.applyRegulationCreationReply(session.draftId, answer, {
      sdkAgentId: sdk.agentId || turn.sdkAgentId,
      forceCreate: turn.forceCreate
    })
    onSessionChange(updated)
  }

  async function continuePendingTurn(): Promise<void> {
    if (busy || ready) return
    setError('')
    setBusy(true)
    pinnedRef.current = true
    try {
      const turn = await api.peekRegulationCreationTurn(session.draftId)
      await runSdkAndApply(turn)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось получить вопрос ИИ')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (busy || ready || !pendingUserId || !window.agent?.start) return
    const key = `${session.draftId}:${pendingUserId}`
    if (resumeKeyRef.current === key) return
    resumeKeyRef.current = key
    void continuePendingTurn()
  }, [session.draftId, pendingUserId, busy, ready])

  return (
    <div className="regchat-page">
      <div className="regchat-head">
        <div className="regchat-head-top">
          <button className="btn-ghost" onClick={onBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 24 }}>
            Создание регламента
          </h1>
          <button
            className="regchat-force"
            onClick={() => void send(FORCE_CREATE_PROMPT, [])}
            disabled={!hasUserMessage || busy}
          >
            Создать принудительно
          </button>
        </div>
        <div className="regchat-subtitle">
          Ответьте на вопросы, и ИИ подготовит регламент в стиле ваших документов
        </div>
      </div>

      <div className="regchat-stage">
        <div
          className="regchat-page-bg"
          style={{ backgroundImage: `url(${wallpaperUrl})` }}
          aria-hidden
        />
        <div className="regchat-feed-wrap">
            <div className="regchat-scroll" ref={scrollRef} onScroll={onScroll}>
              <div className="regchat-column">
              {visible.length === 0 && !busy && (
                <div className="regchat-hint">
                  ИИ задаст несколько вопросов, чтобы собрать регламент. Опишите процесс, который нужно
                  автоматизировать, или приложите файлы.
                </div>
              )}
              {visible.map((m, index) => {
                const isUser = m.role === 'user'
                const names = attachmentsOf(m.structured)
                const quicks = quickAnswers(m.structured)
                const isCurrentStage =
                  !isUser &&
                  !busy &&
                  !ready &&
                  Boolean(lastAssistantId) &&
                  m.messageId === lastAssistantId
                return (
                  <div key={m.messageId || index} className={isUser ? 'regchat-row user' : 'regchat-row ai'}>
                    {!isUser && (
                      <AgentAvatar
                        phase={phase}
                        uid={`msg-${m.messageId || index}`}
                        frozen={!isCurrentStage}
                      />
                    )}
                    <div className="regchat-bubble-col">
                      <div className={isUser ? 'regchat-bubble user' : 'regchat-bubble ai'}>
                        {m.content && visibleAssistantText(m.content) ? (
                          <div className="regchat-bubble-text">
                            {isUser ? m.content : visibleAssistantText(m.content)}
                          </div>
                        ) : null}
                        {names.length > 0 && (
                          <div className="regchat-attach-list">
                            {names.map((n, i) => (
                              <span key={i} className="regchat-file-row">
                                <img className="regchat-file-icon" src={fileTypeIconSrc(n)} alt="" />
                                <span className="regchat-file-name" title={n}>
                                  {n}
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      {!isUser && quicks.length > 0 && !busy && (
                        <div className="regchat-quick-row">
                          {quicks.map((qa) => (
                            <button
                              key={qa}
                              className="regchat-quick-chip"
                              onClick={() => handleQuick(qa, m.content)}
                            >
                              {qa}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
              {busy && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="working" uid="working" />
                  <div className="regchat-bubble-col">
                    <div className="regchat-think">
                      <div className="regchat-think-head">
                        <span>Готовит вопрос</span>
                      </div>
                    </div>
                    <div className="regchat-status">{WORKING_STATUS}</div>
                  </div>
                </div>
              )}
              {ready && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="completed" uid="completed" />
                  <div className="regchat-bubble-col">
                    <div className="regchat-doc-card">
                      <div className="regchat-file-row">
                        <img className="regchat-file-icon" src={fileTypeIconSrc(resultName)} alt="" />
                        <span className="regchat-file-name" title={resultName}>
                          {resultName}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="regchat-doc-download"
                        onClick={() => void downloadResult()}
                      >
                        Скачать
                      </button>
                    </div>
                  </div>
                </div>
              )}
              </div>
            </div>
          </div>

          {error && (
            <div className="status-line" style={{ color: 'var(--error)' }}>
              {error}
            </div>
          )}
          {savedNote && !error && (
            <div className="status-line">{savedNote}</div>
          )}

          {ready && (
            <div className="chat-ready">
              <div>Регламент готов. Файл можно скачать в чате или перейти к проверке.</div>
              <button
                className="btn-primary"
                style={{ maxWidth: 260 }}
                onClick={() => void continueReady()}
              >
                Продолжить
              </button>
            </div>
          )}

          {!ready && (
            <div className="regchat-composer">
              <div className="regchat-composer-box">
                {attachments.length > 0 && (
                  <div className="regchat-files">
                    <button
                      type="button"
                      className="regchat-files-toggle"
                      onClick={() => setFilesOpen((open) => !open)}
                    >
                      <span>{filesOpen ? '\u25BE' : '\u25B8'}</span>
                      <span>
                        {attachments.length} {fileCountLabel(attachments.length)}
                      </span>
                    </button>
                    {filesOpen ? (
                      <div className="regchat-pending">
                        {attachments.map((f) => (
                          <span key={f.path} className="regchat-file-row pending">
                            <img className="regchat-file-icon" src={fileTypeIconSrc(f.name)} alt="" />
                            <span className="regchat-file-name" title={f.name}>
                              {f.name}
                            </span>
                            <button
                              className="regchat-pending-remove"
                              onClick={() => removeAttachment(f.path)}
                              disabled={busy}
                              aria-label="Убрать файл"
                            >
                              {'\u00D7'}
                            </button>
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
            <div className="regchat-composer-input">
              <textarea
                ref={textareaRef}
                value={input}
                placeholder={placeholder}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void send(input, attachments)
                  }
                }}
                disabled={busy}
                rows={1}
              />
              <div className="regchat-composer-tools">
                <button
                  className="regchat-tool-btn"
                  onClick={() => void pickFiles()}
                  disabled={busy}
                  title="Приложить файлы"
                  aria-label="Приложить файлы"
                  type="button"
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                    <path
                      d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <button
                  className="regchat-send-btn"
                  onClick={() => void send(input, attachments)}
                  disabled={busy || (!input.trim() && attachments.length === 0)}
                  title="Отправить"
                  aria-label="Отправить"
                  type="button"
                >
                  <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                    <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>
            </div>
              </div>
            </div>
          )}
      </div>
    </div>
  )
}
