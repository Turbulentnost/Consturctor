import { useState } from 'react'
import type { KpiSide, KpiTile } from '../api/types'

export function formatKpiSide(side: KpiSide | null | undefined): string {
  if (!side || side.value === null || side.value === undefined || side.value === '') return '—'
  const unit = side.unit ? ` ${side.unit}` : ''
  return `${side.value}${unit}`
}

export function tileStatusClass(tile: KpiTile): string {
  const color = (tile.color || '').toLowerCase()
  if (color.includes('green')) return 'green'
  if (color.includes('yellow')) return 'yellow'
  if (color.includes('red')) return 'red'
  if (tile.scorePercent === null || tile.scorePercent === undefined) return 'muted'
  const green = tile.method?.greenMin ?? 90
  const yellow = tile.method?.yellowMin ?? 70
  if (tile.scorePercent >= green) return 'green'
  if (tile.scorePercent >= yellow) return 'yellow'
  return 'red'
}

function frequencyLabel(tile: KpiTile): string {
  const seconds = tile.method?.schedule?.intervalSeconds ?? 0
  if (!seconds) return 'Обновляется после запусков'
  if (seconds % 86400 === 0) {
    const d = seconds / 86400
    return d === 1 ? 'Обновляется раз в день' : `Обновляется раз в ${d} дн.`
  }
  if (seconds % 3600 === 0) {
    const h = seconds / 3600
    return h === 1 ? 'Обновляется раз в час' : `Обновляется раз в ${h} ч`
  }
  const m = Math.round(seconds / 60)
  return `Обновляется раз в ${m} мин`
}

export function KpiTileCard({ tile }: { tile: KpiTile }): React.JSX.Element {
  const [flipped, setFlipped] = useState(false)
  const status = tileStatusClass(tile)
  const scoreText =
    tile.scorePercent === null || tile.scorePercent === undefined
      ? 'KPI —'
      : `${Math.round(tile.scorePercent)}% KPI`

  return (
    <div
      className={`kpi-tile status-${status}`}
      onClick={() => setFlipped((value) => !value)}
      role="button"
    >
      {!flipped ? (
        <>
          <div className="kpi-tile-name">{tile.name || 'KPI'}</div>
          <div className="kpi-tile-freq">{frequencyLabel(tile)}</div>
          <div className="kpi-tile-fact">{formatKpiSide(tile.fact)}</div>
          <div className="kpi-tile-badge">{scoreText}</div>
          <div className="kpi-tile-plan">
            <span>{tile.plan.label || 'План'}</span>
            <strong>{formatKpiSide(tile.plan)}</strong>
          </div>
          {tile.plan.description && <div className="kpi-tile-desc">{tile.plan.description}</div>}
        </>
      ) : (
        <div className="kpi-tile-back">
          <div className="kpi-tile-name">Как считается</div>
          {tile.updatedAt && (
            <p>
              <b>Обновлено.</b> {new Date(tile.updatedAt).toLocaleString('ru-RU')}
            </p>
          )}
          {tile.evidence && (
            <p>
              <b>Данные.</b> {tile.evidence}
            </p>
          )}
          {tile.method?.planExplanation && (
            <p>
              <b>План.</b> {tile.method.planExplanation}
            </p>
          )}
          {tile.method?.factExplanation && (
            <p>
              <b>Факт.</b> {tile.method.factExplanation}
            </p>
          )}
          {tile.method?.scoreExplanation && (
            <p>
              <b>Оценка.</b> {tile.method.scoreExplanation}
            </p>
          )}
          {!tile.evidence &&
            !tile.method?.planExplanation &&
            !tile.method?.factExplanation &&
            !tile.method?.scoreExplanation && <p>{tile.plan.description || 'Расчёт по фактам запусков.'}</p>}
        </div>
      )}
    </div>
  )
}
