import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  IntervalUnit,
  ScheduleDraft,
  ScheduleTriggerSpec,
  TriggerKind,
  WorkflowRecord
} from '../api/types'

interface AgentSchedulePageProps {
  workflowId: string
  title: string
  onBack: () => void
  onNext: (draft: ScheduleDraft) => void
}

/**
 * Fallback description when the backend schedule draft returns an empty goal:
 * reuse whatever the workflow already knows (plan goal, or the playbook's
 * expected result / instructions). No hardcoded copy - only existing data.
 */
function goalFromWorkflow(record: WorkflowRecord): string {
  const planGoal = (record.plan?.goal || '').trim()
  if (planGoal) return planGoal
  const local = record.localRun || {}
  for (const key of ['playbook_draft', 'playbook']) {
    const blob = local[key]
    if (blob && typeof blob === 'object') {
      const data = blob as Record<string, unknown>
      const expected = String(data.expected_result ?? '').trim()
      if (expected) return expected
      const instructions = String(data.instructions ?? '').trim()
      if (instructions) return instructions
    }
  }
  return ''
}

function emptyTrigger(kind: TriggerKind): ScheduleTriggerSpec {
  return {
    kind,
    message: '',
    intervalValue: kind === 'interval' ? 1 : 0,
    intervalUnit: 'hours',
    condition: '',
    at: '',
    once: false
  }
}

