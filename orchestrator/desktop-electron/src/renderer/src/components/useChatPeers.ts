import { useCallback, useEffect, useRef, useState } from 'react'
import { api, parseChatMessage } from '../api/client'
import { previewText } from '../api/chatCodec'
import { loadUserAvatar } from '../api/avatars'
import type { ChatMessage, ChatThread } from '../api/types'

function oneLine(text: string): string {
  return (text || '').replace(/\s+/g, ' ').trim()
}

export function personInitials(fio: string): string {
  const parts = (fio || '').replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

export function shortFio(fio: string): string {
  const parts = (fio || '').replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return ''
  const rest = parts.slice(1).map((part) => `${part[0].toUpperCase()}.`)
  return [parts[0], ...rest].join(' ')
}

export function threadPreview(value: string | ChatMessage): string {
  if (typeof value === 'string') return oneLine(previewText(value))
  const text = oneLine(value.text)
  if (text) return text
  if (value.agent) return oneLine(`Агент: ${value.agent.title || 'ИИ-агент'}`)
  const file = value.attachments[0]
  return file ? oneLine(file.filename || 'Файл') : ''
}

function sameThread(peer: ChatThread, threadId: string, senderId = ''): boolean {
  if (threadId && peer.id === threadId) return true
  if (peer.kind === 'support' && (peer.id === 'support' || peer.id === threadId)) return true
  return Boolean(peer.id.startsWith('dm:') && peer.peerId && (peer.peerId === senderId || peer.peerId === threadId))
}

export function useChatPeers(
  refreshAt = 0,
  currentUserId = '',
  enabled = true
): {
  peers: ChatThread[]
  avatars: Record<string, string>
  loading: boolean
  markRead: (peer: ChatThread) => ChatThread
} {
  const [peers, setPeers] = useState<ChatThread[]>([])
  const [avatars, setAvatars] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const settledRef = useRef(false)

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    let alive = true
    const load = async (): Promise<void> => {
      try {
        const loaded = await api.listChatThreads()
        if (alive) setPeers(loaded)
      } catch {
        if (alive) setPeers([])
      } finally {
        if (!alive) return
        settledRef.current = true
        setLoading(false)
      }
    }
    if (!settledRef.current) setLoading(true)
    void load()
    const timer = window.setInterval(() => {
      void load()
    }, 120_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [refreshAt, enabled])

  useEffect(() => {
    if (!enabled) return
    const unsubscribe = window.api.onChatEvent?.((payload) => {
      const kind = String(payload.type || '')
      if (kind === 'chat_receipt') {
        const threadId = String(payload.thread_id ?? '')
        const readerId = String(payload.reader_id ?? '')
        if (!threadId || (currentUserId && readerId && readerId !== currentUserId)) return
        setPeers((current) => current.map((peer) => (sameThread(peer, threadId) ? { ...peer, unread: 0 } : peer)))
        return
      }
      if (kind !== 'chat_message') return
      const parsed = parseChatMessage(payload.message)
      const threadId = String(payload.thread_id ?? parsed?.id ?? '')
      if (!threadId) return
      setPeers((current) => {
        const idx = current.findIndex((peer) => sameThread(peer, threadId, String(payload.sender_id ?? '')))
        if (idx < 0) return current
        const next = [...current]
        next[idx] = {
          ...next[idx],
          preview: parsed ? threadPreview(parsed) : threadPreview(String(payload.message || '')),
          unread: next[idx].unread + 1
        }
        return next
      })
    })
    return () => unsubscribe?.()
  }, [currentUserId, enabled])

  const people = peers.filter((peer) => peer.kind !== 'support')
  const avatarKey = people
    .map((peer) => `${peer.id}\u0000${peer.peerId || peer.id}\u0000${peer.avatarUrl || ''}`)
    .join('\u0001')

  useEffect(() => {
    if (!enabled) return
    let alive = true
    const entries = avatarKey ? avatarKey.split('\u0001') : []
    void Promise.all(
      entries.map(async (entry) => {
        const [threadId, userId, avatarUrl] = entry.split('\u0000')
        const url = await loadUserAvatar({ id: userId, avatarUrl })
        return [threadId, url] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const map: Record<string, string> = {}
      for (const [id, url] of pairs) {
        if (url) map[id] = url
      }
      setAvatars(map)
    })
    return () => {
      alive = false
    }
  }, [avatarKey, enabled])

  const markRead = useCallback((peer: ChatThread): ChatThread => {
    setPeers((current) => current.map((item) => (item.id === peer.id ? { ...item, unread: 0 } : item)))
    return { ...peer, unread: 0 }
  }, [])

  return { peers: people, avatars, loading, markRead }
}
