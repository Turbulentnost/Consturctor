import { useEffect, useMemo, useRef, useState } from 'react'
import type { BoardAgent, CalendarEvent } from '../../api/types'
import {
  addDays,
  clip,
  DAYS_SHORT,
  formatPeriod,
  groupBySlot,
  groupHeading,
  groupSummary,
  isoWeekday,
  localInputToIso,
  mondayOf,
  nowForInput,
  parseIso,
  sameDay,
  SOURCE_LABEL,
  STATUS_STYLE,
  groupRunStyle,
  timeText,
  type CalendarView
} from '../../utils/calendar'

const HEADER = 54
const HOUR_H = 56
const GUTTER = 52
const COL_MIN = 168

interface RunCalendarProps {
  view: CalendarView
  anchor: Date
  agents: BoardAgent[]
  events: CalendarEvent[]
  agentFilter: string
  onView: (view: CalendarView) => void
  onShift: (step: number) => void
  onToday: () => void
  onAgentFilter: (workflowId: string) => void
  onEventClick: (workflowId: string, runId: string) => void
  onOpenGroup: (events: CalendarEvent[]) => void
  onScheduleRun: (workflowId: string, iso: string) => void
  onSkipSlot?: (event: CalendarEvent) => void
}

interface PopupState {
  events: CalendarEvent[]
  x: number
  y: number
}

interface SlotMenuState {
  event: CalendarEvent
  x: number
  y: number
}

function canSkipEvent(event: CalendarEvent): boolean {
  if (!event.triggerId) return false
  return event.status === 'scheduled' || event.status === 'missed'
}

