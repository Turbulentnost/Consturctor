import { useMemo, type ReactNode } from 'react'

export interface Chip {
  id: string
  label: string
  onClear?: () => void
}

interface FilterBarProps {
  query: string
  onQuery: (value: string) => void
  queryPlaceholder: string
  chips: Chip[]
  onReset: () => void
  children?: ReactNode
  extra?: ReactNode
  /** Controls below the main row (e.g. sort) before chips */
  secondary?: ReactNode
  showSearchIcon?: boolean
  className?: string
}

export function FilterBar({
  query,
  onQuery,
  queryPlaceholder,
  chips,
  onReset,
  children,
  extra,
  secondary,
  showSearchIcon = true,
  className = ''
}: FilterBarProps): React.JSX.Element {
  const applied = useMemo(() => chips.filter((item) => item.label), [chips])
  return (
    <div className={`wp-filters${className ? ` ${className}` : ''}`}>
      <div className="wp-filters-row">
        <label className={`wp-search-wrap${showSearchIcon ? ' has-icon' : ''}`}>
          {showSearchIcon ? (
            <span className="wp-search-ico" aria-hidden>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" />
                <path d="M16.5 16.5L21 21" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </span>
          ) : null}
          <input
            className="wp-search"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder={queryPlaceholder}
          />
        </label>
        {children}
        {extra}
      </div>
      {secondary ? <div className="wp-filters-secondary">{secondary}</div> : null}
      {applied.length > 0 ? (
        <div className="wp-chips">
          {applied.map((chip) =>
            chip.onClear ? (
              <button key={chip.id} type="button" className="wp-chip wp-chip-btn" onClick={chip.onClear}>
                {chip.label}
                <span aria-hidden>×</span>
              </button>
            ) : (
              <span key={chip.id} className="wp-chip">
                {chip.label}
              </span>
            )
          )}
          <button className="wp-reset-link" type="button" onClick={onReset}>
            Сбросить
          </button>
        </div>
      ) : null}
    </div>
  )
}
