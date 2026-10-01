import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

const PIN_EVENT = 'kpi:pin-changed'

function message(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

/** Личный PIN для просмотра зарплаты: задаётся при первом входе в KPI, меняется в «Безопасности». */
export function useKpiPin(): {
  loaded: boolean
  hasPin: boolean
  error: string
  create: (pin: string, repeat: string) => Promise<string>
  change: (current: string, pin: string, repeat: string) => Promise<string>
} {
  const [loaded, setLoaded] = useState(false)
  const [hasPin, setHasPin] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    const load = (): void => {
      void api
        .getKpiPin()
        .then((state) => {
          if (!alive) return
          setHasPin(state.hasPin)
          setError('')
        })
        .catch((err: unknown) => {
          if (alive) setError(message(err, 'Не удалось проверить PIN-код'))
        })
        .finally(() => {
          if (alive) setLoaded(true)
        })
    }
    load()
    window.addEventListener(PIN_EVENT, load)
    return () => {
      alive = false
      window.removeEventListener(PIN_EVENT, load)
    }
  }, [])

  const create = useCallback(async (pin: string, repeat: string): Promise<string> => {
    try {
      await api.createKpiPin(pin, repeat)
      setHasPin(true)
      window.dispatchEvent(new CustomEvent(PIN_EVENT))
      return ''
    } catch (err: unknown) {
      return message(err, 'Не удалось сохранить PIN-код')
    }
  }, [])

  const change = useCallback(async (current: string, pin: string, repeat: string): Promise<string> => {
    try {
      await api.changeKpiPin(current, pin, repeat)
      window.dispatchEvent(new CustomEvent(PIN_EVENT))
      return ''
    } catch (err: unknown) {
      return message(err, 'Не удалось сменить PIN-код')
    }
  }, [])

  return { loaded, hasPin, error, create, change }
}
