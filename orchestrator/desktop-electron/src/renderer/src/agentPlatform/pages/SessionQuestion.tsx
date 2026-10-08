import { useState } from 'react'
import { apiPost } from '../api/client'
import type { AgentQuestion, AgentQuestionItem } from '../api/types'
import { ArrowUpIcon, CheckIcon, QuestionIcon, StopIcon } from '../components/Icons'

interface Draft {
  selected: string[]
  text: string
}

const EMPTY: Draft = { selected: [], text: '' }
// С этого числа вариантов у выбора появляются поиск и прокрутка.
const SEARCH_FROM = 8

interface QuestionFormProps {
  sessionId: string
  question: AgentQuestion
  onAnswered: () => void
  onStop: () => void
}

// Вопрос агента вместо поля ввода: агент стоит на ask_user, пока человек не ответит или не пропустит.
export function QuestionForm({ sessionId, question, onAnswered, onStop }: QuestionFormProps): React.JSX.Element {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const draftOf = (id: string): Draft => drafts[id] ?? EMPTY
  const answered =
    question.questions.some((item) => draftOf(item.id).selected.length || draftOf(item.id).text.trim()) &&
    question.questions.every((item) => !item.choice || draftOf(item.id).selected.length > 0)
  const several = question.questions.length > 1
  const wide = question.questions.some((item) => item.choice && (item.columns?.length || item.options.length > SEARCH_FROM))

  function update(id: string, change: (draft: Draft) => Draft): void {
    setDrafts((current) => ({ ...current, [id]: change(current[id] ?? EMPTY) }))
  }

  function toggle(item: AgentQuestionItem, optionId: string): void {
    update(item.id, (draft) => {
      const on = draft.selected.includes(optionId)
      if (item.allow_multiple) {
        return { ...draft, selected: on ? draft.selected.filter((id) => id !== optionId) : [...draft.selected, optionId] }
      }
      return { ...draft, selected: on ? [] : [optionId] }
    })
  }

  async function submit(skipped: boolean): Promise<void> {
    if (sending || (!skipped && !answered)) return
    setSending(true)
    setError('')
    try {
      await apiPost(
        `/api/v1/platform/sessions/${encodeURIComponent(sessionId)}/questions/${encodeURIComponent(question.id)}/answer`,
        {
          skipped,
          answers: skipped
            ? []
            : question.questions.map((item) => ({
                question_id: item.id,
                selected: draftOf(item.id).selected,
                text: draftOf(item.id).text.trim()
              }))
        }
      )
      onAnswered()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось отправить ответ')
      setSending(false)
    }
  }

  return (
    <form
      className={wide ? 'sess-question wide' : 'sess-question'}
      onSubmit={(event) => {
        event.preventDefault()
        void submit(false)
      }}
    >
      <div className="sess-question-head">
        <QuestionIcon size={15} />
        <span className="sess-question-title">{question.title || 'Агент спрашивает'}</span>
        <span className="sess-question-wait">ждёт ответа</span>
      </div>
      {question.questions.map((item, index) => {
        const draft = draftOf(item.id)
        return (
          <fieldset key={item.id} className="sess-question-item" disabled={sending}>
            <legend>
              {several ? `${index + 1}. ` : ''}
              {item.prompt}
            </legend>
            {item.choice ? (
              <ChoiceList item={item} selected={draft.selected} onToggle={(optionId) => toggle(item, optionId)} />
            ) : item.options.length ? (
              <div className="sess-question-options">
                {item.options.map((option) => {
                  const on = draft.selected.includes(option.id)
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={on ? 'sess-question-option selected' : 'sess-question-option'}
                      aria-pressed={on}
                      onClick={() => toggle(item, option.id)}
                    >
                      {item.allow_multiple ? (
                        <span className="sess-question-check">{on ? <CheckIcon size={11} /> : null}</span>
                      ) : null}
                      {option.label}
                    </button>
                  )
                })}
              </div>
            ) : null}
            {item.choice ? null : (
              <input
                className="sess-question-text"
                value={draft.text}
                placeholder={item.options.length ? 'Или напишите свой ответ' : 'Ваш ответ'}
                onChange={(event) => update(item.id, (current) => ({ ...current, text: event.target.value }))}
              />
            )}
          </fieldset>
        )
      })}
      <div className="sess-question-actions">
        {error ? <span className="sess-question-error">{error}</span> : null}
        <button type="button" className="sess-question-skip" disabled={sending} onClick={() => void submit(true)}>
          Пропустить
        </button>
        <button type="button" className="send sess-stop" title="Остановить агента" aria-label="Остановить агента" onClick={onStop}>
          <StopIcon size={16} />
        </button>
        <button type="submit" className="send sess-question-send" disabled={!answered || sending} aria-label="Ответить">
          <ArrowUpIcon />
        </button>
      </div>
    </form>
  )
}

function matches(label: string, words: string[]): boolean {
  const folded = label.toLocaleLowerCase('ru')
  return words.every((word) => folded.includes(word))
}

function ChoiceList({
  item,
  selected,
  onToggle
}: {
  item: AgentQuestionItem
  selected: string[]
  onToggle: (optionId: string) => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const type = item.choice === 'checkbox' ? 'checkbox' : 'radio'
  const columns = item.columns ?? []
  const words = query.toLocaleLowerCase('ru').split(/\s+/).filter(Boolean)
  const shown = words.length ? item.options.filter((option) => matches(option.label, words)) : item.options
  const long = item.options.length > SEARCH_FROM
  const total = item.options.length
  return (
    <div className="sess-choice" role={type === 'radio' ? 'radiogroup' : 'group'}>
      <div className="sess-choice-bar">
        <span className="sess-choice-hint">
          {type === 'radio' ? 'Выберите один вариант' : 'Выберите все подходящие'}
          {long ? ` · ${words.length ? `найдено ${shown.length} из ${total}` : `${total} вариантов`}` : ''}
          {type === 'checkbox' && selected.length ? ` · выбрано ${selected.length}` : ''}
        </span>
        {long ? (
          <input
            className="sess-question-text sess-choice-search"
            value={query}
            placeholder="Поиск"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') event.preventDefault()
            }}
          />
        ) : null}
      </div>
      <div className={long ? 'sess-choice-list long' : 'sess-choice-list'}>
        {columns.length ? (
          <table className="sess-choice-table">
            <thead>
              <tr>
                <th aria-label="Выбор" />
                {columns.map((column, index) => (
                  <th key={index}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((option) => {
                const on = selected.includes(option.id)
                return (
                  <tr key={option.id} className={on ? 'selected' : undefined} onClick={() => onToggle(option.id)}>
                    <td>
                      <input type={type} name={`choice-${item.id}`} value={option.id} checked={on} onChange={() => undefined} />
                    </td>
                    {columns.map((_, index) => (
                      <td key={index}>{option.cells?.[index] ?? ''}</td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          shown.map((option) => (
            <label key={option.id} className={selected.includes(option.id) ? 'sess-choice-option selected' : 'sess-choice-option'}>
              <input
                type={type}
                name={`choice-${item.id}`}
                value={option.id}
                checked={selected.includes(option.id)}
                onChange={() => onToggle(option.id)}
              />
              <span>{option.label}</span>
            </label>
          ))
        )}
        {words.length && !shown.length ? <span className="sess-choice-empty">Ничего не найдено</span> : null}
      </div>
    </div>
  )
}
