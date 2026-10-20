import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

export const KPI_PROTECTION_EVENT = 'orch-kpi-protection-changed'

type StoredUnlock = { token: string; expiresAt: number }

function unlockKey(userId: string): string {
  return `orch-kpi-unlock-v1:${userId}`
}

export function readKpiUnlock(userId: string): string {
  if (!userId) return ''
  try {
    const raw = sessionStorage.getItem(unlockKey(userId))
    if (!raw) return ''
    const parsed = JSON.parse(raw) as StoredUnlock
    if (!parsed?.token || Number(parsed.expiresAt) * 1000 <= Date.now()) {
      sessionStorage.removeItem(unlockKey(userId))
      return ''
    }
    return parsed.token
  } catch {
    return ''
  }
}

export function writeKpiUnlock(userId: string, unlock: StoredUnlock | null): void {
  if (!userId) return
  try {
    if (unlock?.token) sessionStorage.setItem(unlockKey(userId), JSON.stringify(unlock))
    else sessionStorage.removeItem(unlockKey(userId))
  } catch {
    /* sessionStorage недоступен — разблокировка живёт до перезагрузки */
  }
  window.dispatchEvent(new CustomEvent(KPI_PROTECTION_EVENT))
}

export type KpiProtectionState = {
  loaded: boolean
  enabled: boolean
  hasPassword: boolean
  unlockToken: string
  reload: () => void
}

export function useKpiProtection(userId: string): KpiProtectionState {
  const [state, setState] = useState({ loaded: false, enabled: false, hasPassword: false })
  const [unlockToken, setUnlockToken] = useState(() => readKpiUnlock(userId))
  const [version, setVersion] = useState(0)

  const reload = useCallback(() => setVersion((value) => value + 1), [])

  useEffect(() => {
    const sync = (): void => {
      setUnlockToken(readKpiUnlock(userId))
      reload()
    }
    window.addEventListener(KPI_PROTECTION_EVENT, sync)
    return () => window.removeEventListener(KPI_PROTECTION_EVENT, sync)
  }, [userId, reload])

  useEffect(() => {
    let alive = true
    setUnlockToken(readKpiUnlock(userId))
    void api
      .getKpiProtection()
      .then((next) => {
        if (alive) setState({ loaded: true, ...next })
      })
      .catch(() => {
        if (alive) setState((prev) => ({ ...prev, loaded: true }))
      })
    return () => {
      alive = false
    }
  }, [userId, version])

  return {
    ...state,
    unlockToken: state.enabled ? unlockToken : '',
    reload
  }
}
