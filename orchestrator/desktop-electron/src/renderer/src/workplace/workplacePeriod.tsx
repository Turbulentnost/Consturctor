import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from 'react'
import { KpiRangePicker, type KpiRangeShortcut } from '../pages/KpiRangePicker'
import { currentWeekRange, rollingKpiRange } from './kpiPeriod'

const STORAGE_KEY = 'orch-workplace-period-v1'

type StoredPeriod = {
  from: string
  to: string
  shortcut: KpiRangeShortcut | null
}

function isIsoDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
}

function readStoredPeriod(): StoredPeriod {
  const fallback: StoredPeriod = { ...currentWeekRange(), shortcut: null }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<StoredPeriod>
    const from = isIsoDay(parsed.from || '') ? String(parsed.from) : fallback.from
    const to = isIsoDay(parsed.to || '') ? String(parsed.to) : fallback.to
    const shortcut =
      parsed.shortcut === '7' || parsed.shortcut === '30' || parsed.shortcut === '90'
        ? parsed.shortcut
        : null
    return { from, to, shortcut }
  } catch {
    return fallback
  }
}

type WorkplacePeriodContextValue = {
  from: string
  to: string
  shortcut: KpiRangeShortcut | null
  setRange: (next: { from: string; to: string }) => void
  applyShortcut: (days: KpiRangeShortcut) => void
}

const WorkplacePeriodContext = createContext<WorkplacePeriodContextValue | null>(null)

export function WorkplacePeriodProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const [state, setState] = useState<StoredPeriod>(() => readStoredPeriod())

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      /* ignore */
    }
  }, [state])

  const setRange = useCallback((next: { from: string; to: string }) => {
    setState((prev) => ({
      from: next.from,
      to: next.to,
      shortcut: null
    }))
  }, [])

  const applyShortcut = useCallback((days: KpiRangeShortcut) => {
    const next = rollingKpiRange(days)
    setState({ ...next, shortcut: days })
  }, [])

  const value = useMemo(
    () => ({
      from: state.from,
      to: state.to,
      shortcut: state.shortcut,
      setRange,
      applyShortcut
    }),
    [state, setRange, applyShortcut]
  )

  return <WorkplacePeriodContext.Provider value={value}>{children}</WorkplacePeriodContext.Provider>
}

export function useWorkplacePeriod(): WorkplacePeriodContextValue {
  const ctx = useContext(WorkplacePeriodContext)
  if (!ctx) {
    throw new Error('useWorkplacePeriod must be used within WorkplacePeriodProvider')
  }
  return ctx
}

/** KPI-календарь периода — первый элемент в полосе фильтров вкладок. */
export function WorkplaceGlobalRangePicker(): React.JSX.Element {
  const { from, to, shortcut, setRange, applyShortcut } = useWorkplacePeriod()
  return (
    <div className="workplace-global-period">
      <KpiRangePicker
        from={from}
        to={to}
        shortcut={shortcut}
        onApply={setRange}
        onShortcut={applyShortcut}
      />
    </div>
  )
}

/** Месячный период для KPI: выбор месяца всегда раскрывается в его полные границы. */
export function WorkplaceGlobalMonthPicker(): React.JSX.Element {
  const { from, to, setRange } = useWorkplacePeriod()
  const month = (to || from || new Date().toISOString()).slice(0, 7)

  const monthRange = useCallback((value: string): { from: string; to: string } | null => {
    if (!/^\d{4}-\d{2}$/.test(value)) return null
    const [yearText, monthText] = value.split('-')
    const year = Number(yearText)
    const monthNumber = Number(monthText)
    const lastDay = new Date(year, monthNumber, 0).getDate()
    return {
      from: `${value}-01`,
      to: `${value}-${String(lastDay).padStart(2, '0')}`
    }
  }, [])

  useEffect(() => {
    const fullMonth = monthRange(month)
    if (fullMonth && (from !== fullMonth.from || to !== fullMonth.to)) setRange(fullMonth)
  }, [from, month, monthRange, setRange, to])

  const selectMonth = (value: string): void => {
    const fullMonth = monthRange(value)
    if (fullMonth) setRange(fullMonth)
  }

  return (
    <div className="workplace-global-period">
      <input
        className="workplace-month-picker"
        type="month"
        value={month}
        aria-label="Месяц отчёта"
        onChange={(event) => selectMonth(event.target.value)}
      />
    </div>
  )
}
