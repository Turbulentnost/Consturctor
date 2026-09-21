import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { mapAssignmentFromApi } from './assignmentRegistryMappers'
import type { AssignmentRegistryRow } from './assignmentRegistryTypes'
import {
  clearRegistryPool,
  mergeRegistryPool,
  readRegistryCache,
  readRegistryPool,
  registryCacheKey,
  writeRegistryCache
} from './assignmentRegistryCache'
import {
  filterRegistryRowsByPeriod,
  planRegistryFetchSlices,
  type RegistryLoadedSpan
} from './assignmentRegistryRange'

export const REGISTRY_PAGE_SIZE = 20
export const REGISTRY_MAX_ROWS = 100

function parseAssignmentsPayload(result: unknown): AssignmentRegistryRow[] {
  if (!result || typeof result !== 'object') return []
  const payload = result as Record<string, unknown>
  const list = Array.isArray(payload.assignments) ? payload.assignments : []
  return list
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => mapAssignmentFromApi(item))
}

export function useAssignmentRegistry(
  userId: string,
  dateFrom: string,
  dateTo: string
): {
  rows: AssignmentRegistryRow[]
  loading: boolean
  refreshing: boolean
  loadingMore: boolean
  firstRowReady: boolean
  error: string
  refresh: () => void
} {
  const cacheKey = registryCacheKey(userId, dateFrom, dateTo)
  const cached = readRegistryCache(cacheKey)
  const poolSeed = filterRegistryRowsByPeriod(readRegistryPool(userId), dateFrom, dateTo)
  const initialRows = cached?.rows.length ? cached.rows : poolSeed

  const [rows, setRows] = useState<AssignmentRegistryRow[]>(() => initialRows)
  const [loading, setLoading] = useState(() => !initialRows.length)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [firstRowReady, setFirstRowReady] = useState(() => Boolean(initialRows.length))
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const loadGeneration = useRef(0)
  const loadedSpanRef = useRef<RegistryLoadedSpan | null>(
    cached?.complete && cached.dateFrom && cached.dateTo
      ? { dateFrom: cached.dateFrom, dateTo: cached.dateTo, complete: true }
      : null
  )

  const refresh = useCallback(() => {
    clearRegistryPool(userId)
    loadedSpanRef.current = null
    writeRegistryCache(cacheKey, [], { complete: false, dateFrom, dateTo })
    setRows([])
    setFirstRowReady(false)
    setTick((value) => value + 1)
  }, [cacheKey, dateFrom, dateTo, userId])

  const publishVisible = useCallback(
    (pool: AssignmentRegistryRow[], meta?: { complete?: boolean }) => {
      const visible = filterRegistryRowsByPeriod(pool, dateFrom, dateTo)
      setRows(visible)
      writeRegistryCache(cacheKey, visible, {
        complete: meta?.complete,
        dateFrom,
        dateTo
      })
      if (visible.length) setFirstRowReady(true)
      return visible
    },
    [cacheKey, dateFrom, dateTo]
  )

  useEffect(() => {
    const seq = ++loadGeneration.current
    let alive = true

    const poolVisible = filterRegistryRowsByPeriod(readRegistryPool(userId), dateFrom, dateTo)
    const exactCache = readRegistryCache(cacheKey)

    if (exactCache?.complete && exactCache.rows.length) {
      setRows(exactCache.rows)
      setFirstRowReady(true)
      setLoading(false)
      setRefreshing(false)
      setLoadingMore(false)
      loadedSpanRef.current = {
        dateFrom: exactCache.dateFrom || dateFrom,
        dateTo: exactCache.dateTo || dateTo,
        complete: true
      }
      return
    }

    if (poolVisible.length) {
      publishVisible(readRegistryPool(userId))
    }

    if (!loadedSpanRef.current && poolVisible.length) {
      loadedSpanRef.current = { dateFrom, dateTo, complete: false }
    }

    const slices = planRegistryFetchSlices(loadedSpanRef.current, dateFrom, dateTo)
    if (!slices.length) {
      if (poolVisible.length) publishVisible(readRegistryPool(userId))
      setLoading(false)
      setRefreshing(false)
      setLoadingMore(false)
      return
    }

    if (!poolVisible.length) setLoading(true)
    else setRefreshing(true)
    setError('')

    const load = async (): Promise<void> => {
      let pool = readRegistryPool(userId)
      let spanFinishedComplete = true

      try {
        for (const slice of slices) {
          if (!alive || seq !== loadGeneration.current) return

          const sliceFrom = slice.dateFrom.trim()
          const sliceTo = slice.dateTo.trim()
          let skip = 0
          if (slice.continuePagination) {
            skip = filterRegistryRowsByPeriod(pool, sliceFrom, sliceTo).length
          }

          while (skip < REGISTRY_MAX_ROWS) {
            if (!alive || seq !== loadGeneration.current) return

            const res = await api.invokeServerTool(
              'onec.erp_assignments',
              {
                action: 'list',
                limit: REGISTRY_PAGE_SIZE,
                skip,
                only_open: false,
                include_lines: false,
                profile: true,
                ...(sliceFrom ? { date_from: sliceFrom } : {}),
                ...(sliceTo ? { date_to: sliceTo } : {})
              },
              300_000
            )
            if (!alive || seq !== loadGeneration.current) return

            if (!res.ok) {
              spanFinishedComplete = false
              if (!pool.length) {
                setRows([])
                setError(String(res.error || 'Не удалось загрузить реестр поручений'))
              }
              setFirstRowReady(true)
              break
            }

            const batch = parseAssignmentsPayload(res.result)
            if (import.meta.env.DEV && skip === 0 && res.result && typeof res.result === 'object') {
              const timing = (res.result as Record<string, unknown>).timing_ms
              if (timing) console.info('[registry] page timing_ms', timing)
            }

            if (!batch.length) break

            pool = mergeRegistryPool(userId, batch)
            publishVisible(pool)
            setLoading(false)
            setRefreshing(false)

            if (batch.length < REGISTRY_PAGE_SIZE || skip + batch.length >= REGISTRY_MAX_ROWS) {
              if (batch.length >= REGISTRY_PAGE_SIZE && skip + batch.length >= REGISTRY_MAX_ROWS) {
                spanFinishedComplete = false
              }
              break
            }

            skip += REGISTRY_PAGE_SIZE
            setLoadingMore(true)
          }
        }

        loadedSpanRef.current = { dateFrom, dateTo, complete: spanFinishedComplete }
        publishVisible(pool, { complete: spanFinishedComplete })
      } catch (exc) {
        if (!alive || seq !== loadGeneration.current) return
        spanFinishedComplete = false
        if (!pool.length) {
          setRows([])
          setError(exc instanceof Error ? exc.message : 'Ошибка загрузки реестра')
        }
        setFirstRowReady(true)
      } finally {
        if (seq === loadGeneration.current) {
          setLoading(false)
          setRefreshing(false)
          setLoadingMore(false)
        }
      }
    }

    void load()
    return () => {
      alive = false
    }
  }, [cacheKey, dateFrom, dateTo, publishVisible, tick, userId])

  return { rows, loading, refreshing, loadingMore, firstRowReady, error, refresh }
}
