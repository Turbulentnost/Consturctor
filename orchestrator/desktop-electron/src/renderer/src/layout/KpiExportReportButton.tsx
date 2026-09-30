import { useEffect, useState } from 'react'
import { WorkplaceGlobalMonthPicker } from '../workplace/workplacePeriod'

export function KpiExportReportButton(): React.JSX.Element {
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    const syncState = (event: Event): void => {
      setEditing(Boolean((event as CustomEvent<boolean>).detail))
    }
    window.addEventListener('kpi:widget-edit-state', syncState)
    return () => window.removeEventListener('kpi:widget-edit-state', syncState)
  }, [])

  return (
    <div className="kpi-header-actions">
      <WorkplaceGlobalMonthPicker />
      <button
        type="button"
        className="spec-btn-outline"
        onClick={() => window.dispatchEvent(new Event('kpi:open-bonus-form'))}
      >
        Экспорт отчёта
      </button>
      <button
        type="button"
        className={`spec-btn-outline${editing ? ' is-active' : ''}`}
        aria-pressed={editing}
        onClick={() => window.dispatchEvent(new Event('kpi:toggle-widget-edit'))}
      >
        {editing ? 'Готово' : 'Редактировать виджеты'}
      </button>
    </div>
  )
}