export function RunCalendar(props: RunCalendarProps): React.JSX.Element {
  const { view, anchor, agents, events, agentFilter } = props
  const [showFilters, setShowFilters] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [popup, setPopup] = useState<PopupState | null>(null)
  const [slotMenu, setSlotMenu] = useState<SlotMenuState | null>(null)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const slotMenuRef = useRef<HTMLDivElement>(null)

  const visibleEvents = useMemo(() => {
    let items = [...events]
    if (agentFilter) items = items.filter((item) => item.workflowId === agentFilter)
    if (statusFilter) items = items.filter((item) => item.status === statusFilter)
    if (sourceFilter) items = items.filter((item) => item.source === sourceFilter)
    return items
  }, [events, agentFilter, statusFilter, sourceFilter])

  const days = useMemo(() => {
    if (view === 'day') return [new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())]
    if (view === 'month') return []
    const start = mondayOf(anchor)
    return Array.from({ length: 7 }, (_, i) => addDays(start, i))
  }, [view, anchor])

  useEffect(() => {
    setPopup(null)
    setSlotMenu(null)
  }, [view, anchor, agentFilter, statusFilter, sourceFilter])

  useEffect(() => {
    if (!slotMenu) return
    function onDocClick(evt: MouseEvent): void {
      if (slotMenuRef.current && !slotMenuRef.current.contains(evt.target as Node)) setSlotMenu(null)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [slotMenu])

  function openSlotMenu(event: CalendarEvent, evt: React.MouseEvent): void {
    if (!props.onSkipSlot || !canSkipEvent(event)) return
    setPopup(null)
    setSlotMenu({ event, x: evt.clientX, y: evt.clientY })
  }

  const tags: { text: string; kind: 'agent' | 'status' | 'source' }[] = []
  if (agentFilter) {
    const title = agents.find((a) => a.id === agentFilter)?.title || 'агент'
    tags.push({ text: `Агент: ${title}`, kind: 'agent' })
  }
  if (statusFilter) {
    tags.push({ text: `Статус: ${STATUS_STYLE[statusFilter]?.label ?? statusFilter}`, kind: 'status' })
  }
  if (sourceFilter) {
    tags.push({ text: `Тип: ${SOURCE_LABEL[sourceFilter] ?? sourceFilter}`, kind: 'source' })
  }

  function clearAll(): void {
    props.onAgentFilter('')
    setStatusFilter('')
    setSourceFilter('')
  }

  function clearOne(kind: 'agent' | 'status' | 'source'): void {
    if (kind === 'agent') props.onAgentFilter('')
    else if (kind === 'status') setStatusFilter('')
    else setSourceFilter('')
  }

  function openGroupPopup(group: CalendarEvent[], evt: React.MouseEvent): void {
    if (group.length < 2) {
      if (group.length === 1) props.onEventClick(group[0].workflowId, group[0].runId || '')
      return
    }
    setPopup({ events: group, x: evt.clientX - 24, y: evt.clientY + 8 })
  }

  return (
    <div className="run-calendar">
      <div className="cal-head">
        <div className="cal-heading">
          <div className="cal-title">Календарь запусков</div>
          <div className="cal-period">{formatPeriod(view, anchor)}</div>
        </div>
        <div className="cal-controls">
          <button className="cal-btn cal-btn-arrow" onClick={() => props.onShift(-1)}>
            &lt;
          </button>
          <button className="cal-btn" onClick={props.onToday}>
            Сегодня
          </button>
          <button className="cal-btn cal-btn-arrow" onClick={() => props.onShift(1)}>
            &gt;
          </button>
          <button
            className={view === 'day' ? 'cal-btn active' : 'cal-btn'}
            onClick={() => props.onView('day')}
          >
            День
          </button>
          <button
            className={view === 'week' ? 'cal-btn active' : 'cal-btn'}
            onClick={() => props.onView('week')}
          >
            Неделя
          </button>
          <button
            className={view === 'month' ? 'cal-btn active' : 'cal-btn'}
            onClick={() => props.onView('month')}
          >
            Месяц
          </button>
          <button className="cal-btn" onClick={() => setShowFilters((v) => !v)}>
            Фильтры
          </button>
          <button className="cal-btn primary" onClick={() => setScheduleOpen(true)}>
            Запланировать запуск
          </button>
        </div>
      </div>

      <div className="cal-legend">
        {(['ok', 'scheduled', 'missed', 'error', 'canceled', 'paused'] as const).map((key) => (
          <span key={key} className="cal-legend-item" style={{ color: STATUS_STYLE[key].border }}>
            &#9679;&nbsp;&nbsp;{STATUS_STYLE[key].label}
          </span>
        ))}
      </div>

      {tags.length > 0 && (
        <div className="cal-tags">
          {tags.map((tag) => (
            <button key={tag.kind} className="cal-tag" onClick={() => clearOne(tag.kind)}>
              {tag.text}&nbsp;&nbsp;&times;
            </button>
          ))}
          <button className="cal-btn" onClick={clearAll}>
            Сбросить
          </button>
        </div>
      )}

      {showFilters && (
        <div className="cal-filters">
          <label>Агент</label>
          <select value={agentFilter} onChange={(e) => props.onAgentFilter(e.target.value)}>
            <option value="">Все агенты</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.title || 'ИИ-агент'}
              </option>
            ))}
          </select>
          <label>Статус</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">Все статусы</option>
            {Object.entries(STATUS_STYLE)
              .filter(([key]) => key !== 'cancelled')
              .map(([key, meta]) => (
              <option key={key} value={key}>
                {meta.label}
              </option>
            ))}
          </select>
          <label>Тип</label>
          <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="">Все типы</option>
            <option value="schedule">По расписанию</option>
            <option value="manual">Вручную</option>
            <option value="event">По событию</option>
          </select>
          <button className="cal-btn" onClick={clearAll}>
            Сбросить
          </button>
        </div>
      )}

      {view === 'month' ? (
        <MonthGrid
          anchor={anchor}
          events={visibleEvents}
          onEventClick={props.onEventClick}
          onGroupClick={openGroupPopup}
          onEventContext={openSlotMenu}
        />
      ) : (
        <div className="cal-scroll" ref={scrollRef}>
          <WeekGrid
            days={days}
            events={visibleEvents}
            onEventClick={props.onEventClick}
            onGroupClick={openGroupPopup}
            onEventContext={openSlotMenu}
          />
        </div>
      )}

      {popup && (
        <GroupPopup
          state={popup}
          onClose={() => setPopup(null)}
          onEventClick={(wf, run) => {
            setPopup(null)
            props.onEventClick(wf, run)
          }}
          onOpenAll={(items) => {
            setPopup(null)
            props.onOpenGroup(items)
          }}
          onSkipSlot={
            props.onSkipSlot
              ? (event) => {
                  setPopup(null)
                  props.onSkipSlot?.(event)
                }
              : undefined
          }
        />
      )}

      {slotMenu && props.onSkipSlot && (
        <div
          ref={slotMenuRef}
          className="cal-slot-menu"
          style={{
            left: Math.min(slotMenu.x, window.innerWidth - 220),
            top: Math.min(slotMenu.y, window.innerHeight - 80)
          }}
        >
          <button
            type="button"
            onClick={() => {
              props.onSkipSlot?.(slotMenu.event)
              setSlotMenu(null)
            }}
          >
            Отменить этот запуск
          </button>
        </div>
      )}

      {scheduleOpen && (
        <ScheduleDialog
          agents={agents}
          defaultAgent={agentFilter}
          onCancel={() => setScheduleOpen(false)}
          onConfirm={(workflowId, iso) => {
            setScheduleOpen(false)
            props.onScheduleRun(workflowId, iso)
          }}
        />
      )}
    </div>
  )
}

