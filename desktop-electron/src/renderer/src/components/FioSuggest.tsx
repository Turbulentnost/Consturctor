import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

interface FioSuggestProps {
  value: string
  onChange: (value: string) => void
  onSelect?: (value: string) => void
  placeholder?: string
  inputClassName?: string
  variant?: 'light' | 'dark'
  onEnter?: () => void
  autoFocus?: boolean
}

export function FioSuggest({
  value,
  onChange,
  onSelect,
  placeholder,
  inputClassName,
  variant = 'light',
  onEnter,
  autoFocus
}: FioSuggestProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<string[]>([])
  const [highlight, setHighlight] = useState(-1)
  const wrapRef = useRef<HTMLDivElement>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    function onDocClick(e: MouseEvent): void {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function query(search: string): void {
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(async () => {
      const results = await api.searchUsers(search)
      setItems(results.slice(0, 20))
      setHighlight(-1)
    }, 180)
  }

  function handleFocus(): void {
    setOpen(true)
    query(value)
  }

  function handleChange(next: string): void {
    onChange(next)
    setOpen(true)
    query(next)
  }

  function choose(fio: string): void {
    onChange(fio)
    setOpen(false)
    onSelect?.(fio)
  }

  function onKeyDown(e: React.KeyboardEvent): void {
    if (!open && e.key === 'Enter') {
      onEnter?.()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((h) => Math.min(h + 1, items.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      if (highlight >= 0 && highlight < items.length) {
        e.preventDefault()
        choose(items[highlight])
      } else {
        onEnter?.()
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="fio-suggest" ref={wrapRef}>
      <input
        className={inputClassName}
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onFocus={handleFocus}
        onChange={(e) => handleChange(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {open && items.length > 0 && (
        <div className={variant === 'dark' ? 'fio-popup dark' : 'fio-popup'}>
          {items.map((fio, index) => (
            <div
              key={fio}
              className={index === highlight ? 'fio-option active' : 'fio-option'}
              onMouseEnter={() => setHighlight(index)}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(fio)
              }}
            >
              {fio}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
