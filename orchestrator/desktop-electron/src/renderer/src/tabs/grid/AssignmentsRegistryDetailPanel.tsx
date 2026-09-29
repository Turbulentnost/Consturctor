import { Printer, X } from 'lucide-react'
import type { AssignmentRegistryRow } from '../../workplace/assignmentRegistryTypes'
import { buildAssignmentCardPrintHtml } from '../../workplace/registryPrint'

function DetailField({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <div className="registry-detail-field">
      <span className="registry-detail-label">{label}</span>
      <span className="registry-detail-value">{value || '—'}</span>
    </div>
  )
}

export function AssignmentsRegistryDetailPanel({
  row,
  linesLoading = false,
  onClose
}: {
  row: AssignmentRegistryRow | null
  linesLoading?: boolean
  onClose: () => void
}): React.JSX.Element {
  if (!row) {
    return (
      <aside className="registry-detail-panel registry-detail-panel--empty">
        <p className="registry-detail-placeholder">
          Выберите строку в таблице, чтобы открыть карточку поручения и список задач.
        </p>
      </aside>
    )
  }

  return (
    <aside className={`registry-detail-panel tone-${row.tone}`}>
      <div className="registry-detail-head">
        <div>
          <h3 className="registry-detail-title">{row.number}</h3>
          <p className="registry-detail-subtitle">{row.topic}</p>
        </div>
        <div className="registry-detail-head-actions">
          <button
            type="button"
            className="registry-detail-close"
            title="Печать карточки поручения"
            onClick={() => void window.api.printDialog({ html: buildAssignmentCardPrintHtml(row) })}
          >
            <Printer size={16} aria-hidden />
          </button>
          <button type="button" className="registry-detail-close" title="Закрыть" onClick={onClose}>
            <X size={16} aria-hidden />
          </button>
        </div>
      </div>

      <div className="registry-detail-scroll">
        <div className="registry-detail-grid">
          <DetailField label="Статус" value={row.status} />
          <DetailField label="Дата" value={row.date} />
          <DetailField label="Руководитель" value={row.manager} />
          <DetailField label="Организация" value={row.organization} />
          <DetailField label="Основание" value={row.basis} />
          <DetailField label="Срок устранения" value={row.fullRemediationDue} />
          <DetailField label="Еженедельный отчёт" value={row.weeklyReportDate} />
          <DetailField label="Итоговый доклад" value={row.finalReportDate} />
          <DetailField label="Кто доложит" value={row.reporter} />
          <DetailField label="Секретарь" value={row.secretary} />
        </div>

        <h4 className="registry-detail-tasks-title">
          Задачи {row.lines.length ? `(${row.lines.length})` : ''}
        </h4>
        {linesLoading && !row.lines.length ? (
          <p className="registry-detail-tasks-empty">Загрузка задач из 1С…</p>
        ) : row.lines.length ? (
          <ul className="registry-detail-tasks">
            {row.lines.map((line, index) => (
              <li key={`${row.id}-${line.line}`} className="registry-detail-task">
                <div className="registry-detail-task-head">
                  <span className="registry-detail-task-num">Задача {line.line || index + 1}</span>
                  {line.priority && line.priority !== '—' ? (
                    <span className="registry-detail-task-priority">{line.priority}</span>
                  ) : null}
                </div>
                <p className="registry-detail-task-text">{line.text}</p>
                <dl className="registry-detail-task-meta">
                  <div>
                    <dt>Исполнитель</dt>
                    <dd>{line.executor}</dd>
                  </div>
                  <div>
                    <dt>Срок</dt>
                    <dd>{line.due !== '—' ? line.due : '—'}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        ) : (
          <p className="registry-detail-tasks-empty">Задачи не пришли из 1С — обновите реестр или дождитесь догрузки.</p>
        )}
      </div>
    </aside>
  )
}
