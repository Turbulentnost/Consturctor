import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Lock, Plus, Trash2, X } from 'lucide-react'
import { api } from '../../api/client'
import { meetingInstanceKey, type MeetingEvent } from '../../utils/outlookMeetings'
import {
  createProtocolInOneC,
  draftFromMeeting,
  draftFromOnecForm,
  fetchProtocolForm,
  listMeetingRooms,
  newProtocolRowKey,
  searchMeetingThemes,
  updateProtocolInOneC,
  type MeetingRoom,
  type OnecProtocolForm,
  type ProtocolCreateDraft,
  type ProtocolCreateResult,
  type ProtocolDecisionDraft,
  type ProtocolQuestionDraft,
  type ProtocolTaskDraft,
  type ThemeHint
} from '../../workplace/meetingProtocolCreate'
import { FioCombobox } from './FioCombobox'
import './docflowCreate.css'

const MISSING_ROOM = '__missing_room__'
const ALL_EMPLOYEES_LIMIT = 20000
const MEETING_TYPES = ['Отчетное', 'Внеплановое', 'Селекторное']

type ProtocolFormTab = 'main' | 'attendees' | 'agenda' | 'tasks' | 'decisions'
type Pending = 'save' | 'save-close' | null

function filled(rows: { question?: string; text?: string }[], key: 'question' | 'text'): number {
  return rows.filter((row) => (row[key] || '').trim()).length
}

function Row({
  label,
  required,
  wide,
  children
}: {
  label: string
  required?: boolean
  wide?: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div className={`df1c-row${wide ? ' df1c-row--wide' : ''}${required ? ' is-required' : ''}`}>
      <label className="df1c-label">{label}</label>
      <div className="df1c-control">{children}</div>
    </div>
  )
}

