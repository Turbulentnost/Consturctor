import { useEffect, useState } from 'react'
import type { UserProfile } from '../api/types'
import {
  canActOnDocflowTask,
  docflowActionButtons,
  docflowKindOfContext,
  runDocflowAction,
  runTurboAction,
  turboActionButtons,
  type TurboUiAction
} from './taskSourceActions'
import type { TaskActionContext } from './taskSourceKind'
import { saveStoredTaskProgress } from './taskProgressStore'
import { DOCFLOW_KIND_LABEL, DOCFLOW_KIND_TONE, type DocflowActionSpec } from './docflowTaskKind'
import { SpecPill } from './specV04Components'

const OPEN_CARD_LABEL = 'Карточка в 1С'

export function TaskSourceActionsPanel({
  user,
  ctx,
  projectUrl,
  onCompleted
}: {
  user: UserProfile
  ctx: TaskActionContext | null
  projectUrl?: string
  onCompleted?: () => void
}): React.JSX.Element | null {
  const [busy, setBusy] = useState('')
  const [feedback, setFeedback] = useState('')
  const [feedbackIsError, setFeedbackIsError] = useState(false)
  const [pending, setPending] = useState<DocflowActionSpec | null>(null)
  const [comment, setComment] = useState('')
  const rowId = ctx?.rowId || ''

  useEffect(() => {
    setPending(null)
    setComment('')
    setFeedback('')
    setFeedbackIsError(false)
  }, [rowId])

  if (!ctx || ctx.kind === 'none' || ctx.kind === 'erp') return null

  const run = async (
    label: string,
    fn: () => Promise<{ ok: boolean; message: string }>,
    completesTask = false
  ): Promise<boolean> => {
    setBusy(label)
    setFeedback('')
    try {
      const result = await fn()
      setFeedback(result.message)
      setFeedbackIsError(!result.ok)
      if (result.ok && completesTask) onCompleted?.()
      return result.ok
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Действие не выполнено')
      setFeedbackIsError(true)
      return false
    } finally {
      setBusy('')
    }
  }

  if (ctx.kind === 'docflow') {
    const kind = docflowKindOfContext(ctx)
    const buttons = docflowActionButtons(ctx)
    const submitAction = (btn: DocflowActionSpec, note = ''): void => {
      void run(btn.label, () => runDocflowAction(user, ctx, btn.id, note), true).then((ok) => {
        if (!ok) return
        setPending(null)
        setComment('')
      })
    }
    return (
      <div className="task-source-actions">
        <h4 className="task-source-actions-title">
          Действия 1С:Документооборот
          <SpecPill tone={DOCFLOW_KIND_TONE[kind]}>{DOCFLOW_KIND_LABEL[kind]}</SpecPill>
        </h4>
        {!canActOnDocflowTask(ctx) ? (
          <p className="task-source-feedback">Задача поставлена вами — отметку ставит исполнитель.</p>
        ) : null}
        {pending ? (
          <div className="task-source-comment">
            <label htmlFor="task-source-comment-input">Комментарий для «{pending.label}»</label>
            <textarea
              id="task-source-comment-input"
              rows={3}
              value={comment}
              disabled={Boolean(busy)}
              placeholder="1С не примет этот результат без комментария"
              onChange={(event) => setComment(event.target.value)}
            />
            <div className="task-source-actions-grid">
              <button
                type="button"
                className={pending.tone === 'danger' ? 'spec-btn-danger' : 'spec-btn-launch'}
                disabled={Boolean(busy) || !comment.trim()}
                onClick={() => submitAction(pending, comment)}
              >
                {busy === pending.label ? 'Отправляем…' : pending.label}
              </button>
              <button
                type="button"
                className="spec-btn-outline"
                disabled={Boolean(busy)}
                onClick={() => {
                  setPending(null)
                  setComment('')
                }}
              >
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <div className="task-source-actions-grid">
            {buttons.map((btn) => (
              <button
                key={btn.id}
                type="button"
                disabled={Boolean(busy)}
                className={
                  btn.tone === 'primary'
                    ? 'spec-btn-launch'
                    : btn.tone === 'danger'
                      ? 'spec-btn-outline task-source-btn-danger'
                      : 'spec-btn-outline'
                }
                onClick={() => (btn.needsComment ? setPending(btn) : submitAction(btn))}
              >
                {busy === btn.label ? 'Отправляем…' : btn.label}
              </button>
            ))}
            <button
              type="button"
              disabled={Boolean(busy)}
              className="spec-btn-outline"
              onClick={() => void run(OPEN_CARD_LABEL, () => runDocflowAction(user, ctx, 'open_card'))}
            >
              {busy === OPEN_CARD_LABEL ? 'Открываем…' : OPEN_CARD_LABEL}
            </button>
          </div>
        )}
        {feedback ? (
          <p className={`task-source-feedback${feedbackIsError ? ' is-error' : ''}`}>{feedback}</p>
        ) : null}
      </div>
    )
  }

  const turboButtons = turboActionButtons()
  return (
    <div className="task-source-actions">
      <h4 className="task-source-actions-title">Действия TurboProject</h4>
      <div className="task-source-actions-grid">
        {turboButtons.map((btn) => (
          <button
            key={btn.id}
            type="button"
            disabled={Boolean(busy)}
            className={btn.tone === 'primary' ? 'spec-btn-launch' : 'spec-btn-outline'}
            onClick={() =>
              void run(btn.label, async () => {
                const result = await runTurboAction(user, ctx, btn.id as TurboUiAction, { projectUrl })
                if (result.ok && btn.id === 'mark_done') {
                  saveStoredTaskProgress(ctx.rowId, 100)
                }
                return result
              })
            }
          >
            {busy === btn.label ? '…' : btn.label}
          </button>
        ))}
      </div>
      {feedback ? <p className="task-source-feedback">{feedback}</p> : null}
    </div>
  )
}
