import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Calendar,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Plus,
  RefreshCw,
  X
} from 'lucide-react'
import { api } from '../../api/client'
import { FioSuggest } from '../../components/FioSuggest'
import {
  addDays,
  DAYS_SHORT,
  formatPeriod,
  mondayOf,
  MONTH_TITLE,
  MONTHS_GEN,
  sameDay,
  type CalendarView
} from '../../utils/calendar'
import { formatSurnameInitials } from '../../workplace/tileFilters'
import type { MeetingQuickFilters } from '../../workplace/meetingCalendars'
import './meetingsPanel.css'

export type MeetingCalendarRow = {
  person: string
  color: string
  visible: boolean
  removable: boolean
  hint: string
}

const VIEWS: { id: CalendarView; label: string }[] = [
  { id: 'day', label: 'День' },
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' }
]

function monthTitle(month: Date): string {
  const name = MONTH_TITLE[month.getMonth() + 1]
  return `${name.charAt(0).toLocaleUpperCase('ru')}${name.slice(1)} ${month.getFullYear()}`
}

const QUICK_FILTERS: { id: keyof MeetingQuickFilters; label: string }[] = [
  { id: 'mineOnly', label: 'Только мои' },
  { id: 'withSelected', label: 'С участием выбранных' },
  { id: 'noConflicts', label: 'Без конфликтов' },
  { id: 'importantOnly', label: 'Только важные' }
]

/** Дни, которые попадают в текущий период календаря — их подсвечиваем в мини-месяце. */
function viewWindow(view: CalendarView, anchor: Date): { from: Date; to: Date } {
  if (view === 'day') {
    const day = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
    return { from: day, to: day }
  }
  if (view === 'month') {
    return {
      from: new Date(anchor.getFullYear(), anchor.getMonth(), 1),
      to: new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)
    }
  }
  const from = mondayOf(anchor)
  return { from, to: addDays(from, 6) }
}

