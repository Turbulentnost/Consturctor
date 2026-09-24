import { useEffect, useRef, useState } from 'react'
import { loadUserAvatar } from '../api/avatars'
import { api } from '../api/client'
import type { DirectoryUser } from '../api/types'

interface FioSuggestProps {
  value: string
  onChange: (value: string) => void
  onSelect?: (value: string, user: DirectoryUser) => void
  placeholder?: string
  inputClassName?: string
  variant?: 'light' | 'dark'
  onEnter?: () => void
  autoFocus?: boolean
  /** Login screen: only public /auth/users, no chat/directory (needs JWT and floods ERP). */
  publicOnly?: boolean
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
  autoFocus,
  publicOnly = false
}: FioSuggestProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<DirectoryUser[]>([])
  const [loading, setLoading] = useState(false)
  const [avatars, setAvatars] = useState<Record<string, string>>({})
  const [highlight, setHighlight] = useState(-1)
  const wrapRef = useRef<HTMLDivElement>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  const querySeq = useRef(0)

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
        let url = await loadUserAvatar({ id: user.id, avatarUrl: user.avatarUrl })
        if (!url && user.fio && !publicOnly && user.id) {
          const matches = await api.listDirectoryUsers(user.fio)
          const match =
            matches.find((item) => item.fio.toLowerCase() === user.fio.toLowerCase() && item.id) ||
            matches.find((item) => item.id)
          if (match) {
            url = await loadUserAvatar({
              id: match.id,
              avatarUrl: match.avatarUrl || `/api/v1/auth/users/${match.id}/avatar`
            })
          }
        }
        return [userKey(user), url] as const
      })
    ).then((rows) => {
      if (!alive) return
      setAvatars((prev) => {
        const next = { ...prev }
        for (const [key, url] of rows) {
          if (url) next[key] = url
        }
        return next
      })
    })
    return () => {
      alive = false
    }
  }, [items, publicOnly])

  function query(search: string): void {
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(async () => {
      const seq = ++querySeq.current
      setLoading(true)
      let results: DirectoryUser[] = []
      const onLoginScreen = publicOnly || !api.getToken()
      try {
        if (onLoginScreen) {
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
        } else {
          results = await api.listDirectoryUsers(search)
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
        }
      } catch {
        results = []
      }
      if (seq !== querySeq.current) return
      setItems(results.slice(0, 20))
      setHighlight(-1)
      setLoading(false)
    }, 120)
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
    onSelect?.(user.fio, user)
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

  const showPopup = open && (items.length > 0 || loading)

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
          {loading && !items.length ? (
            <div className="fio-option fio-option-muted">Загружаем список из 1С…</div>
          ) : null}
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