export function MeetingProtocolForm({
  open,
  meeting,
  actorFio,
  mode = 'create',
  refKey = '',
  onClose,
  onCreated
}: {
  open: boolean
  meeting: MeetingEvent
  actorFio: string
  /** create — новый черновик из данных встречи; edit — загрузить протокол refKey из 1С и сохранить (PATCH). */
  mode?: 'create' | 'edit'
  refKey?: string
  onClose: () => void
  onCreated: (result: ProtocolCreateResult) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const isEdit = mode === 'edit'
  const [draft, setDraft] = useState<ProtocolCreateDraft>(() => draftFromMeeting(meeting, actorFio))
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [card, setCard] = useState<OnecProtocolForm | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState<ProtocolFormTab>('main')
  const [pending, setPending] = useState<Pending>(null)
  const [persistKey, setPersistKey] = useState('')
  const [savedNumber, setSavedNumber] = useState('')
  const [sealed, setSealed] = useState(false)
  const [fioHints, setFioHints] = useState<string[]>([])
  const [themes, setThemes] = useState<ThemeHint[]>([])
  const [rooms, setRooms] = useState<MeetingRoom[]>([])
  const readOnly = isEdit && card !== null && !card.editable
  const meetingRef = useRef(meeting)
  meetingRef.current = meeting
  const meetingKey = meetingInstanceKey(meeting)

  useEffect(() => {
    if (!open) return
    setDraft(draftFromMeeting(meetingRef.current, actorFio))
    setBusy(false)
    setError('')
    setNotice('')
    setTab('main')
    setPending(null)
    setPersistKey(isEdit ? refKey : '')
    setSavedNumber('')
    setSealed(false)
    setThemes([])
    setCard(null)
    setLoadError('')
    if (!isEdit) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    void fetchProtocolForm(refKey).then((result) => {
      if (cancelled) return
      setLoading(false)
      if (!result.ok) {
        setLoadError(result.error)
        return
      }
      setCard(result.card)
      setDraft(draftFromOnecForm(result.card))
    })
    return () => {
      cancelled = true
    }
  }, [open, meetingKey, actorFio, isEdit, refKey])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void api
      .searchUsers('', ALL_EMPLOYEES_LIMIT)
      .then((items) => (items.length ? items : api.searchUsers('')))
      .then((items) => {
        if (!cancelled) setFioHints(items)
      })
    void listMeetingRooms().then((items) => {
      if (!cancelled) setRooms(items)
    })
    return () => {
      cancelled = true
    }
  }, [open])

  useEffect(() => {
    const name = draft.room.trim().toLowerCase()
    if (!open || draft.roomKey || !name || !rooms.length) return
    const hit = rooms.find((room) => room.name.toLowerCase() === name)
    if (hit) setDraft((current) => (current.roomKey ? current : { ...current, roomKey: hit.key, room: hit.name }))
  }, [open, rooms, draft.room, draft.roomKey])

  useEffect(() => {
    if (!open || notice || readOnly) return
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
  }, [open, notice, readOnly, draft.topic, draft.themeKey])

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
    setNotice('')
  }

  const askSave = (close: boolean): void => {
    if (!draft.topic.trim() || !draft.date.trim()) {
      setTab('main')
      setError('Заполните тему и дату совещания')
      return
    }
    setError('')
    setPending(close ? 'save-close' : 'save')
  }

  const submit = async (close: boolean): Promise<void> => {
    if (busy || readOnly || sealed) return
    setError('')
    setBusy(true)
    try {
      const result = persistKey
        ? await updateProtocolInOneC(draft, persistKey, meeting)
        : await createProtocolInOneC(draft, meeting)
      if (!result.ok) {
        setPending(null)
        setError(result.error || 'Не удалось записать протокол')
        return
      }
      const merged: ProtocolCreateResult = {
        ...result,
        number: result.number || card?.number || savedNumber,
        refKey: result.refKey || persistKey || card?.refKey || refKey
      }
      if (merged.refKey) setPersistKey(merged.refKey)
      else setSealed(true)
      if (merged.number) setSavedNumber(merged.number)
      const unresolved = merged.unresolved?.length
        ? ` Не сопоставлено с 1С: ${merged.unresolved.join('; ')}.`
        : ''
      setNotice((merged.summary || `Записан протокол ${merged.number || ''}`).trim() + unresolved)
      setPending(null)
      onCreated(merged)
      if (close) onClose()
    } finally {
      setBusy(false)
    }
  }

  const number = card?.number || savedNumber
  const title = number ? `Протокол ${number}` : 'Протокол (создание)'
  const posted = Boolean(card?.posted)
  const status = card?.status || (persistKey || number ? 'Подготовлен' : '')
  const lock = busy || loading || readOnly || sealed
  const roomMissing = !draft.roomKey && Boolean(draft.room.trim()) && rooms.length > 0
  const agendaCount = filled(draft.agenda, 'question')
  const taskCount = filled(draft.tasks, 'text')
  const decisionCount = filled(draft.decisions, 'text')
  const attendeeCount = draft.participants
    .split(/\n/)
    .map((line) => line.trim())
    .filter(Boolean).length

  const updateAgenda = (key: string, partial: Partial<ProtocolQuestionDraft>): void => {
    patch({ agenda: draft.agenda.map((item) => (item.key === key ? { ...item, ...partial } : item)) })
  }
  const updateTask = (key: string, partial: Partial<ProtocolTaskDraft>): void => {
    patch({ tasks: draft.tasks.map((item) => (item.key === key ? { ...item, ...partial } : item)) })
  }
  const updateDecision = (key: string, partial: Partial<ProtocolDecisionDraft>): void => {
    patch({ decisions: draft.decisions.map((item) => (item.key === key ? { ...item, ...partial } : item)) })
  }

  return createPortal(
    <div className="modal-overlay df1c-overlay" onClick={() => !busy && onClose()} role="presentation">
      <div
        className="df1c-window"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="df1c-title">
          <h2 id={titleId}>
            {title}
            {posted ? <span className="df1c-badge is-posted">проведён</span> : null}
            {!posted && (persistKey || isEdit) && !loading && !loadError ? <span className="df1c-badge">черновик</span> : null}
            {status ? <span className="df1c-badge is-status">{status}</span> : null}
          </h2>
          <button type="button" className="df1c-close" title="Закрыть" disabled={busy} onClick={onClose}>
            <X size={18} aria-hidden />
          </button>
        </header>

        <nav className="df1c-tabs" role="tablist">
          {(
            [
              ['main', 'Основное'],
              ['attendees', `Присутствующие${attendeeCount ? ` (${attendeeCount})` : ''}`],
              ['agenda', `Повестка${agendaCount ? ` (${agendaCount})` : ''}`],
              ['tasks', `Задачи${taskCount ? ` (${taskCount})` : ''}`],
              ['decisions', `Решения${decisionCount ? ` (${decisionCount})` : ''}`]
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={tab === id ? 'is-active' : ''}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="df1c-toolbar">
          {pending ? (
            <div className="df1c-confirm">
              <span>{pending === 'save-close' ? 'Записать черновик и закрыть форму?' : 'Записать черновик протокола?'}</span>
              <button
                type="button"
                className="df1c-btn df1c-btn--primary"
                disabled={busy}
                onClick={() => void submit(pending === 'save-close')}
              >
                {busy ? 'Записываем…' : 'Записать'}
              </button>
              <button type="button" className="df1c-btn" disabled={busy} onClick={() => setPending(null)}>
                Вернуться
              </button>
            </div>
          ) : (
            <>
              {readOnly || loadError ? null : (
                <>
                  <button type="button" className="df1c-btn df1c-btn--primary" disabled={lock} onClick={() => askSave(false)}>
                    Записать
                  </button>
                  <button type="button" className="df1c-btn" disabled={lock} onClick={() => askSave(true)}>
                    Записать и закрыть
                  </button>
                </>
              )}
              <button type="button" className="df1c-btn" disabled={busy} onClick={onClose}>
                Закрыть
              </button>
            </>
          )}
        </div>

        {error ? <p className="df1c-error">{error}</p> : null}
        {notice && !error ? <p className="df1c-notice">{notice}</p> : null}
        {readOnly ? (
          <p className="df1c-readonly-banner">
            <Lock size={15} aria-hidden />
            Протокол проведён (статус «{card?.status || 'Проведён'}») — правки только в 1С.
          </p>
        ) : null}

        {loading ? (
          <div className="df1c-body">
            <p className="df1c-muted">Читаем протокол из 1С…</p>
          </div>
        ) : loadError ? (
          <div className="df1c-body">
            <p className="df1c-error">{loadError}</p>
          </div>
        ) : (
          <div className="df1c-body">
            <fieldset className="df1c-fieldset" disabled={readOnly}>
              {tab === 'main' ? (
                <>
                  <Row label="Тема совещания" required wide>
                    <input
                      className="df1c-input"
                      type="text"
                      value={draft.topic}
                      placeholder="Как в справочнике «Темы совещаний»"
                      onChange={(event) => patch({ topic: event.target.value, themeKey: '' })}
                    />
                    {themes.length ? (
                      <ul className="df1c-themes">
                        {themes.map((theme) => (
                          <li key={theme.key || theme.title}>
                            <button type="button" onClick={() => patch({ topic: theme.title, themeKey: theme.key })}>
                              {theme.title}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </Row>
                  <div className="df1c-columns">
                    <div className="df1c-col">
                      <Row label="Дата совещания" required>
                        <input className="df1c-input df1c-date" type="date" value={draft.date} onChange={(event) => patch({ date: event.target.value })} />
                      </Row>
                      <Row label="Время">
                        <div className="df1c-inline">
                          <span className="df1c-inline-label">с</span>
                          <input className="df1c-input" type="time" value={draft.timeStart} onChange={(event) => patch({ timeStart: event.target.value })} />
                          <span className="df1c-inline-label">по</span>
                          <input className="df1c-input" type="time" value={draft.timeEnd} onChange={(event) => patch({ timeEnd: event.target.value })} />
                        </div>
                      </Row>
                      <Row label="Кабинет">
                        <select
                          className="df1c-input"
                          value={draft.roomKey || (roomMissing ? MISSING_ROOM : '')}
                          disabled={!rooms.length && !draft.roomKey}
                          onChange={(event) => {
                            const hit = rooms.find((room) => room.key === event.target.value)
                            patch(hit ? { roomKey: hit.key, room: hit.name } : { roomKey: '', room: '' })
                          }}
                        >
                          <option value="">{rooms.length ? '— не указан —' : 'Загрузка помещений из 1С…'}</option>
                          {roomMissing ? (
                            <option value={MISSING_ROOM} disabled>
                              «{draft.room}» — нет в 1С
                            </option>
                          ) : null}
                          {draft.roomKey && !rooms.some((room) => room.key === draft.roomKey) ? (
                            <option value={draft.roomKey}>{draft.room || 'Помещение из 1С'}</option>
                          ) : null}
                          {rooms.map((room) => (
                            <option key={room.key} value={room.key}>
                              {room.name}
                            </option>
                          ))}
                        </select>
                        {roomMissing ? <span className="df1c-hint">Помещения «{draft.room}» нет в 1С — выберите кабинет из списка</span> : null}
                      </Row>
                      <Row label="Следующее совещание">
                        <input
                          className="df1c-input df1c-date"
                          type="date"
                          value={draft.nextMeetingDate}
                          onChange={(event) => patch({ nextMeetingDate: event.target.value })}
                        />
                      </Row>
                      <Row label="Вид совещания">
                        <select className="df1c-input" value={draft.meetingType} onChange={(event) => patch({ meetingType: event.target.value })}>
                          {draft.meetingType && !MEETING_TYPES.includes(draft.meetingType) ? (
                            <option value={draft.meetingType}>{draft.meetingType}</option>
                          ) : null}
                          {MEETING_TYPES.map((kind) => (
                            <option key={kind} value={kind}>
                              {kind}
                            </option>
                          ))}
                        </select>
                      </Row>
                    </div>
                    <div className="df1c-col">
                      <Row label="Руководитель">
                        <FioCombobox value={draft.leader} hints={fioHints} placeholder="ФИО из 1С" onChange={(leader) => patch({ leader })} />
                      </Row>
                      <Row label="Проверяющий">
                        <FioCombobox
                          value={draft.responsible}
                          hints={fioHints}
                          placeholder="Пусто — из темы или руководитель"
                          onChange={(responsible) => patch({ responsible })}
                        />
                      </Row>
                      <Row label="Отчётный период с">
                        <input className="df1c-input df1c-date" type="date" value={draft.reportFrom} onChange={(event) => patch({ reportFrom: event.target.value })} />
                      </Row>
                      <Row label="Отчётный период по">
                        <input className="df1c-input df1c-date" type="date" value={draft.reportTo} onChange={(event) => patch({ reportTo: event.target.value })} />
                      </Row>
                      <Row label="Гриф доступа">
                        <input className="df1c-input" type="text" value={draft.access} onChange={(event) => patch({ access: event.target.value })} />
                      </Row>
                      <Row label="Подразделение">
                        <input
                          className="df1c-input"
                          type="text"
                          value={draft.department}
                          placeholder="Пусто — из темы"
                          onChange={(event) => patch({ department: event.target.value })}
                        />
                      </Row>
                      <Row label="Проект">
                        <input
                          className="df1c-input"
                          type="text"
                          value={draft.project}
                          placeholder="Пусто — из темы"
                          onChange={(event) => patch({ project: event.target.value })}
                        />
                      </Row>
                    </div>
                  </div>
                  <Row label="Комментарий" wide>
                    <textarea className="df1c-input df1c-textarea" rows={3} value={draft.comment} onChange={(event) => patch({ comment: event.target.value })} />
                  </Row>
                </>
              ) : null}

              {tab === 'attendees' ? (
                <Row label="Присутствующие" wide>
                  <textarea
                    className="df1c-input df1c-textarea"
                    rows={12}
                    value={draft.participants}
                    placeholder="По одному ФИО на строку"
                    onChange={(event) => patch({ participants: event.target.value })}
                  />
                </Row>
              ) : null}

              {tab === 'agenda' ? (
                <section className="df1c-table">
                  <div className="df1c-table-head">
                    <h3>Повестка совещания</h3>
                    {readOnly ? null : (
                      <button
                        type="button"
                        className="df1c-btn"
                        onClick={() => patch({ agenda: [...draft.agenda, { key: newProtocolRowKey(), question: '', responsible: '' }] })}
                      >
                        <Plus size={14} aria-hidden /> Добавить
                      </button>
                    )}
                  </div>
                  {draft.agenda.length ? (
                    <table>
                      <thead>
                        <tr>
                          <th className="df1c-num">N</th>
                          <th>Вопрос</th>
                          <th>Ответственный</th>
                          {readOnly ? null : <th />}
                        </tr>
                      </thead>
                      <tbody>
                        {draft.agenda.map((row, index) => (
                          <tr key={row.key}>
                            <td className="df1c-num">{index + 1}</td>
                            <td>
                              <input
                                className="df1c-input"
                                type="text"
                                placeholder="Вопрос повестки"
                                value={row.question}
                                onChange={(event) => updateAgenda(row.key, { question: event.target.value })}
                              />
                            </td>
                            <td>
                              <FioCombobox
                                value={row.responsible}
                                hints={fioHints}
                                placeholder="ФИО из 1С"
                                onChange={(responsible) => updateAgenda(row.key, { responsible })}
                              />
                            </td>
                            {readOnly ? null : (
                              <td>
                                <button
                                  type="button"
                                  className="df1c-icon-btn"
                                  title="Удалить строку"
                                  onClick={() => patch({ agenda: draft.agenda.filter((item) => item.key !== row.key) })}
                                >
                                  <Trash2 size={14} aria-hidden />
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="df1c-muted">Вопросов нет</p>
                  )}
                </section>
              ) : null}

              {tab === 'tasks' ? (
                <section className="df1c-table">
                  <div className="df1c-table-head">
                    <h3>Поставленные задачи</h3>
                    {readOnly ? null : (
                      <button
                        type="button"
                        className="df1c-btn"
                        onClick={() =>
                          patch({
                            tasks: [...draft.tasks, { key: newProtocolRowKey(), text: '', executor: '', due: '', priority: '', note: '' }]
                          })
                        }
                      >
                        <Plus size={14} aria-hidden /> Добавить
                      </button>
                    )}
                  </div>
                  {draft.tasks.length ? (
                    <table>
                      <thead>
                        <tr>
                          <th className="df1c-num">N</th>
                          <th>Задача</th>
                          <th>Ответственный</th>
                          <th>Срок</th>
                          <th>Приоритет</th>
                          <th>Примечание</th>
                          {readOnly ? null : <th />}
                        </tr>
                      </thead>
                      <tbody>
                        {draft.tasks.map((row, index) => (
                          <tr key={row.key}>
                            <td className="df1c-num">{index + 1}</td>
                            <td>
                              <textarea
                                className="df1c-input df1c-textarea"
                                rows={2}
                                placeholder="Текст задачи"
                                value={row.text}
                                onChange={(event) => updateTask(row.key, { text: event.target.value })}
                              />
                            </td>
                            <td>
                              <FioCombobox
                                value={row.executor}
                                hints={fioHints}
                                placeholder="ФИО из 1С"
                                onChange={(executor) => updateTask(row.key, { executor })}
                              />
                            </td>
                            <td>
                              <input className="df1c-input df1c-date" type="date" value={row.due} onChange={(event) => updateTask(row.key, { due: event.target.value })} />
                            </td>
                            <td>
                              <select className="df1c-input" value={row.priority} onChange={(event) => updateTask(row.key, { priority: event.target.value })}>
                                <option value="">Не указан</option>
                                <option value="Высокий">Высокий</option>
                                <option value="Средний">Средний</option>
                                <option value="Низкий">Низкий</option>
                              </select>
                            </td>
                            <td>
                              <input className="df1c-input" type="text" value={row.note} onChange={(event) => updateTask(row.key, { note: event.target.value })} />
                            </td>
                            {readOnly ? null : (
                              <td>
                                <button
                                  type="button"
                                  className="df1c-icon-btn"
                                  title="Удалить строку"
                                  onClick={() => patch({ tasks: draft.tasks.filter((item) => item.key !== row.key) })}
                                >
                                  <Trash2 size={14} aria-hidden />
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="df1c-muted">Задач нет</p>
                  )}
                </section>
              ) : null}

              {tab === 'decisions' ? (
                <section className="df1c-table">
                  <div className="df1c-table-head">
                    <h3>Решения</h3>
                    {readOnly ? null : (
                      <button
                        type="button"
                        className="df1c-btn"
                        onClick={() => patch({ decisions: [...draft.decisions, { key: newProtocolRowKey(), text: '', due: '' }] })}
                      >
                        <Plus size={14} aria-hidden /> Добавить
                      </button>
                    )}
                  </div>
                  {draft.decisions.length ? (
                    <table>
                      <thead>
                        <tr>
                          <th className="df1c-num">N</th>
                          <th>Текст решения</th>
                          <th>Срок</th>
                          {readOnly ? null : <th />}
                        </tr>
                      </thead>
                      <tbody>
                        {draft.decisions.map((row, index) => (
                          <tr key={row.key}>
                            <td className="df1c-num">{index + 1}</td>
                            <td>
                              <textarea
                                className="df1c-input df1c-textarea"
                                rows={2}
                                placeholder="Текст решения"
                                value={row.text}
                                onChange={(event) => updateDecision(row.key, { text: event.target.value })}
                              />
                            </td>
                            <td>
                              <input className="df1c-input df1c-date" type="date" value={row.due} onChange={(event) => updateDecision(row.key, { due: event.target.value })} />
                            </td>
                            {readOnly ? null : (
                              <td>
                                <button
                                  type="button"
                                  className="df1c-icon-btn"
                                  title="Удалить строку"
                                  onClick={() => patch({ decisions: draft.decisions.filter((item) => item.key !== row.key) })}
                                >
                                  <Trash2 size={14} aria-hidden />
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="df1c-muted">Решений нет</p>
                  )}
                </section>
              ) : null}
            </fieldset>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
