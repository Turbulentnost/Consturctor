import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type RegulationCreationSession } from '../api/types'
import wallpaperUrl from '../assets/chat/wallpaper.png'
import logoUrl from '../assets/logo.png'

interface RegulationChatPageProps {
  session: RegulationCreationSession
  onSessionChange: (session: RegulationCreationSession) => void
  onReady: (session: RegulationCreationSession) => void
  onBack: () => void
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

function quickAnswers(structured: Record<string, unknown>): string[] {
  const raw = structured.quickAnswers
  if (Array.isArray(raw)) return raw.map((x) => String(x)).filter(Boolean)
  return []
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
  onBack
}: RegulationChatPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [placeholder, setPlaceholder] = useState(DEFAULT_PLACEHOLDER)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [attachments, setAttachments] = useState<PendingFile[]>([])
  const [thinking, setThinking] = useState('')
  const [status, setStatus] = useState('')
  const [thinkOpen, setThinkOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!pinnedRef.current) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [session.messages.length, busy, thinking, status])

  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  const hasUserMessage = session.messages.some((m) => m.role === 'user')

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
    setThinking('')
    setStatus('')
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
          content: message,
          structured: files.length ? { attachments: files.map((f) => ({ name: f.name })) } : {}
        }
      ]
    }
    onSessionChange(optimistic)
    setAttachments([])
    try {
      const updated = await api.streamRegulationCreationMessage(
        session.draftId,
        message,
        files.map((f) => f.path),
        (event) => {
          if (event.type === 'thinking' && event.text) {
            setThinking((prev) => prev + event.text)
          } else if (event.type === 'assistant' && event.text) {
            setStatus(event.text)
          } else if (event.type === 'status') {
            setStatus(event.text || 'Готовлю ответ...')
          } else if (event.type === 'error' && event.text) {
            setError(event.text)
          }
        }
      )
      onSessionChange(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка отправки сообщения')
      onSessionChange({ ...session, status: 'idle' })
    } finally {
      setBusy(false)
      setThinking('')
      setStatus('')
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
      filters: [{ name: 'Документы', extensions: ['docx', 'doc', 'pdf', 'md', 'txt'] }],
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
  }

  function removeAttachment(path: string): void {
    setAttachments((prev) => prev.filter((f) => f.path !== path))
  }

  const visible = session.messages.filter((m) => m.role === 'assistant' || m.role === 'user')

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

      <div className="regchat-feed-wrap">
        <div
          className="regchat-feed-bg"
          style={{ backgroundImage: `url(${wallpaperUrl})` }}
          aria-hidden
        />
        <div className="regchat-scroll" ref={scrollRef} onScroll={onScroll}>
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
            return (
              <div key={m.messageId || index} className={isUser ? 'regchat-row user' : 'regchat-row ai'}>
                {!isUser && (
                  <div className="regchat-avatar">
                    <img src={logoUrl} alt="" />
                  </div>
                )}
                <div className="regchat-bubble-col">
                  <div className={isUser ? 'regchat-bubble user' : 'regchat-bubble ai'}>
                    {m.content && <div className="regchat-bubble-text">{m.content}</div>}
                    {names.length > 0 && (
                      <div className="regchat-attach-list">
                        {names.map((n, i) => (
                          <span key={i} className="regchat-attach-chip">
                            {'\uD83D\uDCCE'} {n}
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
              <div className="regchat-avatar">
                <img src={logoUrl} alt="" />
              </div>
              <div className="regchat-bubble-col">
                {thinking ? (
                  <div className="regchat-think">
                    <button
                      className="regchat-think-head"
                      onClick={() => setThinkOpen((v) => !v)}
                    >
                      <span>{thinkOpen ? '\u25BE' : '\u25B8'}</span>
                      <span>Размышляет</span>
                    </button>
                    {thinkOpen && <div className="regchat-think-body">{thinking}</div>}
                  </div>
                ) : null}
                {status ? (
                  <div className="regchat-status">{status}</div>
                ) : (
                  <div className="regchat-bubble ai">
                    <div className="typing">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="status-line" style={{ color: 'var(--error)' }}>
          {error}
        </div>
      )}

      {ready && (
        <div className="chat-ready">
          <div>Регламент готов. Можно перейти к проверке и созданию агента.</div>
          <button
            className="btn-primary"
            style={{ maxWidth: 260 }}
            onClick={() => onReady(session)}
          >
            Продолжить
          </button>
        </div>
      )}

      {!ready && (
        <div className="regchat-composer">
          {attachments.length > 0 && (
            <div className="regchat-pending">
              {attachments.map((f) => (
                <span key={f.path} className="regchat-pending-chip">
                  {'\uD83D\uDCCE'} {f.name}
                  <button
                    className="regchat-pending-remove"
                    onClick={() => removeAttachment(f.path)}
                    aria-label="Убрать файл"
                  >
                    {'\u00D7'}
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="regchat-input-row">
            <button
              className="regchat-attach-btn"
              onClick={() => void pickFiles()}
              disabled={busy}
              title="Приложить файлы"
              aria-label="Приложить файлы"
            >
              {'\uD83D\uDCCE'}
            </button>
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
              rows={2}
            />
            <button
              className="btn-primary"
              style={{ width: 120 }}
              onClick={() => void send(input, attachments)}
              disabled={busy}
            >
              Отправить
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
