import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { mapAssignmentFromApi } from './assignmentRegistryMappers'
import type { AssignmentRegistryRow } from './assignmentRegistryTypes'
import { readRegistryCache, registryCacheKey, writeRegistryCache } from './assignmentRegistryCache'

function parseAssignmentsPayload(result: unknown): AssignmentRegistryRow[] {
  if (!result || typeof result !== 'object') return []
  const payload = result as Record<string, unknown>
  const list = Array.isArray(payload.assignments) ? payload.assignments : []
  return list
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => mapAssignmentFromApi(item))
}

function parseGetAssignment(result: unknown): AssignmentRegistryRow | null {
  if (!result || typeof result !== 'object') return null
  const payload = result as Record<string, unknown>
  const one = payload.assignment
  if (one && typeof one === 'object') {
    return mapAssignmentFromApi(one as Record<string, unknown>)
  }
  return null
}

export function useAssignmentRegistry(
  userId: string,
  dateFrom: string,
  dateTo: string
): {
  rows: AssignmentRegistryRow[]
  loading: boolean
  refreshing: boolean
  error: string
  refresh: () => void
} {
  const cacheKey = registryCacheKey(userId, dateFrom, dateTo)
  const cached = readRegistryCache(cacheKey)

  const [rows, setRows] = useState<AssignmentRegistryRow[]>(() => cached?.rows ?? [])
  const [loading, setLoading] = useState(() => !cached?.rows.length)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const loadGeneration = useRef(0)
  const enrichGeneration = useRef(0)

  const refresh = useCallback(() => setTick((value) => value + 1), [])

  const applyRows = useCallback(
    (next: AssignmentRegistryRow[]) => {
      setRows(next)
      writeRegistryCache(cacheKey, next)
    },
    [cacheKey]
  )

  useEffect(() => {
    const seq = ++loadGeneration.current
    enrichGeneration.current += 1
    const enrichSeq = enrichGeneration.current
    let alive = true

    const hadCache = Boolean(readRegistryCache(cacheKey)?.rows.length)

    const load = async (): Promise<void> => {
      if (!hadCache) setLoading(true)
      else setRefreshing(true)
      setError('')
      try {
        const payload: Record<string, unknown> = {
          action: 'list',
          limit: 100,
          only_open: false
        }
        if (dateFrom.trim()) payload.date_from = dateFrom.trim()
        if (dateTo.trim()) payload.date_to = dateTo.trim()
        const res = await api.invokeServerTool('onec.erp_assignments', payload, 300_000)
        if (!alive || seq !== loadGeneration.current) return
        if (!res.ok) {
          if (!readRegistryCache(cacheKey)?.rows.length) setRows([])
          setError(String(res.error || 'Не удалось загрузить реестр поручений'))
          return
        }
        const mapped = parseAssignmentsPayload(res.result)
        applyRows(mapped)
        if (!mapped.length && res.result && typeof res.result === 'object') {
          const summary = String((res.result as Record<string, unknown>).summary || '').trim()
          if (summary.includes('stub')) {
            setError('OData 1С не настроен на backend (режим stub)')
          }
        }

        void enrichMissingLines(mapped, enrichSeq)
      } catch (exc) {
        if (!alive || seq !== loadGeneration.current) return
        if (!readRegistryCache(cacheKey)?.rows.length) setRows([])
        setError(exc instanceof Error ? exc.message : 'Ошибка загрузки реестра')
      } finally {
        if (seq === loadGeneration.current) {
          setLoading(false)
          setRefreshing(false)
        }
      }
    }

    async function enrichMissingLines(base: AssignmentRegistryRow[], generation: number): Promise<void> {
      const pending = base.filter((row) => row.refKey && row.lines.length === 0)
      if (!pending.length) return
      for (const stub of pending) {
        if (!alive || generation !== enrichGeneration.current || seq !== loadGeneration.current) return
        try {
          const res = await api.invokeServerTool(
            'onec.erp_assignments',
            { action: 'get', ref_key: stub.refKey },
            120_000
          )
          if (!alive || generation !== enrichGeneration.current) return
          if (!res.ok) continue
          const detailed = parseGetAssignment(res.result)
          if (!detailed?.lines.length) continue
          setRows((current) => {
            const merged = current.map((row) => {
              if (row.id !== stub.id) return row
              return {
                ...row,
                lines: detailed.lines,
                reporter: detailed.reporter !== '—' ? detailed.reporter : row.reporter,
                secretary: detailed.secretary !== '—' ? detailed.secretary : row.secretary,
                manager: detailed.manager !== '—' ? detailed.manager : row.manager
              }
            })
            writeRegistryCache(cacheKey, merged)
            return merged
          })
        } catch {
          /* следующее поручение */
        }
      }
    }

    void load()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, tick, cacheKey, applyRows])

  return { rows, loading, refreshing, error, refresh }
}
