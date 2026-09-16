import { useId } from 'react'
import type { WorkplaceKpiEmployeeMetric } from '../../workplace/workplaceKpiTypes'

function sparklinePath(points: number[], width: number, height: number, max: number): string {
  if (!points.length) return ''
  const yMax = Math.max(1, max)
  const step = points.length > 1 ? width / (points.length - 1) : width
  return points
    .map((value, index) => {
      const x = index * step
      const y = height - (value / yMax) * (height - 8) - 4
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function sparklineArea(points: number[], width: number, height: number, max: number): string {
  const line = sparklinePath(points, width, height, max)
  if (!line) return ''
  return `${line} L ${width},${height} L 0,${height} Z`
}

function yMaxForMetric(metric: WorkplaceKpiEmployeeMetric): number {
  if (metric.id === 'quality') return 5
  return 100
}

function KpiEmployeeTile({ metric, gradId }: { metric: WorkplaceKpiEmployeeMetric; gradId: string }): React.JSX.Element {
  const width = 200
  const height = 52
  const yMax = yMaxForMetric(metric)
  const points = metric.sparklinePoints.length ? metric.sparklinePoints : [0]
  const color = metric.sparklineColor || '#1565c0'
  const trendClass =
    metric.trendPositive === false && metric.trendUp ? 'is-warn-up' : metric.trendPositive ? 'is-good' : 'is-bad'

  return (
    <article className="kpi-employee-tile">
      <div className="kpi-employee-tile-head">
        <span className="kpi-employee-tile-title">{metric.title}</span>
      </div>
      <div className="kpi-employee-tile-values">
        <strong>{metric.displayValue}</strong>
        {metric.trendDelta ? (
          <span className={`kpi-employee-trend ${trendClass}`} aria-hidden>
            {metric.trendUp ? '↑' : '↓'} {metric.trendDelta}
          </span>
        ) : null}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="kpi-employee-spark" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <path d={sparklineArea(points, width, height, yMax)} fill={`url(#${gradId})`} />
        <polyline points={sparklinePath(points, width, height, yMax)} fill="none" stroke={color} strokeWidth="2" />
      </svg>
      {metric.footerText ? <p className="kpi-employee-footer">{metric.footerText}</p> : null}
    </article>
  )
}

export function KpiEmployeePanel({
  metrics,
  loading,
  onDetails
}: {
  metrics: WorkplaceKpiEmployeeMetric[]
  loading?: boolean
  onDetails?: () => void
}): React.JSX.Element {
  const gradPrefix = useId().replace(/:/g, '')
  return (
    <section className="kpi-employee-panel">
      <header className="kpi-employee-panel-head">
        <span className="kpi-employee-panel-icon" aria-hidden>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="#1565c0" />
            <path
              d="M12 11a3 3 0 100-6 3 3 0 000 6zM6 19c0-2.2 2.7-4 6-4s6 1.8 6 4"
              stroke="#fff"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </span>
        <h3 className="kpi-employee-panel-title">KPI сотрудника</h3>
        <button type="button" className="kpi-employee-panel-more" onClick={() => onDetails?.()} title="Подробнее">
          Подробнее →
        </button>
      </header>
      {loading && !metrics.length ? (
        <p className="spec-v04-muted kpi-employee-loading">Загружаем…</p>
      ) : (
        <div className="kpi-employee-grid">
          {metrics.map((m) => (
            <KpiEmployeeTile key={m.id} metric={m} gradId={`${gradPrefix}-${m.id}`} />
          ))}
        </div>
      )}
    </section>
  )
}
