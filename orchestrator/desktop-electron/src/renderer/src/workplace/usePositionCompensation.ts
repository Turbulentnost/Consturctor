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
  total: null,
  history: []
}

/** Премия помесячная, как и плитки KPI должности: сервер берёт текущий месяц, календарь периода не влияет. */
export function usePositionCompensation(): {
  compensation: PositionKpiCompensation
  loading: boolean
  unlocking: boolean
  /** Пустая строка — зарплата открыта, иначе текст ошибки. */
  unlock: (pin: string) => Promise<string>
  hide: () => void
} {
  const [compensation, setCompensation] = useState<PositionKpiCompensation>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [unlocking, setUnlocking] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setCompensation(EMPTY)
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

  const unlock = useCallback(async (pin: string): Promise<string> => {
    setUnlocking(true)
    try {
      setCompensation(await api.unlockPositionKpiCompensation(pin))
      return ''
    } catch (err: unknown) {
      return err instanceof Error && err.message ? err.message : 'Не удалось показать зарплату'
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
      total: null,
      history: []
    }))
  }, [])

  return { compensation, loading, unlocking, unlock, hide }
}
