import { useEffect, useMemo, useState } from 'react'
import { TODAY_MAIL_ROWS } from '../tabs/grid/todayDemoData'
import type { SpecMailRow } from './specV04DemoData'
import { outlookMessageToMailRow } from './specV04Mappers'
import { fetchOutlookMailForDay, formatMailReceivedLabel, formatMailTime } from '../utils/outlookMail'
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
    const cacheKey = `today-outlook-mail:${dayKey}`
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
    void fetchOutlookMailForDay(periodDay, { folder: 'Inbox', maxResults: 50 })
      .then((res) => {
        if (!alive) return
        if (!res.ok) {
          setRows([])
          setSource('')
          setError(res.error || 'Outlook недоступен')
          return
        }
        const nextSource = res.source || 'outlook_com'
        const nextRows = res.messages.map((msg, index) => {
          const row = outlookMessageToMailRow(msg, index)
          return {
            ...row,
            time: formatMailTime(row.time),
            receivedLabel: formatMailReceivedLabel(row.time)
          }
        })
        setSource(nextSource)
        setRows(nextRows)
        writeGridCache(cacheKey, { error: '', source: nextSource, rows: nextRows })
      })
      .catch((err) => {
        if (!alive) return
        setRows([])
        setSource('')
        setError(err instanceof Error ? err.message : 'Ошибка загрузки почты')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [dayKey, generation, periodDay])

  const resolvedRows = useMemo(() => {
    if (rows.length) return rows
    return TODAY_MAIL_ROWS
  }, [rows])

  return {
    loading: loading && rows.length === 0,
    error: resolvedRows.length ? '' : error,
    source: resolvedRows.length && !rows.length ? 'demo' : source,
    rows: resolvedRows
  }
}
