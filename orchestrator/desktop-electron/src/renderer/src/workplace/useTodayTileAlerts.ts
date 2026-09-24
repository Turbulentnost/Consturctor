import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { InboxNotification } from '../api/types'
import { useRuns } from '../store/runs'
import {
  collectTodayTileAlerts,
  routeInboxNotification,
  type TodayAlertAgent,
  type TodayAlertTile,
  type TodayTileAlertFlags
} from './todayTileAlerts'

export function useTodayTileAlerts(agents: TodayAlertAgent[]): {
  alerts: TodayTileAlertFlags
  dismissTile: (tile: TodayAlertTile) => void
} {
  const runs = useRuns()
  const [notices, setNotices] = useState<InboxNotification[]>([])

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const items = await api.listNotifications()
      setNotices(items)
    } catch {
      /* keep last snapshot */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 20_000)
    const unsub = window.api.onInboxChanged?.(() => {
      void refresh()
    })
    return () => {
      window.clearInterval(timer)
      unsub?.()
    }
  }, [refresh])

  const liveRuns = useMemo(
    () =>
      Object.values(runs.entries).map((entry) => ({
        workflowId: entry.workflowId,
        title: entry.title,
        background: entry.background,
        running: Boolean(entry.state.running),
        pendingHitl: Boolean(entry.state.pendingHitl),
        pendingQuestion: Boolean(entry.state.pendingQuestion)
      })),
    [runs.entries]
  )

  const alerts = useMemo(
    () => collectTodayTileAlerts({ notices, agents, liveRuns }),
    [agents, liveRuns, notices]
  )

  const dismissTile = useCallback(
    (tile: TodayAlertTile) => {
      const unread = notices.filter((item) => item.unread && routeInboxNotification(item, agents) === tile)
      if (!unread.length) return
      const ids = new Set(unread.map((item) => item.id))
      setNotices((current) =>
        current.map((item) => (ids.has(item.id) ? { ...item, unread: false } : item))
      )
      for (const item of unread) {
        void api.markNotificationRead(item.id).catch(() => undefined)
      }
    },
    [agents, notices]
  )

  return { alerts, dismissTile }
}
