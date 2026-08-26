import { useState } from 'react'
import type { PendingQuestion } from './types'

interface ClarifyCardProps {
  question: PendingQuestion
  allowFiles?: boolean
  onAnswer: (requestId: string, value: string, filePaths?: string[]) => void
}

function optionKey(index: number): string {
  return String.fromCharCode(65 + index)
}

export function ClarifyCard({
  question,
  allowFiles = false,
  onAnswer
}: ClarifyCardProps): React.JSX.Element {
  const [collapsed, setCollapsed] = useState(false)
  const [selected, setSelected] = useState('')
  const [useCustom, setUseCustom] = useState(question.options.length === 0)
  const [custom, setCustom] = useState('')
  const [filePaths, setFilePaths] = useState<string[]>([])

  const hasAnswer = Boolean(useCustom ? custom.trim() || filePaths.length : selected)

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
      title: 'Прикрепить файл к ответу',
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    setFilePaths((prev) => Array.from(new Set([...prev, ...paths])))
  }

  const removeFile = (path: string): void => {
    setFilePaths((prev) => prev.filter((item) => item !== path))
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
              {allowFiles && (
                <button
                  type="button"
                  className="clarify-clip"
                  onClick={() => void pickFiles()}
                  title="Прикрепить файл"
                >
                  {'\uD83D\uDCCE'}
                </button>
              )}
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
            </div>
          )}

          {allowFiles &&
            useCustom &&
            filePaths.map((path) => (
              <div className="clarify-file" key={path}>
                <span className="clarify-file-name">{path.split(/[\\/]/).pop() || path}</span>
                <button type="button" className="clarify-file-remove" onClick={() => removeFile(path)}>
                  {'\u00D7'}
                </button>
              </div>
            ))}

          <button className="clarify-submit" onClick={submit} disabled={!hasAnswer}>
            Продолжить
          </button>
        </>
      )}
    </div>
  )
}
