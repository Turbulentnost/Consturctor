import { useEffect, useRef, useState } from 'react'
import { Plus, Users, X } from 'lucide-react'
import { calendarStatusFor, useTrackedCalendars } from '../../utils/trackedCalendars'

export function TrackedCalendarsControl({ fio }: { fio: string }): React.JSX.Element {
  const { people, statuses, add, remove } = useTrackedCalendars(fio)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const submit = (): void => {
    if (!name.trim()) return
    add(name)
    setName('')
  }

  return (
    <div className="tracked-calendars" ref={rootRef}>
      <button
        type="button"
        className={`tracked-calendars-btn${people.length ? ' is-active' : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        title="Показывать совещания сотрудников из Outlook"
      >
        <Users size={14} aria-hidden />
        <span>Календари сотрудников{people.length ? ` (${people.length})` : ''}</span>
      </button>
      {open ? (
        <div className="tracked-calendars-pop" role="dialog" aria-label="Календари сотрудников">
          <p className="tracked-calendars-note">
            Введите ФИО сотрудника — его совещания из Outlook появятся рядом с вашими. Нужен доступ к его календарю.
          </p>
          <form
            className="tracked-calendars-form"
            onSubmit={(event) => {
              event.preventDefault()
              submit()
            }}
          >
            <input
              className="wp-input"
              value={name}
              placeholder="Фамилия Имя Отчество"
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
            <button type="submit" className="btn-light" disabled={!name.trim()}>
              <Plus size={14} aria-hidden />
              Добавить
            </button>
          </form>
          {people.length ? (
            <ul className="tracked-calendars-list">
              {people.map((person) => {
                const status = calendarStatusFor(person, statuses)
                const tone = !status ? 'pending' : status.hint ? 'error' : 'ok'
                const label = !status
                  ? 'обновится при следующей загрузке'
                  : status.hint || `встреч в периоде: ${status.count}`
                return (
                  <li key={person} className="tracked-calendars-item">
                    <span className="tracked-calendars-name">{person}</span>
                    <span className={`tracked-calendars-status is-${tone}`}>{label}</span>
                    <button
                      type="button"
                      className="tracked-calendars-remove"
                      aria-label={`Убрать ${person}`}
                      onClick={() => remove(person)}
                    >
                      <X size={14} aria-hidden />
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="tracked-calendars-empty">Пока никого не отслеживаете.</p>
          )}
        </div>
      ) : null}
    </div>
  )
}
