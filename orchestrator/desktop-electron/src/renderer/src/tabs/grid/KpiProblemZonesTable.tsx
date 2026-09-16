import { SpecPill } from '../../workplace/specV04Components'
import type { WorkplaceKpiProblemZone } from '../../workplace/workplaceKpiTypes'

function TypeIcon({ severity }: { severity: string }): React.JSX.Element {
  const tone = severity === 'red' ? '#c0392b' : '#e8943a'
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="kpi-pz-type-icon" aria-hidden>
      <path
        d="M12 3L2 21h20L12 3z"
        fill={tone}
        stroke={tone}
        strokeWidth="0.5"
        strokeLinejoin="round"
      />
      <path d="M12 9v5M12 16v1" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function KpiProblemZonesTable({
  zones,
  loading
}: {
  zones: WorkplaceKpiProblemZone[]
  loading?: boolean
}): React.JSX.Element {
  const count = zones.length
  return (
    <section className="kpi-problem-zones kpi-problem-zones--strip">
      <header className="kpi-problem-zones-head">
        <span className="kpi-problem-zones-icon" aria-hidden>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="#c0392b" />
            <path d="M12 7v6M12 16v1" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </span>
        <h3 className="kpi-problem-zones-title">Проблемные зоны / отклонения</h3>
        <span className="kpi-problem-zones-all">Все отклонения ({count}) →</span>
      </header>
      <div className="spec-v04-table-wrap kpi-problem-zones-table-wrap">
        <table className="spec-v04-table kpi-problem-zones-table">
          <colgroup>
            <col className="kpi-pz-col-type" />
            <col className="kpi-pz-col-process" />
            <col className="kpi-pz-col-indicator" />
            <col className="kpi-pz-col-current" />
            <col className="kpi-pz-col-target" />
            <col className="kpi-pz-col-dev" />
            <col className="kpi-pz-col-status" />
            <col className="kpi-pz-col-rec" />
          </colgroup>
          <thead>
            <tr>
              <th>Тип</th>
              <th>Процесс</th>
              <th>Показатель</th>
              <th>Текущее</th>
              <th>Целевое</th>
              <th>Откл.</th>
              <th>Статус</th>
              <th>Рекомендации</th>
            </tr>
          </thead>
          <tbody>
            {loading && !zones.length ? (
              <tr>
                <td colSpan={8} className="spec-v04-empty">
                  Загружаем…
                </td>
              </tr>
            ) : null}
            {!loading && !zones.length ? (
              <tr>
                <td colSpan={8} className="spec-v04-empty">
                  Нет проблемных зон
                </td>
              </tr>
            ) : null}
            {zones.map((zone) => (
              <tr key={zone.id}>
                <td>
                  <div className="kpi-pz-type-cell">
                    <TypeIcon severity={zone.severity} />
                    <strong>{zone.typeLabel || zone.metric}</strong>
                  </div>
                </td>
                <td title={zone.process || zone.zone}>{zone.process || zone.zone}</td>
                <td>{zone.indicator || zone.metric}</td>
                <td className="kpi-pz-num">{zone.currentValue || zone.value}</td>
                <td className="kpi-pz-num">{zone.targetValue || '—'}</td>
                <td className="kpi-pz-deviation kpi-pz-num">{zone.deviation || '—'}</td>
                <td>
                  <SpecPill tone={zone.statusTone}>{zone.status}</SpecPill>
                </td>
                <td title={zone.recommendation}>{zone.recommendation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
