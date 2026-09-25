import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import { GRID_DATA_TTL_MS, clearGridCacheForUser } from './gridDataCache'

type GridDataRefreshContextValue = {
  /** Монотонный счётчик: интервал TTL, смена пользователя, кнопка обновить. */
  generation: number
  forceRefresh: () => void
  /** Перечитать источники без обхода кеша SOAP (после записи в 1С). */
  softRefresh: () => void
  /** True once after the user clicked refresh (bypass SOAP cache). */
  takeHardRefresh: () => boolean
}

const GridDataRefreshContext = createContext<GridDataRefreshContextValue | null>(null)

export function GridDataRefreshProvider({
  userId,
  children
}: {
  userId?: string
  children: ReactNode
}): React.JSX.Element {
  const [generation, setGeneration] = useState(0)
  const prevUserIdRef = useRef<string | undefined>(undefined)
  const hardRefreshRef = useRef(false)

  const bump = useCallback((): void => {
    setGeneration((value) => value + 1)
  }, [])

  const forceRefresh = useCallback((): void => {
    hardRefreshRef.current = true
    bump()
  }, [bump])

  const takeHardRefresh = useCallback((): boolean => {
    const next = hardRefreshRef.current
    hardRefreshRef.current = false
    return next
  }, [])

  useEffect(() => {
    const uid = (userId || '').trim()
    if (!uid) return
    if (prevUserIdRef.current !== uid) {
      const previous = prevUserIdRef.current
      if (previous) clearGridCacheForUser(previous)
      prevUserIdRef.current = uid
      // First login already triggers hook effects at generation 0.
      // Do not bump: a second generation cancels in-flight Outlook/1C/Turbo fetches.
      if (previous) bump()
    }
  }, [userId, bump])

  useEffect(() => {
    const timer = window.setInterval(bump, GRID_DATA_TTL_MS)
    return () => window.clearInterval(timer)
  }, [bump])

  const value = useMemo(
    () => ({
      generation,
      forceRefresh,
      softRefresh: bump,
      takeHardRefresh
    }),
    [generation, forceRefresh, bump, takeHardRefresh]
  )

  return <GridDataRefreshContext.Provider value={value}>{children}</GridDataRefreshContext.Provider>
}

export function useGridDataRefreshContext(): GridDataRefreshContextValue {
  const ctx = useContext(GridDataRefreshContext)
  if (!ctx) {
    throw new Error('useGridDataRefreshContext requires GridDataRefreshProvider')
  }
  return ctx
}

/** @deprecated scopeKey ignored — используйте локальные deps эффекта для смены дня/фильтра. */
export function useGridRefreshGeneration(_scopeKey?: string): number {
  return useGridDataRefreshContext().generation
}