interface GridProps {
  days: Date[]
  events: CalendarEvent[]
  onEventClick: (workflowId: string, runId: string) => void
  onGroupClick: (group: CalendarEvent[], evt: React.MouseEvent) => void
  onEventContext?: (event: CalendarEvent, evt: React.MouseEvent) => void
}

function WeekGrid({ days, events, onEventClick, onGroupClick, onEventContext }: GridProps): React.JSX.Element {
  const eventHours: number[] = []
  for (const item of events) {
    const stamp = parseIso(item.startAt)
    if (stamp) eventHours.push(stamp.getHours())
  }
  const startHour = Math.min(8, ...eventHours)
  let endHour = Math.max(20, ...eventHours.map((h) => h + 1))
  endHour = Math.min(24, Math.max(endHour, startHour + 1))
  const hourCount = Math.max(1, endHour - startHour)
  const width = GUTTER + days.length * COL_MIN
  const height = HEADER + hourCount * HOUR_H
  const today = new Date()
  const now = new Date()

  const groups = groupBySlot(events)

  const hourLines: React.JSX.Element[] = []
  for (let hour = startHour; hour <= endHour; hour++) {
    const y = HEADER + (hour - startHour) * HOUR_H
    hourLines.push(
      <div key={`line-${hour}`} className="cal-hour-line" style={{ top: y, left: GUTTER, width: days.length * COL_MIN }} />
    )
    hourLines.push(
      <div key={`hlabel-${hour}`} className="cal-hour-label" style={{ top: y - 8, width: GUTTER - 6 }}>
        {String(hour).padStart(2, '0')}:00
      </div>
    )
  }

  return (
    <div className="cal-week" style={{ width, height }}>
      {days.map((day, index) => {
        const x = GUTTER + index * COL_MIN
        const isToday = sameDay(day, today)
        const count = events.filter((item) => {
          const stamp = parseIso(item.startAt)
          return stamp ? sameDay(stamp, day) : false
        }).length
        return (
          <div key={`col-${index}`}>
            {isToday && (
              <div className="cal-today-col" style={{ left: x, width: COL_MIN, height }} />
            )}
            <div className="cal-col-sep" style={{ left: x, height }} />
            <div className="cal-day-head" style={{ left: x, width: COL_MIN }}>
              {isToday ? (
                <span className="cal-day-pill">
                  {DAYS_SHORT[isoWeekday(day)]} {day.getDate()}
                </span>
              ) : (
                <span className="cal-day-label">
                  {DAYS_SHORT[isoWeekday(day)]} {day.getDate()}
                </span>
              )}
              {count > 0 && (
                <span className={isToday ? 'cal-day-count today' : 'cal-day-count'}>{count}</span>
              )}
            </div>
            {isToday && now.getHours() >= startHour && now.getHours() <= endHour && (
              <div
                className="cal-now-line"
                style={{
                  left: x,
                  width: COL_MIN,
                  top: HEADER + ((now.getHours() - startHour) * 60 + now.getMinutes()) / 60 * HOUR_H
                }}
              />
            )}
          </div>
        )
      })}
      {hourLines}
      {groups.map((group, gi) => {
        const sample = group[0]
        const stamp = parseIso(sample.startAt)
        if (!stamp) return null
        const dayIndex = days.findIndex((d) => sameDay(d, stamp))
        if (dayIndex < 0) return null
        const x = GUTTER + dayIndex * COL_MIN + 4
        const y = HEADER + ((stamp.getHours() - startHour) * 60) / 60 * HOUR_H + 4
        const w = Math.max(72, COL_MIN - 10)
        const style = { left: x, top: y, width: w } as React.CSSProperties
        if (group.length === 1) {
          return (
            <EventBlock
              key={`ev-${gi}`}
              event={sample}
              style={style}
              onClick={onEventClick}
              onContextMenu={onEventContext}
            />
          )
        }
        return (
          <GroupBlock key={`grp-${gi}`} events={group} style={style} onClick={onGroupClick} />
        )
      })}
    </div>
  )
}

