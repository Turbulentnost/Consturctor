import { useEffect, useMemo, useRef, useState } from 'react'
import {
  buildMonthGrid,
  formatAdminDateRange,
  isDateInRange,
  isRangeEdge,
  isSameDay,
  MONTH_LABELS,
  startOfDay,
  type AdminDateRange
} from '../../admin/utils/dateRange'

const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export function OrchDateRangePicker({
  value,
  onChange,
  label = 'Период'
}: {
  value: AdminDateRange
  onChange: (value: AdminDateRange) => void
  label?: string
}): React.JSX.Element {
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [draftStart, setDraftStart] = useState<Date | null>(null)
  const [viewMonth, setViewMonth] = useState(value.end.getMonth())
  const [viewYear, setViewYear] = useState(value.end.getFullYear())

  useEffect(() => {
    function handleClick(event: MouseEvent): void {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleDayClick(date: Date): void {
    const day = startOfDay(date)
    if (!draftStart) {
      setDraftStart(day)
      onChange({ start: day, end: day })
      return
    }
    const start = day.getTime() <= draftStart.getTime() ? day : draftStart
    const end = day.getTime() >= draftStart.getTime() ? day : draftStart
    onChange({ start, end })
    setDraftStart(null)
    setOpen(false)
  }

  function openCalendar(): void {
    setDraftStart(null)
    setViewMonth(value.end.getMonth())
    setViewYear(value.end.getFullYear())
    setOpen((prev) => !prev)
  }

  const cells = useMemo(() => buildMonthGrid(viewYear, viewMonth), [viewMonth, viewYear])
  const today = startOfDay(new Date())

  return (
    <div ref={rootRef} className={`orch-date-range${open ? ' is-open' : ''}`}>
      <button type="button" className="orch-date-range-trigger" onClick={openCalendar}>
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
          <rect x="2.5" y="3" width="11" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.2" fill="none" />
          <path d="M5 2v2M11 2v2M2.5 6h11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <span className="orch-date-range-label">{label}:</span>
        <span>{formatAdminDateRange(value)}</span>
      </button>
      {open ? (
        <div className="orch-date-range-popup">
          <div className="orch-date-range-head">
            <button
              type="button"
              className="orch-date-range-nav"
              onClick={() => {
                if (viewMonth === 0) {
                  setViewMonth(11)
                  setViewYear((year) => year - 1)
                } else setViewMonth((month) => month - 1)
              }}
            >
              ‹
            </button>
            <strong>
              {MONTH_LABELS[viewMonth]} {viewYear}
            </strong>
            <button
              type="button"
              className="orch-date-range-nav"
              onClick={() => {
                if (viewMonth === 11) {
                  setViewMonth(0)
                  setViewYear((year) => year + 1)
                } else setViewMonth((month) => month + 1)
              }}
            >
              ›
            </button>
          </div>
          <div className="orch-date-range-weekdays">
            {WEEKDAY_LABELS.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
          <div className="orch-date-range-grid">
            {cells.map(({ date, muted }) => {
              const inRange = isDateInRange(date, value)
              const edge = isRangeEdge(date, value)
              const isToday = isSameDay(date, today)
              return (
                <button
                  key={date.toISOString()}
                  type="button"
                  className={[
                    muted ? 'muted' : '',
                    inRange ? 'in-range' : '',
                    edge ? 'edge' : '',
                    isToday ? 'today' : ''
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => handleDayClick(date)}
                >
                  {date.getDate()}
                </button>
              )
            })}
          </div>
          <div className="orch-date-range-hint">Выберите начало и конец периода</div>
        </div>
      ) : null}
    </div>
  )
}
