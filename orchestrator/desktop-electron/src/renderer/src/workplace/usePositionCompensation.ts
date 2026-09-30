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

export function usePositionCompensation(from: string, to: string): {
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
      .getPositionKpiCompensation(to)
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
  }, [to])

  const unlock = useCallback(
    async (pin: string): Promise<boolean> => {
      setUnlocking(true)
      setError('')
      try {
        const next = await api.unlockPositionKpiCompensation(pin, from, to)
        setCompensation(next)
        return true
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Не удалось показать зарплату')
        return false
      } finally {
        setUnlocking(false)
      }
    },
    [from, to]
  )

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
