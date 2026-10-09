import { useEffect, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { parseMeetingTime, type MeetingEvent } from '../../utils/outlookMeetings'
import { invokeLocalAcTool } from '../../utils/localAcTool'

/** Поля формы совещания по образцу Outlook: тема, место, время, участники, приглашения, текст. */

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function dateValue(day: Date): string {
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

function timeValue(day: Date): string {
  return `${pad(day.getHours())}:${pad(day.getMinutes())}`
}

/** Локальное время без смещения: бэкенд считает его настенным временем Outlook. */
function localIso(date: string, time: string): string {
  return `${date}T${time}:00`
}

function parseAttendees(raw: string): string[] {
  return raw
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function defaultStartFor(now: Date): Date {
  const next = new Date(now)
  next.setMinutes(0, 0, 0)
  next.setHours(next.getHours() + 1)
  return next
}

export function MeetingEditorDialog({
  mode,
  meeting,
  defaultStart,
  onClose,
  onSaved
}: {
  mode: 'create' | 'edit'
  meeting?: MeetingEvent | null
  defaultStart?: Date | null
  onClose: () => void
  onSaved: () => void
}): React.JSX.Element {
  const initialStart =
    (meeting ? parseMeetingTime(meeting.start) : null) ?? defaultStart ?? defaultStartFor(new Date())
  const initialEnd =
    (meeting ? parseMeetingTime(meeting.end) : null) ?? new Date(initialStart.getTime() + 60 * 60_000)

  const [subject, setSubject] = useState(meeting?.subject && meeting.subject !== 'Совещание' ? meeting.subject : '')
  const [location, setLocation] = useState(meeting?.location || '')
  const [startDate, setStartDate] = useState(dateValue(initialStart))
  const [startTime, setStartTime] = useState(timeValue(initialStart))
  const [endDate, setEndDate] = useState(dateValue(initialEnd))
  const [endTime, setEndTime] = useState(timeValue(initialEnd))
  const [attendees, setAttendees] = useState(meeting?.attendees || '')
  const [sendInvites, setSendInvites] = useState(true)
  const [body, setBody] = useState('')
  const [bodyTouched, setBodyTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const title = subject.trim()
    if (!title) {
      setError('Укажите тему совещания')
      return
    }
    const start = localIso(startDate, startTime)
    const end = localIso(endDate, endTime)
    if (!(new Date(end).getTime() > new Date(start).getTime())) {
      setError('Окончание должно быть позже начала')
      return
    }
    if (mode === 'edit' && (!meeting?.id || meeting.id.startsWith('meeting-'))) {
      setError('У встречи нет идентификатора Outlook — откройте её из календаря заново')
      return
    }
    const people = parseAttendees(attendees)
    setBusy(true)
    setError('')
    const common = {
      subject: title,
      start,
      end,
      location: location.trim(),
      attendees: people,
      send_invites: sendInvites && people.length > 0
    }
    const result =
      mode === 'create'
        ? await invokeLocalAcTool('outlook.create_event', {
            ...common,
            body: body.trim(),
            // Встречи из формы Orchestrator — обычные совещания, без пометки ИИ-агента.
            stamp_ai_agent: false
          })
        : await invokeLocalAcTool('outlook.update_event', {
            ...common,
            entry_id: meeting?.id,
            ...(bodyTouched ? { body: body.trim() } : {})
          })
    setBusy(false)
    if (!result.ok) {
      setError(result.error || 'Outlook не сохранил совещание')
      return
    }
    onSaved()
    onClose()
  }

  return createPortal(
    <div className="modal-overlay meeting-editor-overlay" role="presentation" onClick={busy ? undefined : onClose}>
      <form
        className="modal-card is-resizable meeting-editor"
        role="dialog"
        aria-modal="true"
        aria-label={mode === 'create' ? 'Новое совещание' : 'Изменить совещание'}
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => void submit(event)}
      >
        <header className="meeting-editor-head">
          <h3>{mode === 'create' ? 'Новое совещание' : 'Изменить совещание'}</h3>
          <span className="meeting-editor-hint">Сохраняется в Outlook</span>
        </header>

        <label className="meeting-editor-row">
          <span>Тема</span>
          <input value={subject} onChange={(event) => setSubject(event.target.value)} autoFocus />
        </label>
        <label className="meeting-editor-row">
          <span>Место</span>
          <input value={location} onChange={(event) => setLocation(event.target.value)} />
        </label>

        <div className="meeting-editor-times">
          <div className="meeting-editor-row">
            <span>Начало</span>
            <div className="meeting-editor-pair">
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
              <input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
            </div>
          </div>
          <div className="meeting-editor-row">
            <span>Окончание</span>
            <div className="meeting-editor-pair">
              <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
              <input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
            </div>
          </div>
        </div>

        <label className="meeting-editor-row">
          <span>Участники (через «;»)</span>
          <textarea rows={2} value={attendees} onChange={(event) => setAttendees(event.target.value)} />
        </label>
        <label className="meeting-editor-check">
          <input type="checkbox" checked={sendInvites} onChange={(event) => setSendInvites(event.target.checked)} />
          <span>Отправить приглашения участникам</span>
        </label>
        <label className="meeting-editor-row">
          <span>Текст {mode === 'edit' ? '(оставьте пустым, чтобы не менять)' : ''}</span>
          <textarea
            rows={4}
            value={body}
            onChange={(event) => {
              setBody(event.target.value)
              setBodyTouched(true)
            }}
          />
        </label>

        {error ? <p className="meeting-editor-error">{error}</p> : null}

        <footer className="meeting-editor-actions">
          <button type="button" className="btn-light" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Сохраняем…' : mode === 'create' ? 'Создать в Outlook' : 'Сохранить в Outlook'}
          </button>
        </footer>
      </form>
    </div>,
    document.body
  )
}