interface EventBlockProps {
  event: CalendarEvent
  style: React.CSSProperties
  onClick: (workflowId: string, runId: string) => void
  onContextMenu?: (event: CalendarEvent, evt: React.MouseEvent) => void
  compact?: boolean
}

function EventBlock({ event, style, onClick, compact, onContextMenu }: EventBlockProps): React.JSX.Element {
  const meta = STATUS_STYLE[event.status] ?? STATUS_STYLE.scheduled
  const tip = [
    event.title,
    `${timeText(event.startAt)} · ${meta.label}`,
    SOURCE_LABEL[event.source] ?? '',
    event.subtitle
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <div
      className={compact ? 'cal-event compact' : 'cal-event'}
      style={{ ...style, background: meta.bg, borderColor: meta.border }}
      title={tip}
      onClick={(e) => {
        e.stopPropagation()
        onClick(event.workflowId, event.runId || '')
      }}
      onContextMenu={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onContextMenu?.(event, e)
      }}
    >
      <div className="cal-event-title">
        {timeText(event.startAt)}&nbsp;&nbsp;{event.title}
      </div>
      <div className="cal-event-sub">{clip(event.subtitle || meta.label, 42)}</div>
    </div>
  )
}

interface GroupBlockProps {
  events: CalendarEvent[]
  style: React.CSSProperties
  onClick: (group: CalendarEvent[], evt: React.MouseEvent) => void
  compact?: boolean
}

function GroupBlock({ events, style, onClick, compact }: GroupBlockProps): React.JSX.Element {
  const { title, subtitle, color } = groupSummary(events)
  const tone = groupRunStyle(events)
  const bg = tone.bg
  const border = tone.border
  return (
    <div
      className={compact ? 'cal-group compact' : 'cal-group'}
      style={style}
      title={`${title}\n${subtitle}`}
      onClick={(e) => {
        e.stopPropagation()
        onClick(events, e)
      }}
    >
      <div className="cal-group-stack s2" style={{ background: bg, borderColor: border }} />
      <div className="cal-group-stack s1" style={{ background: bg, borderColor: border }} />
      <div className="cal-group-front" style={{ background: bg, borderColor: border }}>
        <div className="cal-event-title">{title}</div>
        <div className="cal-event-sub" style={{ color }}>
          {subtitle}
        </div>
      </div>
    </div>
  )
}

interface MonthGridProps {
  anchor: Date
  events: CalendarEvent[]
  onEventClick: (workflowId: string, runId: string) => void
  onGroupClick: (group: CalendarEvent[], evt: React.MouseEvent) => void
  onEventContext?: (event: CalendarEvent, evt: React.MouseEvent) => void
}

