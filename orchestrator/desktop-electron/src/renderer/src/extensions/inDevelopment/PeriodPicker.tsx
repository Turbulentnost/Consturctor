import { useEffect, useRef, useState } from 'react'
import { Calendar, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  MONTHS,
  WEEKDAYS,
  monthCells,
  parts,
  rangeLabel,
  spanDays,
  todayIso,
  type DayRange
} from './periodDates'

export function PeriodPicker({
  value,
  onChange
}: {
  value: DayRange
  onChange: (next: DayRange) => void
}): React.JSX.Element {
  const rootRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const dragStart = useRef<string | null>(null)
  const dragEnd = useRef<string | null>(null)
  const dragMoved = useRef(false)
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [draft, setDraft] = useState<DayRange | null>(null)
  const initial = parts(value.from)
  const [year, setYear] = useState(initial.year)
  const [month, setMonth] = useState(initial.month)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onDown = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown)
    }
  }, [open])

  function shiftMonth(step: number): void {
    const next = new Date(year, month + step, 1)
    setYear(next.getFullYear())
    setMonth(next.getMonth())
  }

  function dayAt(event: { clientX: number; clientY: number }): string | null {
    const node = document.elementFromPoint(event.clientX, event.clientY)
    return node?.closest<HTMLElement>('[data-day]')?.dataset.day ?? null
  }

  function finish(day: string): void {
    const start = dragStart.current
    dragStart.current = null
    setDraft(null)
    setHover(null)
    if (!start) return
    if (dragMoved.current && day !== start) {
      setAnchor(null)
      onChange(spanDays(start, day))
      return
    }
    if (anchor && anchor !== day) {
      setAnchor(null)
      onChange(spanDays(anchor, day))
      return
    }
    setAnchor(day)
    onChange({ from: day, to: day })
  }

  const shown = draft ?? (anchor && hover ? spanDays(anchor, hover) : value)
  const today = todayIso()

  return (
    <div ref={rootRef} className={open ? 'period-picker is-open' : 'period-picker'}>
      <button
        type="button"
        className="period-picker-trigger"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((current) => !current)}
      >
        <Calendar size={16} strokeWidth={1.8} aria-hidden />
        <span className="period-picker-kicker">Период</span>
        <span className="period-picker-value">{rangeLabel(value)}</span>
        <ChevronDown size={16} strokeWidth={1.8} aria-hidden />
      </button>
      {open ? (
        <div className="period-popover" role="dialog" aria-label="Выбор периода">
          <div className="period-nav">
            <button type="button" aria-label="Предыдущий год" onClick={() => setYear((current) => current - 1)}>
              <ChevronLeft size={16} aria-hidden />
            </button>
            <span>{year}</span>
            <button type="button" aria-label="Следующий год" onClick={() => setYear((current) => current + 1)}>
              <ChevronRight size={16} aria-hidden />
            </button>
          </div>
          <div className="period-nav">
            <button type="button" aria-label="Предыдущий месяц" onClick={() => shiftMonth(-1)}>
              <ChevronLeft size={16} aria-hidden />
            </button>
            <span>{MONTHS[month]}</span>
            <button type="button" aria-label="Следующий месяц" onClick={() => shiftMonth(1)}>
              <ChevronRight size={16} aria-hidden />
            </button>
          </div>
          <div className="period-weekdays">
            {WEEKDAYS.map((name) => (
              <span key={name}>{name}</span>
            ))}
          </div>
          <div
            ref={gridRef}
            className="period-grid"
            onPointerDown={(event) => {
              const day = (event.target as HTMLElement).closest<HTMLElement>('[data-day]')?.dataset.day
              if (!day) return
              event.preventDefault()
              gridRef.current?.setPointerCapture(event.pointerId)
              dragStart.current = day
              dragEnd.current = day
              dragMoved.current = false
              setDraft({ from: day, to: day })
            }}
            onPointerMove={(event) => {
              if (!dragStart.current) return
              const day = dayAt(event)
              if (!day) return
              if (day !== dragStart.current) dragMoved.current = true
              dragEnd.current = day
              setDraft(spanDays(dragStart.current, day))
            }}
            onPointerUp={(event) => finish(dayAt(event) || dragEnd.current || dragStart.current || '')}
            onPointerCancel={() => {
              dragStart.current = null
              setDraft(null)
            }}
          >
            {monthCells(year, month).map((day, index) =>
              day ? (
                <button
                  key={day}
                  type="button"
                  data-day={day}
                  className={[
                    'period-day',
                    shown && day >= shown.from && day <= shown.to ? 'is-in' : '',
                    shown && (day === shown.from || day === shown.to) ? 'is-edge' : '',
                    day === today ? 'is-today' : ''
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onMouseEnter={() => {
                    if (anchor && !dragStart.current) setHover(day)
                  }}
                >
                  {parts(day).date}
                </button>
              ) : (
                <span key={`empty-${index}`} />
              )
            )}
          </div>
          <p className="period-hint">Проведите по дням или выберите первый и последний день.</p>
        </div>
      ) : null}
    </div>
  )
}
