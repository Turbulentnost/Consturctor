import { useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { sameDay } from '../../utils/calendar'
import { meetingMinutes } from '../../utils/meetingOverlap'
import { parseMeetingTime, type MeetingEvent } from '../../utils/outlookMeetings'
import { invokeLocalAcTool } from '../../utils/localAcTool'
import { api } from '../../api/client'

/** Поля формы совещания по образцу Outlook: тема, место, время, участники, приглашения, текст. */

const DAY_FROM = 7 * 60
const DAY_TO = 20 * 60
const SNAP = 15
const DEFAULT_DURATION = 60

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function dateValue(day: Date): string {
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

function clock(minutes: number): string {
  const clamped = ((minutes % (24 * 60)) + 24 * 60) % (24 * 60)
  return `${pad(Math.floor(clamped / 60))}:${pad(clamped % 60)}`
}

function snap(minutes: number): number {
  return Math.round(minutes / SNAP) * SNAP
}

/** Локальное время без смещения: запись в Outlook считает его настенным временем. */
function localIso(date: string, time: string): string {
  return `${date}T${time}:00`
}

function parseDay(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

function parseAttendees(raw: string): string[] {
  return raw
    .split(/[,;\n]/)
    .map((part) => part.replace(/,$/, '').trim())
    .filter(Boolean)
}

const WEEKDAY_EVERY = [
  'каждое воскресенье',
  'каждый понедельник',
  'каждый вторник',
  'каждую среду',
  'каждый четверг',
  'каждую пятницу',
  'каждую субботу'
]

function shortPersonName(fio: string): string {
  const parts = fio.replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (parts.length >= 3 && parts[1][0] && parts[2][0]) return `${parts[0]} ${parts[1][0]}.${parts[2][0]}.`
  if (parts.length === 2 && parts[1][0]) return `${parts[0]} ${parts[1][0]}.`
  return fio.trim()
}

function plannerLine(fio: string, position: string): string {
  const tail = [shortPersonName(fio), position.trim()].filter(Boolean).join(' ')
  return tail ? `запланировал(а) ${tail}` : 'запланировал(а)'
}

function participantLine(raw: string): string {
  const email = /<([^<>@\s]+@[^<>\s]+)>/.exec(raw)
  const name = raw.replace(/<[^>]*>/g, '').trim()
  return email ? `${name} <${email[1]}>` : name
}

function participantsBody(people: string[], fio: string, position: string): string {
  if (!people.length) return ''
  const lines = people.map((person, index) => {
    const line = participantLine(person)
    return index < people.length - 1 ? `${line};` : line
  })
  return ['Участники', '', ...lines, '', plannerLine(fio, position)].join('\n')
}

function isWeekend(day: Date): boolean {
  const weekday = day.getDay()
  return weekday === 0 || weekday === 6
}

function nearestWorkdayLabel(day: Date): string {
  const moved = new Date(day)
  if (moved.getDay() === 6) moved.setDate(moved.getDate() - 1)
  else if (moved.getDay() === 0) moved.setDate(moved.getDate() + 1)
  return moved.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

function slotFromRange(start: Date, end: Date): { start: number; end: number } {
  let from = snap(start.getHours() * 60 + start.getMinutes())
  let to = snap(end.getHours() * 60 + end.getMinutes())
  if (to <= from) to = from + DEFAULT_DURATION
  from = Math.max(DAY_FROM, Math.min(from, DAY_TO - SNAP))
  to = Math.max(from + SNAP, Math.min(to, DAY_TO))
  return { start: from, end: to }
}

function attendeeFragment(raw: string, caret: number): { start: number; end: number; query: string } {
  const pos = Math.max(0, Math.min(caret, raw.length))
  const before = raw.slice(0, pos)
  const from = Math.max(before.lastIndexOf(';'), before.lastIndexOf('\n'), before.lastIndexOf(',')) + 1
  const after = raw.slice(pos)
  const rel = after.search(/[;\n,]/)
  const to = rel < 0 ? raw.length : pos + rel
  return { start: from, end: to, query: raw.slice(from, to).trim() }
}

function defaultStartFor(now: Date): Date {
  const next = new Date(now)
  next.setMinutes(0, 0, 0)
  next.setHours(next.getHours() + 1)
  return next
}

type DayBlock = { meeting: MeetingEvent; from: number; to: number }

type SlotSuggestion = { label: string; start: number; end: number }

function dayBlocks(meetings: MeetingEvent[], day: Date): DayBlock[] {
  const blocks: DayBlock[] = []
  for (const meeting of meetings) {
    const start = parseMeetingTime(meeting.start)
    if (!start || !sameDay(start, day)) continue
    const minutes = meetingMinutes(meeting)
    if (!minutes) continue
    const from = Math.max(DAY_FROM, minutes.from)
    const to = Math.min(DAY_TO, minutes.to)
    if (to <= from) continue
    blocks.push({ meeting, from, to })
  }
  return blocks.sort((left, right) => left.from - right.from || left.to - right.to)
}

function overlaps(start: number, end: number, block: DayBlock): boolean {
  return start < block.to && block.from < end
}

function mergedBusy(blocks: DayBlock[]): Array<[number, number]> {
  const merged: Array<[number, number]> = []
  for (const block of [...blocks].sort((left, right) => left.from - right.from)) {
    const last = merged[merged.length - 1]
    if (last && block.from <= last[1]) last[1] = Math.max(last[1], block.to)
    else merged.push([block.from, block.to])
  }
  return merged
}

function slotSuggestions(blocks: DayBlock[], start: number, end: number): SlotSuggestion[] {
  const hits = blocks.filter((block) => overlaps(start, end, block))
  if (!hits.length) return []
  const duration = Math.max(SNAP, end - start)
  const busy = mergedBusy(blocks)
  const gaps: Array<[number, number]> = []
  let cursor = DAY_FROM
  for (const [from, to] of busy) {
    if (from > cursor) gaps.push([cursor, from])
    cursor = Math.max(cursor, to)
  }
  if (cursor < DAY_TO) gaps.push([cursor, DAY_TO])
  const fitting = gaps
    .map(([from, to]) => [snap(from), to] as [number, number])
    .filter(([from, to]) => to - from >= duration)

  const ideas: SlotSuggestion[] = []
  const push = (label: string, nextStart: number): void => {
    const nextEnd = nextStart + duration
    if (nextStart < DAY_FROM || nextEnd > DAY_TO) return
    if (blocks.some((block) => overlaps(nextStart, nextEnd, block))) return
    if (ideas.some((item) => item.start === nextStart && item.end === nextEnd)) return
    ideas.push({ label, start: nextStart, end: nextEnd })
  }

  const earliest = hits.reduce((best, block) => (block.from < best.from ? block : best))
  const latest = hits.reduce((best, block) => (block.to > best.to ? block : best))
  push(`До «${earliest.meeting.subject}», ${clock(earliest.from - duration)}–${clock(earliest.from)}`, earliest.from - duration)
  push(`После «${latest.meeting.subject}», ${clock(latest.to)}–${clock(latest.to + duration)}`, latest.to)

  const nearest = [...fitting].sort(
    (left, right) => Math.abs(left[0] - start) - Math.abs(right[0] - start)
  )
  for (const [from] of nearest) {
    if (from === start) continue
    push(`Свободно ${clock(from)}–${clock(from + duration)}`, from)
    if (ideas.length >= 3) break
  }
  return ideas.slice(0, 3)
}

function initialSlot(day: Date): { start: number; end: number } {
  const now = new Date()
  let start = 10 * 60
  if (sameDay(now, day)) {
    start = snap(now.getHours() * 60 + now.getMinutes() + SNAP)
    if (start < DAY_FROM) start = DAY_FROM
    if (start > DAY_TO - DEFAULT_DURATION) start = DAY_TO - DEFAULT_DURATION
  }
  return { start, end: start + DEFAULT_DURATION }
}

function topPct(minutes: number): string {
  return `${((minutes - DAY_FROM) / (DAY_TO - DAY_FROM)) * 100}%`
}

function heightPct(from: number, to: number): string {
  return `${((to - from) / (DAY_TO - DAY_FROM)) * 100}%`
}

export function MeetingEditorDialog({
  mode,
  meeting,
  day,
  meetings = [],
  defaultStart,
  plannerFio = '',
  plannerPosition = '',
  onClose,
  onSaved
}: {
  mode: 'create' | 'edit'
  meeting?: MeetingEvent | null
  /** День, открытый в календаре: с него начинается выбор слота. */
  day?: Date | null
  meetings?: MeetingEvent[]
  defaultStart?: Date | null
  /** Кто создаёт совещание: попадёт в текст как «запланировал(а) Фамилия И.О. Должность». */
  plannerFio?: string
  plannerPosition?: string
  onClose: () => void
  onSaved: () => void
}): React.JSX.Element {
  const openedOn = day ?? defaultStart ?? new Date()
  const initialStart =
    (meeting ? parseMeetingTime(meeting.start) : null) ?? defaultStart ?? defaultStartFor(new Date())
  const initialEnd =
    (meeting ? parseMeetingTime(meeting.end) : null) ?? new Date(initialStart.getTime() + DEFAULT_DURATION * 60_000)
  const seeded = mode === 'edit' ? slotFromRange(initialStart, initialEnd) : initialSlot(openedOn)

  const [subject, setSubject] = useState(meeting?.subject && meeting.subject !== 'Совещание' ? meeting.subject : '')
  const [location, setLocation] = useState(meeting?.location || '')
  const [startDate, setStartDate] = useState(dateValue(mode === 'create' ? openedOn : initialStart))
  const [slotStart, setSlotStart] = useState(seeded.start)
  const [slotEnd, setSlotEnd] = useState(seeded.end)
  const [attendees, setAttendees] = useState(meeting?.attendees || '')
  const [attendeeCaret, setAttendeeCaret] = useState((meeting?.attendees || '').length)
  const [suggestOpen, setSuggestOpen] = useState(false)
  const [suggestActive, setSuggestActive] = useState(-1)
  const [employees, setEmployees] = useState<string[]>([])
  const [sendInvites, setSendInvites] = useState(true)
  const [repeatOn, setRepeatOn] = useState(false)
  const [repeatKind, setRepeatKind] = useState<'weekly' | 'monthly'>('weekly')
  const [monthDay, setMonthDay] = useState(openedOn.getDate())
  const [monthDayTouched, setMonthDayTouched] = useState(false)
  const [workWeek, setWorkWeek] = useState(false)
  const [body, setBody] = useState('')
  const [bodyTouched, setBodyTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const boardRef = useRef<HTMLDivElement>(null)
  const attendeeRef = useRef<HTMLTextAreaElement>(null)
  const dragRef = useRef<{ mode: 'move' | 'resize'; origin: number; start: number; end: number } | null>(null)

  const selectedDay = parseDay(startDate) ?? openedOn
  const blocks = useMemo(() => {
    const rest = meeting?.id ? meetings.filter((item) => item.id !== meeting.id) : meetings
    return dayBlocks(rest, selectedDay)
  }, [meeting?.id, meetings, selectedDay])
  const conflicts = useMemo(
    () => blocks.filter((block) => overlaps(slotStart, slotEnd, block)),
    [blocks, slotEnd, slotStart]
  )
  const suggestions = useMemo(
    () => slotSuggestions(blocks, slotStart, slotEnd),
    [blocks, slotEnd, slotStart]
  )
  const people = useMemo(() => parseAttendees(attendees), [attendees])
  const fragment = attendeeFragment(attendees, attendeeCaret)
  const employeeMatches = useMemo(() => {
    const words = fragment.query.toLowerCase().replace(/ё/g, 'е').split(/\s+/).filter(Boolean)
    if (!words.length) return []
    const taken = new Set(
      people
        .map((item) => item.replace(/<[^>]*>/g, '').trim().toLowerCase().replace(/ё/g, 'е'))
        .filter((item) => item && item !== words.join(' '))
    )
    return employees
      .filter((fio) => {
        const key = fio.toLowerCase().replace(/ё/g, 'е')
        if (taken.has(key)) return false
        return words.every((word) => key.includes(word))
      })
      .slice(0, 8)
  }, [employees, fragment.query, people])

  useEffect(() => {
    setSuggestActive(employeeMatches.length ? 0 : -1)
  }, [employeeMatches])

  useEffect(() => {
    if (monthDayTouched) return
    const next = parseDay(startDate)
    if (next) setMonthDay(next.getDate())
  }, [monthDayTouched, startDate])

  useEffect(() => {
    if (bodyTouched) return
    setBody(participantsBody(people, plannerFio, plannerPosition))
  }, [bodyTouched, people, plannerFio, plannerPosition])

  useEffect(() => {
    let alive = true
    void api.searchUsers('', 20000).then((items) => {
      if (alive) setEmployees(items)
    })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  function minuteAt(event: ReactPointerEvent): number {
    const rect = boardRef.current?.getBoundingClientRect()
    if (!rect || rect.height <= 0) return slotStart
    const ratio = (event.clientY - rect.top) / rect.height
    return snap(DAY_FROM + ratio * (DAY_TO - DAY_FROM))
  }

  function onBoardPointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    if (busy) return
    const target = event.target as HTMLElement
    const minute = minuteAt(event)
    const duration = Math.max(SNAP, slotEnd - slotStart)
    if (target.dataset.role === 'resize') {
      dragRef.current = { mode: 'resize', origin: minute, start: slotStart, end: slotEnd }
    } else if (target.closest('[data-role="selection"]')) {
      dragRef.current = { mode: 'move', origin: minute, start: slotStart, end: slotEnd }
    } else {
      const start = Math.max(DAY_FROM, Math.min(minute, DAY_TO - duration))
      setSlotStart(start)
      setSlotEnd(start + duration)
      dragRef.current = { mode: 'move', origin: minute, start, end: start + duration }
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onBoardPointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    const drag = dragRef.current
    if (!drag) return
    const minute = minuteAt(event)
    const delta = minute - drag.origin
    if (drag.mode === 'move') {
      const duration = drag.end - drag.start
      const start = Math.max(DAY_FROM, Math.min(drag.start + delta, DAY_TO - duration))
      setSlotStart(start)
      setSlotEnd(start + duration)
      return
    }
    setSlotEnd(Math.max(drag.start + SNAP, Math.min(DAY_TO, minute)))
  }

  function onBoardPointerUp(): void {
    dragRef.current = null
  }

  function pickEmployee(fio: string): void {
    const frag = attendeeFragment(attendees, attendeeCaret)
    const next = `${attendees.slice(0, frag.start)}${fio}; ${attendees.slice(frag.end).replace(/^\s+/, '')}`
    const pos = frag.start + fio.length + 2
    setAttendees(next)
    setAttendeeCaret(pos)
    setSuggestOpen(false)
    setSuggestActive(-1)
    requestAnimationFrame(() => {
      attendeeRef.current?.focus()
      attendeeRef.current?.setSelectionRange(pos, pos)
    })
  }

  function onAttendeeKey(event: React.KeyboardEvent<HTMLTextAreaElement>): void {
    if (!suggestOpen || !employeeMatches.length) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setSuggestActive((index) => Math.min(employeeMatches.length - 1, index + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setSuggestActive((index) => Math.max(0, index - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      pickEmployee(employeeMatches[suggestActive >= 0 ? suggestActive : 0])
    } else if (event.key === 'Escape') {
      event.stopPropagation()
      setSuggestOpen(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const title = subject.trim()
    if (!title) {
      setError('Укажите тему совещания')
      return
    }
    const start = localIso(startDate, clock(slotStart))
    const end = localIso(startDate, clock(slotEnd))
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
      send_invites: sendInvites,
      planner_fio: plannerFio,
      planner_position: plannerPosition
    }
    const schedule = {
      body: body.trim(),
      work_week: workWeek,
      ...(repeatOn
        ? {
            recurrence: {
              kind: repeatKind,
              day_of_month: Math.min(31, Math.max(1, monthDay || 1))
            }
          }
        : {})
    }
    const result =
      mode === 'create'
        ? await invokeLocalAcTool('outlook.create_event', {
            ...common,
            ...schedule,
            stamp_ai_agent: false
          })
        : await invokeLocalAcTool('outlook.update_event', {
            ...common,
            ...schedule,
            entry_id: meeting?.id
          })
    setBusy(false)
    if (!result.ok) {
      setError(result.error || 'Outlook не сохранил совещание')
      return
    }
    onSaved()
    onClose()
  }

  const hours = Array.from({ length: (DAY_TO - DAY_FROM) / 60 + 1 }, (_, index) => DAY_FROM / 60 + index)

  return createPortal(
    <div className="modal-overlay meeting-editor-overlay" role="presentation" onClick={busy ? undefined : onClose}>
      <form
        className="modal-card is-resizable meeting-editor is-create"
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

        <div className="meeting-editor-body">
        <div className="meeting-editor-fields">
        <label className="meeting-editor-row">
          <span>Тема</span>
          <input value={subject} onChange={(event) => setSubject(event.target.value)} autoFocus />
        </label>
        <label className="meeting-editor-row">
          <span>Место</span>
          <input value={location} onChange={(event) => setLocation(event.target.value)} />
        </label>

        <div className="meeting-editor-row meeting-attendees">
          <span>Участники</span>
          <div className="meeting-attendees-field">
            <textarea
              ref={attendeeRef}
              rows={2}
              value={attendees}
              placeholder="Начните вводить фамилию"
              onChange={(event) => {
                setAttendees(event.target.value)
                setAttendeeCaret(event.target.selectionStart)
                setSuggestOpen(true)
                setSuggestActive(-1)
              }}
              onSelect={(event) => setAttendeeCaret(event.currentTarget.selectionStart)}
              onFocus={(event) => {
                setAttendeeCaret(event.currentTarget.selectionStart)
                setSuggestOpen(true)
              }}
              onBlur={() => setSuggestOpen(false)}
              onKeyDown={onAttendeeKey}
            />
            {suggestOpen && employeeMatches.length ? (
              <ul className="meeting-attendees-list">
                {employeeMatches.map((fio, index) => (
                  <li key={fio}>
                    <button
                      type="button"
                      className={index === suggestActive ? 'is-active' : ''}
                      onMouseDown={(event) => {
                        event.preventDefault()
                        pickEmployee(fio)
                      }}
                    >
                      {fio}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
        <label className="meeting-editor-check">
          <input type="checkbox" checked={sendInvites} onChange={(event) => setSendInvites(event.target.checked)} />
          <span>Отправить приглашения участникам</span>
        </label>
        <div className="meeting-editor-toggles">
            <button
              type="button"
              className={`meeting-editor-toggle${repeatOn ? ' is-on' : ''}`}
              onClick={() => setRepeatOn((value) => !value)}
            >
              Повторяющееся совещание
            </button>
            <button
              type="button"
              className={`meeting-editor-toggle${workWeek ? ' is-on' : ''}`}
              title="С учётом рабочей недели: встреча с выходного переносится на ближайший рабочий день. Повтор серии остаётся на выбранном дне."
              onClick={() => setWorkWeek((value) => !value)}
            >
            Рабочая неделя
          </button>
        </div>
        {repeatOn ? (
          <div className="meeting-repeat-panel">
            <button
              type="button"
              className={`meeting-editor-toggle${repeatKind === 'weekly' ? ' is-on' : ''}`}
              onClick={() => setRepeatKind('weekly')}
            >
              Раз в неделю
            </button>
            <button
              type="button"
              className={`meeting-editor-toggle${repeatKind === 'monthly' ? ' is-on' : ''}`}
              onClick={() => setRepeatKind('monthly')}
            >
              Число месяца
            </button>
            {repeatKind === 'weekly' ? (
              <span>{WEEKDAY_EVERY[selectedDay.getDay()]}</span>
            ) : (
              <label className="meeting-repeat-day">
                <span>Число</span>
                <input
                  type="number"
                  min={1}
                  max={31}
                  value={monthDay}
                  onChange={(event) => {
                    setMonthDayTouched(true)
                    const next = Number(event.target.value)
                    setMonthDay(Number.isFinite(next) ? next : 1)
                  }}
                />
              </label>
            )}
          </div>
        ) : null}
        {workWeek && isWeekend(selectedDay) ? (
          <p className="meeting-slot-note">
            {repeatOn
              ? `Выходной переносится на ${nearestWorkdayLabel(selectedDay)}. Серия и дальше повторяется в выбранный день: сдвигается только тот повтор, который снова выпал на выходной.`
              : `Выходной: совещание будет создано на ${nearestWorkdayLabel(selectedDay)}.`}
          </p>
        ) : null}
        <label className="meeting-editor-row meeting-editor-text">
          <span>Текст</span>
          <textarea
            rows={Math.min(12, Math.max(3, people.length + 4))}
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
        </div>

        <div className="meeting-slot">
            <div className="meeting-slot-head">
              <label>
                <span>День</span>
                <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
              </label>
              <strong>
                {clock(slotStart)}–{clock(slotEnd)}
                <em>{` · ${slotEnd - slotStart} мин`}</em>
              </strong>
            </div>
            <div
              ref={boardRef}
              className="meeting-slot-board"
              onPointerDown={onBoardPointerDown}
              onPointerMove={onBoardPointerMove}
              onPointerUp={onBoardPointerUp}
              onPointerCancel={onBoardPointerUp}
            >
              {hours.map((hour) => (
                <span key={hour} className="meeting-slot-hour" style={{ top: topPct(hour * 60) }}>
                  {clock(hour * 60)}
                </span>
              ))}
              {blocks.map((block) => (
                <div
                  key={`${block.meeting.id}-${block.from}`}
                  className="meeting-slot-busy"
                  style={{ top: topPct(block.from), height: heightPct(block.from, block.to) }}
                  title={`${block.meeting.subject} ${clock(block.from)}–${clock(block.to)}`}
                >
                  <b>{block.meeting.subject}</b>
                  <i>
                    {clock(block.from)}–{clock(block.to)}
                  </i>
                </div>
              ))}
              <div
                data-role="selection"
                className={`meeting-slot-pick${conflicts.length ? ' is-conflict' : ''}`}
                style={{ top: topPct(slotStart), height: heightPct(slotStart, slotEnd) }}
              >
                <span>
                  {clock(slotStart)}–{clock(slotEnd)}
                </span>
                <button type="button" data-role="resize" aria-label="Изменить длительность" />
              </div>
            </div>
            <p className="meeting-slot-note">
              Нажмите на свободное или занятое время. Нижний край выбранного слота меняет длительность.
            </p>
            {conflicts.length ? (
              <div className="meeting-slot-conflict">
                <p>
                  Пересекается с{' '}
                  {conflicts
                    .map((block) => `«${block.meeting.subject}» ${clock(block.from)}–${clock(block.to)}`)
                    .join(', ')}
                  . Сохранить можно и так: в Outlook попадёт выбранное время.
                </p>
                {suggestions.length ? (
                  <div className="meeting-slot-options">
                    {suggestions.map((item) => (
                      <button
                        key={`${item.start}-${item.end}`}
                        type="button"
                        onClick={() => {
                          setSlotStart(item.start)
                          setSlotEnd(item.end)
                        }}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </form>
    </div>,
    document.body
  )
}
