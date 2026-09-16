import { useEffect, useId } from 'react'
import { createPortal } from 'react-dom'
import { SpecPill } from '../../workplace/specV04Components'
import type { TodayDayBreakdown } from '../../workplace/useTodayKpiData'

function BreakdownSection({
  title,
  items
}: {
  title: string
  items: TodayDayBreakdown['done']
}): React.JSX.Element {
  return (
    <section className="today-day-breakdown-section">
      <h5>
        {title}
        <span className="spec-v04-muted">{items.length}</span>
      </h5>
      {items.length ? (
        <ul className="today-day-breakdown-list">
          {items.map((item) => (
            <li key={item.id} className="today-day-breakdown-item">
              <div className="today-day-breakdown-body">
                <strong>{item.title}</strong>
                <small className="spec-v04-muted">
                  {item.source}
                  {item.deadline && item.deadline !== '—' ? ` · ${item.deadline}` : ''}
                </small>
              </div>
              <SpecPill tone={item.statusTone}>{item.status}</SpecPill>
            </li>
          ))}
        </ul>
      ) : (
        <p className="today-table-status">Нет позиций</p>
      )}
    </section>
  )
}

export function TodayDayBreakdownModal({
  open,
  breakdown,
  loading,
  onClose
}: {
  open: boolean
  breakdown: TodayDayBreakdown
  loading?: boolean
  onClose: () => void
}): React.JSX.Element | null {
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div className="modal-overlay today-day-breakdown-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card today-day-breakdown-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-plan-detail-head">
          <h4 className="modal-title" id={titleId}>
            Выполнение дня
            {breakdown.dayTotal ? ` · ${breakdown.dayDone} из ${breakdown.dayTotal}` : ''}
          </h4>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <p className="today-day-breakdown-hint spec-v04-muted">Задачи 1С и регламентные агенты на сегодня</p>
        {loading && !breakdown.dayTotal ? (
          <p className="today-table-status">Загружаем…</p>
        ) : !breakdown.dayTotal ? (
          <p className="today-table-status">Нет задач 1С и регламентных запусков на сегодня</p>
        ) : (
          <>
            <BreakdownSection title="Сделано" items={breakdown.done} />
            <BreakdownSection title="Ещё сделать" items={breakdown.todo} />
          </>
        )}
        <div className="modal-actions">
          <button type="button" className="btn-light" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
