import { useEffect, useState } from 'react'
import {
  dedupeMeetingEvents,
  ensureOutlookMeetings,
  type MeetingEvent
} from '../utils/outlookMeetings'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'

function dayKeyFrom(day: Date): string {
  return `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`
}

export interface TodayOutlookMeetingsState {
  loading: boolean
  error: string
  meetings: MeetingEvent[]
}

/**
 * Own Outlook calendar for the week around «Период».
 * Same source as the day plan and the calendar tab — not the KPI snapshot.
 */
export function useTodayOutlookMeetings(
  periodDay: Date,
  options: { userId: string; fio: string }
): TodayOutlookMeetingsState {
  const { userId, fio } = options
  const generation = useGridRefreshGeneration()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])

  const dayKey = dayKeyFrom(periodDay)

  useEffect(() => {
    let alive = true
    const cacheKey = `today-outlook-meetings:${userId}:${dayKey}`
    if (!shouldRunGridFetch(cacheKey, generation)) {
      const cached = readGridCache<{ meetings: MeetingEvent[]; error: string }>(cacheKey)
      if (cached) {
        setMeetings(cached.meetings)
        setError(cached.error)
        setLoading(false)
        return
      }
    }
    const hadCache = Boolean(readGridCache<{ meetings: MeetingEvent[]; error: string }>(cacheKey))
    if (!hadCache) setLoading(true)
    setError('')
    void ensureOutlookMeetings('week', periodDay, { owner: fio })
      .then((res) => {
        if (!alive) return
        if (!res.ok) {
          const errText = res.error || 'Outlook недоступен'
          setMeetings([])
          setError(errText)
          writeGridCache(cacheKey, { meetings: [], error: errText })
          return
        }
        const next = dedupeMeetingEvents(res.meetings || [])
        setMeetings(next)
        setError('')
        writeGridCache(cacheKey, { meetings: next, error: '' })
      })
      .catch((err) => {
        if (!alive) return
        const errText = err instanceof Error ? err.message : 'Ошибка календаря'
        setMeetings([])
        setError(errText)
        writeGridCache(cacheKey, { meetings: [], error: errText })
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [dayKey, fio, generation, periodDay, userId])

  return {
    loading: loading && meetings.length === 0,
    error: meetings.length ? '' : error,
    meetings
  }
}
