import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus } from 'lucide-react'

export type KpiTask = {
  fio: string
  title: string
  done: boolean
  late: boolean
  dueAt: string
  createdAt: string
  completedAt: string
}

export type KpiSlice = {
  person: string
  from: string
  to: string
  status: 'all' | 'open' | 'done' | 'overdue'
}

type Preset = 'week' | 'month' | 'quarter' | 'custom'
type HoverKind = 'posted' | 'done' | 'due' | ''
type ChartMode = 'all' | 'groups' | 'people'
type KpiView = 'summary' | 'load'
type LoadKind = 'open' | 'overdue' | 'ontime' | 'late'

type PlotTask = {
  key: string
  title: string
  fio: string
  start: string
  end: string
  due: string
  done: boolean
  knownEnd: boolean
  open: boolean
  overdue: boolean
  late: boolean
}

type LineSeries = {
  key: string
  label: string
  color: string
  values: number[]
  dashed?: boolean
  hover: HoverKind
  fios?: string[]
}

type StaffGroup = {
  id: string
  name: string
  members: string[]
}

const GROUP_COLORS = ['#1565c0', '#2e7d32', '#6a1b9a', '#ef6c00', '#00838f', '#c62828', '#455a64', '#ad1457']

const POSTED = '#ef6c00'
const ON_TIME = '#2e7d32'
const LATE = '#c62828'
const CHART_W = 780
const PAD_L = 36
const PAD_R = 12
const DUE = '#0d3b73'

function parseStamp(value: string): Date | null {
  const text = value.trim()
  if (!text) return null
  const stamp = new Date(text.includes('T') ? text : text.replace(' ', 'T'))
  return Number.isNaN(stamp.getTime()) ? null : stamp
}

function isoDay(stamp: Date): string {
  const month = String(stamp.getMonth() + 1).padStart(2, '0')
  const day = String(stamp.getDate()).padStart(2, '0')
  return `${stamp.getFullYear()}-${month}-${day}`
}

function startOfDay(stamp: Date): Date {
  return new Date(stamp.getFullYear(), stamp.getMonth(), stamp.getDate())
}

function formatDay(value: string): string {
  const stamp = parseStamp(value)
  if (!stamp) return '—'
  return `${String(stamp.getDate()).padStart(2, '0')}.${String(stamp.getMonth() + 1).padStart(2, '0')}`
}

function dayOf(value: string): string {
  const stamp = parseStamp(value)
  return stamp ? isoDay(startOfDay(stamp)) : ''
}

function percentOf(part: number, total: number): string {
  if (total <= 0) return '0%'
  return `${Math.round((part / total) * 100)}%`
}

function weekRange(now = new Date()): { from: string; to: string } {
  const day = startOfDay(now)
  const monday = new Date(day)
  monday.setDate(day.getDate() - ((day.getDay() + 6) % 7))
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  return { from: isoDay(monday), to: isoDay(sunday) }
}

function monthRange(now = new Date()): { from: string; to: string } {
  return {
    from: isoDay(new Date(now.getFullYear(), now.getMonth(), 1)),
    to: isoDay(new Date(now.getFullYear(), now.getMonth() + 1, 0))
  }
}

function quarterRange(now = new Date()): { from: string; to: string } {
  const quarter = Math.floor(now.getMonth() / 3)
  return {
    from: isoDay(new Date(now.getFullYear(), quarter * 3, 1)),
    to: isoDay(new Date(now.getFullYear(), quarter * 3 + 3, 0))
  }
}

