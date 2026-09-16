import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { WorkplaceKpiDashboard } from './workplaceKpiTypes'
import {
  formatWorkplaceKpiLoadError,
  shouldUseWorkplaceKpiReferenceFallback
} from './workplaceKpiLoadError'
import { buildReferenceWorkplaceKpiDashboard } from './workplaceKpiReferenceFallback'
import { currentWeekRange } from './kpiPeriod'

const WEEK = currentWeekRange()
const DEFAULT_FROM = WEEK.from
const DEFAULT_TO = WEEK.to

const OFFLINE_NOTICE =
  'Показаны эталонные KPI (offline): маршрут /api/v1/workplace/kpi недоступен на gateway — обновите LAN или используйте локальный backend.'

export function useWorkplaceKpiDashboard(periodFrom = DEFAULT_FROM, periodTo = DEFAULT_TO): {
  data: WorkplaceKpiDashboard | null
  loading: boolean
  error: string
  notice: string
  reload: () => void
} {
  const [data, setData] = useState<WorkplaceKpiDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const reload = useCallback(() => {
    setLoading(true)
    setError('')
    setNotice('')
    void api
      .getWorkplaceKpi({ from: periodFrom, to: periodTo })
      .then((next) => setData(next))
      .catch((err: unknown) => {
        if (shouldUseWorkplaceKpiReferenceFallback(err)) {
          setData(buildReferenceWorkplaceKpiDashboard(periodFrom, periodTo))
          setError('')
          setNotice(OFFLINE_NOTICE)
          return
        }
        setData(null)
        setError(formatWorkplaceKpiLoadError(err))
      })
      .finally(() => setLoading(false))
  }, [periodFrom, periodTo])

  useEffect(() => {
    reload()
  }, [reload])

  return { data, loading, error, notice, reload }
}
