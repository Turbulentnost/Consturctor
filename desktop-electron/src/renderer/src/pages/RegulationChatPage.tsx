import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type RegulationCreationSession } from '../api/types'

interface RegulationChatPageProps {
  session: RegulationCreationSession
  onSessionChange: (session: RegulationCreationSession) => void
  onReady: (session: RegulationCreationSession) => void
  onBack: () => void
}

function quickAnswers(structured: Record<string, unknown>): string[] {
  const raw = structured.quickAnswers
  if (Array.isArray(raw)) return raw.map((x) => String(x)).filter(Boolean)
  return []
}

export function RegulationChatPage({
  session,
  onSessionChange,
  onReady,
  onBack
}: RegulationChatPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [session.messages.length, busy])

  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)

  async function send(text: string): Promise<void> {
    const message = text.trim()
    if (!message || busy) return
    setInput('')
    setError('')
    setBusy(true)
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
          structured: {}
        }
      ]
    }
    onSessionChange(optimistic)
    try {
      const updated = await api.sendRegulationCreationMessage(session.draftId, message)
      onSessionChange(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка отправки сообщения')
      onSessionChange({ ...session, status: 'idle' })
    } finally {
      setBusy(false)
    }
  }

  const visible = session.messages.filter(
    (m) => m.role === 'assistant' || m.role === 'user'
  )

  return (
    <div className="chat-page">
      <div className="chat-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <h1 className="page-title" style={{ fontSize: 24 }}>
          Создание регламента с ИИ
        </h1>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {visible.length === 0 && !busy && (
          <div className="chat-hint">
            ИИ задаст несколько вопросов, чтобы собрать регламент. Опишите процесс, который нужно
            автоматизировать.
          </div>
        )}
        {visible.map((m, index) => (
          <div key={m.messageId || index} className={m.role === 'user' ? 'bubble user' : 'bubble ai'}>
            <div className="bubble-text">{m.content}</div>
            {m.role === 'assistant' && quickAnswers(m.structured).length > 0 && !busy && (
              <div className="quick-row">
                {quickAnswers(m.structured).map((qa) => (
                  <button key={qa} className="quick-chip" onClick={() => send(qa)}>
                    {qa}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="bubble ai">
            <div className="typing">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        )}
      </div>

      {error && <div className="status-line" style={{ color: 'var(--error)' }}>{error}</div>}

      {ready && (
        <div className="chat-ready">
          <div>Регламент готов. Можно перейти к проверке и созданию агента.</div>
          <button className="btn-primary" style={{ maxWidth: 260 }} onClick={() => onReady(session)}>
            Продолжить
          </button>
        </div>
      )}

      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Опишите процесс или ответьте на вопрос ИИ..."
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
          disabled={busy}
          rows={2}
        />
        <button className="btn-primary" style={{ width: 120 }} onClick={() => send(input)} disabled={busy}>
          Отправить
        </button>
      </div>
    </div>
  )
}
