import { useState } from 'react'
import type { PendingQuestion } from './types'

interface ClarifyCardProps {
  question: PendingQuestion
  onAnswer: (requestId: string, value: string) => void
}

export function ClarifyCard({ question, onAnswer }: ClarifyCardProps): React.JSX.Element {
  const [selected, setSelected] = useState('')
  const [custom, setCustom] = useState('')

  const submit = (): void => {
    const value = (custom.trim() || selected).trim()
    if (!value) return
    onAnswer(question.requestId, value)
  }

  return (
    <div className="feed-clarify">
      <div className="feed-clarify-badge">Уточняющий вопрос</div>
      <div className="feed-clarify-question">{question.question}</div>
      {question.options.length > 0 && (
        <div className="feed-clarify-options">
          {question.options.map((option) => (
            <label
              key={option}
              className={selected === option ? 'feed-clarify-option active' : 'feed-clarify-option'}
            >
              <input
                type="radio"
                name={`q-${question.requestId}`}
                checked={selected === option}
                onChange={() => {
                  setSelected(option)
                  setCustom('')
                }}
              />
              <span>{option}</span>
            </label>
          ))}
        </div>
      )}
      <textarea
        className="feed-clarify-input"
        placeholder="Или впишите свой ответ"
        value={custom}
        onChange={(e) => setCustom(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit()
        }}
      />
      <div className="feed-clarify-actions">
        <button
          className="btn-primary"
          disabled={!custom.trim() && !selected}
          onClick={submit}
        >
          Ответить и продолжить
        </button>
      </div>
    </div>
  )
}
