import { useEffect, useState } from 'react'
import { WorkplaceGlobalMonthPicker } from '../workplace/workplacePeriod'

export function KpiExportReportButton(): React.JSX.Element | null {
  const [editing, setEditing] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)

  useEffect(() => {
    const syncState = (event: Event): void => {
      setEditing(Boolean((event as CustomEvent<boolean>).detail))
    }
    const syncChat = (event: Event): void => {
      setChatOpen(Boolean((event as CustomEvent<boolean>).detail))
    }
    window.addEventListener('kpi:widget-edit-state', syncState)
    window.addEventListener('kpi:module-chat-state', syncChat)
    return () => {
      window.removeEventListener('kpi:widget-edit-state', syncState)
      window.removeEventListener('kpi:module-chat-state', syncChat)
    }
  }, [])

  if (chatOpen) return null

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
