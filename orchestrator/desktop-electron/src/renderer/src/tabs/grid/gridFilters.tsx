import { SpecIconCalendar, SpecIconSearch } from '../../workplace/specV04Icons'
import { SpecFilters } from '../../workplace/specV04Components'

export type GridFilterOption = { value: string; label: string }

export type GridFilterSelectField = {
  id: string
  value: string
  emptyLabel: string
  options: GridFilterOption[]
  onChange: (value: string) => void
}

export type GridFilterToggleField = {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}

export function uniqueFilterValues(values: Array<string | undefined | null>): string[] {
  return [...new Set(values.map((value) => String(value || '').trim()).filter((value) => value && value !== '—'))].sort(
    (left, right) => left.localeCompare(right, 'ru')
  )
}

export function toFilterOptions(values: string[]): GridFilterOption[] {
  return values.map((value) => ({ value, label: value }))
}

export function GridFilterBar({
  search,
  selects,
  sort,
  toggles,
  onReset,
  extra
}: {
  search?: { value: string; onChange: (value: string) => void; placeholder?: string }
  selects?: GridFilterSelectField[]
  sort?: GridFilterSelectField
  toggles?: GridFilterToggleField[]
  onReset: () => void
  extra?: React.ReactNode
}): React.JSX.Element {
  return (
    <SpecFilters layout="row">
      {(selects || []).map((field) => (
        <select
          key={field.id}
          className="wp-select spec-filter-field"
          value={field.value}
          onChange={(event) => field.onChange(event.target.value)}
        >
          <option value="">{field.emptyLabel}</option>
          {field.options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ))}
      {search ? (
        <label className="spec-filter-input spec-filter-search">
          <SpecIconSearch />
          <input
            className="wp-search"
            type="search"
            value={search.value}
            placeholder={search.placeholder || 'Поиск…'}
            onChange={(event) => search.onChange(event.target.value)}
          />
        </label>
      ) : null}
      {sort ? (
        <label className="spec-filter-input spec-filter-period">
          <SpecIconCalendar />
          <select
            className="wp-select"
            value={sort.value}
            onChange={(event) => sort.onChange(event.target.value)}
          >
            {sort.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {(toggles || []).map((toggle) => (
        <label key={toggle.id} className="spec-v04-toggle-inline spec-filter-field">
          <input
            type="checkbox"
            checked={toggle.checked}
            onChange={(event) => toggle.onChange(event.target.checked)}
          />
          {toggle.label}
        </label>
      ))}
      {extra}
      <button type="button" className="spec-filter-reset" onClick={onReset}>
        Сбросить фильтры
      </button>
    </SpecFilters>
  )
}

/** Search-only fallback for tabs that have not wired selects yet. */
export function StandardGridFilters({
  searchPlaceholder = 'Поиск…',
  searchValue = '',
  onSearchChange,
  onReset
}: {
  searchPlaceholder?: string
  searchValue?: string
  onSearchChange?: (value: string) => void
  onReset?: () => void
}): React.JSX.Element {
  return (
    <GridFilterBar
      search={
        onSearchChange
          ? { value: searchValue, onChange: onSearchChange, placeholder: searchPlaceholder }
          : undefined
      }
      onReset={() => {
        onSearchChange?.('')
        onReset?.()
      }}
    />
  )
}
