import { useEffect, useRef, useState } from 'react'
import type { AgentDraft, QuestionChatSession } from '../api/types'

interface ReadinessPageProps {
  draft: AgentDraft
  chat: QuestionChatSession | null
  busy?: boolean
  onBack: () => void
  onSend: (questionId: string, message: string) => void
  onSkipToAgents: () => void
}

export function ReadinessPage({
  draft,
  chat,
  busy,
  onBack,
  onSend,
  onSkipToAgents
}: ReadinessPageProps): React.JSX.Element {
  const readiness = draft.readiness
  const questions = readiness?.questions ?? []
  const unanswered = questions.filter((q) => !q.answered)
  const current = unanswered[0]
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat?.messages.length, busy])

  const visible = (chat?.messages ?? []).filter((m) => m.role === 'assistant' || m.role === 'user')
  const questionId = chat?.questionId || current?.questionId || ''

  function send(text: string): void {
    const message = text.trim()
    if (!message || !questionId || busy) return
    setInput('')
    onSend(questionId, message)
  }

  return (
    <div className="chat-page">
      <div className="chat-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <h1 className="page-title" style={{ fontSize: 28 }}>
          Уточнение регламента
        </h1>
        <p className="page-subtitle">
          Закрываем пробелы в логике, прежде чем собирать паспорт агента
        </p>
      </div>

      <div className="review-stats">
        <div className="stat">
          <div className="stat-value">{questions.length}</div>
          <div className="stat-label">вопросов</div>
        </div>
        <div className="stat">
          <div className="stat-value">{unanswered.length}</div>
          <div className="stat-label">осталось</div>
        </div>
        <div className="stat">
          <div className="stat-value">{readiness?.score ?? 0}</div>
          <div className="stat-label">готовность</div>
        </div>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {current && (
          <div className="chat-hint">
            <b>{current.question}</b>
            {current.reason && <div style={{ marginTop: 6 }}>{current.reason}</div>}
          </div>
        )}
        {visible.map((m, index) => (
          <div key={m.messageId || index} className={m.role === 'user' ? 'bubble user' : 'bubble ai'}>
            <div className="bubble-text">{m.content}</div>
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
        {!current && !busy && (
          <div className="chat-ready">
            <div>Все уточнения закрыты. Можно перейти к списку ИИ-агентов.</div>
            <button className="btn-primary" style={{ maxWidth: 260 }} onClick={onSkipToAgents}>
              К агентам
            </button>
          </div>
        )}
      </div>

      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Ответьте своими словами..."
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
          disabled={busy || !current}
          rows={2}
        />
        <button className="btn-primary" style={{ width: 120 }} onClick={() => send(input)} disabled={busy || !current}>
          Отправить
        </button>
      </div>
    </div>
  )
}
