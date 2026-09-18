import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { mapAssignmentFromApi } from './assignmentRegistryMappers'
import type { AssignmentRegistryRow } from './assignmentRegistryTypes'
import { readRegistryCache, registryCacheKey, writeRegistryCache } from './assignmentRegistryCache'

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

function mergeAssignmentRows(
  current: AssignmentRegistryRow[],
  batch: AssignmentRegistryRow[]
): AssignmentRegistryRow[] {
  if (!batch.length) return current
  const seen = new Set(current.map((row) => row.id))
  const next = [...current]
  for (const row of batch) {
    if (seen.has(row.id)) continue
    seen.add(row.id)
    next.push(row)
  }
  return next
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

  const [rows, setRows] = useState<AssignmentRegistryRow[]>(() => cached?.rows ?? [])
  const [loading, setLoading] = useState(() => !cached?.rows.length)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [firstRowReady, setFirstRowReady] = useState(() => Boolean(cached?.rows.length))
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const loadGeneration = useRef(0)

  const refresh = useCallback(() => {
    setRows([])
    writeRegistryCache(cacheKey, [])
    setFirstRowReady(false)
    setTick((value) => value + 1)
  }, [cacheKey])

  const applyRows = useCallback(
    (next: AssignmentRegistryRow[]) => {
      setRows(next)
      writeRegistryCache(cacheKey, next)
    },
    [cacheKey]
  )

  useEffect(() => {
    const seq = ++loadGeneration.current
    let alive = true

    const hadCache = Boolean(readRegistryCache(cacheKey)?.rows.length)

    const load = async (): Promise<void> => {
      if (!hadCache) setLoading(true)
      else setRefreshing(true)
      setLoadingMore(false)
      setError('')

      const basePayload: Record<string, unknown> = {
        action: 'list',
        limit: REGISTRY_PAGE_SIZE,
        only_open: false,
        include_lines: false,
        profile: true
      }
      if (dateFrom.trim()) basePayload.date_from = dateFrom.trim()
      if (dateTo.trim()) basePayload.date_to = dateTo.trim()

      const cachedRows = readRegistryCache(cacheKey)?.rows ?? []
      let accumulated: AssignmentRegistryRow[] = hadCache && cachedRows.length ? [...cachedRows] : []
      let skip = 0
      setFirstRowReady(Boolean(accumulated.length))

      try {
        while (skip < REGISTRY_MAX_ROWS) {
          if (!alive || seq !== loadGeneration.current) return

          const res = await api.invokeServerTool(
            'onec.erp_assignments',
            { ...basePayload, skip },
            300_000
          )
          if (!alive || seq !== loadGeneration.current) return

          if (!res.ok) {
            if (!accumulated.length) {
              setRows([])
              setError(String(res.error || 'Не удалось загрузить реестр поручений'))
            }
            setFirstRowReady(true)
            return
          }

          const batch = parseAssignmentsPayload(res.result)
          if (import.meta.env.DEV && skip === 0 && res.result && typeof res.result === 'object') {
            const timing = (res.result as Record<string, unknown>).timing_ms
            if (timing) console.info('[registry] page timing_ms', timing)
          }

          if (!batch.length) {
            setFirstRowReady(true)
            break
          }

          accumulated = mergeAssignmentRows(accumulated, batch)
          applyRows(accumulated)
          if (accumulated.length) setFirstRowReady(true)

          if (seq === loadGeneration.current) {
            setLoading(false)
            setRefreshing(false)
          }

          if (batch.length < REGISTRY_PAGE_SIZE || accumulated.length >= REGISTRY_MAX_ROWS) {
            setLoadingMore(false)
            break
          }

          skip += REGISTRY_PAGE_SIZE
          setLoadingMore(true)
        }

        if (!accumulated.length) {
          setError('')
        }
      } catch (exc) {
        if (!alive || seq !== loadGeneration.current) return
        if (!accumulated.length) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, tick, cacheKey, applyRows])

  return { rows, loading, refreshing, loadingMore, firstRowReady, error, refresh }
}
