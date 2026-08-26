import { useRef, useState } from 'react'
import type { PendingQuestion } from './types'

interface ClarifyCardProps {
  question: PendingQuestion
  onAnswer: (requestId: string, value: string) => void
}

function optionKey(index: number): string {
  return String.fromCharCode(65 + index)
}

export function ClarifyCard({ question, onAnswer }: ClarifyCardProps): React.JSX.Element {
  const [collapsed, setCollapsed] = useState(false)
  const [selected, setSelected] = useState('')
  const [useCustom, setUseCustom] = useState(question.options.length === 0)
  const [custom, setCustom] = useState('')
  const [fileName, setFileName] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const hasAnswer = Boolean(useCustom ? custom.trim() || fileName : selected)

  const submit = (): void => {
    let value = useCustom ? custom.trim() : selected
    if (useCustom && fileName) value = value ? `${value}\n[файл: ${fileName}]` : `[файл: ${fileName}]`
    if (!value) return
    onAnswer(question.requestId, value)
  }

  const pickFile = (): void => fileRef.current?.click()

  const onFile = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0]
    setFileName(file ? file.name : '')
  }

  const clearFile = (): void => {
    setFileName('')
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div className="clarify">
      <button className="clarify-head" onClick={() => setCollapsed((v) => !v)}>
        <span className="clarify-icon" aria-hidden>
          {'\uD83D\uDCAC'}
        </span>
        <span className="clarify-title">Уточнение</span>
        <span className="clarify-chevron">{collapsed ? '\u2304' : '\u2303'}</span>
      </button>

      {!collapsed && (
        <>
          <div className="clarify-question">
            <span className="clarify-qnum">1.</span>
            <span>{question.question || 'Агент задаёт уточняющий вопрос'}</span>
          </div>

          <div className="clarify-options">
            {question.options.map((option, index) => {
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
                  <span className="clarify-key">{optionKey(index)}</span>
                  <span className="clarify-option-label">{option}</span>
                </button>
              )
            })}

            <button
              type="button"
              className={useCustom ? 'clarify-option other active' : 'clarify-option other'}
              onClick={() => {
                setUseCustom(true)
                setSelected('')
              }}
            >
              <span className="clarify-key muted">{'\uFF0B'}</span>
              <span className="clarify-option-label muted">Свой ответ…</span>
            </button>
          </div>

          {useCustom && (
            <div className="clarify-custom">
              <button
                type="button"
                className="clarify-clip"
                onClick={pickFile}
                title="Прикрепить файл"
              >
                {'\uD83D\uDCCE'}
              </button>
              <input
                className="clarify-custom-input"
                placeholder="Напишите свой ответ…"
                value={custom}
                autoFocus
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
              />
              <input ref={fileRef} type="file" hidden onChange={onFile} />
            </div>
          )}

          {useCustom && fileName && (
            <div className="clarify-file">
              <span className="clarify-file-name">{fileName}</span>
              <button type="button" className="clarify-file-remove" onClick={clearFile}>
                {'\u00D7'}
              </button>
            </div>
          )}

          <button className="clarify-submit" onClick={submit} disabled={!hasAnswer}>
            Продолжить
          </button>
        </>
      )}
    </div>
  )
}
