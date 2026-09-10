import { useEffect, useRef, useState } from 'react'
import { FILE_QUESTION_SKIP_ANSWER, FILE_QUESTION_WAIT_SECONDS } from './questionArgs'
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
  const [held, setHeld] = useState(false)
  const needsFile = Boolean(question.needsFile)
  const autoWaitSeconds = needsFile
    ? question.autoContinueSeconds || FILE_QUESTION_WAIT_SECONDS
    : question.autoContinueSeconds || 0
  const [left, setLeft] = useState(autoWaitSeconds)
  const cardRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const submittedRef = useRef(false)
  const hold = (): void => setHeld(true)

  useEffect(() => {
    if (useCustom) {
      inputRef.current?.focus()
      return
    }
    cardRef.current?.focus()
  }, [useCustom, question.requestId])
  const accept = question.accept?.length ? question.accept : []
  const canAttach = allowFiles || needsFile
  const skipText =
    question.autoContinueAnswer?.trim() ||
    (needsFile ? FILE_QUESTION_SKIP_ANSWER : 'Файла нет. Ищи данные в 1С и папках, не спрашивай файл снова.')
  const canAuto = autoWaitSeconds > 0
  const hasAnswer = needsFile
    ? filePaths.length > 0 || Boolean(useCustom ? custom.trim() : selected) || canAuto
    : Boolean(useCustom ? custom.trim() || filePaths.length : selected)

  const submit = (forced?: string): void => {
    if (submittedRef.current) return
    const text = (forced || (useCustom ? custom.trim() : selected)).trim()
    const names = filePaths.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const value = [text, names.length ? `Прикрепленные файлы: ${names.join(', ')}` : '']
      .filter(Boolean)
      .join('\n')
    if (!value && filePaths.length === 0) {
      if (!canAuto) return
      submittedRef.current = true
      onAnswer(question.requestId, skipText, [])
      return
    }
    submittedRef.current = true
    onAnswer(question.requestId, value, filePaths)
  }

  useEffect(() => {
    submittedRef.current = false
    setHeld(false)
    setLeft(autoWaitSeconds)
  }, [question.requestId, question.autoContinueSeconds, question.needsFile, autoWaitSeconds])

  useEffect(() => {
    if (!canAuto || held || filePaths.length > 0) return
    if (left <= 0) {
      submit(skipText)
      return
    }
    const timer = window.setTimeout(() => setLeft((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [canAuto, held, filePaths.length, left, skipText])

  const pickFiles = async (): Promise<void> => {
    const paths = await window.api.openFile({
      title: needsFile ? 'Загрузить файл для этого запуска' : 'Прикрепить файл к ответу',
      properties: ['openFile', 'multiSelections'],
      filters:
        canAttach && accept.length
          ? [
              {
                name: accept.join(', '),
                extensions: accept
              },
              { name: 'Все файлы', extensions: ['*'] }
            ]
          : canAttach
            ? [{ name: 'Все файлы', extensions: ['*'] }]
            : undefined
    })
    if (!paths.length) return
    hold()
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
            hold()
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
              Временный файл: только для этого запуска, в базу знаний не попадает.
              {canAuto
                ? ` Если не прикрепить, через ${left} сек агент сам возьмёт данные из 1С и папок.`
                : ' Если файла нет — напишите это в «Свой вариант».'}
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
        <button className="clarify-submit" onClick={() => submit()} disabled={!hasAnswer}>
          {canAuto && !held && filePaths.length === 0 && left > 0 ? `Далее (${left})` : 'Далее'}
        </button>
      </div>
    </div>
  )
}
