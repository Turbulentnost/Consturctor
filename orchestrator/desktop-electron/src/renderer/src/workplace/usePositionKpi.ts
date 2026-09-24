import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type PositionKpiDaily } from '../api/types'
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
      sparklinePoints: [tile.score ?? tile.fact ?? 0],
      sparklineColor: sparkColor(tile.score, tile.plan),
      source: 'computed'
    }
  })
}

export function positionKpiNeedsBuild(opts: {
  loading: boolean
  missing: boolean
  snap: PositionKpiDaily | null
}): boolean {
  if (opts.loading) return false
  if (opts.missing) return true
  return !opts.snap || opts.snap.tiles.length === 0
}

export function usePositionKpi(position = ''): {
  snap: PositionKpiDaily | null
  metrics: WorkplaceKpiEmployeeMetric[]
  loading: boolean
  error: string
  missing: boolean
  incomplete: boolean
  needsBuild: boolean
  reload: () => void
} {
  const [snap, setSnap] = useState<PositionKpiDaily | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [missing, setMissing] = useState(false)

  const reload = useCallback(() => {
    let alive = true
    setLoading(true)
    void api
      .getPositionKpi(position)
      .then((next) => {
        if (!alive) return
        setSnap(next)
        setMissing(false)
        setError('')
      })
      .catch((err: unknown) => {
        if (!alive) return
        if (err instanceof ApiError && err.status === 404) {
          setSnap(null)
          setMissing(true)
          setError('')
          return
        }
        setMissing(false)
        setError(err instanceof Error ? err.message : 'Не удалось загрузить KPI должности')
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

  const incomplete = Boolean(snap) && snap!.tiles.length === 0
  const needsBuild = positionKpiNeedsBuild({ loading, missing, snap })

  return {
    snap,
    metrics: snap && snap.tiles.length ? positionTilesToEmployeeMetrics(snap) : [],
    loading,
    error,
    missing,
    incomplete,
    needsBuild,
    reload
  }
}
