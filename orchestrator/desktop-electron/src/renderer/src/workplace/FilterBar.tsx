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
}

export function FilterBar({
  query,
  onQuery,
  queryPlaceholder,
  chips,
  onReset,
  children,
  extra
}: FilterBarProps): React.JSX.Element {
  const applied = useMemo(() => chips.filter((item) => item.label), [chips])
  return (
    <div className="wp-filters">
      <div className="wp-filters-row">
        <input
          className="wp-search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={queryPlaceholder}
        />
        {children}
        {extra}
        <button className="btn-ghost wp-reset" type="button" onClick={onReset}>
          Сбросить
        </button>
      </div>
      {applied.length > 0 && (
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
        </div>
      )}
    </div>
  )
}
