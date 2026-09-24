import { useEffect, useId } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { SpecPill } from '../../workplace/specV04Components'
import type { SpecTaskRow } from '../../workplace/specV04DemoData'
import { formatPlatformDateTime, PLATFORM_STATUS_LABEL } from '../../workplace/platformTasks'
import { openWorkplaceTab } from '../../workplace/workplaceNav'

/** Строка любого виджета задач «Сегодня»: 1С, платформа, проекты Turbo. */
export type TodayTaskDetailRow = Partial<SpecTaskRow> &
  Pick<SpecTaskRow, 'id' | 'title' | 'status' | 'statusTone'>

function text(value: string | undefined): string {
  const clean = (value || '').trim()
  return clean && clean !== '—' ? clean : ''
}

/** Полное описание задачи: у платформы — текст постановки, у 1С — шаг и комментарий. */
function description(row: TodayTaskDetailRow): string {
  if (row.platform) return row.platform.description.trim()
  return [text(row.process), text(row.taskName)].filter(Boolean).join('\n')
}

export function TodayTaskDetailModal({
  row,
  onClose,
  onAskOrchestrator
}: {
  row: TodayTaskDetailRow | null
  onClose: () => void
  onAskOrchestrator?: (message: string, appContext: string) => void
}): React.JSX.Element | null {
  const titleId = useId()

  useEffect(() => {
    if (!row) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [row, onClose])

  if (!row) return null
  const platform = row.platform
  const body = description(row)
  const fields: { label: string; value: string }[] = [
    { label: 'Номер', value: text(row.taskNumber) },
    { label: 'Проект', value: text(row.project) },
    { label: 'Шаг', value: text(row.step) },
    { label: 'Автор', value: text(row.author) },
    { label: 'Исполнитель', value: text(row.performer || row.executor) },
    { label: 'Срок', value: text(row.deadline) },
    {
      label: 'Принять до',
      value: platform?.awaitingReview && platform.reviewDueAt ? formatPlatformDateTime(platform.reviewDueAt) : ''
    },
    {
      label: 'Отметка исполнителя',
      value: platform && platform.status !== 'open' ? PLATFORM_STATUS_LABEL[platform.status] : ''
    },
    { label: 'Комментарий исполнителя', value: text(platform?.statusComment) },
    { label: 'Возвратов на доработку', value: platform?.reworkCount ? String(platform.reworkCount) : '' }
  ].filter((item) => item.value)

  return createPortal(
    <div className="modal-overlay today-task-detail-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card today-task-detail"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-task-detail-head">
          <div>
            <h4 className="modal-title" id={titleId}>
              {row.title}
            </h4>
            <div className="today-task-detail-pills">
              <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
              {text(row.priority) ? (
                <SpecPill tone={row.priorityTone || 'gray'}>{row.priority}</SpecPill>
              ) : null}
              {text(row.source) ? <SpecPill tone={row.sourceTone || 'blue'}>{row.source}</SpecPill> : null}
            </div>
          </div>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            <X size={16} aria-hidden />
          </button>
        </header>

        <div className="today-task-detail-body">
          {body ? (
            <p className="today-task-detail-text">{body}</p>
          ) : (
            <p className="today-task-detail-text spec-v04-muted">Описание в задаче не заполнено</p>
          )}
          {fields.length ? (
            <dl className="today-task-detail-fields">
              {fields.map((item) => (
                <div key={item.label}>
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>

        <div className="today-task-detail-actions">
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              onClose()
              openWorkplaceTab('tasks')
            }}
          >
            Открыть в задачах
          </button>
          {onAskOrchestrator ? (
            <button
              type="button"
              className="btn-light"
              onClick={() => {
                onClose()
                onAskOrchestrator(
                  `Помоги с задачей «${row.title}»${text(row.author) ? ` от ${row.author}` : ''}`,
                  'Сегодня · задача'
                )
              }}
            >
              Передать ИИ
            </button>
          ) : null}
          <button type="button" className="btn-light" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
