import { useEffect, useState } from 'react'
import { api } from '../api/client'

export type ScheduleMode = 'once' | 'interval' | 'event' | 'manual'

export interface ScheduleSpec {
  mode: ScheduleMode
  message: string
  at?: string
  intervalSeconds?: number
  condition?: string
}

interface AgentSchedulePageProps {
  workflowId: string
  title: string
  onBack: () => void
  onNext: (spec: ScheduleSpec) => void
}

function defaultDateTimeLocal(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function AgentSchedulePage({
  workflowId,
  title,
  onBack,
  onNext
}: AgentSchedulePageProps): React.JSX.Element {
  const [mode, setMode] = useState<ScheduleMode>('once')
  const [message, setMessage] = useState('')
  const [at, setAt] = useState(defaultDateTimeLocal())
  const [intervalMinutes, setIntervalMinutes] = useState(60)
  const [condition, setCondition] = useState('')
  const [suggestion, setSuggestion] = useState('')

  useEffect(() => {
    let alive = true
    void api
      .proposeScheduleDraft(workflowId)
      .then((draft) => {
        if (!alive) return
        const text =
          (draft.summary as string) ||
          (draft.description as string) ||
          (draft.recommendation as string) ||
          ''
        if (text) setSuggestion(String(text))
        const draftMessage = (draft.message as string) || ''
        if (draftMessage) setMessage(String(draftMessage))
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [workflowId])

  const build = (): ScheduleSpec => {
    if (mode === 'once') {
      const iso = at ? new Date(at).toISOString() : ''
      return { mode, message, at: iso }
    }
    if (mode === 'interval') {
      return { mode, message, intervalSeconds: Math.max(60, intervalMinutes * 60) }
    }
    if (mode === 'event') {
      return { mode, message, condition }
    }
    return { mode, message }
  }

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>Расписание запуска</h2>
          <p>{title}</p>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main" style={{ padding: 20, overflowY: 'auto' }}>
          {suggestion && (
            <div className="feed-system success" style={{ marginBottom: 16 }}>
              Рекомендация: {suggestion}
            </div>
          )}

          <div className="agent-side-card" style={{ marginBottom: 14 }}>
            <h4>Когда запускать агента</h4>
            <div className="feed-clarify-options" style={{ marginTop: 8 }}>
              {(
                [
                  ['once', 'Разово в указанное время'],
                  ['interval', 'Периодически'],
                  ['event', 'По событию (условие)'],
                  ['manual', 'Только вручную']
                ] as [ScheduleMode, string][]
              ).map(([value, label]) => (
                <label
                  key={value}
                  className={mode === value ? 'feed-clarify-option active' : 'feed-clarify-option'}
                >
                  <input
                    type="radio"
                    name="schedule-mode"
                    checked={mode === value}
                    onChange={() => setMode(value)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>

          {mode === 'once' && (
            <div className="agent-side-card" style={{ marginBottom: 14 }}>
              <h4>Дата и время</h4>
              <input
                type="datetime-local"
                value={at}
                onChange={(e) => setAt(e.target.value)}
                style={{ padding: 8, borderRadius: 8, border: '1px solid var(--card-border)' }}
              />
            </div>
          )}
          {mode === 'interval' && (
            <div className="agent-side-card" style={{ marginBottom: 14 }}>
              <h4>Интервал, минут</h4>
              <input
                type="number"
                min={1}
                value={intervalMinutes}
                onChange={(e) => setIntervalMinutes(Number(e.target.value) || 1)}
                style={{ padding: 8, borderRadius: 8, border: '1px solid var(--card-border)', width: 120 }}
              />
            </div>
          )}
          {mode === 'event' && (
            <div className="agent-side-card" style={{ marginBottom: 14 }}>
              <h4>Условие запуска</h4>
              <textarea
                className="feed-clarify-input"
                placeholder="Например: пришло письмо от контрагента с темой ..."
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
              />
            </div>
          )}

          <div className="agent-side-card">
            <h4>Задача для запуска (необязательно)</h4>
            <textarea
              className="feed-clarify-input"
              placeholder="Что именно агент должен сделать при запуске"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>

          <div className="feed-clarify-actions" style={{ marginTop: 16 }}>
            <button
              className="btn-primary"
              disabled={mode === 'event' && !condition.trim()}
              onClick={() => onNext(build())}
            >
              Далее к публикации
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
