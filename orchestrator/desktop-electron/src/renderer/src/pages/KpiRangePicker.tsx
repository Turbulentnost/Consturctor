import { useEffect, useMemo, useRef, useState } from 'react'
import { addDays, DAYS_SHORT, mondayOf, MONTH_TITLE } from '../utils/calendar'

const iconCalendar = new URL('../../../temp/KPI/calendar.png', import.meta.url).href

/** Abbreviated Russian months for the KPI range label (mockup: «авг.»). */
export const KPI_MONTHS_SHORT = [
  'янв.',
  'февр.',
  'марта',
  'апр.',
  'мая',
  'июня',
  'июля',
  'авг.',
  'сент.',
  'окт.',
  'нояб.',
  'дек.'
] as const

export type KpiRangeShortcut = '7' | '30' | '90'

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

export function dayKeyFromDate(stamp: Date): string {
  return `${stamp.getFullYear()}-${pad2(stamp.getMonth() + 1)}-${pad2(stamp.getDate())}`
}

function parseDayKey(key: string): Date | null {
  const [year, month, day] = key.split('-').map(Number)
  if (!year || !month || !day) return null
  const stamp = new Date(year, month - 1, day)
  return Number.isNaN(stamp.getTime()) ? null : stamp
}

function orderedKeys(a: string, b: string): { from: string; to: string } {
  return a <= b ? { from: a, to: b } : { from: b, to: a }
}

function inInclusiveRange(key: string, from: string, to: string): boolean {
  if (!from || !to) return false
  const { from: lo, to: hi } = orderedKeys(from, to)
  return key >= lo && key <= hi
}

export function formatKpiRangeLabel(fromKey: string, toKey: string): string {
  const from = parseDayKey(fromKey)
  const to = parseDayKey(toKey)
  if (!from || !to) return fromKey && toKey ? `${fromKey} – ${toKey}` : 'Период'
  const fromDay = pad2(from.getDate())
  const toDay = pad2(to.getDate())
  const fromMon = KPI_MONTHS_SHORT[from.getMonth()]
  const toMon = KPI_MONTHS_SHORT[to.getMonth()]
  const fromYear = from.getFullYear()
  const toYear = to.getFullYear()
  if (fromKey === toKey) return `${fromDay} ${fromMon} ${fromYear}`
  if (from.getMonth() === to.getMonth() && fromYear === toYear) {
    return `${fromDay}–${toDay} ${fromMon} ${fromYear}`
  }
  if (fromYear === toYear) {
    return `${fromDay} ${fromMon} – ${toDay} ${toMon} ${toYear}`
  }
  return `${fromDay} ${fromMon} ${fromYear} – ${toDay} ${toMon} ${toYear}`
}

function monthCells(year: number, month: number): Date[] {
  const start = mondayOf(new Date(year, month, 1))
  return Array.from({ length: 42 }, (_, index) => addDays(start, index))
}

export function KpiRangePicker({
  from,
  to,
  shortcut,
  onApply,
  onShortcut,
  showShortcuts = true
}: {
  from: string
  to: string
  shortcut?: KpiRangeShortcut | null
  onApply: (next: { from: string; to: string }) => void
  onShortcut?: (days: KpiRangeShortcut) => void
  showShortcuts?: boolean
}): React.JSX.Element {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [view, setView] = useState(() => parseDayKey(to) || new Date())
  const [draftFrom, setDraftFrom] = useState(from)
  const [draftTo, setDraftTo] = useState(to)
  const [hoverKey, setHoverKey] = useState('')

  const pickingEnd = Boolean(draftFrom) && !draftTo
  const label = formatKpiRangeLabel(from, to)

  useEffect(() => {
    if (!open) return
    const onDoc = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const openPicker = (): void => {
    const anchor = parseDayKey(to) || new Date()
    setView(new Date(anchor.getFullYear(), anchor.getMonth(), 1))
    setDraftFrom(from)
    setDraftTo(to)
    setHoverKey('')
    setOpen((value) => !value)
  }

  const previewTo = pickingEnd && hoverKey ? hoverKey : draftTo
  const cells = useMemo(() => monthCells(view.getFullYear(), view.getMonth()), [view])
  const today = dayKeyFromDate(new Date())
  const hint = pickingEnd ? 'Выберите дату окончания' : 'Выберите дату начала, затем окончания'
  const draftLabel = draftFrom
    ? formatKpiRangeLabel(draftFrom, previewTo || draftFrom)
    : '—'

  const pickDay = (key: string): void => {
    if (!draftFrom || draftTo) {
      setDraftFrom(key)
      setDraftTo('')
      setHoverKey('')
      return
    }
    const next = orderedKeys(draftFrom, key)
    setDraftFrom(next.from)
    setDraftTo(next.to)
    setHoverKey('')
    onApply(next)
    setOpen(false)
  }

  const applyShortcut = (days: KpiRangeShortcut): void => {
    onShortcut?.(days)
    setOpen(false)
  }

  const shiftMonth = (step: number): void => {
    setView((prev) => new Date(prev.getFullYear(), prev.getMonth() + step, 1))
  }

  return (
    <div className="kpi-range-picker" ref={rootRef}>
      <button
        type="button"
        className={`kpi-range-picker-btn${open ? ' open' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Период ${label}`}
        onClick={openPicker}
      >
        <img src={iconCalendar} alt="" />
        <span>{label}</span>
      </button>
      {open ? (
        <div className="kpi-range-picker-pop" role="dialog" aria-label="Выбор периода">
          <div className="kpi-range-picker-nav">
            <button type="button" className="kpi-range-picker-nav-btn" onClick={() => shiftMonth(-1)} aria-label="Предыдущий месяц">
              ‹
            </button>
            <strong>
              {MONTH_TITLE[view.getMonth() + 1]} {view.getFullYear()}
            </strong>
            <button type="button" className="kpi-range-picker-nav-btn" onClick={() => shiftMonth(1)} aria-label="Следующий месяц">
              ›
            </button>
          </div>
          <div className="kpi-range-picker-week">
            {DAYS_SHORT.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="kpi-range-picker-grid">
            {cells.map((stamp) => {
              const key = dayKeyFromDate(stamp)
              const outside = stamp.getMonth() !== view.getMonth()
              const start = key === draftFrom
              const end = Boolean(previewTo) && key === (previewTo || draftTo)
              const range = inInclusiveRange(key, draftFrom, previewTo || draftFrom)
              const classes = [
                'kpi-range-picker-day',
                outside ? 'outside' : '',
                key === today ? 'today' : '',
                range ? 'in-range' : '',
                start ? 'start' : '',
                end ? 'end' : ''
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <button
                  key={key}
                  type="button"
                  className={classes}
                  onMouseEnter={() => pickingEnd && setHoverKey(key)}
                  onFocus={() => pickingEnd && setHoverKey(key)}
                  onClick={() => pickDay(key)}
                >
                  {stamp.getDate()}
                </button>
              )
            })}
          </div>
          <p className="kpi-range-picker-hint">{hint}</p>
          {showShortcuts && onShortcut ? (
            <div className="kpi-range-picker-shortcuts">
              {(['7', '30', '90'] as const).map((days) => (
                <button
                  key={days}
                  type="button"
                  className={shortcut === days ? 'active' : ''}
                  onClick={() => applyShortcut(days)}
                >
                  {days} дн.
                </button>
              ))}
            </div>
          ) : null}
          <div className="kpi-range-picker-draft">{draftLabel}</div>
        </div>
      ) : null}
    </div>
  )
}
