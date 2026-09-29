import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Trash2, X } from 'lucide-react'
import { api } from '../../api/client'
import {
  createAssignmentInOneC,
  emptyCreateDraft,
  type AssignmentCreateDraft,
  type AssignmentCreateLineDraft
} from '../../workplace/assignmentRegistryCreate'

function newLineKey(): string {
  return `line-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function FioInput({
  id,
  label,
  value,
  onChange,
  required,
  placeholder,
  listId
}: {
  id?: string
  label: string
  value: string
  onChange: (value: string) => void
  required?: boolean
  placeholder?: string
  listId?: string
}): React.JSX.Element {
  return (
    <label className="registry-create-field" htmlFor={id}>
      <span className="modal-label">
        {label}
        {required ? ' *' : ''}
      </span>
      <input
        id={id}
        className="onec-reconnect-input"
        type="text"
        value={value}
        list={listId}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

export function AssignmentsRegistryCreateDialog({
  open,
  onClose,
  onCreated
}: {
  open: boolean
  onClose: () => void
  onCreated: (message: string) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const fioListId = useId()
  const [draft, setDraft] = useState<AssignmentCreateDraft>(() => emptyCreateDraft())
  const [step, setStep] = useState<'form' | 'confirm'>('form')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [fioHints, setFioHints] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    setDraft(emptyCreateDraft())
    setStep('form')
    setConfirmed(false)
    setError('')
    setBusy(false)
  }, [open])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void api.searchUsers('').then((items) => {
      if (!cancelled) setFioHints(items.slice(0, 200))
    })
    return () => {
      cancelled = true
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  const patchLine = (key: string, patch: Partial<AssignmentCreateLineDraft>): void => {
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line))
    }))
  }

  const addLine = (): void => {
    setDraft((current) => ({
      ...current,
      lines: [...current.lines, { key: newLineKey(), text: '', executor: '', due: '', priority: '' }]
    }))
  }

  const removeLine = (key: string): void => {
    setDraft((current) => {
      const next = current.lines.filter((line) => line.key !== key)
      return {
        ...current,
        lines: next.length ? next : [{ key: newLineKey(), text: '', executor: '', due: '', priority: '' }]
      }
    })
  }

  const goConfirm = (): void => {
    setError('')
    const topic = draft.topic.trim()
    const customer = draft.customer.trim()
    const due = draft.due.trim()
    if (!topic) {
      setError('Заполните поле «О чём»')
      return
    }
    if (!customer) {
      setError('Укажите руководителя (заказчика)')
      return
    }
    if (!due) {
      setError('Укажите срок полного устранения')
      return
    }
    if (!draft.lines.some((line) => line.text.trim())) {
      setError('Добавьте текст хотя бы одной задачи')
      return
    }
    setStep('confirm')
    setConfirmed(false)
  }

  async function submitCreate(): Promise<void> {
    if (!confirmed) {
      setError('Отметьте подтверждение записи в 1С')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await createAssignmentInOneC(draft)
      if (!result.ok) {
        setError(result.error || 'Ошибка создания')
        return
      }
      const msg = result.number
        ? `Создано поручение ${result.number}`
        : result.summary || 'Поручение создано в 1С'
      onCreated(msg)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return createPortal(
    <div className="modal-overlay registry-create-overlay" onClick={() => !busy && onClose()} role="presentation">
      <div
        className="modal-card registry-create-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="registry-create-head">
          <div className="registry-create-head-text">
            <h2 className="modal-title" id={titleId}>
              Новое поручение
            </h2>
            <p className="modal-note registry-create-sub">
              Запись в журнал АСТ00 через 1С. Тестовые данные не подставляются — только ваш ввод.
            </p>
            <div className="registry-create-steps" aria-hidden>
              <span className={step === 'form' ? 'is-active' : ''}>1. Данные</span>
              <span className={step === 'confirm' ? 'is-active' : ''}>2. Проверка</span>
            </div>
          </div>
          <button
            type="button"
            className="registry-detail-close registry-create-close"
            title="Закрыть"
            disabled={busy}
            onClick={onClose}
          >
            <X size={18} aria-hidden />
          </button>
        </header>

        {step === 'form' ? (
          <div className="registry-create-body">
            <datalist id={fioListId}>
              {fioHints.map((fio) => (
                <option key={fio} value={fio} />
              ))}
            </datalist>

            <section className="registry-create-section">
              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">О чём *</span>
                <textarea
                  className="onec-reconnect-input registry-create-textarea"
                  rows={3}
                  value={draft.topic}
                  placeholder="Краткая тема поручения"
                  onChange={(event) => setDraft((c) => ({ ...c, topic: event.target.value }))}
                />
              </label>

              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">Основание</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.basis}
                  placeholder="Устное поручение, протокол…"
                  onChange={(event) => setDraft((c) => ({ ...c, basis: event.target.value }))}
                />
              </label>
            </section>

            <section className="registry-create-section registry-create-grid">
              <FioInput
                label="Руководитель (заказчик)"
                required
                listId={fioListId}
                placeholder="ФИО из справочника 1С"
                value={draft.customer}
                onChange={(value) => setDraft((c) => ({ ...c, customer: value }))}
              />
              <label className="registry-create-field">
                <span className="modal-label">Срок полного устранения *</span>
                <input
                  className="onec-reconnect-input"
                  type="date"
                  value={draft.due}
                  onChange={(event) => setDraft((c) => ({ ...c, due: event.target.value }))}
                />
              </label>
              <FioInput
                label="Кто доложит"
                listId={fioListId}
                value={draft.reporter}
                onChange={(value) => setDraft((c) => ({ ...c, reporter: value }))}
              />
              <FioInput
                label="Секретарь"
                listId={fioListId}
                value={draft.secretary}
                onChange={(value) => setDraft((c) => ({ ...c, secretary: value }))}
              />
            </section>

            <section className="registry-create-section">
              <div className="registry-create-lines-head">
                <h3 className="registry-create-lines-title">Задачи (мероприятия)</h3>
                <button type="button" className="btn-light registry-create-add-line" onClick={addLine}>
                  <Plus size={14} aria-hidden /> Добавить
                </button>
              </div>

              <ul className="registry-create-lines">
                {draft.lines.map((line, index) => (
                  <li key={line.key} className="registry-create-line-card">
                    <div className="registry-create-line-card-head">
                      <span className="registry-create-line-num">Задача {index + 1}</span>
                      <button
                        type="button"
                        className="registry-create-line-remove"
                        title="Удалить задачу"
                        disabled={draft.lines.length <= 1}
                        onClick={() => removeLine(line.key)}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </div>
                    <textarea
                      className="onec-reconnect-input registry-create-line-text"
                      rows={2}
                      placeholder="Текст задачи"
                      value={line.text}
                      onChange={(event) => patchLine(line.key, { text: event.target.value })}
                    />
                    <div className="registry-create-line-meta">
                      <label className="registry-create-field">
                        <span className="modal-label">Исполнитель</span>
                        <input
                          className="onec-reconnect-input"
                          type="text"
                          list={fioListId}
                          placeholder="ФИО"
                          value={line.executor}
                          onChange={(event) => patchLine(line.key, { executor: event.target.value })}
                        />
                      </label>
                      <label className="registry-create-field">
                        <span className="modal-label">Срок</span>
                        <input
                          className="onec-reconnect-input"
                          type="date"
                          title="Если пусто — общий срок поручения"
                          value={line.due}
                          onChange={(event) => patchLine(line.key, { due: event.target.value })}
                        />
                      </label>
                      <label className="registry-create-field">
                        <span className="modal-label">Приоритет</span>
                        <select
                          className="onec-reconnect-input registry-create-select"
                          value={line.priority}
                          onChange={(event) => patchLine(line.key, { priority: event.target.value })}
                        >
                          <option value="">Не указан</option>
                          <option value="Высокий">Высокий</option>
                          <option value="Средний">Средний</option>
                          <option value="Низкий">Низкий</option>
                        </select>
                      </label>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            {error ? <p className="onec-reconnect-form-error">{error}</p> : null}

            <div className="modal-actions registry-create-foot">
              <button type="button" className="btn-light" disabled={busy} onClick={onClose}>
                Отмена
              </button>
              <button type="button" className="btn-primary" disabled={busy} onClick={goConfirm}>
                Далее: проверка
              </button>
            </div>
          </div>
        ) : (
          <div className="registry-create-body">
            <div className="registry-create-confirm">
              <p>
                <b>О чём:</b> {draft.topic.trim()}
              </p>
              <p>
                <b>Основание:</b> {draft.basis.trim() || '—'}
              </p>
              <p>
                <b>Руководитель:</b> {draft.customer.trim()}
              </p>
              <p>
                <b>Срок устранения:</b> {draft.due}
              </p>
              <p>
                <b>Задач:</b> {draft.lines.filter((line) => line.text.trim()).length}
              </p>
              <ul className="registry-create-confirm-lines">
                {draft.lines
                  .filter((line) => line.text.trim())
                  .map((line, index) => (
                    <li key={line.key}>
                      {index + 1}. {line.text.trim()}
                      {line.executor.trim() ? ` — ${line.executor.trim()}` : ''}
                    </li>
                  ))}
              </ul>
            </div>

            <label className="registry-create-confirm-check">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              Подтверждаю создание документа в 1С (запись необратима без ручной отмены в ERP)
            </label>

            {error ? <p className="onec-reconnect-form-error">{error}</p> : null}

            <div className="modal-actions registry-create-foot">
              <button
                type="button"
                className="btn-light"
                disabled={busy}
                onClick={() => {
                  setStep('form')
                  setError('')
                }}
              >
                Назад
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={busy || !confirmed}
                onClick={() => void submitCreate()}
              >
                {busy ? 'Создаём…' : 'Создать в 1С'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
