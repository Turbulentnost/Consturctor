import { useEffect, useRef, useState } from 'react'
import { loadUserAvatar } from '../api/avatars'
import { api } from '../api/client'
import type { DirectoryUser } from '../api/types'

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

function initials(name: string): string {
  const parts = (name || '').replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function userKey(user: DirectoryUser): string {
  return user.id || user.fio
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
  const [items, setItems] = useState<DirectoryUser[]>([])
  const [avatars, setAvatars] = useState<Record<string, string>>({})
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

  useEffect(() => {
    let alive = true
    void Promise.all(
      items.map(async (user) => {
        const url = await loadUserAvatar({ id: user.id, avatarUrl: user.avatarUrl })
        return [userKey(user), url] as const
      })
    ).then((rows) => {
      if (!alive) return
      const next: Record<string, string> = {}
      for (const [key, url] of rows) {
        if (url) next[key] = url
      }
      setAvatars(next)
    })
    return () => {
      alive = false
    }
  }, [items])

  function query(search: string): void {
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(async () => {
      let results: DirectoryUser[] = []
      try {
        results = await api.listDirectoryUsers(search)
      } catch {
        results = []
      }
      if (!results.length) {
        const names = await api.searchUsers(search)
        results = names.map((fio) => ({
          id: '',
          fio,
          position: '',
          department: '',
          activityStatus: 'online',
          online: false,
          isSupport: false,
          avatarUrl: null
        }))
      }
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

  function choose(user: DirectoryUser): void {
    onChange(user.fio)
    setOpen(false)
    onSelect?.(user.fio)
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

  const showPopup = open && items.length > 0

  return (
    <div className={showPopup ? 'fio-suggest open' : 'fio-suggest'} ref={wrapRef}>
      <input
        className={inputClassName}
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onFocus={handleFocus}
        onChange={(e) => handleChange(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {showPopup && (
        <div className={variant === 'dark' ? 'fio-popup dark' : 'fio-popup'}>
          {items.map((user, index) => {
            const key = userKey(user)
            const avatar = avatars[key]
            return (
              <div
                key={key}
                className={index === highlight ? 'fio-option active' : 'fio-option'}
                onMouseEnter={() => setHighlight(index)}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(user)
                }}
              >
                <span className="fio-option-avatar">
                  {avatar ? <img src={avatar} alt="" /> : initials(user.fio)}
                </span>
                <span className="fio-option-name">{user.fio}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
