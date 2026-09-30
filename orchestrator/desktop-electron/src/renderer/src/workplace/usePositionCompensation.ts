import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { PositionKpiCompensation } from '../api/types'

const EMPTY: PositionKpiCompensation = {
  available: false,
  unlocked: false,
  currency: 'RUB',
  effectiveFrom: '',
  salary: null,
  bonus: null,
  total: null
}

/** Премия помесячная, как и плитки KPI должности: сервер берёт текущий месяц, календарь периода не влияет. */
export function usePositionCompensation(): {
  compensation: PositionKpiCompensation
  loading: boolean
  unlocking: boolean
  error: string
  unlock: (pin: string) => Promise<boolean>
  hide: () => void
} {
  const [compensation, setCompensation] = useState<PositionKpiCompensation>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [unlocking, setUnlocking] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setLoading(true)
    setCompensation(EMPTY)
    setError('')
    void api
      .getPositionKpiCompensation()
      .then((next) => {
        if (alive) setCompensation(next)
      })
      .catch(() => {
        if (alive) setCompensation(EMPTY)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const unlock = useCallback(async (pin: string): Promise<boolean> => {
    setUnlocking(true)
    setError('')
    try {
      const next = await api.unlockPositionKpiCompensation(pin)
      setCompensation(next)
      return true
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Не удалось показать зарплату')
      return false
    } finally {
      setUnlocking(false)
    }
  }, [])

  const hide = useCallback(() => {
    setCompensation((current) => ({
      ...current,
      unlocked: false,
      salary: null,
      bonus: null,
      total: null
    }))
    setError('')
  }, [])

  return { compensation, loading, unlocking, error, unlock, hide }
}
