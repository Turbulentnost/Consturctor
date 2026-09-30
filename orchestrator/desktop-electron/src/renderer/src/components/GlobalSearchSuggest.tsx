import { useEffect, useRef, useState } from 'react'
import { useGlobalSearch } from '../layout/globalSearch'

export function GlobalSearchSuggest({
  inputClassName,
  placeholder = 'Поиск'
}: {
  inputClassName?: string
  placeholder?: string
}): React.JSX.Element {
  const { query, setQuery, results, choose } = useGlobalSearch()
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(-1)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const close = (event: MouseEvent): void => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  useEffect(() => {
    setHighlight(-1)
  }, [query])

  const showPopup = open && query.trim().length > 0

  return (
    <div className={showPopup ? 'global-search-suggest open' : 'global-search-suggest'} ref={wrapRef}>
      <input
        className={inputClassName}
        type="search"
        value={query}
        placeholder={placeholder}
        aria-label="Глобальный поиск"
        aria-expanded={showPopup}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value)
          setOpen(true)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            setHighlight((value) => Math.min(value + 1, results.length - 1))
          } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            setHighlight((value) => Math.max(value - 1, 0))
          } else if (event.key === 'Enter' && highlight >= 0 && results[highlight]) {
            event.preventDefault()
            choose(results[highlight])
            setOpen(false)
          } else if (event.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {showPopup ? (
        <div className="global-search-popup" role="listbox">
          {results.length ? (
            results.map((entry, index) => (
              <button
                key={entry.id}
                type="button"
                role="option"
                aria-selected={index === highlight}
                className={index === highlight ? 'global-search-option active' : 'global-search-option'}
                onMouseEnter={() => setHighlight(index)}
                onMouseDown={(event) => {
                  event.preventDefault()
                  choose(entry)
                  setOpen(false)
                }}
              >
                <span className="global-search-option-title">{entry.title}</span>
                <span className="global-search-option-meta">{entry.subtitle || entry.pageKey}</span>
              </button>
            ))
          ) : (
            <div className="global-search-empty">Ничего не найдено</div>
          )}
        </div>
      ) : null}
    </div>
  )
}
