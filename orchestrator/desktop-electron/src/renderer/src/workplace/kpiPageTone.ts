import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'
import type { PositionKpiDaily } from '../api/types'

export type KpiPageTone = 'good' | 'bad' | 'neutral'

/** С какого общего процента KPI шапка зелёная; ниже — красная. */
export const KPI_GOOD_PCT = 80

/**
 * Общий KPI как у премии: сумма вкладов (вес × балл / 100) по посчитанным показателям.
 * Показатели без модуля не тянут итог к нулю — делим на сумму их весов.
 */
export function overallKpiPercent(snap: PositionKpiDaily | null): number | null {
  if (!snap) return null
  let contrib = 0
  let weight = 0
  for (const tile of snap.tiles) {
    if (tile.score == null || !(tile.weight > 0)) continue
    contrib += tile.contrib ?? (tile.weight * tile.score) / 100
    weight += tile.weight
  }
  if (!weight) return null
  return (contrib / weight) * 100
}

export function kpiPageTone(percent: number | null, broken: boolean): KpiPageTone {
  if (broken || percent == null || !Number.isFinite(percent)) return 'neutral'
  return percent + 1e-9 >= KPI_GOOD_PCT ? 'good' : 'bad'
}

/** Красит шапку страницы KPI до низа плиток, дальше цвет плавно уходит в белое. Снимается при уходе со страницы. */
export function useKpiPageTone(anchorRef: RefObject<HTMLElement | null>, tone: KpiPageTone, active = true): void {
  const gridRef = useRef<HTMLElement | null>(null)
  const toneRef = useRef(tone)
  toneRef.current = tone

  useLayoutEffect(() => {
    if (!active) return
    const anchor = anchorRef.current
    const grid = anchor?.closest<HTMLElement>('.orch-grid') ?? null
    const bar = anchor?.closest<HTMLElement>('.tab-chrome-tiles-bar') ?? anchor
    if (!grid || !bar) return
    gridRef.current = grid
    grid.dataset.kpiTone = toneRef.current
    const measure = (): void => {
      const height = bar.getBoundingClientRect().bottom - grid.getBoundingClientRect().top
      grid.style.setProperty('--kpi-hero-h', `${Math.max(0, Math.round(height))}px`)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(grid)
    observer.observe(bar)
    return () => {
      observer.disconnect()
      grid.style.removeProperty('--kpi-hero-h')
      delete grid.dataset.kpiTone
      gridRef.current = null
    }
  }, [anchorRef, active])

  useEffect(() => {
    if (active && gridRef.current) gridRef.current.dataset.kpiTone = tone
  }, [tone, active])
}
