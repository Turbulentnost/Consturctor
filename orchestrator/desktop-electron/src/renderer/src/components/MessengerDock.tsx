import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus } from 'lucide-react'
import { api } from '../api/client'
import type { ChatThread, DirectoryUser } from '../api/types'
import { FioSuggest } from './FioSuggest'
import { useReportError } from './ErrorToast'
import { personInitials, shortFio, threadPreview, useChatPeers } from './useChatPeers'

const SKELETON_COUNT = 4

function missedCount(peer: ChatThread, active: boolean): number {
  if (active) return 0
  return peer.unread > 0 ? peer.unread : 0
}

function badgeLabel(count: number): string {
  if (count > 99) return '99+'
  return String(count)
}

const MONTHS = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря'
]

function messageWhen(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const startOf = (day: Date): number => new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime()
  const diff = Math.round((startOf(new Date()) - startOf(date)) / 86400000)
  if (diff === 0) return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (diff === 1) return 'вчера'
  const label = `${date.getDate()} ${MONTHS[date.getMonth()]}`
  const year = date.getFullYear()
  return year === new Date().getFullYear() ? label : `${label} ${year}`
}

function normName(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function findExistingChat(threads: ChatThread[], name: string, peerId?: string): ChatThread | undefined {
  const people = threads.filter((item) => item.kind !== 'support')
  if (peerId) {
    const byPeer = people.find((item) => item.peerId === peerId || item.id === peerId || item.id === `dm:${peerId}`)
    if (byPeer) return byPeer
  }
  const key = normName(name)
  if (!key) return undefined
  return people.find((item) => normName(item.title) === key)
}

function finderAnchor(button: HTMLElement | null): { left: number; bottom: number } {
  const width = 340
  const margin = 12
  const rect = button?.getBoundingClientRect()
  if (!rect) return { left: margin, bottom: 72 }
  const left = Math.min(Math.max(margin, rect.left - 4), window.innerWidth - width - margin)
  return { left, bottom: Math.max(margin, window.innerHeight - rect.top + 8) }
}

function blankThread(user: DirectoryUser, name: string, peerId: string): ChatThread {
  return {
    id: `dm:${peerId}`,
    kind: 'dm',
    title: user.fio || name,
    position: user.position,
    preview: '',
    lastMessageAt: '',
    unread: 0,
    pinned: false,
    peerId,
    activityStatus: user.activityStatus,
    online: user.online,
    ticketStatus: '',
    avatarUrl: user.avatarUrl
  }
}

export function MessengerDock({
  open,
  refreshAt = 0,
  currentUserId = '',
  activeThreadId = '',
  onOpenThread
}: {
  open: boolean
  refreshAt?: number
  currentUserId?: string
  activeThreadId?: string
  onOpenThread: (thread: ChatThread) => void
}): React.JSX.Element {
  const { peers, avatars, loading, markRead } = useChatPeers(refreshAt, currentUserId, true)
  const dockRef = useRef<HTMLElement>(null)
  const finderRef = useRef<HTMLDivElement>(null)
  const addRef = useRef<HTMLButtonElement>(null)
  const choosingRef = useRef(false)
  const [finderOpen, setFinderOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [anchor, setAnchor] = useState({ left: 12, bottom: 72 })
  const showSkeletons = loading && peers.length === 0
  useReportError(error)

  function toggleFinder(): void {
    setError('')
    setStatus('')
    if (finderOpen) {
      setFinderOpen(false)
      return
    }
    setAnchor(finderAnchor(addRef.current))
    setQuery('')
    setFinderOpen(true)
  }

  useEffect(() => {
    if (!finderOpen) return
    const place = (): void => {
      setAnchor((prev) => {
        const next = finderAnchor(addRef.current)
        return prev.bottom === next.bottom && prev.left === next.left ? prev : next
      })
    }
    place()
    const observer = new ResizeObserver(place)
    const node = dockRef.current
    if (node) observer.observe(node)
    if (node?.parentElement) observer.observe(node.parentElement)
    window.addEventListener('resize', place)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', place)
    }
  }, [finderOpen, open])

  useEffect(() => {
    if (!finderOpen) return
    const onPointer = (event: MouseEvent): void => {
      const target = event.target as Node
      if (finderRef.current?.contains(target)) return
      if (addRef.current?.contains(target)) return
      setFinderOpen(false)
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setFinderOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [finderOpen])

  async function chooseEmployee(fio: string, user: DirectoryUser): Promise<void> {
    if (choosingRef.current) return
    const name = (user.fio || fio).trim()
    if (!name) return
    if (currentUserId && user.id === currentUserId) {
      setError('Нельзя открыть переписку с собой')
      return
    }
    choosingRef.current = true
    setError('')
    setStatus('')
    try {
      let peerId = user.id
      let existing = findExistingChat(peers, name, peerId)
      if (!existing) {
        const threads = await api.listChatThreads()
        if (!peerId) {
          const users = await api.listDirectoryUsers(name)
          const resolved =
            users.find((item) => normName(item.fio) === normName(name) && item.id && item.id !== currentUserId) ||
            users.find((item) => item.id && item.id !== currentUserId) ||
            null
          peerId = resolved?.id || ''
        }
        if (currentUserId && peerId === currentUserId) {
          setError('Нельзя открыть переписку с собой')
          return
        }
        existing = findExistingChat(threads, name, peerId)
      }
      if (existing) {
        setQuery('')
        setFinderOpen(false)
        onOpenThread(markRead(existing))
        return
      }
      if (!peerId) {
        setError('Сотрудник не найден')
        return
      }
      setStatus('Открываем переписку…')
      try {
        await api.openDirectChat(peerId)
      } catch {
        /* диалог всё равно откроется локально */
      }
      const next = (await api.listChatThreads()).find((item) => item.kind !== 'support' && item.peerId === peerId)
      setQuery('')
      setFinderOpen(false)
      onOpenThread(markRead(next || blankThread(user, name, peerId)))
    } catch (err) {
      setStatus('')
      setError(err instanceof Error ? err.message : 'Не удалось открыть переписку')
    } finally {
      choosingRef.current = false
    }
  }

  return (
    <aside
      ref={dockRef}
      className={open ? 'msg-dock msg-dock--open' : 'msg-dock'}
      aria-label="Сообщения"
    >
      <div className="msg-dock-list" aria-busy={showSkeletons}>
        {showSkeletons
          ? Array.from({ length: SKELETON_COUNT }, (_, index) => (
              <div className="msg-dock-skeleton-slot" key={index} aria-hidden>
                <span className="msg-dock-skeleton" />
              </div>
            ))
          : peers.map((peer) => {
              const active = peer.id === activeThreadId || (peer.peerId !== '' && peer.peerId === activeThreadId)
              const preview = threadPreview(peer.preview)
              const missed = missedCount(peer, active)
              const name = peer.title || 'Собеседник'
              const when = messageWhen(peer.lastMessageAt)
              return (
                <button
                  key={peer.id}
                  type="button"
                  className={active ? 'msg-dock-item is-active' : 'msg-dock-item'}
                  title={[name, when, preview].filter(Boolean).join('\n')}
                  aria-label={[name, when, missed > 0 ? `непрочитанных ${missed}` : ''].filter(Boolean).join(', ')}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => onOpenThread(markRead(peer))}
                >
                  <span className="msg-dock-avatar">
                    {missed > 0 ? (
                      <i className="msg-dock-badge" aria-hidden>
                        {badgeLabel(missed)}
                      </i>
                    ) : null}
                    {avatars[peer.id] ? <img src={avatars[peer.id]} alt="" /> : personInitials(name)}
                  </span>
                  <span className="msg-dock-copy">
                    <span className="msg-dock-line">
                      <span className="msg-dock-name">{shortFio(name)}</span>
                      {when ? <time className="msg-dock-time">{when}</time> : null}
                    </span>
                    {preview ? <span className="msg-dock-preview">{preview}</span> : null}
                  </span>
                </button>
              )
            })}
        {open && !showSkeletons && peers.length === 0 ? <p className="msg-dock-empty">Нет диалогов</p> : null}
      </div>
      <button
        ref={addRef}
        type="button"
        className={finderOpen ? 'msg-dock-add is-open' : 'msg-dock-add'}
        aria-label="Найти сотрудника"
        aria-expanded={finderOpen}
        title="Найти сотрудника"
        onClick={toggleFinder}
      >
        <Plus size={18} strokeWidth={2.25} aria-hidden />
      </button>
      {finderOpen
        ? createPortal(
            <div
              ref={finderRef}
              className="msg-dock-finder"
              style={{ left: anchor.left, bottom: anchor.bottom }}
              role="dialog"
              aria-label="Поиск сотрудников"
            >
              <FioSuggest
                value={query}
                onChange={setQuery}
                onSelect={(value, user) => {
                  void chooseEmployee(value, user)
                }}
                placeholder="Поиск сотрудника"
                inputClassName="msg-dock-finder-input"
                autoFocus
              />
              {status ? <p className="msg-dock-finder-status">{status}</p> : null}
            </div>,
            document.body
          )
        : null}
    </aside>
  )
}