function clockFromAt(at: string): string {
  const m = /(\d{1,2})[:.](\d{2})/.exec(at || '')
  if (!m) return ''
  const h = Number(m[1])
  const min = Number(m[2])
  if (h > 23 || min > 59) return ''
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`
}

function hasDate(at: string): boolean {
  return /\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}/.test(at || '')
}

function prettyDateTime(at: string): string {
  const raw = (at || '').trim()
  const clock = clockFromAt(raw)
  // ISO datetime -> local pretty
  const parsed = new Date(raw)
  if (!Number.isNaN(parsed.getTime()) && hasDate(raw)) {
    return parsed.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }
  return clock || raw.slice(0, 40)
}

export function triggerChipLabel(spec: ScheduleTriggerSpec): string {
  const kind = (spec.kind || '').toLowerCase()
  if (kind === 'interval') {
    const value = spec.intervalValue || 0
    const unit = (spec.intervalUnit || 'hours').toLowerCase()
    const amount = Number.isInteger(value) ? value : Number(value.toFixed(1))
    if (unit === 'minutes') return amount === 1 ? 'каждую минуту' : `каждые ${amount} мин`
    if (unit === 'days') return amount === 1 ? 'ежедневно' : `каждые ${amount} дн.`
    return amount === 1 ? 'каждый час' : `каждые ${amount} ч`
  }
  if (kind === 'datetime') {
    const clock = clockFromAt(spec.at)
    if ((!spec.once || !hasDate(spec.at)) && clock) return `ежедневно в ${clock}`
    return prettyDateTime(spec.at) || 'в указанное время'
  }
  let condition = (spec.condition || spec.message || '').trim()
  if (condition.length > 60) condition = condition.slice(0, 57).replace(/\s+\S*$/, '') + '…'
  return condition ? `при событии: ${condition}` : 'по событию'
}

function toDateTimeLocal(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function specToDateTimeLocal(spec: ScheduleTriggerSpec): string {
  const raw = (spec.at || '').trim()
  if (raw) {
    const clock = clockFromAt(raw)
    if (clock && !hasDate(raw)) {
      const now = new Date()
      const [h, m] = clock.split(':')
      now.setHours(Number(h), Number(m), 0, 0)
      return toDateTimeLocal(now)
    }
    const parsed = new Date(raw)
    if (!Number.isNaN(parsed.getTime())) return toDateTimeLocal(parsed)
  }
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000)
  return toDateTimeLocal(tomorrow)
}

const KIND_LABELS: { value: TriggerKind; label: string }[] = [
  { value: 'interval', label: 'Через время после последнего запуска' },
  { value: 'event', label: 'Событие (файл, сообщение)' },
  { value: 'datetime', label: 'В определённое время' }
]

const UNIT_LABELS: { value: IntervalUnit; label: string }[] = [
  { value: 'minutes', label: 'мин.' },
  { value: 'hours', label: 'час.' },
  { value: 'days', label: 'дн.' }
]

function TriggerEditModal({
  initial,
  onSave,
  onCancel
}: {
  initial: ScheduleTriggerSpec
  onSave: (spec: ScheduleTriggerSpec) => void
  onCancel: () => void
}): React.JSX.Element {
  const [kind, setKind] = useState<TriggerKind>(initial.kind || 'interval')
  const [intervalValue, setIntervalValue] = useState(initial.intervalValue || 1)
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>(initial.intervalUnit || 'hours')
  const [condition, setCondition] = useState(initial.condition || '')
  const [dtLocal, setDtLocal] = useState(specToDateTimeLocal(initial))
  const [once, setOnce] = useState(initial.kind === 'datetime' ? Boolean(initial.once) : false)
  const [message, setMessage] = useState(initial.message || '')

  const save = (): void => {
    let at = ''
    if (kind === 'datetime') {
      const parsed = new Date(dtLocal)
      if (!Number.isNaN(parsed.getTime())) {
        at = once
          ? parsed.toISOString()
          : `${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}`
      }
    }
    onSave({
      kind,
      message: message.trim(),
      intervalValue: Number(intervalValue) || 0,
      intervalUnit,
      condition: condition.trim(),
      at,
      once: kind === 'datetime' ? once : false
    })
  }

  return (
    <div className="passport-modal-overlay" onClick={onCancel}>
      <div className="passport-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Когда запускается</h3>
        <label className="passport-field-label">Тип триггера</label>
        <select
          className="passport-select"
          value={kind}
          onChange={(e) => setKind(e.target.value as TriggerKind)}
        >
          {KIND_LABELS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>

        {kind === 'interval' && (
          <div className="passport-row">
            <input
              type="number"
              min={0.1}
              step={0.1}
              className="passport-input"
              value={intervalValue}
              onChange={(e) => setIntervalValue(Number(e.target.value) || 0)}
            />
            <select
              className="passport-select"
              value={intervalUnit}
              onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}
            >
              {UNIT_LABELS.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>
        )}

        {kind === 'event' && (
          <input
            type="text"
            className="passport-input"
            placeholder="Например: изменён файл на шаре"
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
          />
        )}

        {kind === 'datetime' && (
          <div className="passport-row">
            <input
              type="datetime-local"
              className="passport-input"
              value={dtLocal}
              onChange={(e) => setDtLocal(e.target.value)}
            />
            <label className="passport-check">
              <input type="checkbox" checked={once} onChange={(e) => setOnce(e.target.checked)} />
              <span>Один раз</span>
            </label>
          </div>
        )}

        <label className="passport-field-label">Задача при запуске (кратко)</label>
        <input
          type="text"
          className="passport-input"
          placeholder="Что агент делает при запуске"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />

        <div className="passport-modal-actions">
          <button className="btn-ghost" onClick={onCancel}>
            Отмена
          </button>
          <button className="btn-primary" onClick={save}>
            Готово
          </button>
        </div>
      </div>
    </div>
  )
}

export function AgentSchedulePage({
  workflowId,
  title,
  onBack,
  onNext
}: AgentSchedulePageProps): React.JSX.Element {
  const [name, setName] = useState(title || 'ИИ-агент')
  const [goal, setGoal] = useState('')
  const [triggers, setTriggers] = useState<ScheduleTriggerSpec[]>([])
  const [suggestion, setSuggestion] = useState('')
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const loadedRef = useRef(false)

  useEffect(() => {
    if (loadedRef.current) return
    loadedRef.current = true
    let alive = true
    void (async () => {
      const [draftResult, recordResult] = await Promise.allSettled([
        api.proposeScheduleDraft(workflowId),
        api.getWorkflow(workflowId)
      ])
      if (!alive) return
      const draft = draftResult.status === 'fulfilled' ? draftResult.value : null
      const record = recordResult.status === 'fulfilled' ? recordResult.value : null
      const fallbackGoal = record ? goalFromWorkflow(record) : ''
      if (draft) {
        const cleanName = (draft.name || '').trim()
        if (cleanName && !['notes', 'notes.txt'].includes(cleanName.toLowerCase())) {
          setName(cleanName)
        }
        if (draft.goal) setGoal(draft.goal)
        else if (fallbackGoal) setGoal(fallbackGoal)
        if (draft.summary) setSuggestion(draft.summary)
        if (draft.triggers.length > 0) setTriggers(draft.triggers)
      } else if (fallbackGoal) {
        setGoal(fallbackGoal)
      }
    })()
    return () => {
      alive = false
    }
  }, [workflowId])

  const editingSpec = useMemo(
    () => (editIndex !== null ? triggers[editIndex] : null),
    [editIndex, triggers]
  )

  const addPreset = (spec: ScheduleTriggerSpec, edit = false): void => {
    setTriggers((prev) => {
      const next = [...prev, spec]
      if (edit) setEditIndex(next.length - 1)
      return next
    })
    setAddOpen(false)
  }

  const removeTrigger = (index: number): void => {
    setTriggers((prev) => prev.filter((_, i) => i !== index))
  }

  const saveEdited = (spec: ScheduleTriggerSpec): void => {
    if (editIndex === null) return
    setTriggers((prev) => prev.map((t, i) => (i === editIndex ? spec : t)))
    setEditIndex(null)
  }

  const validate = (): string => {
    for (const spec of triggers) {
      if (spec.kind === 'interval' && spec.intervalValue <= 0) return 'Укажите интервал больше нуля.'
      if (spec.kind === 'event' && !spec.condition.trim())
        return 'Опишите событие: изменён файл или получено сообщение.'
      if (spec.kind === 'datetime' && !spec.at.trim()) return 'Укажите дату и время запуска.'
    }
    return ''
  }

  const goNext = async (): Promise<void> => {
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    const draft: ScheduleDraft = {
      name: name.trim() || 'ИИ-агент',
      goal: goal.trim(),
      summary: suggestion,
      triggers
    }
    setSaving(true)
    setError('')
    try {
      await api.persistScheduleDraft(workflowId, draft)
      onNext(draft)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить паспорт агента')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>Паспорт агента</h2>
          <p>Название, цель и когда запускать. Пустой список триггеров — только вручную из чата.</p>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main" style={{ padding: 20, overflowY: 'auto' }}>
          {suggestion && (
            <div className="feed-system success" style={{ marginBottom: 16 }}>
              Рекомендация: {suggestion}
            </div>
          )}

          <div className="passport-card">
            <label className="passport-field-label">Название</label>
            <input
              type="text"
              className="passport-input"
              placeholder="Название агента"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />

            <label className="passport-field-label">Цель</label>
            <textarea
              className="passport-textarea"
              placeholder="Что агент делает и зачем"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />

            <label className="passport-field-label">Когда запускается</label>
            <div className="passport-triggers">
              {triggers.length === 0 && (
                <div className="passport-empty">Триггеров нет — агент запускается только вручную.</div>
              )}
              {triggers.map((spec, index) => (
                <div
                  key={index}
                  className="passport-chip"
                  onClick={() => setEditIndex(index)}
                  role="button"
                >
                  <span className="passport-chip-label">{triggerChipLabel(spec)}</span>
                  <button
                    className="passport-chip-close"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeTrigger(index)
                    }}
                    title="Убрать"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>

            <div className="passport-add-wrap">
              <button className="btn-ghost" onClick={() => setAddOpen((v) => !v)}>
                + Добавить триггер
              </button>
              {addOpen && (
                <div className="passport-add-menu">
                  <button
                    onClick={() =>
                      addPreset({
                        ...emptyTrigger('interval'),
                        intervalValue: 15,
                        intervalUnit: 'minutes'
                      })
                    }
                  >
                    Каждые 15 мин
                  </button>
                  <button
                    onClick={() =>
                      addPreset({ ...emptyTrigger('datetime'), at: '12:00', once: false })
                    }
                  >
                    Ежедневно в 12:00
                  </button>
                  <button
                    onClick={() =>
                      addPreset(
                        {
                          ...emptyTrigger('event'),
                          condition: 'изменён файл или получено сообщение'
                        },
                        true
                      )
                    }
                  >
                    По событию
                  </button>
                </div>
              )}
            </div>
          </div>

          {error && (
            <div className="feed-system error" style={{ marginTop: 14 }}>
              {error}
            </div>
          )}

          <div className="feed-clarify-actions" style={{ marginTop: 16 }}>
            <button className="btn-primary" disabled={saving} onClick={goNext}>
              {saving ? 'Сохраняем…' : 'Далее к KPI'}
            </button>
          </div>
        </div>
      </div>

      {editingSpec && (
        <TriggerEditModal
          initial={editingSpec}
          onSave={saveEdited}
          onCancel={() => setEditIndex(null)}
        />
      )}
    </div>
  )
}