function MiniMonth({
  month,
  anchor,
  view,
  onPickDay
}: {
  month: Date
  anchor: Date
  view: CalendarView
  onPickDay: (day: Date) => void
}): React.JSX.Element {
  const today = new Date()
  const cells = useMemo(() => {
    const start = mondayOf(new Date(month.getFullYear(), month.getMonth(), 1))
    return Array.from({ length: 42 }, (_, index) => addDays(start, index))
  }, [month])
  const period = viewWindow(view, anchor)

  return (
    <div className="meet-rail-mini">
      <div className="meet-rail-mini-week">
        {DAYS_SHORT.map((name) => (
          <span key={name}>{name}</span>
        ))}
      </div>
      <div className="meet-rail-mini-grid">
        {cells.map((day) => {
          const classes = ['meet-rail-mini-day']
          if (day.getMonth() !== month.getMonth()) classes.push('is-out')
          if (day >= period.from && day <= period.to) classes.push('is-period')
          if (sameDay(day, anchor)) classes.push('is-anchor')
          if (sameDay(day, today)) classes.push('is-today')
          return (
            <button
              key={day.toISOString()}
              type="button"
              className={classes.join(' ')}
              onClick={() => onPickDay(day)}
            >
              {day.getDate()}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function MeetingsSidePanel({
  view,
  anchor,
  onView,
  onShift,
  onToday,
  onPickDay,
  calendars,
  onToggleCalendar,
  onMoveCalendar,
  onRemoveCalendar,
  onAddCalendar,
  filters,
  onFilters,
  loading,
  syncedAt,
  onRefresh
}: {
  view: CalendarView
  anchor: Date
  onView: (view: CalendarView) => void
  onShift: (step: number) => void
  onToday: () => void
  onPickDay: (day: Date) => void
  calendars: MeetingCalendarRow[]
  onToggleCalendar: (person: string) => void
  onMoveCalendar: (person: string, step: number) => void
  onRemoveCalendar: (person: string) => void
  /** Возвращает текст ошибки, если календарь уже открыт. */
  onAddCalendar: (person: string) => string
  filters: MeetingQuickFilters
  onFilters: (next: MeetingQuickFilters) => void
  loading: boolean
  syncedAt: string
  onRefresh: () => void
}): React.JSX.Element {
  const [month, setMonth] = useState(() => new Date(anchor.getFullYear(), anchor.getMonth(), 1))
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    setMonth(new Date(anchor.getFullYear(), anchor.getMonth(), 1))
  }, [anchor])

  const closeAdd = useCallback(() => {
    setAdding(false)
    setName('')
    setNote('')
  }, [])

  const addPerson = useCallback(
    (person: string) => {
      const error = onAddCalendar(person)
      if (error) {
        setNote(error)
        return
      }
      closeAdd()
    },
    [onAddCalendar, closeAdd]
  )

  /** Ввели фамилию и нажали Enter — добавляем найденного сотрудника, а не текст из поля. */
  const resolveAndAdd = useCallback(async () => {
    const text = name.trim()
    if (text.length < 2) return
    setNote('Ищем сотрудника…')
    const found = await api.searchUsers(text).catch(() => [])
    const exact = found.find((item) => item.toLocaleLowerCase('ru') === text.toLocaleLowerCase('ru'))
    if (exact) {
      addPerson(exact)
      return
    }
    if (found.length === 1) {
      addPerson(found[0])
      return
    }
    setNote(found.length ? 'Нашли несколько — выберите из списка' : 'Такого сотрудника не нашли')
  }, [name, addPerson])

  const hasOthers = calendars.some((row) => row.removable && row.visible)
  const today = new Date()

  return (
    <div className="wp-card meet-rail">
      <div className="meet-rail-period">
        <button
          type="button"
          className="meet-rail-arrow"
          aria-label="Предыдущий период"
          onClick={() => onShift(-1)}
        >
          <ChevronLeft size={14} aria-hidden />
        </button>
        <span className="meet-rail-period-text">
          <Calendar size={13} aria-hidden />
          {formatPeriod(view, anchor)}
        </span>
        <button
          type="button"
          className="meet-rail-arrow"
          aria-label="Следующий период"
          onClick={() => onShift(1)}
        >
          <ChevronRight size={14} aria-hidden />
        </button>
      </div>

      <div className="meet-rail-views" role="group" aria-label="Масштаб календаря">
        {VIEWS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`meet-rail-view${view === item.id ? ' is-active' : ''}`}
            aria-pressed={view === item.id}
            onClick={() => onView(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="meet-rail-mini-head">
        <button
          type="button"
          className="meet-rail-arrow"
          aria-label="Предыдущий месяц"
          onClick={() => setMonth((current) => new Date(current.getFullYear(), current.getMonth() - 1, 1))}
        >
          <ChevronLeft size={14} aria-hidden />
        </button>
        <span>{monthTitle(month)}</span>
        <button
          type="button"
          className="meet-rail-arrow"
          aria-label="Следующий месяц"
          onClick={() => setMonth((current) => new Date(current.getFullYear(), current.getMonth() + 1, 1))}
        >
          <ChevronRight size={14} aria-hidden />
        </button>
      </div>
      <MiniMonth month={month} anchor={anchor} view={view} onPickDay={onPickDay} />
      <button
        type="button"
        className="meet-rail-today"
        onClick={onToday}
        disabled={sameDay(anchor, today)}
      >
        Сегодня, {today.getDate()} {MONTHS_GEN[today.getMonth() + 1]}
      </button>

      <section className="meet-rail-block">
        <div className="meet-rail-block-head">
          <h4>Календари</h4>
          <button
            type="button"
            className="meet-rail-add"
            aria-label={adding ? 'Закрыть добавление' : 'Добавить календарь'}
            aria-expanded={adding}
            onClick={() => (adding ? closeAdd() : setAdding(true))}
          >
            {adding ? <X size={14} aria-hidden /> : <Plus size={14} aria-hidden />}
          </button>
        </div>
        {adding ? (
          <div className="meet-rail-add-form">
            <FioSuggest
              value={name}
              autoFocus
              placeholder="Начните вводить фамилию"
              inputClassName="meet-rail-add-input"
              onChange={(value) => {
                setName(value)
                setNote('')
              }}
              onSelect={(value) => addPerson(value)}
              onEnter={() => void resolveAndAdd()}
            />
            <p className="meet-rail-add-note">{note || 'Выберите сотрудника из списка'}</p>
          </div>
        ) : null}
        <p className="meet-rail-hint">
          Порядок = приоритет: в пересечении видно совещание того, кто выше.
        </p>
        <ul className="meet-rail-calendars">
          {calendars.map((row, index) => (
            <li key={row.person} className="meet-rail-calendar" title={row.hint || row.person}>
              <label className="meet-rail-calendar-label">
                <input
                  type="checkbox"
                  checked={row.visible}
                  onChange={() => onToggleCalendar(row.person)}
                />
                <span className="meet-rail-calendar-dot" style={{ background: row.color }} aria-hidden />
                <span className="meet-rail-calendar-name">{formatSurnameInitials(row.person)}</span>
              </label>
              <span className="meet-rail-calendar-tools">
                <button
                  type="button"
                  className="meet-rail-calendar-move"
                  aria-label={`Поднять приоритет ${row.person}`}
                  disabled={index === 0}
                  onClick={() => onMoveCalendar(row.person, -1)}
                >
                  <ChevronUp size={12} aria-hidden />
                </button>
                <button
                  type="button"
                  className="meet-rail-calendar-move"
                  aria-label={`Опустить приоритет ${row.person}`}
                  disabled={index === calendars.length - 1}
                  onClick={() => onMoveCalendar(row.person, 1)}
                >
                  <ChevronDown size={12} aria-hidden />
                </button>
                {row.removable ? (
                  <button
                    type="button"
                    className="meet-rail-calendar-remove"
                    aria-label={`Убрать календарь ${row.person}`}
                    onClick={() => onRemoveCalendar(row.person)}
                  >
                    <X size={13} aria-hidden />
                  </button>
                ) : (
                  <span className="meet-rail-calendar-move is-placeholder" aria-hidden />
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="meet-rail-block">
        <h4>Быстрые фильтры</h4>
        <ul className="meet-rail-quick">
          {QUICK_FILTERS.map((item) => {
            const disabled = item.id === 'withSelected' && !hasOthers
            return (
              <li key={item.id}>
                <label className={disabled ? 'is-disabled' : ''}>
                  <input
                    type="checkbox"
                    checked={filters[item.id]}
                    disabled={disabled}
                    onChange={(event) => onFilters({ ...filters, [item.id]: event.target.checked })}
                  />
                  <span>{item.label}</span>
                </label>
              </li>
            )
          })}
        </ul>
      </section>

      <footer className="meet-rail-sync">
        <span>{loading ? 'Читаем Outlook…' : syncedAt ? `Outlook · обновлено ${syncedAt}` : 'Outlook'}</span>
        <button
          type="button"
          className="meet-rail-arrow"
          aria-label="Обновить из Outlook"
          onClick={onRefresh}
          disabled={loading}
        >
          <RefreshCw size={13} aria-hidden />
        </button>
      </footer>
    </div>
  )
}
