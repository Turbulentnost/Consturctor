import { useState } from 'react'
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
  const passport = session?.passport
  const missing = passport?.missingFields ?? []
  const questions = passport?.questions ?? []
  const current = questions[0]
  const prompt = String(current?.prompt || current?.question || '')
  const ready = Boolean(passport?.name.trim()) && missing.length === 0

  function send(): void {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    const field = String(current?.field || missing[0] || 'answer')
    onAnswer({ [field]: text, answer: text })
  }

  return (
    <div>
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
          {error && <div className="status-line" style={{ color: 'var(--error)' }}>{error}</div>}
          {!session && (
            <div className="chat-hint">Собираю черновик паспорта агента…</div>
          )}
          {session && prompt && !ready && (
            <div className="chat-hint">
              <b>{prompt}</b>
            </div>
          )}
          {ready && (
            <div className="chat-ready">
              <div>Паспорт готов — можно перейти к проектированию агента.</div>
            </div>
          )}
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
              disabled={busy || ready}
              rows={2}
            />
            <button className="btn-primary" style={{ width: 120 }} onClick={send} disabled={busy || ready}>
              Отправить
            </button>
          </div>
        </div>

        <div className="option-card passport-card">
          <h3>Паспорт агента</h3>
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

      <div className="review-actions">
        <button className="btn-ghost-dark" onClick={onBack}>
          Назад
        </button>
        <button className="btn-primary" style={{ maxWidth: 280 }} onClick={onFinish} disabled={!ready || busy}>
          К проектированию
        </button>
      </div>
    </div>
  )
}

function toSnake(key: string): string {
  return key.replace(/[A-Z]/g, (ch) => `_${ch.toLowerCase()}`)
}
