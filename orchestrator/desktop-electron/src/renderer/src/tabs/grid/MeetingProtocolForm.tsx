import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Trash2, X } from 'lucide-react'
import { api } from '../../api/client'
import type { MeetingEvent } from '../../utils/outlookMeetings'
import {
  createProtocolInOneC,
  draftFromMeeting,
  newProtocolRowKey,
  searchMeetingThemes,
  type ProtocolCreateDraft,
  type ProtocolCreateResult,
  type ThemeHint
} from '../../workplace/meetingProtocolCreate'

function FioField({
  label,
  value,
  onChange,
  listId,
  placeholder
}: {
  label: string
  value: string
  onChange: (value: string) => void
  listId: string
  placeholder?: string
}): React.JSX.Element {
  return (
    <label className="registry-create-field">
      <span className="modal-label">{label}</span>
      <input
        className="onec-reconnect-input"
        type="text"
        list={listId}
        value={value}
        placeholder={placeholder || 'ФИО из 1С'}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

export function MeetingProtocolForm({
  open,
  meeting,
  actorFio,
  onClose,
  onCreated
}: {
  open: boolean
  meeting: MeetingEvent
  actorFio: string
  onClose: () => void
  onCreated: (result: ProtocolCreateResult) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const fioListId = useId()
  const [draft, setDraft] = useState<ProtocolCreateDraft>(() => draftFromMeeting(meeting, actorFio))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<ProtocolCreateResult | null>(null)
  const [fioHints, setFioHints] = useState<string[]>([])
  const [themes, setThemes] = useState<ThemeHint[]>([])

  useEffect(() => {
    if (!open) return
    setDraft(draftFromMeeting(meeting, actorFio))
    setBusy(false)
    setError('')
    setDone(null)
    setThemes([])
  }, [open, meeting, actorFio])

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
    if (!open || done) return
    const query = draft.topic.trim()
    if (query.length < 3 || draft.themeKey) {
      setThemes([])
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void searchMeetingThemes(query).then((items) => {
        if (!cancelled) setThemes(items)
      })
    }, 400)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [open, done, draft.topic, draft.themeKey])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  if (!open) return null

  const patch = (partial: Partial<ProtocolCreateDraft>): void => {
    setDraft((current) => ({ ...current, ...partial }))
  }

  const submit = async (): Promise<void> => {
    if (busy) return
    setError('')
    setBusy(true)
    try {
      const result = await createProtocolInOneC(draft, meeting.id)
      if (!result.ok) {
        setError(result.error || 'Не удалось создать протокол')
        return
      }
      setDone(result)
      onCreated(result)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="modal-overlay registry-create-overlay" onClick={() => !busy && onClose()}>
      <div
        className="modal-card registry-create-dialog"
        role="dialog"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="registry-create-head">
          <div className="registry-create-head-text">
            <div className="modal-title" id={titleId}>
              Протокол в 1С
            </div>
            <p className="registry-create-sub">
              Черновик документа «Протокол» (статус «Подготовлен»). Номер присвоит 1С, проведёт секретарь.
            </p>
          </div>
          <button type="button" className="registry-create-close" disabled={busy} onClick={onClose}>
            <X size={18} aria-hidden />
          </button>
        </header>

        {done ? (
          <div className="registry-create-body">
            <p>{done.summary || `Создан протокол ${done.number || ''}`.trim()}</p>
            {done.number ? (
              <p>
                Номер: <b>{done.number}</b>
              </p>
            ) : null}
            {done.unresolved?.length ? (
              <p className="meeting-protocol-hint">
                Не сопоставлено с 1С: {done.unresolved.join('; ')}. Эти значения записаны в комментарий документа.
              </p>
            ) : null}
            <div className="modal-actions registry-create-foot">
              <button type="button" className="btn-primary" onClick={onClose}>
                Закрыть
              </button>
            </div>
          </div>
        ) : (
          <div className="registry-create-body">
            <datalist id={fioListId}>
              {fioHints.map((fio) => (
                <option key={fio} value={fio} />
              ))}
            </datalist>

            <section className="registry-create-section">
              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">Тема совещания *</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.topic}
                  placeholder="Как в справочнике «Темы совещаний»"
                  onChange={(event) => patch({ topic: event.target.value, themeKey: '' })}
                />
              </label>
              {themes.length ? (
                <ul className="meeting-protocol-themes">
                  {themes.map((theme) => (
                    <li key={theme.key || theme.title}>
                      <button
                        type="button"
                        onClick={() => patch({ topic: theme.title, themeKey: theme.key })}
                      >
                        {theme.title}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section className="registry-create-section registry-create-grid">
              <label className="registry-create-field">
                <span className="modal-label">Дата совещания *</span>
                <input
                  className="onec-reconnect-input"
                  type="date"
                  value={draft.date}
                  onChange={(event) => patch({ date: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">С</span>
                <input
                  className="onec-reconnect-input"
                  type="time"
                  value={draft.timeStart}
                  onChange={(event) => patch({ timeStart: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">По</span>
                <input
                  className="onec-reconnect-input"
                  type="time"
                  value={draft.timeEnd}
                  onChange={(event) => patch({ timeEnd: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Кабинет</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.room}
                  placeholder="Помещение из 1С"
                  onChange={(event) => patch({ room: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Дата следующего совещания</span>
                <input
                  className="onec-reconnect-input"
                  type="date"
                  value={draft.nextMeetingDate}
                  onChange={(event) => patch({ nextMeetingDate: event.target.value })}
                />
              </label>
              <FioField
                label="Руководитель"
                listId={fioListId}
                value={draft.leader}
                onChange={(leader) => patch({ leader })}
              />
              <FioField
                label="Проверяющий"
                listId={fioListId}
                value={draft.responsible}
                placeholder="Пусто — из темы или руководитель"
                onChange={(responsible) => patch({ responsible })}
              />
              <label className="registry-create-field">
                <span className="modal-label">Вид совещания</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.meetingType}
                  onChange={(event) => patch({ meetingType: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Отчётный период с</span>
                <input
                  className="onec-reconnect-input"
                  type="date"
                  value={draft.reportFrom}
                  onChange={(event) => patch({ reportFrom: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Отчётный период по</span>
                <input
                  className="onec-reconnect-input"
                  type="date"
                  value={draft.reportTo}
                  onChange={(event) => patch({ reportTo: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Гриф доступа</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.access}
                  onChange={(event) => patch({ access: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Подразделение</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.department}
                  placeholder="Пусто — из темы"
                  onChange={(event) => patch({ department: event.target.value })}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Проект</span>
                <input
                  className="onec-reconnect-input"
                  type="text"
                  value={draft.project}
                  placeholder="Пусто — из темы"
                  onChange={(event) => patch({ project: event.target.value })}
                />
              </label>
            </section>

            <section className="registry-create-section">
              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">Присутствующие</span>
                <textarea
                  className="onec-reconnect-input registry-create-textarea"
                  rows={3}
                  value={draft.participants}
                  placeholder="По одному ФИО на строку"
                  onChange={(event) => patch({ participants: event.target.value })}
                />
              </label>
            </section>

            <section className="registry-create-section">
              <div className="registry-create-lines-head">
                <h3 className="registry-create-lines-title">Повестка совещания</h3>
                <button
                  type="button"
                  className="btn-light registry-create-add-line"
                  onClick={() =>
                    patch({
                      agenda: [...draft.agenda, { key: newProtocolRowKey(), question: '', responsible: '' }]
                    })
                  }
                >
                  <Plus size={14} aria-hidden /> Вопрос
                </button>
              </div>
              <ul className="registry-create-lines">
                {draft.agenda.map((row, index) => (
                  <li key={row.key} className="registry-create-line-card">
                    <div className="registry-create-line-card-head">
                      <span className="registry-create-line-num">Вопрос {index + 1}</span>
                      <button
                        type="button"
                        className="registry-create-line-remove"
                        disabled={draft.agenda.length <= 1}
                        onClick={() => patch({ agenda: draft.agenda.filter((item) => item.key !== row.key) })}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </div>
                    <input
                      className="onec-reconnect-input"
                      type="text"
                      placeholder="Вопрос повестки"
                      value={row.question}
                      onChange={(event) =>
                        patch({
                          agenda: draft.agenda.map((item) =>
                            item.key === row.key ? { ...item, question: event.target.value } : item
                          )
                        })
                      }
                    />
                    <FioField
                      label="Ответственный"
                      listId={fioListId}
                      value={row.responsible}
                      onChange={(responsible) =>
                        patch({
                          agenda: draft.agenda.map((item) =>
                            item.key === row.key ? { ...item, responsible } : item
                          )
                        })
                      }
                    />
                  </li>
                ))}
              </ul>
            </section>

            <section className="registry-create-section">
              <div className="registry-create-lines-head">
                <h3 className="registry-create-lines-title">Поставленные задачи</h3>
                <button
                  type="button"
                  className="btn-light registry-create-add-line"
                  onClick={() =>
                    patch({
                      tasks: [
                        ...draft.tasks,
                        { key: newProtocolRowKey(), text: '', executor: '', due: '', priority: '', note: '' }
                      ]
                    })
                  }
                >
                  <Plus size={14} aria-hidden /> Задача
                </button>
              </div>
              <ul className="registry-create-lines">
                {draft.tasks.map((row, index) => (
                  <li key={row.key} className="registry-create-line-card">
                    <div className="registry-create-line-card-head">
                      <span className="registry-create-line-num">Задача {index + 1}</span>
                      <button
                        type="button"
                        className="registry-create-line-remove"
                        disabled={draft.tasks.length <= 1}
                        onClick={() => patch({ tasks: draft.tasks.filter((item) => item.key !== row.key) })}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </div>
                    <textarea
                      className="onec-reconnect-input registry-create-line-text"
                      rows={2}
                      placeholder="Текст задачи"
                      value={row.text}
                      onChange={(event) =>
                        patch({
                          tasks: draft.tasks.map((item) =>
                            item.key === row.key ? { ...item, text: event.target.value } : item
                          )
                        })
                      }
                    />
                    <div className="registry-create-line-meta">
                      <FioField
                        label="Ответственный"
                        listId={fioListId}
                        value={row.executor}
                        onChange={(executor) =>
                          patch({
                            tasks: draft.tasks.map((item) =>
                              item.key === row.key ? { ...item, executor } : item
                            )
                          })
                        }
                      />
                      <label className="registry-create-field">
                        <span className="modal-label">Срок исполнения</span>
                        <input
                          className="onec-reconnect-input"
                          type="date"
                          value={row.due}
                          onChange={(event) =>
                            patch({
                              tasks: draft.tasks.map((item) =>
                                item.key === row.key ? { ...item, due: event.target.value } : item
                              )
                            })
                          }
                        />
                      </label>
                      <label className="registry-create-field">
                        <span className="modal-label">Приоритет</span>
                        <select
                          className="onec-reconnect-input registry-create-select"
                          value={row.priority}
                          onChange={(event) =>
                            patch({
                              tasks: draft.tasks.map((item) =>
                                item.key === row.key ? { ...item, priority: event.target.value } : item
                              )
                            })
                          }
                        >
                          <option value="">Не указан</option>
                          <option value="Высокий">Высокий</option>
                          <option value="Средний">Средний</option>
                          <option value="Низкий">Низкий</option>
                        </select>
                      </label>
                    </div>
                    <label className="registry-create-field">
                      <span className="modal-label">Примечание</span>
                      <input
                        className="onec-reconnect-input"
                        type="text"
                        value={row.note}
                        onChange={(event) =>
                          patch({
                            tasks: draft.tasks.map((item) =>
                              item.key === row.key ? { ...item, note: event.target.value } : item
                            )
                          })
                        }
                      />
                    </label>
                  </li>
                ))}
              </ul>
            </section>

            <section className="registry-create-section">
              <div className="registry-create-lines-head">
                <h3 className="registry-create-lines-title">Решения</h3>
                <button
                  type="button"
                  className="btn-light registry-create-add-line"
                  onClick={() =>
                    patch({ decisions: [...draft.decisions, { key: newProtocolRowKey(), text: '', due: '' }] })
                  }
                >
                  <Plus size={14} aria-hidden /> Решение
                </button>
              </div>
              <ul className="registry-create-lines">
                {draft.decisions.map((row, index) => (
                  <li key={row.key} className="registry-create-line-card">
                    <div className="registry-create-line-card-head">
                      <span className="registry-create-line-num">Решение {index + 1}</span>
                      <button
                        type="button"
                        className="registry-create-line-remove"
                        disabled={draft.decisions.length <= 1}
                        onClick={() =>
                          patch({ decisions: draft.decisions.filter((item) => item.key !== row.key) })
                        }
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </div>
                    <textarea
                      className="onec-reconnect-input registry-create-line-text"
                      rows={2}
                      placeholder="Текст решения"
                      value={row.text}
                      onChange={(event) =>
                        patch({
                          decisions: draft.decisions.map((item) =>
                            item.key === row.key ? { ...item, text: event.target.value } : item
                          )
                        })
                      }
                    />
                    <label className="registry-create-field">
                      <span className="modal-label">Срок</span>
                      <input
                        className="onec-reconnect-input"
                        type="date"
                        value={row.due}
                        onChange={(event) =>
                          patch({
                            decisions: draft.decisions.map((item) =>
                              item.key === row.key ? { ...item, due: event.target.value } : item
                            )
                          })
                        }
                      />
                    </label>
                  </li>
                ))}
              </ul>
            </section>

            <label className="registry-create-field registry-create-field--wide">
              <span className="modal-label">Комментарий</span>
              <textarea
                className="onec-reconnect-input registry-create-textarea"
                rows={2}
                value={draft.comment}
                onChange={(event) => patch({ comment: event.target.value })}
              />
            </label>

            {error ? <p className="onec-reconnect-form-error">{error}</p> : null}

            <div className="modal-actions registry-create-foot">
              <button type="button" className="btn-light" disabled={busy} onClick={onClose}>
                Отмена
              </button>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => void submit()}>
                {busy ? 'Создание…' : 'Создать в 1С'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
