import { useEffect, useMemo, useState } from 'react'
import type { SpecMailRow } from './specV04DemoData'
import { outlookMessageToMailRow } from './specV04Mappers'
import {
  dayKeyLocal,
  ensureOutlookMailRange,
  formatMailReceivedLabel,
  formatMailTime
} from '../utils/outlookMail'
import { filterMessagesOnDay } from './mailProbe'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'

function dayKeyFrom(day: Date): string {
  return `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`
}

export interface TodayOutlookMailState {
  loading: boolean
  error: string
  source: string
  rows: SpecMailRow[]
}

export function useTodayOutlookMail(periodDay: Date): TodayOutlookMailState {
  const generation = useGridRefreshGeneration()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [source, setSource] = useState('')
  const [rows, setRows] = useState<SpecMailRow[]>([])

  const dayKey = dayKeyFrom(periodDay)

  useEffect(() => {
    let alive = true
    const cacheKey = `today-outlook-mail-inout:${dayKey}`
    if (!shouldRunGridFetch(cacheKey, generation)) {
      const cached = readGridCache<{ error: string; source: string; rows: SpecMailRow[] }>(cacheKey)
      if (cached) {
        setError(cached.error)
        setSource(cached.source)
        setRows(cached.rows)
        setLoading(false)
        return
      }
    }
    setLoading(true)
    setError('')
    void (async () => {
      try {
        const dayIso = dayKeyLocal(periodDay)
        const batch = await ensureOutlookMailRange('', dayIso, dayIso, {
          folder: 'All',
          maxResults: 80
        })
        if (!alive) return
        if (!batch.ok) {
          setRows([])
          setSource('')
          setError(batch.error || 'Outlook недоступен')
          return
        }
        const combined = filterMessagesOnDay(batch.messages, dayIso).sort((left, right) =>
          String(right.datetime || right.sent_at || right.received_at || '').localeCompare(
            String(left.datetime || left.sent_at || left.received_at || '')
          )
        )
        const mapped = combined.map(
          (msg, index) => {
            const row = outlookMessageToMailRow(msg, index)
            return {
              ...row,
              receivedAt: String(msg.datetime || msg.received_at || msg.sent_at || row.receivedAt || row.time),
              time: formatMailTime(String(msg.datetime || msg.received_at || msg.sent_at || row.time)),
              receivedLabel: formatMailReceivedLabel(
                String(msg.datetime || msg.received_at || msg.sent_at || row.time)
              )
            }
          }
        )
        const seen = new Set<string>()
        const nextRows = mapped.filter((row) => {
          const key = row.id
          if (!key || seen.has(key)) return false
          seen.add(key)
          return true
        })
        const nextSource = batch.cached ? 'outlook_com (cache)' : 'outlook_com (All)'
        const nextError = ''
        setSource(nextSource)
        setRows(nextRows)
        setError(nextRows.length ? '' : nextError)
        writeGridCache(cacheKey, { error: nextRows.length ? '' : nextError, source: nextSource, rows: nextRows })
      } catch (err) {
        if (!alive) return
        setRows([])
        setSource('')
        setError(err instanceof Error ? err.message : 'Ошибка загрузки почты')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [dayKey, generation, periodDay])

  const resolvedRows = useMemo(() => {
    return rows
  }, [rows])

  return {
    loading: loading && resolvedRows.length === 0,
    error: resolvedRows.length ? '' : error,
    source,
    rows: resolvedRows
  }
}
