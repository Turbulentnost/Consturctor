import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import type { BoardAgent, CalendarEvent, WorkflowBoard } from '../../api/types'
import { MeetingsCalendar } from '../../components/agents/MeetingsCalendar'
import { RunCalendar } from '../../components/agents/RunCalendar'
import { savedFio } from '../../store/session'
import {
  shiftAnchor,
  type CalendarView,
  windowFor
} from '../../utils/calendar'
import { ensureOutlookMeetings, type MeetingEvent } from '../../utils/outlookMeetings'

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

export function TodayFullPlanModal({
  open,
  periodDay,
  fio,
  onClose,
  onOpenRun
}: {
  open: boolean
  periodDay: Date
  fio: string
  onClose: () => void
  onOpenRun?: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const [view, setView] = useState<CalendarView>('week')
  const [anchor, setAnchor] = useState(periodDay)
  const [tab, setTab] = useState<'meetings' | 'runs'>('meetings')
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])
  const [meetingsLoading, setMeetingsLoading] = useState(false)
  const [meetingsError, setMeetingsError] = useState('')
  const meetingsBusyRef = useRef(false)
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [agentFilter, setAgentFilter] = useState('')

  useEffect(() => {
    if (!open) return
    setView('week')
    setAnchor(periodDay)
    setTab('meetings')
  }, [open, periodDay])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  async function loadMeetings(nextView: CalendarView, nextAnchor: Date, force: boolean): Promise<void> {
    if (meetingsBusyRef.current) return
    meetingsBusyRef.current = true
    setMeetingsLoading(true)
    if (force) setMeetingsError('')
    try {
      const res = await ensureOutlookMeetings(nextView, nextAnchor, { force, owner: fio })
      setMeetings(res.ok ? res.meetings : [])
      setMeetingsError(res.ok ? '' : res.error || 'Не удалось прочитать календарь Outlook')
    } catch (err) {
      setMeetings([])
      setMeetingsError(err instanceof Error ? err.message : 'Ошибка календаря Outlook')
    } finally {
      meetingsBusyRef.current = false
      setMeetingsLoading(false)
    }
  }

  async function loadBoard(nextView: CalendarView, nextAnchor: Date): Promise<void> {
    const win = windowFor(nextView, nextAnchor)
    try {
      setBoard(await api.getWorkflowBoard({ window_from: win.from, window_to: win.to }))
    } catch {
      setBoard(EMPTY_BOARD)
    }
  }

  const loadMeetingsRef = useRef(loadMeetings)
  loadMeetingsRef.current = loadMeetings
  const loadBoardRef = useRef(loadBoard)
  loadBoardRef.current = loadBoard

  useEffect(() => {
    if (!open) return
    void loadMeetingsRef.current(view, anchor, false)
    void loadBoardRef.current(view, anchor)
  }, [open, view, anchor])

  const workflowAgents = useMemo(
    () => board.agents.filter((item: BoardAgent) => item.kind === 'workflow'),
    [board]
  )

  function changeView(nextView: CalendarView): void {
    setView(nextView)
  }

  function shift(step: number): void {
    setAnchor(shiftAnchor(view, anchor, step))
  }

  function goToday(): void {
    setAnchor(new Date())
  }

  function openRun(workflowId: string, runId: string): void {
    const title = workflowAgents.find((item) => item.id === workflowId)?.title || 'ИИ-агент'
    onOpenRun?.(workflowId, title, runId)
    onClose()
  }

  if (!open) return null

  return createPortal(
    <div className="modal-overlay today-day-breakdown-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card today-full-plan-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-plan-detail-head">
          <h4 className="modal-title" id={titleId}>
            Полный план
          </h4>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>

        <div className="cal-with-tabs today-full-plan-cal">
          <div className="cal-subtabs">
            <button
              type="button"
              className={tab === 'meetings' ? 'cal-subtab active' : 'cal-subtab'}
              onClick={() => setTab('meetings')}
            >
              Совещания
            </button>
            <button
              type="button"
              className={tab === 'runs' ? 'cal-subtab active' : 'cal-subtab'}
              onClick={() => setTab('runs')}
            >
              Запуски
            </button>
          </div>
          {tab === 'meetings' ? (
            <MeetingsCalendar
              view={view}
              anchor={anchor}
              meetings={meetings}
              loading={meetingsLoading}
              error={meetingsError}
              ownerName={fio || savedFio()}
              onView={changeView}
              onShift={shift}
              onToday={goToday}
              onRefresh={() => void loadMeetings(view, anchor, true)}
            />
          ) : (
            <RunCalendar
              title="Календарь запусков"
              view={view}
              anchor={anchor}
              agents={workflowAgents}
              events={board.events as CalendarEvent[]}
              agentFilter={agentFilter}
              showSchedule={false}
              onView={changeView}
              onShift={shift}
              onToday={goToday}
              onAgentFilter={setAgentFilter}
              onEventClick={openRun}
              onOpenGroup={(items) => {
                if (items.length) openRun(items[0].workflowId, items[0].runId || '')
              }}
            />
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}
