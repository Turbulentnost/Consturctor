import { useEffect, useRef, useState } from 'react'
import type { AgentSuggestion, PassportSession } from '../api/types'

const FIELDS: { key: keyof PassportSession['passport']; label: string }[] = [
  { key: 'name', label: 'Название' },
  { key: 'goal', label: 'Цель' },
  { key: 'trigger', label: 'Триггер' },
  { key: 'receives', label: 'Получает' },
  { key: 'checks', label: 'Проверяет' },
  { key: 'decisions', label: 'Принимает решения' },
  { key: 'canAutonomous', label: 'Может самостоятельно' },
  { key: 'needsHumanApproval', label: 'Требует подтверждения человека' },
  { key: 'forbidden', label: 'Не может' },
  { key: 'result', label: 'Результат' }
]

interface ChatMsg {
  role: 'ai' | 'user'
  text: string
}

interface PassportPageProps {
  suggestion: AgentSuggestion
  session: PassportSession | null
  error?: string
  busy?: boolean
  onBack: () => void
  onAnswer: (answers: Record<string, string>) => void
  onFinish: () => void
}

export function PassportPage({
  suggestion,
  session,
  error,
  busy,
  onBack,
  onAnswer,
  onFinish
}: PassportPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastPromptRef = useRef<string>('')

  const passport = session?.passport
  const missing = passport?.missingFields ?? []
  const questions = passport?.questions ?? []
  const current = questions[0]
  const prompt = String(current?.prompt || current?.question || '')
  const ready = Boolean(passport?.name.trim()) && missing.length === 0

  useEffect(() => {
    if (prompt && prompt !== lastPromptRef.current) {
      lastPromptRef.current = prompt
      setMessages((prev) => [...prev, { role: 'ai', text: prompt }])
    }
  }, [prompt])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy, ready])

  function send(): void {
    const text = input.trim()
    if (!text || busy || ready) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', text }])
    const field = String(current?.field || missing[0] || 'answer')
    onAnswer({ [field]: text, answer: text })
  }

  return (
    <div className="passport-page page-with-footer">
      <div className="chat-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <h1 className="page-title" style={{ fontSize: 28 }}>
          {suggestion.title || 'Паспорт ИИ-агента'}
        </h1>
        <p className="page-subtitle">Карточка обновляется после каждого ответа в чате</p>
      </div>

      <div className="passport-grid">
        <div className="chat-col">
          <div className="passport-chat-scroll" ref={scrollRef}>
            {!session && !messages.length && (
              <div className="chat-hint">Собираю черновик паспорта агента…</div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`bubble ${message.role}`}>
                <div className="bubble-text">{message.text}</div>
              </div>
            ))}
            {busy && (
              <div className="bubble ai">
                <div className="typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
            {ready && (
              <div className="chat-ready">
                <div>Паспорт готов — можно перейти к проектированию агента.</div>
              </div>
            )}
          </div>

          {error && (
            <div className="status-line" style={{ color: 'var(--error)' }}>
              {error}
            </div>
          )}

          {!ready && (
            <div className="chat-input">
              <textarea
                value={input}
                placeholder="Ответьте на уточнение..."
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                }}
                disabled={busy}
                rows={2}
              />
              <button
                className="btn-primary"
                style={{ width: 120 }}
                onClick={send}
                disabled={busy || !input.trim()}
              >
                Отправить
              </button>
            </div>
          )}
        </div>

        <div className="option-card passport-card">
          <h3>Паспорт агента</h3>
          <div className="passport-fields">
            {FIELDS.map((field) => {
              const value = String(passport?.[field.key] || '').trim()
              const isMissing = missing.includes(field.key) || missing.includes(toSnake(field.key))
              return (
                <div key={field.key} className={isMissing ? 'passport-field missing' : 'passport-field'}>
                  <div className="passport-label">{field.label}</div>
                  <div className="passport-value">{value || (busy ? '…' : '—')}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="page-footer">
        <div className="page-footer-actions">
          <button className="btn-ghost-dark" onClick={onBack}>
            Назад
          </button>
          <button
            className="btn-primary"
            style={{ maxWidth: 280 }}
            onClick={onFinish}
            disabled={!ready || busy}
          >
            К проектированию
          </button>
        </div>
      </div>
    </div>
  )
}

function toSnake(key: string): string {
  return key.replace(/[A-Z]/g, (ch) => `_${ch.toLowerCase()}`)
}
