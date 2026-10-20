import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bot, RefreshCw, X } from 'lucide-react'
import { AgentFeed } from '../../components/agentfeed/AgentFeed'
import { useRuns } from '../../store/runs'
import {
  buildPlannerMessage,
  fetchMemoRequests,
  formatDay,
  memoWhen,
  PLANNER_AGENT_TITLE,
  resolvePlannerAgentWorkflowId,
  type MemoRequest
} from '../../workplace/meetingPlannerAgent'
import './meetingPlanner.css'

const MEMO_CACHE_MS = 3 * 60 * 1000

/** Список живёт дольше окна: 1С отвечает десятки секунд, а окно открывают повторно. */
let memoCache: { at: number; memos: MemoRequest[] } | null = null

function plannedLabel(memo: MemoRequest): string {
  if (!memo.planned) return ''
  const [day, time] = memo.planned.start.split('T')
  return `Уже в «Совещаниях»: ${formatDay(day)} ${time || ''}`.trim()
}

function MemoRow({
  memo,
  checked,
  onToggle
}: {
  memo: MemoRequest
  checked: boolean
  onToggle: () => void
}): React.JSX.Element {
  const id = useId()
  const planned = Boolean(memo.planned)
  return (
    <li className={`memo-planner-row${checked ? ' is-checked' : ''}${planned ? ' is-planned' : ''}`}>
      <input id={id} type="checkbox" checked={checked} disabled={planned} onChange={onToggle} />
      <label htmlFor={id} className="memo-planner-row-body">
        <span className="memo-planner-row-head">
          <span className="memo-planner-number">№{memo.number}</span>
          <span className="memo-planner-muted">от {formatDay(memo.date)}</span>
          {memo.desiredInPast ? <span className="memo-planner-badge is-warn">Желаемая дата прошла</span> : null}
          {planned ? <span className="memo-planner-badge is-done">{plannedLabel(memo)}</span> : null}
        </span>
        <span className="memo-planner-topic">{memo.topic || memo.purpose || 'Без темы'}</span>
        <span className="memo-planner-facts">
          <span>
            <b>Когда:</b> {memoWhen(memo)}
          </span>
          <span>
            <b>Где:</b> {memo.place || 'не указано'}
          </span>
          <span>
            <b>Руководитель:</b> {memo.leader || 'не указан'}
          </span>
        </span>
        {memo.participants.length ? (
          <span className="memo-planner-people" title={memo.participants.join(', ')}>
            <b>Участники ({memo.participants.length}):</b> {memo.participants.join(', ')}
          </span>
        ) : null}
      </label>
    </li>
  )
}

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
  const [memos, setMemos] = useState<MemoRequest[] | null>(() => memoCache?.memos ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [starting, setStarting] = useState(false)
  const [picking, setPicking] = useState(false)
  const [draft, setDraft] = useState('')

  const entry = useMemo(
    () => Object.values(runs.entries).find((item) => !item.background && item.title === PLANNER_AGENT_TITLE),
    [runs.entries]
  )
  const state = entry?.state
  const live = Boolean(state?.running || state?.pendingHitl || state?.pendingQuestion)
  const showRun = Boolean(entry) && !picking

  const load = useCallback(async (force = false) => {
    if (!force && memoCache && Date.now() - memoCache.at < MEMO_CACHE_MS) {
      setMemos(memoCache.memos)
      return
    }
    setLoading(true)
    setError('')
    const res = await fetchMemoRequests()
    setLoading(false)
    if (!res.ok) {
      setError(res.error)
      return
    }
    memoCache = { at: Date.now(), memos: res.memos }
    setMemos(res.memos)
    setSelected((current) => current.filter((number) => res.memos.some((memo) => memo.number === number)))
  }, [])

  useEffect(() => {
    if (open && !showRun) void load(false)
  }, [open, showRun, load])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Каждое успешно созданное совещание — один раз: сетка на странице перечитывает календарь.
  const seenCreated = useRef(new Set<string>())
  useEffect(() => {
    let fresh = false
    for (const item of state?.items || []) {
      if (item.kind !== 'tool' || item.tool !== 'outlook.ews_create_meeting' || !item.done || item.error) continue
      if (item.result?.created !== true || seenCreated.current.has(item.id)) continue
      seenCreated.current.add(item.id)
      fresh = true
    }
    if (fresh) {
      memoCache = null
      onMeetingCreated()
    }
  }, [state?.items, onMeetingCreated])

  const selectable = useMemo(() => (memos || []).filter((memo) => !memo.planned), [memos])
  const allChecked = selectable.length > 0 && selectable.every((memo) => selected.includes(memo.number))

  const toggle = (number: string): void =>
    setSelected((current) =>
      current.includes(number) ? current.filter((item) => item !== number) : [...current, number]
    )

  const start = async (): Promise<void> => {
    const chosen = (memos || []).filter((memo) => selected.includes(memo.number))
    if (!chosen.length || starting) return
    setStarting(true)
    setError('')
    try {
      const workflowId = await resolvePlannerAgentWorkflowId()
      if (entry) runs.clear(entry.workflowId)
      runs.startRun({
        workflowId,
        title: PLANNER_AGENT_TITLE,
        message: buildPlannerMessage(chosen),
        shownMessage: `Спланировать совещания: ${chosen.map((memo) => `№${memo.number}`).join(', ')}`
      })
      setPicking(false)
      setSelected([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось запустить агента')
    } finally {
      setStarting(false)
    }
  }

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
              {showRun
                ? 'Агент проверяет занятость Амураля И.Б. и ставит совещания в календарь «Совещания». Каждое совещание — после вашего подтверждения.'
                : 'Служебные записки 1С «Организация совещаний (регл.)», которые ещё не согласованы и без назначенной даты.'}
            </p>
          </div>
          <button type="button" className="memo-planner-close" onClick={onClose} aria-label="Закрыть">
            <X size={16} />
          </button>
        </header>

        {showRun && state ? (
          <>
            <div className="memo-planner-feed">
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
            </div>
            <footer className="memo-planner-footer">
              {live ? (
                <>
                  <span className="memo-planner-muted">Окно можно закрыть — агент продолжит работу.</span>
                  <button
                    type="button"
                    className="btn-light"
                    onClick={() => runs.cancel(entry!.workflowId, entry!.backendRunId)}
                  >
                    Остановить
                  </button>
                </>
              ) : (
                <>
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
                  <button type="button" className="btn-primary" onClick={() => setPicking(true)}>
                    Выбрать другие записки
                  </button>
                </>
              )}
            </footer>
          </>
        ) : (
          <>
            <div className="memo-planner-toolbar">
              <label className="memo-planner-all">
                <input
                  type="checkbox"
                  checked={allChecked}
                  disabled={!selectable.length}
                  onChange={() => setSelected(allChecked ? [] : selectable.map((memo) => memo.number))}
                />
                Выбрать все
              </label>
              <span className="memo-planner-muted">
                {memos ? `Актуальных записок: ${memos.length}` : ''}
              </span>
              <button
                type="button"
                className="memo-planner-refresh"
                onClick={() => void load(true)}
                disabled={loading}
                title="Перечитать из 1С"
              >
                <RefreshCw size={14} className={loading ? 'is-spinning' : ''} aria-hidden /> Обновить
              </button>
            </div>
            <div className="memo-planner-list-wrap">
              {loading && !memos ? (
                <p className="memo-planner-empty">Читаю служебные записки в 1С…</p>
              ) : error ? (
                <p className="meeting-protocol-error">{error}</p>
              ) : memos && !memos.length ? (
                <p className="memo-planner-empty">Актуальных служебных записок на организацию совещаний нет.</p>
              ) : (
                <ul className="memo-planner-list">
                  {(memos || []).map((memo) => (
                    <MemoRow
                      key={memo.ref || memo.number}
                      memo={memo}
                      checked={selected.includes(memo.number)}
                      onToggle={() => toggle(memo.number)}
                    />
                  ))}
                </ul>
              )}
            </div>
            <footer className="memo-planner-footer">
              <span className="memo-planner-muted">
                {selected.length ? `Выбрано: ${selected.length}` : 'Отметьте записки, по которым нужно совещание'}
              </span>
              {entry ? (
                <button type="button" className="btn-light" onClick={() => setPicking(false)}>
                  К работе агента
                </button>
              ) : (
                <button type="button" className="btn-light" onClick={onClose}>
                  Отмена
                </button>
              )}
              <button
                type="button"
                className="btn-primary"
                onClick={() => void start()}
                disabled={!selected.length || starting || live}
                title={live ? 'Агент ещё работает с предыдущими записками' : undefined}
              >
                {starting ? 'Запуск…' : `Спланировать${selected.length ? ` (${selected.length})` : ''}`}
              </button>
            </footer>
          </>
        )}
      </div>
    </div>,
    document.body
  )
}