function MonthGrid({
  anchor,
  events,
  onEventClick,
  onGroupClick,
  onEventContext
}: MonthGridProps): React.JSX.Element {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const start = mondayOf(first)
  const today = new Date()
  const cells = Array.from({ length: 42 }, (_, i) => addDays(start, i))

  return (
    <div className="cal-month">
      <div className="cal-month-head">
        {DAYS_SHORT.map((name) => (
          <div key={name} className="cal-month-weekday">
            {name}
          </div>
        ))}
      </div>
      <div className="cal-month-grid">
        {cells.map((day, index) => {
          const inMonth = day.getMonth() === anchor.getMonth()
          const isToday = sameDay(day, today)
          const dayEvents = events.filter((item) => {
            const stamp = parseIso(item.startAt)
            return stamp ? sameDay(stamp, day) : false
          })
          const groups = groupBySlot(dayEvents)
          const shown = groups.slice(0, 3)
          const leftover = groups.length - shown.length
          return (
            <div
              key={index}
              className={isToday ? 'cal-month-cell today' : 'cal-month-cell'}
            >
              <div
                className="cal-month-day"
                style={{ color: isToday ? '#1565C0' : inMonth ? '#10141A' : '#9BB4D0' }}
              >
                {day.getDate()}
              </div>
              {shown.map((group, gi) =>
                group.length === 1 ? (
                  <EventBlock
                    key={gi}
                    event={group[0]}
                    style={{ position: 'relative' }}
                    onClick={onEventClick}
                    onContextMenu={onEventContext}
                    compact
                  />
                ) : (
                  <GroupBlock
                    key={gi}
                    events={group}
                    style={{ position: 'relative' }}
                    onClick={onGroupClick}
                    compact
                  />
                )
              )}
              {leftover > 0 && <div className="cal-month-more">+{leftover}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

interface GroupPopupProps {
  state: PopupState
  onClose: () => void
  onEventClick: (workflowId: string, runId: string) => void
  onOpenAll: (events: CalendarEvent[]) => void
  onSkipSlot?: (event: CalendarEvent) => void
}

function GroupPopup({
  state,
  onClose,
  onEventClick,
  onOpenAll,
  onSkipSlot
}: GroupPopupProps): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDocClick(evt: MouseEvent): void {
      if (ref.current && !ref.current.contains(evt.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [onClose])

  const left = Math.min(state.x, window.innerWidth - 340)
  const top = Math.min(state.y, window.innerHeight - 320)

  return (
    <div className="cal-popup" ref={ref} style={{ left, top }}>
      <div className="cal-popup-head">{groupHeading(state.events)}</div>
      {state.events.map((item) => {
        const meta = STATUS_STYLE[item.status] ?? STATUS_STYLE.scheduled
        return (
          <div key={item.id} className="cal-popup-row-wrap">
            <button
              className="cal-popup-row"
              onClick={() => onEventClick(item.workflowId, item.runId || '')}
            >
              <span className="cal-popup-avatar">{(item.title || 'А').charAt(0).toUpperCase()}</span>
              <span className="cal-popup-text">
                <span className="cal-popup-name">
                  {timeText(item.startAt)}&nbsp;&nbsp;{item.title || 'ИИ-агент'}
                </span>
                <span className="cal-popup-status" style={{ color: meta.border }}>
                  &#9679;&nbsp;&nbsp;{meta.label}
                </span>
              </span>
            </button>
            {onSkipSlot && canSkipEvent(item) ? (
              <button
                type="button"
                className="cal-popup-skip"
                onClick={() => onSkipSlot(item)}
              >
                Отменить
              </button>
            ) : null}
          </div>
        )
      })}
      <button className="cal-popup-all" onClick={() => onOpenAll(state.events)}>
        Открыть все запуски
      </button>
    </div>
  )
}

interface ScheduleDialogProps {
  agents: BoardAgent[]
  defaultAgent: string
  onCancel: () => void
  onConfirm: (workflowId: string, iso: string) => void
}

function ScheduleDialog({
  agents,
  defaultAgent,
  onCancel,
  onConfirm
}: ScheduleDialogProps): React.JSX.Element {
  const [workflowId, setWorkflowId] = useState(defaultAgent || agents[0]?.id || '')
  const [when, setWhen] = useState(nowForInput())

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-card schedule-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">Запланировать запуск</div>
        {agents.length === 0 ? (
          <div className="modal-note">Нет опубликованных агентов для планирования.</div>
        ) : (
          <>
            <label className="modal-label">Агент</label>
            <select
              className="plain-input"
              value={workflowId}
              onChange={(e) => setWorkflowId(e.target.value)}
            >
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.title || 'ИИ-агент'}
                </option>
              ))}
            </select>
            <label className="modal-label">Время запуска</label>
            <input
              className="plain-input"
              type="datetime-local"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
            />
          </>
        )}
        <div className="modal-actions">
          <button className="btn-light" onClick={onCancel}>
            Отмена
          </button>
          <button
            className="btn-primary"
            disabled={!workflowId || !when}
            onClick={() => {
              const iso = localInputToIso(when)
              if (workflowId && iso) onConfirm(workflowId, iso)
            }}
          >
            Запланировать
          </button>
        </div>
      </div>
    </div>
  )
}
