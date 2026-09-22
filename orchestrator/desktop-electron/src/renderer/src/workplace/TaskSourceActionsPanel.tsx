import { useState } from 'react'
import type { UserProfile } from '../api/types'
import {
  docflowActionButtons,
  runDocflowAction,
  runTurboAction,
  turboActionButtons,
  type DocflowUiAction,
  type TurboUiAction
} from './taskSourceActions'
import type { TaskActionContext } from './taskSourceKind'
import { saveStoredTaskProgress } from './taskProgressStore'

export function TaskSourceActionsPanel({
  user,
  ctx,
  projectUrl,
}: {
  user: UserProfile
  ctx: TaskActionContext | null
  projectUrl?: string
}): React.JSX.Element | null {
  const [busy, setBusy] = useState('')
  const [feedback, setFeedback] = useState('')

  if (!ctx || ctx.kind === 'none' || ctx.kind === 'erp') return null

  const run = async (label: string, fn: () => Promise<{ ok: boolean; message: string }>): Promise<void> => {
    setBusy(label)
    setFeedback('')
    try {
      const result = await fn()
      setFeedback(result.message)
    } finally {
      setBusy('')
    }
  }

  if (ctx.kind === 'docflow') {
    const buttons = docflowActionButtons(ctx)
    return (
      <div className="task-source-actions">
        <h4 className="task-source-actions-title">Действия 1С:Документооборот</h4>
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
              onClick={() =>
                void run(btn.label, () => runDocflowAction(user, ctx, btn.id as DocflowUiAction))
              }
            >
              {busy === btn.label ? '…' : btn.label}
            </button>
          ))}
        </div>
        {feedback ? <p className={`task-source-feedback${feedback.includes('не') ? ' is-error' : ''}`}>{feedback}</p> : null}
      </div>
    )
  }

  const turboButtons = turboActionButtons({ taskUid: ctx.taskUid })
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
