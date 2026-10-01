import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type PositionKpiDaily, type PositionKpiMethodology } from '../api/types'
import type { WorkplaceKpiEmployeeMetric } from './workplaceKpiTypes'

function formatPct(value: number | null): string {
  if (value == null) return 'нет данных'
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`.replace('.0%', '%')
}

function sparkColor(score: number | null, plan: number | null): string {
  if (score == null) return '#6B7773'
  const target = plan ?? 95
  if (score + 1e-9 >= target) return '#08745F'
  if (score + 1e-9 >= target - 10) return '#C9A227'
  return '#C0392B'
}

export function positionTilesToEmployeeMetrics(snap: PositionKpiDaily): WorkplaceKpiEmployeeMetric[] {
  return snap.tiles.map((tile) => {
    const good = tile.score != null && tile.plan != null && tile.score + 1e-9 >= tile.plan
    return {
      id: tile.code,
      title: tile.name,
      displayValue: formatPct(tile.fact),
      trendDelta: tile.plan != null ? `план ${formatPct(tile.plan)}` : '',
      trendUp: good,
      trendPositive: good || tile.score == null,
      footerText: tile.evidence,
      sparklinePoints: tile.history.length
        ? tile.history.map((point) => point.value)
        : tile.fact != null
          ? [tile.fact]
          : [],
      sparklineColor: sparkColor(tile.score, tile.plan),
      source: 'computed',
      planValue: tile.plan,
      weight: tile.weight
    }
  })
}

export function usePositionKpi(position = ''): {
  snap: PositionKpiDaily | null
  metrics: WorkplaceKpiEmployeeMetric[]
  loading: boolean
  error: string
  missing: boolean
  incomplete: boolean
  needsBuild: boolean
  methodology: PositionKpiMethodology | null
  methodologyStatus: PositionKpiMethodology['status']
  reload: () => void
} {
  const [snap, setSnap] = useState<PositionKpiDaily | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [missing, setMissing] = useState(false)
  const [methodology, setMethodology] = useState<PositionKpiMethodology | null>(null)

  const reload = useCallback(() => {
    let alive = true
    setLoading(true)
    const methodRequest = api.getPositionKpiMethodology()
    void methodRequest
      .then((value) => {
        if (!alive) return
        setMethodology(value)
        setMissing(value.status === 'none')
      })
      .catch(() => undefined)
    void Promise.allSettled([methodRequest, api.getPositionKpi(position)])
      .then(([methodResult, kpiResult]) => {
        if (!alive) return
        if (methodResult.status === 'rejected') {
          setMethodology(null)
          setMissing(false)
          setError(
            methodResult.reason instanceof Error
              ? methodResult.reason.message
              : 'Не удалось проверить методику KPI'
          )
        }
        if (kpiResult.status === 'fulfilled') {
          setSnap(kpiResult.value)
          if (methodResult.status === 'fulfilled') setError('')
        } else if (kpiResult.reason instanceof ApiError && kpiResult.reason.status === 404) {
          setSnap(null)
        } else {
          setSnap(null)
          setError(
            kpiResult.reason instanceof Error
              ? kpiResult.reason.message
              : 'Не удалось загрузить KPI должности'
          )
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [position])

  useEffect(() => reload(), [reload])

  useEffect(() => {
    if (!snap || snap.tiles.length === 0 || snap.tiles.some((tile) => tile.fact != null)) return
    const timer = window.setTimeout(() => reload(), 12_000)
    return () => window.clearTimeout(timer)
  }, [snap, reload])

  // Пока статус не пришёл (или запрос упал), «методики нет» не показываем — это неизвестность, а не отсутствие.
  const methodologyStatus = methodology?.status ?? 'ready'
  const incomplete = methodologyStatus === 'needs_modules'
  const needsBuild = methodologyStatus === 'needs_modules'

  return {
    snap,
    metrics: snap && snap.tiles.length ? positionTilesToEmployeeMetrics(snap) : [],
    loading,
    error,
    missing,
    incomplete,
    needsBuild,
    methodology,
    methodologyStatus,
    reload
  }
}
