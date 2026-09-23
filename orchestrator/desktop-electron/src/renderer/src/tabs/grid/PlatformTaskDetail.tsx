import { useEffect, useState } from 'react'
import { Paperclip } from 'lucide-react'
import { api } from '../../api/client'
import { SpecPill } from '../../workplace/specV04Components'
import type { SpecTaskRow } from '../../workplace/specV04DemoData'
import {
  formatPlatformDateTime,
  isPlatformTaskMine,
  PLATFORM_PRIORITY_LABEL,
  type PlatformTask
} from '../../workplace/platformTasks'
import './platformTasks.css'

export async function completePlatformTask(task: PlatformTask): Promise<string> {
  await api.setPlatformTaskStatus(task.id, 'done')
  return 'Задача отмечена исполненной, постановщик получит уведомление.'
}

export function PlatformTaskDetail({
  row,
  onChanged
}: {
  row: SpecTaskRow
  onChanged: (message: string) => void
}): React.JSX.Element | null {
  const task = row.platform
  const [rejecting, setRejecting] = useState(false)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setRejecting(false)
    setComment('')
    setError('')
  }, [task?.id])

  if (!task) return null
  const canAct = isPlatformTaskMine(task) && task.status === 'open'

  const run = async (action: 'done' | 'reject'): Promise<void> => {
    if (action === 'reject' && !comment.trim()) {
      setError('Укажите причину отклонения')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.setPlatformTaskStatus(task.id, action, comment.trim())
      onChanged(
        action === 'done'
          ? 'Задача отмечена исполненной, постановщик получит уведомление.'
          : 'Задача отклонена, постановщик получит уведомление.'
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось изменить задачу')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`spec-detail-card wp-card ptask-detail prio-${task.priority}`}>
      <h2>{row.title}</h2>
      <div className="ptask-detail-pills">
        <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
        <SpecPill tone={row.priorityTone}>Приоритет: {PLATFORM_PRIORITY_LABEL[task.priority].toLowerCase()}</SpecPill>
      </div>
      <p className="ptask-detail-text">{task.description}</p>
      <dl className="spec-detail-meta">
        <div>
          <dt>Постановщик</dt>
          <dd>{task.authorFio || '—'}</dd>
        </div>
        <div>
          <dt>Исполнитель</dt>
          <dd>{task.assigneeFio || '—'}</dd>
        </div>
        <div>
          <dt>Поставлена</dt>
          <dd>{formatPlatformDateTime(task.postedAt)}</dd>
        </div>
        <div>
          <dt>Срок</dt>
          <dd className={task.overdue && task.status === 'open' ? 'spec-deadline-urgent' : undefined}>
            {formatPlatformDateTime(task.dueAt)}
          </dd>
        </div>
        {task.status !== 'open' && task.statusAt ? (
          <div>
            <dt>{task.status === 'done' ? 'Исполнена' : 'Отклонена'}</dt>
            <dd>{formatPlatformDateTime(task.statusAt)}</dd>
          </div>
        ) : null}
        {task.statusComment ? (
          <div>
            <dt>Комментарий</dt>
            <dd>{task.statusComment}</dd>
          </div>
        ) : null}
      </dl>
      {task.files.length ? (
        <div className="ptask-detail-files">
          <h3>Файлы</h3>
          {task.files.map((file) => (
            <button
              key={file.id}
              type="button"
              className="ptask-file"
              onClick={() => void api.downloadPlatformTaskFile(task.id, file.id, file.filename)}
            >
              <Paperclip size={13} aria-hidden /> {file.filename}
            </button>
          ))}
        </div>
      ) : null}
      {canAct ? (
        <div className="ptask-detail-actions">
          {rejecting ? (
            <>
              <textarea
                className="onec-reconnect-input"
                rows={3}
                value={comment}
                placeholder="Причина отклонения — её увидит постановщик"
                onChange={(event) => setComment(event.target.value)}
              />
              <div className="ptask-detail-buttons">
                <button type="button" className="spec-btn-outline" disabled={busy} onClick={() => setRejecting(false)}>
                  Отмена
                </button>
                <button
                  type="button"
                  className="spec-btn-outline task-source-btn-danger"
                  disabled={busy}
                  onClick={() => void run('reject')}
                >
                  {busy ? 'Отправляем…' : 'Отклонить задачу'}
                </button>
              </div>
            </>
          ) : (
            <div className="ptask-detail-buttons">
              <button type="button" className="spec-btn-launch" disabled={busy} onClick={() => void run('done')}>
                {busy ? 'Отправляем…' : 'Исполнено'}
              </button>
              <button
                type="button"
                className="spec-btn-outline task-source-btn-danger"
                disabled={busy}
                onClick={() => setRejecting(true)}
              >
                Отклонить
              </button>
            </div>
          )}
        </div>
      ) : null}
      {error ? <p className="ptask-detail-error">{error}</p> : null}
    </div>
  )
}
