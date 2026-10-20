import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bot, X } from 'lucide-react'
import { AgentFeed } from '../../components/agentfeed/AgentFeed'
import { useRuns } from '../../store/runs'
import { PLANNER_AGENT_TITLE, resolvePlannerAgentWorkflowId } from '../../workplace/meetingPlannerAgent'
import './meetingPlanner.css'

/** Без номеров записок: агент сам читает 1С и спрашивает, какие планировать. */
const LAUNCH_MESSAGE = [
  'Найди актуальные служебные записки на организацию совещаний.',
  'Номера не заданы: покажи список и спроси, какие из них планировать.'
].join(' ')

export function MeetingPlannerPanel({
  open,
  onClose,
  onMeetingCreated
}: {
  open: boolean
  onClose: () => void
  /** Агент поставил совещание — календарь на странице стоит перечитать. */
  onMeetingCreated: () => void
}): React.JSX.Element | null {
  const titleId = useId()
  const runs = useRuns()
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const launchedWhileOpen = useRef(false)

  const entry = useMemo(
    () => Object.values(runs.entries).find((item) => !item.background && item.title === PLANNER_AGENT_TITLE),
    [runs.entries]
  )
  const state = entry?.state
  const live = Boolean(state?.running || state?.pendingHitl || state?.pendingQuestion)

  const launch = useCallback(async () => {
    setError('')
    try {
      const workflowId = await resolvePlannerAgentWorkflowId()
      if (entry && !live) runs.clear(entry.workflowId)
      runs.startRun({
        workflowId,
        title: PLANNER_AGENT_TITLE,
        message: LAUNCH_MESSAGE,
        shownMessage: 'Найти служебные записки и спросить, какие планировать'
      })
    } catch (err) {
      launchedWhileOpen.current = false
      setError(err instanceof Error ? err.message : 'Не удалось запустить агента')
    }
  }, [entry, live, runs])

  useEffect(() => {
    if (!open) {
      launchedWhileOpen.current = false
      return
    }
    if (live || launchedWhileOpen.current) return
    launchedWhileOpen.current = true
    void launch()
  }, [open, live, launch])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const seenCreated = useRef(new Set<string>())
  useEffect(() => {
    let fresh = false
    for (const item of state?.items || []) {
      if (item.kind !== 'tool' || item.tool !== 'outlook.ews_create_meeting' || !item.done || item.error) continue
      if (item.result?.created !== true || seenCreated.current.has(item.id)) continue
      seenCreated.current.add(item.id)
      fresh = true
    }
    if (fresh) onMeetingCreated()
  }, [state?.items, onMeetingCreated])

  const send = (): void => {
    const text = draft.trim()
    if (!text || !entry || live) return
    runs.startRun({ workflowId: entry.workflowId, title: PLANNER_AGENT_TITLE, message: text, shownMessage: text })
    setDraft('')
  }

  if (!open) return null

  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card memo-planner"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="memo-planner-header">
          <span className="memo-planner-icon" aria-hidden>
            <Bot size={18} />
          </span>
          <div className="memo-planner-heading">
            <h4 className="modal-title" id={titleId}>
              {PLANNER_AGENT_TITLE}
            </h4>
            <p className="memo-planner-muted">
              Агент сам читает служебные записки в 1С и спрашивает, какие из них планировать.
            </p>
          </div>
          <button type="button" className="memo-planner-close" onClick={onClose} aria-label="Закрыть">
            <X size={16} />
          </button>
        </header>

        <div className="memo-planner-feed">
          {error ? (
            <p className="meeting-protocol-error">{error}</p>
          ) : state ? (
            <AgentFeed
              items={state.items}
              status={state.status}
              running={state.running}
              pendingQuestion={state.pendingQuestion}
              pendingHitl={state.pendingHitl}
              emptyHint="Агент запускается…"
              onAnswer={(requestId, value, filePaths) => runs.answer(entry!.workflowId, requestId, value, filePaths)}
              onHitl={(requestId, approved) => runs.respondHitl(entry!.workflowId, requestId, approved)}
              onSkip={() => runs.skip(entry!.workflowId)}
            />
          ) : (
            <p className="memo-planner-empty">Запускаю агента…</p>
          )}
        </div>
        <footer className="memo-planner-footer">
          {error ? (
            <button type="button" className="btn-primary" onClick={() => void launch()}>
              Запустить снова
            </button>
          ) : live ? (
            <>
              <span className="memo-planner-muted">Окно можно закрыть — агент продолжит работу.</span>
              <button
                type="button"
                className="btn-light"
                onClick={() => entry && runs.cancel(entry.workflowId, entry.backendRunId)}
              >
                Остановить
              </button>
            </>
          ) : entry ? (
            <form
              className="memo-planner-composer"
              onSubmit={(event) => {
                event.preventDefault()
                send()
              }}
            >
              <input
                className="onec-reconnect-input"
                value={draft}
                placeholder="Написать агенту, например: перенеси второе на 15:00"
                onChange={(event) => setDraft(event.target.value)}
              />
              <button type="submit" className="btn-light" disabled={!draft.trim()}>
                Отправить
              </button>
            </form>
          ) : null}
        </footer>
      </div>
    </div>,
    document.body
  )
}
