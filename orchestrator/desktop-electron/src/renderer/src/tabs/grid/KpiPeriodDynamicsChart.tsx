import type { WorkplaceKpiDynamics } from '../../workplace/workplaceKpiTypes'

const PAD = { left: 28, right: 8, top: 8, bottom: 22 }

function chartPoints(
  points: number[],
  width: number,
  height: number,
  yMax: number
): { x: number; y: number }[] {
  if (!points.length) return []
  const innerW = width - PAD.left - PAD.right
  const innerH = height - PAD.top - PAD.bottom
  const step = points.length > 1 ? innerW / (points.length - 1) : 0
  const max = Math.max(1, yMax)
  return points.map((value, index) => ({
    x: PAD.left + index * step,
    y: PAD.top + innerH - (value / max) * innerH
  }))
}

export function KpiPeriodDynamicsChart({ dynamics }: { dynamics: WorkplaceKpiDynamics }): React.JSX.Element {
  const width = 320
  const height = 120
  const yMax = dynamics.yMax || 100
  const labels = dynamics.xLabels
  const yTicks = [0, 50, 100].filter((t) => t <= yMax)

  const innerW = width - PAD.left - PAD.right
  const innerH = height - PAD.top - PAD.bottom

  return (
    <div className="kpi-period-dynamics">
      <svg viewBox={`0 0 ${width} ${height}`} className="kpi-period-dynamics-svg" preserveAspectRatio="xMidYMid meet">
        {yTicks.map((tick) => {
          const y = PAD.top + innerH - (tick / yMax) * innerH
          return (
            <g key={`y-${tick}`}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y} y2={y} className="kpi-period-grid" />
              <text x={PAD.left - 4} y={y + 3} textAnchor="end" className="kpi-period-axis-y">
                {tick}
              </text>
            </g>
          )
        })}
        {labels.map((label, index) => {
          const step = labels.length > 1 ? innerW / (labels.length - 1) : 0
          const x = PAD.left + index * step
          return (
            <g key={`x-${label}-${index}`}>
              <line x1={x} x2={x} y1={PAD.top} y2={PAD.top + innerH} className="kpi-period-grid kpi-period-grid--v" />
              <text x={x} y={height - 4} textAnchor="middle" className="kpi-period-axis-x">
                {label}
              </text>
            </g>
          )
        })}
        {dynamics.series.map((series) => {
          const pts = chartPoints(series.points, width, height, yMax)
          const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
          return (
            <g key={series.id}>
              {line ? (
                <polyline points={line} fill="none" stroke={series.color} strokeWidth={2} className="kpi-period-line" />
              ) : null}
              {pts.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={3} fill={series.color} className="kpi-period-dot" />
              ))}
            </g>
          )
        })}
      </svg>
      <div className="kpi-period-dynamics-legend">
        {dynamics.series.map((series) => (
          <span key={series.id}>
            <i style={{ background: series.color }} />
            {series.label}
          </span>
        ))}
      </div>
    </div>
  )
}
