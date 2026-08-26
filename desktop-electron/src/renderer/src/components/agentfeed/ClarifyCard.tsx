import { useState } from 'react'
import type { PendingQuestion } from './types'

interface ClarifyCardProps {
  question: PendingQuestion
  allowFiles?: boolean
  onAnswer: (requestId: string, value: string, filePaths?: string[]) => void
}

export function ClarifyCard({ question, allowFiles = false, onAnswer }: ClarifyCardProps): React.JSX.Element {
  const [selected, setSelected] = useState('')
  const [custom, setCustom] = useState('')
  const [filePaths, setFilePaths] = useState<string[]>([])

  const submit = (): void => {
    const text = (custom.trim() || selected).trim()
    if (!text && filePaths.length === 0) return
    const names = filePaths.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const value = [text, names.length ? `Прикрепленные файлы: ${names.join(', ')}` : '']
      .filter(Boolean)
      .join('\n')
    onAnswer(question.requestId, value, filePaths)
  }

  const pickFiles = async (): Promise<void> => {
    const paths = await window.api.openFile({
      title: 'Прикрепить файл к ответу',
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    setFilePaths((prev) => Array.from(new Set([...prev, ...paths])))
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
      {allowFiles && (
        <div className="feed-clarify-files">
          <button type="button" className="btn-ghost" onClick={() => void pickFiles()}>
            Прикрепить файл
          </button>
          {filePaths.length > 0 && (
            <div className="feed-clarify-file-list">
              {filePaths.map((path) => (
                <span key={path}>{path.split(/[\\/]/).pop() || path}</span>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="feed-clarify-actions">
        <button
          className="btn-primary"
          disabled={!custom.trim() && !selected && filePaths.length === 0}
          onClick={submit}
        >
          Ответить и продолжить
        </button>
      </div>
    </div>
  )
}
