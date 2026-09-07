import { useState } from 'react'
import type { StreamEvent, WorkflowRecord } from '../api/types'

interface WorkflowPageProps {
  record: WorkflowRecord | null
  events: StreamEvent[]
  busy?: boolean
  stage: string
  error?: string
  onBack: () => void
  onClarify: (answers: Record<string, string>) => void
  onDemo: () => void
}

export function WorkflowPage({
  record,
  events,
  busy,
  stage,
  error,
  onBack,
  onClarify,
  onDemo
}: WorkflowPageProps): React.JSX.Element {
  const plan = record?.plan
  const questions = (plan?.openQuestions ?? []).filter((q) => !q.answer.trim())
  const [answers, setAnswers] = useState<Record<string, string>>({})

  return (
    <div>
      <div className="chat-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <h1 className="page-title" style={{ fontSize: 28 }}>
          {record?.title || 'Формирование агента'}
        </h1>
        <p className="page-subtitle">{stage}</p>
      </div>

      {error && <div className="status-line" style={{ color: 'var(--error)' }}>{error}</div>}

      {plan && (
        <div className="option-card" style={{ alignItems: 'stretch', marginTop: 20 }}>
          <h3 style={{ textAlign: 'left' }}>{plan.title || 'План агента'}</h3>
          {plan.goal && <p style={{ textAlign: 'left' }}>{plan.goal}</p>}
          {plan.steps.length > 0 && (
            <ol className="plan-steps">
              {plan.steps.map((step) => (
                <li key={step.id || step.title}>
                  <b>{step.title}</b>
                  {step.action && <div>{step.action}</div>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {questions.length > 0 && (
        <div className="option-card" style={{ alignItems: 'stretch', marginTop: 16 }}>
          <h3 style={{ textAlign: 'left' }}>Нужны уточнения</h3>
          {questions.map((q) => (
            <label key={q.id} className="passport-field">
              <div className="passport-label">{q.question}</div>
              {q.why && <div className="page-subtitle" style={{ paddingRight: 0 }}>{q.why}</div>}
              <input
                className="plain-input"
                value={answers[q.id] ?? ''}
                onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                disabled={busy}
              />
            </label>
          ))}
          <button
            className="btn-primary"
            style={{ maxWidth: 240, marginTop: 8 }}
            disabled={busy || questions.some((q) => !(answers[q.id] || '').trim())}
            onClick={() => onClarify(answers)}
          >
            {busy ? 'Обновляем план...' : 'Ответить и продолжить'}
          </button>
        </div>
      )}

      {record && questions.length === 0 && record.phase !== 'tested' && record.phase !== 'done' && (
        <div className="review-actions">
          <button className="btn-primary" style={{ maxWidth: 280 }} onClick={onDemo} disabled={busy}>
            {busy ? 'Идёт пробный прогон...' : 'Пробный прогон'}
          </button>
        </div>
      )}

      {record?.lastResult && (
        <div className="option-card" style={{ alignItems: 'stretch', marginTop: 16 }}>
          <h3 style={{ textAlign: 'left' }}>Результат прогона</h3>
          <pre className="result-pre">{record.lastResult}</pre>
        </div>
      )}

      {events.length > 0 && (
        <div className="stream-log">
          {events.map((event, index) => (
            <div key={index} className={`stream-line ${event.type}`}>
              <span className="stream-type">{event.type}</span>
              <span>{event.text || event.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
