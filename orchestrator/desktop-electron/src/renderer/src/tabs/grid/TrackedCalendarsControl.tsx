import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Users, X } from 'lucide-react'
import { calendarStatusFor, useTrackedCalendars } from '../../utils/trackedCalendars'

const POP_WIDTH = 360
const POP_GAP = 6

export function TrackedCalendarsControl({ fio }: { fio: string }): React.JSX.Element {
  const { people, statuses, add, remove } = useTrackedCalendars(fio)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const popRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!open) return
    // Панель в портале: фильтры обрезают overflow, поэтому позицию считаем от кнопки.
    const place = (): void => {
      const rect = rootRef.current?.getBoundingClientRect()
      if (!rect) return
      const width = Math.min(POP_WIDTH, window.innerWidth - 16)
      const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8))
      setPos({ top: rect.bottom + POP_GAP, left })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent): void => {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || popRef.current?.contains(target)) return
      setOpen(false)
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

  const pop =
    open && pos
      ? createPortal(
          <div
            ref={popRef}
            className="tracked-calendars-pop"
            role="dialog"
            aria-label="Календари сотрудников"
            style={{ top: pos.top, left: pos.left }}
          >
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
                className="tracked-calendars-input"
                value={name}
                placeholder="Фамилия Имя Отчество"
                autoFocus
                onChange={(event) => setName(event.target.value)}
              />
              <button type="submit" className="btn-light" disabled={!name.trim()}>
                <Plus size={13} aria-hidden />
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
          </div>,
          document.body
        )
      : null

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
      {pop}
    </div>
  )
}