function daysBetween(from: string, to: string): string[] {
  const start = parseStamp(from)
  const end = parseStamp(to)
  if (!start || !end) return []
  const cursor = startOfDay(start)
  const last = startOfDay(end).getTime()
  if (cursor.getTime() > last) return []
  const out: string[] = []
  while (cursor.getTime() <= last && out.length < 120) {
    out.push(isoDay(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
}

function normName(value: string): string {
  return value.toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim()
}

function surname(fio: string): string {
  return fio.split(' ')[0] || fio
}

function cut(text: string, max: number): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean
}

function isOverdue(row: KpiTask, today = startOfDay(new Date())): boolean {
  if (row.done) return false
  const due = parseStamp(row.dueAt)
  return due != null && startOfDay(due).getTime() < today.getTime()
}

function plotTask(row: KpiTask, index: number, today: string): PlotTask {
  const completed = dayOf(row.completedAt)
  return {
    key: `${row.fio}|${row.createdAt}|${row.title}|${index}`,
    title: row.title,
    fio: row.fio,
    start: dayOf(row.createdAt),
    end: completed || (!row.done ? today : ''),
    due: dayOf(row.dueAt),
    done: row.done,
    knownEnd: Boolean(completed),
    open: !row.done,
    overdue: isOverdue(row),
    late: row.late
  }
}

function taskWasLate(task: PlotTask): boolean {
  if (!task.done) return task.overdue
  if (task.late) return true
  if (task.knownEnd && task.due) return task.end > task.due
  return false
}

function finishDay(task: PlotTask): string {
  if (task.knownEnd) return task.end
  if (task.done && task.due) return task.due
  return ''
}

function readGroups(ownerId: string): StaffGroup[] {
  try {
    const raw = localStorage.getItem(`orch.subordinate-tasks.groups:${ownerId || 'local'}`)
    const parsed = raw ? (JSON.parse(raw) as StaffGroup[]) : []
    return Array.isArray(parsed) ? parsed.filter((item) => item && item.id && item.name) : []
  } catch {
    return []
  }
}

const LOAD_KIND: { key: LoadKind; label: string; color: string }[] = [
  { key: 'open', label: 'открытые', color: DUE },
  { key: 'overdue', label: 'просроченные', color: LATE },
  { key: 'ontime', label: 'в срок', color: ON_TIME },
  { key: 'late', label: 'с опозданием', color: POSTED }
]

function loadKind(task: PlotTask): LoadKind {
  if (!task.done) return task.overdue ? 'overdue' : 'open'
  return taskWasLate(task) ? 'late' : 'ontime'
}

function hitsPeriod(row: KpiTask, from: string, to: string): boolean {
  return [dayOf(row.createdAt), dayOf(row.completedAt), dayOf(row.dueAt)].some((day) => day && day >= from && day <= to)
}

function FlowChart({
  days,
  lines,
  tasks,
  today,
  hoverDay,
  hoverKind,
  hoverKey,
  focusKey,
  hiddenKeys,
  selected,
  plotHeight,
  onHover,
  onToggleDay,
  onToggleTask
}: {
  days: string[]
  lines: LineSeries[]
  tasks: PlotTask[]
  today: string
  hoverDay: string
  hoverKind: HoverKind
  hoverKey: string
  focusKey: string
  hiddenKeys: string[]
  selected: string[]
  plotHeight: number
  onHover: (day: string, kind: HoverKind, lineKey?: string) => void
  onToggleDay: (day: string, kind: HoverKind, lineKey?: string) => void
  onToggleTask: (key: string) => void
}): React.JSX.Element {
  const [tracerHover, setTracerHover] = useState<PlotTask | null>(null)
  const max = Math.max(1, ...lines.flatMap((line) => line.values))
  const tracers = tasks.filter((task) => selected.includes(task.key))
  const plotTop = 12
  const plotH = Math.max(220, plotHeight)
  const height = plotTop + plotH + 24
  const plotW = CHART_W - PAD_L - PAD_R
  const xOf = (index: number) => PAD_L + (days.length <= 1 ? plotW / 2 : (index / (days.length - 1)) * plotW)
  const yOf = (value: number) => plotTop + plotH - (value / max) * plotH
  const indexOf = (iso: string) => {
    if (!days.length || !iso) return 0
    if (iso <= days[0]) return 0
    if (iso >= days[days.length - 1]) return days.length - 1
    const found = days.indexOf(iso)
    return found >= 0 ? found : 0
  }
  const ticks = max <= 6 ? Array.from({ length: max + 1 }, (_, index) => index) : [0, Math.round(max / 2), max]
  const gridRows = Array.from({ length: max + 1 }, (_, index) => index)
  const futureAt = days.findIndex((day) => day > today)
  const futureX = futureAt > 0 ? (xOf(futureAt - 1) + xOf(futureAt)) / 2 : futureAt === 0 ? PAD_L : null
  const hoverLine = lines.find((item) => item.key === hoverKey)
  const hoverTasks = tasks.filter((task) => {
    const onDay = hoverKind === 'due' ? task.due === hoverDay : hoverKind === 'done' ? finishDay(task) === hoverDay : task.start === hoverDay
    if (!onDay) return false
    return hoverLine?.fios ? hoverLine.fios.includes(task.fio) : true
  })

  function points(values: number[]): string {
    return days.map((_, index) => `${xOf(index)},${yOf(values[index] || 0)}`).join(' ')
  }

  function tracerEnd(task: PlotTask): string {
    if (task.knownEnd) return task.end
    if (task.due) return task.due
    return task.open ? today : ''
  }

  function pointY(day: string, kind: 'posted' | 'due' | 'done', task: PlotTask): number {
    const index = indexOf(day)
    const match = lines.find((line) => {
      if (line.fios && !line.fios.includes(task.fio)) return false
      if (kind === 'posted') return line.hover === 'posted'
      if (kind === 'due') return line.hover === 'due'
      const lateLine = line.key.startsWith('late')
      return line.hover === 'done' && lateLine === taskWasLate(task) && line.key.endsWith('-due') === !task.knownEnd
    })
    const value = match?.values[index] || 0
    return yOf(value)
  }

  const cardTasks = tracerHover ? [tracerHover] : hoverTasks
  const cardX = tracerHover ? xOf(indexOf(tracerEnd(tracerHover))) : hoverDay ? xOf(indexOf(hoverDay)) : 0
  const cardSide = cardX > CHART_W / 2 ? 'left' : 'right'

  return (
    <div
      className="sub-kpi-plot"
      onMouseLeave={() => {
        setTracerHover(null)
        onHover('', '')
      }}
    >
      {cardTasks.length > 0 ? (
        <div
          className={`sub-kpi-hover-card is-${cardSide}`}
          style={{ left: `${(cardX / CHART_W) * 100}%` }}
        >
          {cardTasks.slice(0, 6).map((task) => (
            <button key={task.key} type="button" onClick={() => onToggleTask(task.key)}>
              {cut(task.title, 52)}
            </button>
          ))}
          {cardTasks.length > 6 ? <span>ещё {cardTasks.length - 6}</span> : null}
        </div>
      ) : null}
      <svg viewBox={`0 0 ${CHART_W} ${height}`} role="img" aria-label="Поставленные и выполненные задачи по дням">
        <defs>
          <pattern id="sub-kpi-future" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
            <line x1="0" y1="0" x2="0" y2="8" stroke="#6a1b9a" strokeWidth="2" />
          </pattern>
        </defs>
        {gridRows.map((row) => (
          <line key={`row-${row}`} x1={PAD_L} x2={CHART_W - PAD_R} y1={yOf(row)} y2={yOf(row)} stroke="#d5e2f2" />
        ))}
        {ticks.map((tick) => (
          <text key={`tick-${tick}`} x={PAD_L - 6} y={yOf(tick) + 4} textAnchor="end" className="sub-kpi-axis">
            {tick}
          </text>
        ))}
        {days.map((day, index) => {
          const x = xOf(index)
          const step = days.length <= 1 ? plotW : plotW / (days.length - 1)
          const labelStep = days.length > 45 ? 7 : days.length > 16 ? 5 : 1
          const label = index % labelStep === 0 ? formatDay(day) : ''
          return (
            <g key={day}>
              <line x1={x} x2={x} y1={plotTop} y2={plotTop + plotH} stroke={hoverDay === day ? '#1565c0' : '#d5e2f2'} />
              <rect
                x={x - step / 2}
                y={plotTop}
                width={Math.max(step, 8)}
                height={plotH}
                fill="transparent"
                className="sub-kpi-hit"
                onMouseEnter={() => onHover(day, 'posted')}
                onClick={() => onToggleDay(day, 'posted')}
              />
              {label ? (
                <text x={x} y={plotTop + plotH + 16} textAnchor="middle" className="sub-kpi-axis">
                  {label}
                </text>
              ) : null}
            </g>
          )
        })}
        {futureX != null ? (
          <g pointerEvents="none">
            <rect
              x={futureX}
              y={plotTop}
              width={Math.max(0, CHART_W - PAD_R - futureX)}
              height={plotH}
              fill="url(#sub-kpi-future)"
              opacity="0.7"
            />
            <line
              x1={futureX}
              x2={futureX}
              y1={plotTop}
              y2={plotTop + plotH}
              stroke="#6a1b9a"
              strokeWidth={2}
              strokeDasharray="5 4"
            />
          </g>
        ) : null}
        {lines.map((line) => {
          if (hiddenKeys.includes(line.key) || !line.values.some((value) => value > 0)) return null
          const muted = Boolean(focusKey) && focusKey !== line.key
          return (
            <polyline
              key={line.key}
              points={points(line.values)}
              fill="none"
              stroke={muted ? '#c5ced8' : line.color}
              strokeWidth={focusKey === line.key ? 3 : 2}
              strokeDasharray={line.dashed ? '5 4' : undefined}
            />
          )
        })}
        {days.map((day, index) => {
          const x = xOf(index)
          return (
            <g key={`${day}-mark`}>
              {lines.map((line) => {
                if (hiddenKeys.includes(line.key) || line.values[index] <= 0) return null
                const muted = Boolean(focusKey) && focusKey !== line.key
                return (
                  <circle
                    key={line.key}
                    cx={x}
                    cy={yOf(line.values[index])}
                    r={focusKey === line.key || hoverDay === day ? 5.5 : 4}
                    fill={muted ? '#c5ced8' : line.color}
                    stroke="#fff"
                    strokeWidth={1.5}
                    className="sub-kpi-hit"
                    onMouseEnter={() => onHover(day, line.hover || 'posted', line.key)}
                    onClick={(event) => {
                      event.stopPropagation()
                      onToggleDay(day, line.hover || 'posted', line.key)
                    }}
                  />
                )
              })}
            </g>
          )
        })}
        {tracers.map((task) => {
          const origin = task.start || task.due
          const endIso = tracerEnd(task)
          if (!origin || !endIso) return null
          const x = xOf(indexOf(origin))
          const x2 = xOf(indexOf(endIso))
          const y = pointY(origin, 'posted', task)
          const y2 = task.knownEnd ? pointY(endIso, 'done', task) : pointY(endIso, 'due', task)
          const late = taskWasLate(task)
          const color = late ? LATE : task.done ? ON_TIME : DUE
          return (
            <g
              key={task.key}
              className="sub-kpi-hit"
              onMouseEnter={() => setTracerHover(task)}
              onMouseLeave={() => setTracerHover((current) => (current?.key === task.key ? null : current))}
              onClick={() => onToggleTask(task.key)}
            >
              <line x1={x} x2={x2} y1={y} y2={y2} stroke="transparent" strokeWidth={12} />
              <line
                x1={x}
                x2={x2}
                y1={y}
                y2={y2}
                stroke={color}
                strokeWidth={2.5}
                strokeDasharray={task.knownEnd ? undefined : '4 3'}
              />
              <circle cx={x} cy={y} r={4} fill={POSTED} stroke="#fff" />
              <circle cx={x2} cy={y2} r={5} fill={color} stroke="#fff" />
            </g>
          )
        })}
        {tasks.length === 0 ? (
          <text x={CHART_W / 2} y={plotTop + plotH / 2} textAnchor="middle" className="sub-kpi-axis">
            В этом периоде задач нет
          </text>
        ) : null}
      </svg>
    </div>
  )
}

function OccupancyBoard({
  staff,
  tasks,
  today
}: {
  staff: string[]
  tasks: PlotTask[]
  today: string
}): React.JSX.Element {
  const boardRef = useRef<HTMLDivElement>(null)
  const [focusFio, setFocusFio] = useState('')
  const [tip, setTip] = useState<{ x: number; y: number; lines: string[]; left: boolean } | null>(null)
  const rows = useMemo(() => {
    return staff
      .map((fio) => {
        const mine = tasks.filter((task) => task.fio === fio)
        const parts = Object.fromEntries(
          LOAD_KIND.map((item) => [item.key, mine.filter((task) => loadKind(task) === item.key)])
        ) as Record<LoadKind, PlotTask[]>
        return { fio, parts, total: mine.length }
      })
      .sort((left, right) => right.total - left.total || left.fio.localeCompare(right.fio, 'ru'))
  }, [staff, tasks])
  const shown = focusFio ? rows.filter((row) => row.fio === focusFio) : rows
  const max = Math.max(1, ...shown.map((row) => row.total))

  function dayCount(fromDay: string, toDay: string): number {
    const start = parseStamp(fromDay)
    const end = parseStamp(toDay)
    if (!start || !end) return 0
    return Math.max(0, Math.round((startOfDay(end).getTime() - startOfDay(start).getTime()) / 86_400_000))
  }

  function daysLeft(task: PlotTask): number | null {
    if (!task.due) return null
    if (!task.open) return 0
    return dayCount(today, task.due)
  }

  function showTip(event: React.MouseEvent<HTMLElement>, lines: string[]) {
    const pane = boardRef.current
    if (!pane) return
    const box = pane.getBoundingClientRect()
    const x = event.clientX - box.left
    setTip({ x, y: event.clientY - box.top, lines, left: x > box.width * 0.62 })
  }

  function toggleFocus(fio: string) {
    setFocusFio((current) => (current === fio ? '' : fio))
  }

  if (rows.length === 0) {
    return <p className="sub-kpi-note">Отметьте сотрудников слева — здесь появится их загрузка.</p>
  }

  const shownTasks = shown.flatMap((row) =>
    row.parts.open.concat(row.parts.overdue, row.parts.ontime, row.parts.late)
  )
  const maxDays = Math.max(1, ...shownTasks.map((task) => daysLeft(task) ?? 0))

  function ratioLines(row: (typeof rows)[number]): string[] {
    const lines = [`${surname(row.fio)} · ${row.total}`]
    for (const item of LOAD_KIND) {
      const count = row.parts[item.key].length
      if (count === 0) continue
      lines.push(`${item.label} — ${count} (${percentOf(count, row.total)})`)
    }
    return lines
  }

  return (
    <div className="sub-kpi-load" ref={boardRef} onMouseLeave={() => setTip(null)}>
      <section className="sub-kpi-load-pane" aria-label="Количество задач">
        <h3>Задачи по сотрудникам</h3>
        {focusFio ? (
          <button type="button" className="sub-kpi-load-clear" onClick={() => setFocusFio('')}>
            Все сотрудники
          </button>
        ) : null}
        {shown.map((row) => (
          <div
            key={row.fio}
            className="sub-kpi-bar-row"
            onMouseEnter={(event) => showTip(event, ratioLines(row))}
          >
            <button type="button" title={row.fio} onClick={() => toggleFocus(row.fio)}>
              {surname(row.fio)}
            </button>
            <div className="sub-kpi-bar-track" aria-label={`${row.fio}: ${row.total}`}>
              {LOAD_KIND.map((item) => {
                const count = row.parts[item.key].length
                if (count === 0) return null
                return (
                  <button
                    key={item.key}
                    type="button"
                    style={{ width: `${(count / max) * 100}%`, background: item.color }}
                    aria-label={`${surname(row.fio)}, ${item.label}: ${count}`}
                    onClick={() => toggleFocus(row.fio)}
                  />
                )
              })}
            </div>
            <strong>{row.total}</strong>
          </div>
        ))}
        <p className="sub-kpi-load-scale">0 — {max}</p>
        <div className="sub-kpi-load-legend">
          {LOAD_KIND.map((item) => (
            <span key={item.key}>
              <i style={{ background: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      </section>
      <section className="sub-kpi-load-pane" aria-label="Срок задач">
        <h3>Осталось до срока</h3>
        {shownTasks.length === 0 ? (
          <p className="sub-kpi-note">В этом периоде задач нет.</p>
        ) : (
          <>
            <p className="sub-kpi-load-scale">Длина полосы — сколько дней ещё осталось до срока.</p>
            {shown
              .filter((row) => row.total > 0)
              .map((row) => (
                <div key={row.fio}>
                  {focusFio ? null : (
                    <button type="button" className="sub-kpi-gantt-person" onClick={() => toggleFocus(row.fio)}>
                      {surname(row.fio)}
                    </button>
                  )}
                  {row.parts.open
                    .concat(row.parts.overdue, row.parts.ontime, row.parts.late)
                    .map((task) => {
                      const left = daysLeft(task)
                      const kind = LOAD_KIND.find((item) => item.key === loadKind(task))
                      const dueText = task.due ? `${formatDay(task.due)}.${parseStamp(task.due)?.getFullYear() ?? ''}` : 'нет срока'
                      const width = left && left > 0 ? (left / maxDays) * 100 : 0
                      return (
                        <div key={task.key} className="sub-kpi-gantt-row">
                          <span title={task.title}>{cut(task.title, 22)}</span>
                          <div className="sub-kpi-gantt-lane">
                            {left == null ? (
                              <span className="sub-kpi-load-scale">нет срока</span>
                            ) : width > 0 ? (
                              <div className="sub-kpi-gantt-window" style={{ width: `${width}%` }}>
                                <button
                                  type="button"
                                  style={{ width: '100%', background: kind?.color || DUE }}
                                  aria-label={task.title}
                                  onMouseEnter={(event) =>
                                    showTip(event, [task.title, `срок ${dueText}`, `осталось ${left} дн.`])
                                  }
                                />
                              </div>
                            ) : null}
                          </div>
                          <strong title={left == null ? 'Нет срока' : task.open ? `Осталось ${left} дн. до ${dueText}` : 'Исполнено'}>
                            {left == null ? '—' : `${left} дн.`}
                          </strong>
                        </div>
                      )
                    })}
                </div>
              ))}
          </>
        )}
      </section>
      {tip ? (
        <div className={`sub-kpi-load-tip${tip.left ? ' is-left' : ''}`} style={{ left: tip.x, top: tip.y }}>
          {tip.lines.map((line, index) => (
            <p key={`${index}-${line}`}>{line}</p>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function SubordinateKpiDialog({
  tasks,
  people = [],
  directory = [],
  ownerId = 'local',
  dateFrom,
  dateTo,
  person,
  onClose,
  onDownload,
  onApply,
  onAddPerson
}: {
  tasks: KpiTask[]
  people: string[]
  directory?: string[]
  ownerId?: string
  dateFrom: string
  dateTo: string
  person: string
  onClose: () => void
  onDownload: () => void
  onApply: (slice: KpiSlice) => void
  onAddPerson: (fio: string) => void
}): React.JSX.Element {
  const today = isoDay(startOfDay(new Date()))
  const [preset, setPreset] = useState<Preset>('custom')
  const [from, setFrom] = useState(dateFrom)
  const [to, setTo] = useState(dateTo)
  const [checked, setChecked] = useState<Set<string>>(() => new Set(people))
  const [hoverDay, setHoverDay] = useState('')
  const [hoverKind, setHoverKind] = useState<HoverKind>('')
  const [hoverKey, setHoverKey] = useState('')
  const [legendHover, setLegendHover] = useState('')
  const [hiddenLines, setHiddenLines] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [groups, setGroups] = useState<StaffGroup[]>(() => readGroups(ownerId))
  const [mode, setMode] = useState<ChartMode>('all')
  const [view, setView] = useState<KpiView>('summary')
  const [renameId, setRenameId] = useState('')
  const [openIds, setOpenIds] = useState<Set<string>>(new Set())
  const [overId, setOverId] = useState('')
  const plotRef = useRef<HTMLDivElement>(null)
  const [plotHeight, setPlotHeight] = useState(420)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const staff = useMemo(() => {
    const names = [...people]
    return names.sort((a, b) => {
      if (a === person) return -1
      if (b === person) return 1
      return a.localeCompare(b, 'ru')
    })
  }, [people, person])

  const days = useMemo(() => daysBetween(from, to), [from, to])
  const periodTasks = useMemo(
    () => tasks.filter((row) => checked.has(row.fio) && hitsPeriod(row, from, to)),
    [tasks, checked, from, to]
  )
  const plotted = useMemo(
    () => periodTasks.map((row, index) => plotTask(row, index, today)),
    [periodTasks, today]
  )
  useEffect(() => {
    localStorage.setItem(`orch.subordinate-tasks.groups:${ownerId || 'local'}`, JSON.stringify(groups))
  }, [groups, ownerId])

  useEffect(() => {
    const node = plotRef.current
    if (!node) return
    const update = () => {
      const width = node.clientWidth || CHART_W
      const height = node.clientHeight || 420
      const viewH = (CHART_W * height) / width
      setPlotHeight(Math.max(220, Math.floor(viewH - 36)))
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [view])

  const posted = days.map((day) => plotted.filter((task) => task.start === day).length)
  const dueCounts = days.map((day) => plotted.filter((task) => task.due === day).length)
  const onTimeKnown = days.map((day) => plotted.filter((task) => task.knownEnd && task.end === day && !taskWasLate(task)).length)
  const lateKnown = days.map((day) => plotted.filter((task) => task.knownEnd && task.end === day && taskWasLate(task)).length)
  const onTimeDue = days.map((day) => plotted.filter((task) => !task.knownEnd && task.done && task.due === day && !taskWasLate(task)).length)
  const lateDue = days.map((day) => plotted.filter((task) => !task.knownEnd && task.done && task.due === day && taskWasLate(task)).length)
  const postedCount = plotted.filter((task) => task.start >= from && task.start <= to).length
  const doneCount = plotted.filter((task) => task.done).length
  const overdueCount = plotted.filter((task) => task.overdue).length
  const unknownDone = plotted.filter((task) => task.done && !task.knownEnd).length
  const grouped = new Set(groups.flatMap((group) => group.members))
  const looseStaff = staff.filter((fio) => !grouped.has(fio))
  const allOn = staff.length > 0 && staff.every((fio) => checked.has(fio))
  const suggestions = useMemo(() => {
    const needle = normName(query)
    if (needle.length < 2) return []
    const have = new Set(staff)
    return directory.filter((fio) => fio && !have.has(fio) && normName(fio).includes(needle)).slice(0, 8)
  }, [directory, query, staff])
  const lines = useMemo<LineSeries[]>(() => {
    if (mode === 'people') {
      return staff
        .filter((fio) => checked.has(fio))
        .map((fio, index) => ({
          key: fio,
          label: surname(fio),
          color: GROUP_COLORS[index % GROUP_COLORS.length],
          hover: 'posted' as const,
          fios: [fio],
          values: days.map((day) => plotted.filter((task) => task.fio === fio && task.start === day).length)
        }))
    }
    if (mode === 'groups') {
      const folders = groups.filter((group) => group.members.some((fio) => checked.has(fio)))
      const loose = staff.filter((fio) => checked.has(fio) && !groups.some((group) => group.members.includes(fio)))
      const packs = [
        ...folders.map((group) => ({ id: group.id, label: group.name, members: group.members.filter((fio) => checked.has(fio)) })),
        ...(loose.length ? [{ id: 'loose', label: 'Без группы', members: loose }] : [])
      ]
      return packs.map((pack, index) => ({
        key: pack.id,
        label: pack.label,
        color: GROUP_COLORS[index % GROUP_COLORS.length],
        hover: 'posted' as const,
        fios: pack.members,
        values: days.map((day) => plotted.filter((task) => pack.members.includes(task.fio) && task.start === day).length)
      }))
    }
    const next: LineSeries[] = [
      { key: 'posted', label: 'поставленные', color: POSTED, values: posted, hover: 'posted' },
      { key: 'deadline', label: 'срок', color: DUE, values: dueCounts, hover: 'due' }
    ]
    if (onTimeKnown.some((value) => value > 0)) next.push({ key: 'ontime', label: 'выполнено', color: ON_TIME, values: onTimeKnown, hover: 'done' })
    if (lateKnown.some((value) => value > 0)) next.push({ key: 'late', label: 'просрочено', color: LATE, values: lateKnown, hover: 'done' })
    if (onTimeDue.some((value) => value > 0)) next.push({ key: 'ontime-due', label: 'по сроку', color: ON_TIME, values: onTimeDue, dashed: true, hover: 'done' })
    if (lateDue.some((value) => value > 0)) next.push({ key: 'late-due', label: 'после срока', color: LATE, values: lateDue, dashed: true, hover: 'done' })
    return next
  }, [mode, checked, days, dueCounts, groups, lateDue, lateKnown, onTimeDue, onTimeKnown, plotted, posted, staff])

  function applyPreset(next: Exclude<Preset, 'custom'>) {
    const range = next === 'week' ? weekRange() : next === 'month' ? monthRange() : quarterRange()
    setPreset(next)
    setFrom(range.from)
    setTo(range.to)
    setSelected([])
  }

  function toggleLine(key: string) {
    setHiddenLines((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function togglePerson(fio: string) {
    setChecked((current) => {
      const next = new Set(current)
      if (next.has(fio)) next.delete(fio)
      else next.add(fio)
      return next
    })
    setSelected([])
  }

  function toggleDay(day: string, kind: HoverKind, lineKey = '') {
    const fios = lines.find((line) => line.key === lineKey)?.fios
    const keys = plotted
      .filter((task) => {
        const onDay = kind === 'due' ? task.due === day : kind === 'done' ? finishDay(task) === day : task.start === day
        if (!onDay) return false
        return fios ? fios.includes(task.fio) : true
      })
      .map((task) => task.key)
    setSelected((current) => {
      const every = keys.length > 0 && keys.every((key) => current.includes(key))
      if (every) return current.filter((key) => !keys.includes(key))
      return [...new Set([...current, ...keys])]
    })
  }

  function addPerson(fio: string) {
    onAddPerson(fio)
    setChecked((current) => new Set(current).add(fio))
    setQuery('')
  }

  function createGroup() {
    const id = `g-${Date.now()}`
    setGroups([...groups, { id, name: `Группа ${groups.length + 1}`, members: [] }])
    setOpenIds((current) => new Set(current).add(id))
    setRenameId(id)
  }

  function toggleGroup(id: string) {
    setOpenIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function renameGroup(id: string, name: string) {
    const next = name.replace(/\s+/g, ' ').trim()
    if (!next) return
    setGroups(groups.map((group) => (group.id === id ? { ...group, name: next } : group)))
  }

  function personButton(fio: string) {
    return (
      <button
        key={fio}
        type="button"
        draggable
        className={`sub-kpi-person-btn${checked.has(fio) ? ' is-active' : ''}`}
        onClick={() => togglePerson(fio)}
        onDragStart={(event) => {
          event.dataTransfer.setData('text/plain', fio)
          event.dataTransfer.effectAllowed = 'move'
        }}
      >
        {fio}
      </button>
    )
  }

  function assignGroup(fio: string, groupId: string) {
    setGroups(
      groups.map((group) => ({
        ...group,
        members:
          group.id === groupId
            ? [...group.members.filter((item) => item !== fio), fio]
            : group.members.filter((item) => item !== fio)
      }))
    )
  }

  function applySlice() {
    const chosen = staff.filter((fio) => checked.has(fio))
    onApply({
      person: chosen.length === 1 ? chosen[0] : '',
      from,
      to,
      status: 'all'
    })
  }

  return createPortal(
    <div className="sub-kpi-modal" role="dialog" aria-modal="true" aria-labelledby="sub-kpi-title">
      <button type="button" className="sub-kpi-backdrop" aria-label="Закрыть" onClick={onClose} />
      <div className="sub-kpi-card sub-kpi-dashboard">
        <header className="sub-kpi-head">
          <div>
            <h2 id="sub-kpi-title">Сводка KPI</h2>
            <p>
              {view === 'load'
                ? 'Слева — соотношение задач. Справа — сколько дней осталось до срока. Нажатие на сотрудника оставляет только его.'
                : 'Наведите на точку — задачи появятся над графиком. Нажмите — линия от постановки до выполнения.'}
            </p>
          </div>
          <button type="button" className="sub-tasks-btn" onClick={onClose}>
            Закрыть
          </button>
        </header>
        <div className="sub-kpi-layout">
          <aside className="sub-kpi-settings">
            <h3>Период</h3>
            <div className="sub-tasks-presets" role="group" aria-label="Период">
              {(
                [
                  ['week', 'Неделя'],
                  ['month', 'Месяц'],
                  ['quarter', 'Квартал']
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`sub-tasks-preset${preset === id ? ' is-active' : ''}`}
                  aria-pressed={preset === id}
                  onClick={() => applyPreset(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="sub-tasks-date">
              с
              <input
                type="date"
                value={from}
                onChange={(event) => {
                  setPreset('custom')
                  setFrom(event.target.value)
                  setSelected([])
                }}
              />
            </label>
            <label className="sub-tasks-date">
              по
              <input
                type="date"
                value={to}
                onChange={(event) => {
                  setPreset('custom')
                  setTo(event.target.value)
                  setSelected([])
                }}
              />
            </label>
            <h3>Сотрудники</h3>
            <div className="sub-tasks-add">
              <input
                type="search"
                value={query}
                placeholder="Найти и добавить"
                aria-label="Добавить сотрудника"
                onChange={(event) => setQuery(event.target.value)}
              />
              {query.trim().length >= 2 ? (
                <ul className="sub-tasks-suggest">
                  {suggestions.length === 0 ? (
                    <li className="sub-tasks-suggest-empty">Нет такого подчинённого</li>
                  ) : (
                    suggestions.map((fio) => (
                      <li key={fio}>
                        <button type="button" onClick={() => addPerson(fio)}>
                          {fio}
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              ) : null}
            </div>
            <div
              className="sub-kpi-staff"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                const fio = event.dataTransfer.getData('text/plain')
                if (fio) assignGroup(fio, '')
              }}
            >
            {staff.length > 0 ? (
              <button
                type="button"
                className={`sub-kpi-person-btn${allOn ? ' is-active' : ''}`}
                onClick={() => {
                  setChecked(allOn ? new Set() : new Set(staff))
                  setSelected([])
                }}
              >
                Все
              </button>
            ) : null}
              {looseStaff.map((fio) => personButton(fio))}
            </div>
            <div className="sub-kpi-groups-head">
              <h3>Группы</h3>
              <button type="button" className="sub-kpi-plus" aria-label="Новая группа" onClick={createGroup}>
                <Plus size={18} strokeWidth={2.25} />
              </button>
            </div>
            {groups.map((group) => {
              const opened = openIds.has(group.id)
              return (
              <div
                key={group.id}
                className={`sub-kpi-folder${overId === group.id ? ' is-over' : ''}${opened ? ' is-open' : ''}`}
                onDragOver={(event) => {
                  event.preventDefault()
                  setOverId(group.id)
                }}
                onDragLeave={() => setOverId((current) => (current === group.id ? '' : current))}
                onDrop={(event) => {
                  event.preventDefault()
                  setOverId('')
                  const fio = event.dataTransfer.getData('text/plain')
                  if (fio) {
                    assignGroup(fio, group.id)
                    setOpenIds((current) => new Set(current).add(group.id))
                  }
                }}
              >
                <div className="sub-kpi-folder-head">
                {renameId === group.id ? (
                  <input
                    autoFocus
                    aria-label="Название группы"
                    defaultValue={group.name}
                    onBlur={(event) => {
                      renameGroup(group.id, event.target.value)
                      setRenameId('')
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') event.currentTarget.blur()
                    }}
                  />
                ) : (
                  <button
                    type="button"
                    aria-expanded={opened}
                    onClick={() => toggleGroup(group.id)}
                    onDoubleClick={() => setRenameId(group.id)}
                  >
                    {opened ? '▾' : '▸'} {group.name}
                  </button>
                )}
                <span>{group.members.length}</span>
                <button type="button" onClick={() => setGroups(groups.filter((item) => item.id !== group.id))}>
                  Удалить
                </button>
                </div>
                {opened ? (
                  <div className="sub-kpi-folder-members">
                    {group.members.length === 0 ? <span>В группе никого нет</span> : group.members.map((fio) => personButton(fio))}
                  </div>
                ) : null}
              </div>
              )
            })}
          </aside>
          <div className="sub-kpi-main">
            <div className="sub-kpi-cards">
              <article className="sub-kpi-card-metric">
                <span>Поставлено</span>
                <strong>{postedCount}</strong>
                <small>{percentOf(postedCount, plotted.length)} от всех</small>
              </article>
              <article className="sub-kpi-card-metric">
                <span>Выполнено</span>
                <strong>{doneCount}</strong>
                <small>{percentOf(doneCount, plotted.length)} от всех</small>
              </article>
              <article className="sub-kpi-card-metric">
                <span>Просрочено</span>
                <strong>{overdueCount}</strong>
                <small>{percentOf(overdueCount, plotted.length)} от всех</small>
              </article>
            </div>
            <section className="sub-kpi-section sub-kpi-chart">
              <div className="sub-tasks-presets sub-kpi-chart-modes" role="tablist" aria-label="Вкладка KPI">
                {(
                  [
                    ['summary', 'Сводка'],
                    ['load', 'Гистограмма занятости']
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`sub-tasks-preset${view === id ? ' is-active' : ''}`}
                    aria-pressed={view === id}
                    onClick={() => setView(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {view === 'load' ? (
                <OccupancyBoard staff={staff.filter((fio) => checked.has(fio))} tasks={plotted} today={today} />
              ) : (
              <>
              <div className="sub-tasks-presets sub-kpi-chart-modes" role="group" aria-label="Вид графика">
                {(
                  [
                    ['groups', 'Группы'],
                    ['people', 'Люди'],
                    ['all', 'Общее']
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`sub-tasks-preset${mode === id ? ' is-active' : ''}`}
                    aria-pressed={mode === id}
                    onClick={() => setMode(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="sub-kpi-flow-legend" onMouseLeave={() => setLegendHover('')}>
                {lines.map((line) => {
                  const hidden = hiddenLines.has(line.key)
                  const dim = Boolean(legendHover) && legendHover !== line.key
                  return (
                    <button
                      key={line.key}
                      type="button"
                      className={`sub-kpi-legend-btn${hidden ? ' is-off' : ''}${dim ? ' is-dim' : ''}`}
                      aria-pressed={!hidden}
                      onMouseEnter={() => setLegendHover(line.key)}
                      onClick={() => toggleLine(line.key)}
                    >
                      <i style={{ background: hidden || dim ? '#c5ced8' : line.color, borderBottom: line.dashed ? '2px dashed #fff' : undefined }} />
                      {line.label}
                    </button>
                  )
                })}
              </div>
              <div className="sub-kpi-plot-frame" ref={plotRef}>
              <FlowChart
                days={days}
                lines={lines}
                tasks={plotted}
                today={today}
                hoverDay={hoverDay}
                hoverKind={hoverKind}
                hoverKey={hoverKey}
                focusKey={legendHover}
                hiddenKeys={[...hiddenLines]}
                selected={selected}
                plotHeight={plotHeight}
                onHover={(day, kind, lineKey) => {
                  setHoverDay(day)
                  setHoverKind(kind)
                  setHoverKey(lineKey || '')
                }}
                onToggleDay={toggleDay}
                onToggleTask={(key) => setSelected((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]))}
              />
              </div>
              {unknownDone > 0 ? (
                <p className="sub-kpi-note">
                  У {unknownDone} выполненных задач нет дня выполнения в 1С. Пунктир «по сроку» стоит на сроке задачи: зелёный — в срок, красный — после срока.
                </p>
              ) : null}
              </>
              )}
            </section>
          </div>
        </div>
        <footer className="sub-kpi-foot">
          <button type="button" className="sub-tasks-btn" onClick={onDownload}>
            Скачать CSV
          </button>
          <button type="button" className="sub-tasks-btn is-primary" onClick={applySlice}>
            Показать в задачах
          </button>
        </footer>
      </div>
    </div>,
    document.body
  )
}
