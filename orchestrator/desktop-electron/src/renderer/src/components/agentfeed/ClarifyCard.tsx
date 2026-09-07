import { useEffect, useRef, useState } from 'react'
import type { PendingQuestion } from './types'

interface ClarifyCardProps {
  question: PendingQuestion
  allowFiles?: boolean
  onAnswer: (requestId: string, value: string, filePaths?: string[]) => void
}

export function ClarifyCard({
  question,
  allowFiles = false,
  onAnswer
}: ClarifyCardProps): React.JSX.Element {
  const [selected, setSelected] = useState('')
  const [useCustom, setUseCustom] = useState(question.options.length === 0)
  const [custom, setCustom] = useState('')
  const [filePaths, setFilePaths] = useState<string[]>([])
  const cardRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (useCustom) {
      inputRef.current?.focus()
      return
    }
    cardRef.current?.focus()
  }, [useCustom, question.requestId])

  const needsFile = Boolean(question.needsFile)
  const accept = question.accept?.length ? question.accept : ['xlsx', 'xlsm', 'docx']
  const canAttach = allowFiles || needsFile
  const hasAnswer = needsFile
    ? filePaths.length > 0
    : Boolean(useCustom ? custom.trim() || filePaths.length : selected)

  const submit = (): void => {
    const text = (useCustom ? custom.trim() : selected).trim()
    const names = filePaths.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const value = [text, names.length ? `Прикрепленные файлы: ${names.join(', ')}` : '']
      .filter(Boolean)
      .join('\n')
    if (!value && filePaths.length === 0) return
    onAnswer(question.requestId, value, filePaths)
  }

  const pickFiles = async (): Promise<void> => {
    const paths = await window.api.openFile({
      title: needsFile ? 'Загрузить Excel или Word' : 'Прикрепить файл к ответу',
      properties: ['openFile', 'multiSelections'],
      filters: canAttach
        ? [
            {
              name: 'Excel или Word',
              extensions: accept
            }
          ]
        : undefined
    })
    if (!paths.length) return
    setFilePaths((prev) => Array.from(new Set([...prev, ...paths])))
  }

  const onCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.target instanceof HTMLTextAreaElement) return
    if (!hasAnswer) return
    event.preventDefault()
    submit()
  }

  const title = question.question.trim() || 'Агенту нужно уточнение'

  return (
    <div
      className="clarify"
      ref={cardRef}
      tabIndex={0}
      onKeyDown={onCardKeyDown}
    >
      <div className="clarify-kicker">Агенту нужно уточнение</div>
      <div className="clarify-question">{title}</div>

      {question.options.length > 0 && (
        <div className="clarify-options">
          {question.options.map((option) => {
            const active = !useCustom && selected === option
            return (
              <button
                key={option}
                type="button"
                className={active ? 'clarify-option active' : 'clarify-option'}
                onClick={() => {
                  setSelected(option)
                  setUseCustom(false)
                }}
              >
                <span className={active ? 'clarify-radio on' : 'clarify-radio'} />
                <span className="clarify-option-label">{option}</span>
              </button>
            )
          })}
        </div>
      )}

      <div className={useCustom ? 'clarify-custom-row on' : 'clarify-custom-row'}>
        <button
          type="button"
          className={useCustom ? 'clarify-option other active' : 'clarify-option other'}
          onClick={() => {
            setUseCustom(true)
            setSelected('')
            inputRef.current?.focus()
          }}
        >
          <span className={useCustom ? 'clarify-radio on' : 'clarify-radio'} />
          <span className="clarify-option-label">Свой вариант</span>
        </button>
        <input
          ref={inputRef}
          className="clarify-custom-input"
          placeholder="Напишите свой ответ"
          value={custom}
          onFocus={() => {
            setUseCustom(true)
            setSelected('')
          }}
          onChange={(e) => {
            setCustom(e.target.value)
            setUseCustom(true)
            setSelected('')
          }}
        />
      </div>

      {canAttach && (
        <div className="clarify-files">
          <button type="button" className="btn-ghost clarify-attach" onClick={() => void pickFiles()}>
            {needsFile ? 'Прикрепить файл для этого запуска' : 'Прикрепить файл'}
          </button>
          {needsFile && (
            <span className="clarify-file-hint">
              Временный файл: используется только в этом запуске и не сохраняется в базу знаний.
            </span>
          )}
          {filePaths.map((path) => (
            <span key={path} className="clarify-file-name">
              {path.split(/[\\/]/).pop() || path}
            </span>
          ))}
        </div>
      )}

      <div className="clarify-actions">
        <button className="clarify-submit" onClick={submit} disabled={!hasAnswer}>
          Далее
        </button>
      </div>
    </div>
  )
}
