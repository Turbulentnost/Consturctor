import { useCallback, useEffect, useState } from 'react'
import { notifyExtensionsChanged, ORCH_EXTENSIONS_CHANGED } from './extensionEvents'
import { registeredExtensionIds } from './extensionModules'

const STORAGE_KEY = 'orch-user-extensions-v1'

type Stored = {
  pinned: string[]
}

const knownIds = (): Set<string> => new Set(registeredExtensionIds())

function readStored(userId: string): Stored {
  const key = `${STORAGE_KEY}:${userId.trim() || 'default'}`
  const allowed = knownIds()
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return { pinned: [] }
    const parsed = JSON.parse(raw) as Stored
    const pinned = Array.isArray(parsed.pinned)
      ? parsed.pinned.filter((id): id is string => typeof id === 'string' && allowed.has(id))
      : []
    return { pinned: [...new Set(pinned)] }
  } catch {
    return { pinned: [] }
  }
}

function writeStored(userId: string, data: Stored): void {
  const key = `${STORAGE_KEY}:${userId.trim() || 'default'}`
  localStorage.setItem(key, JSON.stringify(data))
  notifyExtensionsChanged(userId)
}

export function useUserExtensions(userId: string): {
  pinned: string[]
  isPinned: (id: string) => boolean
  pin: (id: string) => void
  unpin: (id: string) => void
  togglePin: (id: string) => void
} {
  const [pinned, setPinned] = useState<string[]>(() => readStored(userId).pinned)

  const reload = useCallback(() => {
    setPinned(readStored(userId).pinned)
  }, [userId])

  useEffect(() => {
    reload()
  }, [reload])

  useEffect(() => {
    const uid = userId.trim() || 'default'
    const onChange = (event: Event): void => {
      const detail = (event as CustomEvent<{ userId?: string }>).detail
      if ((detail?.userId || 'default') === uid) reload()
    }
    window.addEventListener(ORCH_EXTENSIONS_CHANGED, onChange)
    const onStorage = (event: StorageEvent): void => {
      if (event.key === `${STORAGE_KEY}:${uid}`) reload()
    }
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(ORCH_EXTENSIONS_CHANGED, onChange)
      window.removeEventListener('storage', onStorage)
    }
  }, [reload, userId])

  const persist = useCallback(
    (next: string[]) => {
      setPinned(next)
      writeStored(userId, { pinned: next })
    },
    [userId]
  )

  const isPinned = useCallback((id: string) => pinned.includes(id), [pinned])

  const pin = useCallback(
    (id: string) => {
      if (!knownIds().has(id) || pinned.includes(id)) return
      persist([...pinned, id])
    },
    [persist, pinned]
  )

  const unpin = useCallback(
    (id: string) => {
      persist(pinned.filter((item) => item !== id))
    },
    [persist, pinned]
  )

  const togglePin = useCallback(
    (id: string) => {
      if (pinned.includes(id)) unpin(id)
      else pin(id)
    },
    [pin, pinned, unpin]
  )

  return { pinned, isPinned, pin, unpin, togglePin }
}
