import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Filter, Plus } from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import { canUseSubordinateTasks } from '../../extensions/extensionAccess'
import { OrchSlotMain } from '../../layout/GridSlots'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'
import { textMatchesPageSearch, usePageSearchOptional } from '../../layout/pageSearchContext'
import { SpecSummaryTiles } from '../../workplace/specV04Components'
import { SubordinateKpiDialog } from './SubordinateKpiDialog'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import './subordinateTasks.css'

type PeriodPreset = 'span' | 'month' | 'quarter' | 'custom'

type TaskFilter = 'all' | 'open' | 'overdue' | 'critical' | 'done'

type TaskColumn = 'fio' | 'title' | 'kind' | 'due' | 'status' | 'source'

type SortState = { col: TaskColumn; dir: 'asc' | 'desc' } | null

type StaffGroup = { id: string; name: string; members: string[] }

type TaskKind = 'overdue' | 'critical' | 'open' | 'done'

type OnecTask = {
  number: string
  title: string
  done: boolean
  late: boolean
  dueAt: string
  createdAt: string
  completedAt: string
  comment: string
  approval: string
  source: string
  kindName: string
  origin: string
}

type PersonNode = {
  fio: string
  position: string
  department: string
  level: number
  tasks: OnecTask[]
  subordinates: PersonNode[]
}

type FlatTask = OnecTask & {
  fio: string
  position: string
  department: string
  kind: TaskKind
}

type PersonLoad = {
  fio: string
  position: string
  department: string
  level: number
  open: number
  overdue: number
  critical: number
  done: number
  doneOfDue: number
  dueReached: number
}

const CRITICAL_DAYS = 3

const TASK_COLUMNS: { id: TaskColumn; label: string; filter?: boolean }[] = [
  { id: 'fio', label: 'Подчинённый' },
  { id: 'title', label: 'Задача' },
  { id: 'kind', label: 'Вид' },
  { id: 'due', label: 'Срок', filter: false },
  { id: 'status', label: 'Статус' },
  { id: 'source', label: 'Откуда' }
]

const KIND_LABEL: Record<string, string> = {
  execute: 'Исполнение',
  check: 'Проверка исполнения',
  acquaint: 'Ознакомление',
  acquaint_result: 'Ознакомление с результатом',
  approve: 'Согласование',
  confirm: 'Утверждение',
  consider: 'Рассмотрение',
  question: 'Вопрос',
  resolution: 'Резолюция',
  project: 'Задача проекта',
  other: 'Задача'
}

function isoDay(stamp: Date): string {
  const month = String(stamp.getMonth() + 1).padStart(2, '0')
  const day = String(stamp.getDate()).padStart(2, '0')
  return `${stamp.getFullYear()}-${month}-${day}`
}

function spanRange(now = new Date()): { from: string; to: string } {
  return {
    from: isoDay(new Date(now.getFullYear(), now.getMonth() - 1, 1)),
    to: isoDay(new Date(now.getFullYear(), now.getMonth() + 1, 0))
  }
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

function rangeFor(preset: PeriodPreset): { from: string; to: string } {
  if (preset === 'month') return monthRange()
  if (preset === 'quarter') return quarterRange()
  return spanRange()
}

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function str(value: unknown): string {
  return String(value ?? '').trim()
}

function parseStamp(value: string): Date | null {
  const text = value.trim()
  if (!text) return null
  const stamp = new Date(text.includes('T') ? text : text.replace(' ', 'T'))
  return Number.isNaN(stamp.getTime()) ? null : stamp
}

function startOfDay(stamp: Date): number {
  return new Date(stamp.getFullYear(), stamp.getMonth(), stamp.getDate()).getTime()
}

function formatDue(value: string): string {
  const stamp = parseStamp(value)
  if (!stamp) return '—'
  const day = String(stamp.getDate()).padStart(2, '0')
  const month = String(stamp.getMonth() + 1).padStart(2, '0')
  const hours = String(stamp.getHours()).padStart(2, '0')
  const minutes = String(stamp.getMinutes()).padStart(2, '0')
  const date = `${day}.${month}.${stamp.getFullYear()}`
  return hours === '00' && minutes === '00' ? date : `${date} ${hours}:${minutes}`
}

function formatPeriod(from: string, to: string): string {
  return `${formatDue(from)} — ${formatDue(to)}`
}

function percentOf(part: number, total: number): string {
  if (total <= 0) return '0%'
  return `${Math.round((part / total) * 100)}%`
}

function taskKind(task: OnecTask, today = new Date()): TaskKind {
  if (task.done) return 'done'
  const due = parseStamp(task.dueAt)
  if (!due) return 'open'
  const dueDay = startOfDay(due)
  const start = startOfDay(today)
  if (dueDay < start) return 'overdue'
  if (dueDay <= start + CRITICAL_DAYS * 24 * 60 * 60 * 1000) return 'critical'
  return 'open'
}

function dayStamp(value: string): number | null {
  const stamp = parseStamp(value)
  return stamp ? startOfDay(stamp) : null
}

/** Задача попадает в период по сроку. Если срока нет — по дате исполнения или создания. */
function taskInPeriod(task: OnecTask, from: string, to: string): boolean {
  const start = dayStamp(from)
  const end = dayStamp(to)
  if (start == null || end == null) return true
  const mark = dayStamp(task.dueAt) ?? dayStamp(task.completedAt) ?? dayStamp(task.createdAt)
  if (mark == null) return false
  return mark >= start && mark <= end
}

function fetchFrom(from: string): string {
  const stamp = parseStamp(from)
  if (!stamp) return from
  return isoDay(new Date(stamp.getFullYear(), stamp.getMonth() - 1, 1))
}

function dueHasArrived(task: OnecTask, today = new Date()): boolean {
  const due = parseStamp(task.dueAt)
  if (!due) return false
  return startOfDay(due) <= startOfDay(today)
}

function readTask(value: unknown): OnecTask | null {
  const row = rec(value)
  const title = str(row.title)
  const number = str(row.number)
  if (!title && !number) return null
  return {
    number,
    title: title || number,
    done: Boolean(row.done),
    late: Boolean(row.late),
    dueAt: str(row.due_at),
    createdAt: str(row.created_at),
    completedAt: str(row.completed_at),
    comment: str(row.comment),
    approval: str(row.approval),
    source: str(row.source),
    kindName: str(row.kind),
    origin: str(row.origin) || str(row.project_name)
  }
}

function readPeople(value: unknown): PersonNode[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    const row = rec(item)
    const tasks = Array.isArray(row.tasks)
      ? row.tasks.map(readTask).filter((task): task is OnecTask => task !== null)
      : []
    return {
      fio: str(row.fio),
      position: str(row.position),
      department: str(row.department),
      level: Number(row.level) || 1,
      tasks,
      subordinates: readPeople(row.subordinates)
    }
  })
}

function flattenPeople(nodes: PersonNode[]): PersonNode[] {
  const out: PersonNode[] = []
  const walk = (list: PersonNode[]) => {
    for (const node of list) {
      out.push(node)
      walk(node.subordinates)
    }
  }
  walk(nodes)
  return out
}

function taskIdentity(row: { fio: string; title: string; source?: string }): string {
  return `${row.fio}\n${row.source || ''}\n${row.title.replace(/\s+/g, ' ').trim().toLowerCase()}`
}

/** Перенос срока в 1С оставляет прежнюю задачу и создаёт новую с тем же текстом. В расчёт берём последний срок. */
function keepCurrentTerm(rows: FlatTask[]): FlatTask[] {
  const groups = new Map<string, FlatTask[]>()
  for (const row of rows) {
    const key = taskIdentity(row)
    const list = groups.get(key)
    if (list) list.push(row)
    else groups.set(key, [row])
  }
  const current: FlatTask[] = []
  const latest = (list: FlatTask[]) =>
    [...list].sort((a, b) => (parseStamp(b.dueAt)?.getTime() ?? 0) - (parseStamp(a.dueAt)?.getTime() ?? 0))[0]
  for (const list of groups.values()) {
    const open = list.filter((row) => !row.done)
    const done = list.filter((row) => row.done)
    if (open.length > 0) {
      const chosen = latest(open)
      current.push({ ...chosen, kind: taskKind(chosen) })
    }
    if (done.length > 0) {
      const chosen = latest(done)
      current.push({ ...chosen, kind: 'done' })
    }
  }
  return current
}

function sortTasks(rows: FlatTask[]): FlatTask[] {
  const rank: Record<TaskKind, number> = { overdue: 0, critical: 1, open: 2, done: 3 }
  return [...rows].sort((a, b) => {
    const byKind = rank[a.kind] - rank[b.kind]
    if (byKind !== 0) return byKind
    const aDue = parseStamp(a.dueAt)?.getTime() ?? Number.MAX_SAFE_INTEGER
    const bDue = parseStamp(b.dueAt)?.getTime() ?? Number.MAX_SAFE_INTEGER
    if (a.kind === 'done') return bDue - aDue
    return aDue - bDue
  })
}

function flattenTasks(people: PersonNode[]): FlatTask[] {
  const rows: FlatTask[] = []
  for (const person of people) {
    for (const task of person.tasks) {
      rows.push({
        ...task,
        fio: person.fio,
        position: person.position,
        department: person.department,
        kind: taskKind(task)
      })
    }
  }
  return sortTasks(keepCurrentTerm(rows))
}

function personLoad(people: PersonNode[], rows: FlatTask[]): PersonLoad[] {
  const byFio = new Map<string, FlatTask[]>()
  for (const row of rows) {
    const list = byFio.get(row.fio) || []
    list.push(row)
    byFio.set(row.fio, list)
  }
  return people
    .map((person) => {
      const items = byFio.get(person.fio) || []
      const kinds = items.map((task) => task.kind)
      const doneOfDue = items.filter((task) => task.done && dueHasArrived(task)).length
      const dueReached = items.filter((task) => dueHasArrived(task)).length
      return {
        fio: person.fio,
        position: person.position,
        department: person.department,
        level: person.level,
        open: kinds.filter((kind) => kind !== 'done').length,
        overdue: kinds.filter((kind) => kind === 'overdue').length,
        critical: kinds.filter((kind) => kind === 'critical').length,
        done: kinds.filter((kind) => kind === 'done').length,
        doneOfDue,
        dueReached
      }
    })
    .sort((a, b) => b.overdue - a.overdue || b.open - a.open || a.fio.localeCompare(b.fio, 'ru'))
}

function statusLabel(row: FlatTask): string {
  if (row.kind === 'done' && row.late) return 'выполнена с опозданием'
  if (row.kind === 'done') return 'выполнена'
  if (row.kind === 'overdue') return 'просрочена'
  if (row.kind === 'critical') return 'подходит срок'
  return 'поставлена'
}

function sourceLabel(source: string): string {
  if (source === 'erp_pm') return '1С ERP'
  if (source === 'документооборот') return 'Документооборот'
  if (source === 'документооборот (от меня)') return 'Документооборот'
  if (source === 'turboproject') return 'Турбопроект'
  if (source === 'stub') return 'нет связи с 1С'
  return source || '1С'
}

function kindLabel(row: Pick<FlatTask, 'kindName' | 'source'>): string {
  if (row.kindName && KIND_LABEL[row.kindName]) return KIND_LABEL[row.kindName]
  if (row.source === 'turboproject') return 'Задача проекта'
  if (row.source === 'erp_pm') return 'Задача ERP'
  return 'Задача'
}

function originLabel(row: Pick<FlatTask, 'source' | 'origin'>): string {
  const base = sourceLabel(row.source)
  return row.origin ? `${base} · ${row.origin}` : base
}

function columnText(row: FlatTask, col: TaskColumn): string {
  if (col === 'fio') return row.fio
  if (col === 'title') return row.title
  if (col === 'kind') return kindLabel(row)
  if (col === 'status') return statusLabel(row)
  if (col === 'source') return originLabel(row)
  return formatDue(row.dueAt)
}

function compareTasks(left: FlatTask, right: FlatTask, col: TaskColumn, dir: 'asc' | 'desc'): number {
  const sign = dir === 'asc' ? 1 : -1
  if (col === 'due') {
    const a = parseStamp(left.dueAt)?.getTime() ?? 0
    const b = parseStamp(right.dueAt)?.getTime() ?? 0
    return (a - b) * sign
  }
  return columnText(left, col).localeCompare(columnText(right, col), 'ru') * sign
}

function groupsKey(userId: string): string {
  return `orch.subordinate-tasks.groups:${userId || 'local'}`
}

function readGroups(userId: string): StaffGroup[] {
  try {
    const raw = localStorage.getItem(groupsKey(userId))
    const parsed = raw ? (JSON.parse(raw) as StaffGroup[]) : []
    return Array.isArray(parsed) ? parsed.filter((item) => item && item.id && item.name) : []
  } catch {
    return []
  }
}

function csvCell(value: string): string {
  const text = value.replace(/"/g, '""')
  return /[;"\n\r]/.test(text) ? `"${text}"` : text
}

function downloadCsv(filename: string, header: string[], rows: string[][]) {
  const body = [header, ...rows].map((line) => line.map(csvCell).join(';')).join('\r\n')
  const blob = new Blob([`\uFEFF${body}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function normName(value: string): string {
  return value.toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim()
}

function pickedStorageKey(userId: string): string {
  return `orch.subordinate-tasks.picked:${userId || 'local'}`
}

function readPicked(userId: string): string[] {
  try {
    const raw = localStorage.getItem(pickedStorageKey(userId))
    const parsed = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    const names: string[] = []
    for (const item of parsed) {
      const fio = String(item || '').trim()
      if (fio && !names.includes(fio)) names.push(fio)
    }
    return names
  } catch {
    return []
  }
}

function writePicked(userId: string, names: string[]): void {
  try {
    const key = pickedStorageKey(userId)
    if (names.length === 0) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(names))
  } catch {
    /* переполненное хранилище — выбор останется до закрытия вкладки */
  }
}

function matchesFilter(row: FlatTask, filter: TaskFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'open') return row.kind !== 'done'
  return row.kind === filter
}

export function SubordinateTasksGridTab({ user }: { user: UserProfile }): React.JSX.Element {
  const allowed = canUseSubordinateTasks(user)
  const initial = spanRange()
  const [preset, setPreset] = useState<PeriodPreset>('span')
  const [dateFrom, setDateFrom] = useState(initial.from)
  const [dateTo, setDateTo] = useState(initial.to)
  const [filter, setFilter] = useState<TaskFilter>('all')
  const [picked, setPicked] = useState<string[]>(() => readPicked(user.id))
  const [focusFio, setFocusFio] = useState('')
  const [kpiOpen, setKpiOpen] = useState(false)
  const [nameQuery, setNameQuery] = useState('')
  const [sort, setSort] = useState<SortState>(null)
  const [columnFilters, setColumnFilters] = useState<Partial<Record<TaskColumn, string>>>({})
  const [filterMenu, setFilterMenu] = useState<TaskColumn | null>(null)
  const [staffView, setStaffView] = useState<'people' | 'groups'>('people')
  const [draggingFio, setDraggingFio] = useState('')
  const [groups, setGroups] = useState<StaffGroup[]>(() => readGroups(user.id))
  const [renameId, setRenameId] = useState('')
  const [pickGroupId, setPickGroupId] = useState('')
  const [overId, setOverId] = useState('')
  const [turboTasks, setTurboTasks] = useState<FlatTask[]>([])
  const [turboNote, setTurboNote] = useState('')
  const [people, setPeople] = useState<PersonNode[]>([])
  const [source, setSource] = useState('')
  const [warning, setWarning] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(0)
  const pickedOwner = useRef(user.id)
  const pageSearch = usePageSearchOptional()
  const pageQuery = pageSearch?.query ?? ''

  useEffect(() => {
    if (!allowed || !dateFrom || !dateTo) return
    const id = ++requestId.current
    setLoading(true)
    setError('')
    void api
      .invokeServerTool(
        'onec.erp_subordinate_tasks',
        {
          include_done: true,
          include_self: false,
          limit_per_person: 150,
          date_from: fetchFrom(dateFrom),
          date_to: dateTo
        },
        180_000
      )
      .then((response) => {
        if (id !== requestId.current) return
        if (!response.ok) {
          setError(response.error || 'Не удалось прочитать задачи подчинённых из 1С')
          setPeople([])
          return
        }
        const payload = rec(response.result)
        setPeople(flattenPeople(readPeople(payload.tree)))
        setSource(str(payload.source))
        setWarning(str(payload.docflow_warning))
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false)
      })
  }, [allowed, dateFrom, dateTo])

  useEffect(() => {
    if (pickedOwner.current !== user.id) {
      pickedOwner.current = user.id
      setPicked(readPicked(user.id))
      return
    }
    writePicked(user.id, picked)
  }, [user.id, picked])

  useEffect(() => {
    localStorage.setItem(groupsKey(user.id), JSON.stringify(groups))
  }, [groups, user.id])

  useEffect(() => {
    if (!allowed || picked.length === 0) {
      setTurboTasks([])
      setTurboNote('')
      return
    }
    let cancelled = false
    void api
      .invokeServerTool('turboproject.tasks_for_people', { fios: picked, limit_projects: 8 }, 120_000)
      .then((response) => {
        if (cancelled) return
        if (!response.ok) {
          setTurboTasks([])
          setTurboNote(response.error || '')
          return
        }
        const payload = rec(response.result)
        const rows = Array.isArray(payload.tasks) ? payload.tasks : []
        const flat: FlatTask[] = []
        for (const item of rows) {
          const task = readTask(item)
          if (!task) continue
          const fio = str(rec(item).performer)
          if (!fio) continue
          flat.push({ ...task, fio, position: '', department: '', kind: taskKind(task) })
        }
        setTurboTasks(flat)
        setTurboNote(rows.length === 0 ? '' : '')
      })
      .catch(() => {
        if (!cancelled) setTurboTasks([])
      })
    return () => {
      cancelled = true
    }
  }, [allowed, picked])

  const tasks = useMemo(() => {
    const base = flattenTasks(people)
    const seen = new Set(base.map((row) => `${row.fio}\n${row.number}\n${row.title}`))
    const extra = turboTasks.filter((row) => !seen.has(`${row.fio}\n${row.number}\n${row.title}`))
    return extra.length ? sortTasks(keepCurrentTerm([...base, ...extra])) : base
  }, [people, turboTasks])
  const periodTasks = useMemo(
    () => tasks.filter((row) => taskInPeriod(row, dateFrom, dateTo)),
    [tasks, dateFrom, dateTo]
  )
  const loads = useMemo(() => personLoad(people, periodTasks), [people, periodTasks])

  useEffect(() => {
    if (!people.length) return
    const known = new Set(loads.map((row) => row.fio))
    setPicked((current) => {
      const next = current.filter((fio) => known.has(fio))
      return next.length === current.length ? current : next
    })
  }, [people, loads])
  const pickedSet = useMemo(() => new Set(picked), [picked])
  const scopedTasks = useMemo(
    () => periodTasks.filter((row) => pickedSet.has(row.fio)),
    [periodTasks, pickedSet]
  )
  const kpiTasks = useMemo(
    () => tasks.filter((row) => pickedSet.has(row.fio)),
    [tasks, pickedSet]
  )
  const focusedFio = focusFio && pickedSet.has(focusFio) ? focusFio : ''
  const scopedLoads = useMemo(
    () => loads.filter((row) => pickedSet.has(row.fio)),
    [loads, pickedSet]
  )

  const suggestions = useMemo(() => {
    const needle = normName(nameQuery)
    if (needle.length < 2) return []
    return loads
      .filter((row) => row.fio && !pickedSet.has(row.fio) && normName(row.fio).includes(needle))
      .slice(0, 8)
  }, [loads, nameQuery, pickedSet])

  const visibleLoads = useMemo(
    () =>
      scopedLoads.filter((row) =>
        textMatchesPageSearch(row.fio, pageQuery)
      ),
    [scopedLoads, pageQuery]
  )

  const visibleTasks = useMemo(() => {
    const filtered = scopedTasks.filter((row) => {
      if (focusFio && row.fio !== focusFio) return false
      if (!matchesFilter(row, filter)) return false
      for (const col of TASK_COLUMNS) {
        if (col.filter === false) continue
        const value = columnFilters[col.id]
        if (value && columnText(row, col.id) !== value) return false
      }
      return textMatchesPageSearch(
        `${row.fio} ${row.title} ${row.number} ${row.comment} ${row.approval} ${statusLabel(row)} ${kindLabel(row)} ${originLabel(row)}`,
        pageQuery
      )
    })
    if (!sort) return filtered
    return [...filtered].sort((left, right) => compareTasks(left, right, sort.col, sort.dir))
  }, [scopedTasks, focusFio, filter, pageQuery, columnFilters, sort])

  const filterOptions = useMemo(() => {
    const pool = scopedTasks.filter((row) => {
      if (focusFio && row.fio !== focusFio) return false
      if (!matchesFilter(row, filter)) return false
      return true
    })
    const options = {} as Record<TaskColumn, string[]>
    for (const col of TASK_COLUMNS) {
      options[col.id] = [...new Set(pool.map((row) => columnText(row, col.id)).filter((value) => value && value !== '—'))].sort((a, b) =>
        a.localeCompare(b, 'ru')
      )
    }
    return options
  }, [scopedTasks, focusFio, filter])

  const tiles = useMemo<SpecSummaryTile[]>(() => {
    const focused = focusFio && pickedSet.has(focusFio) ? focusFio : ''
    const tileTasks = focused ? scopedTasks.filter((row) => row.fio === focused) : scopedTasks
    const open = tileTasks.filter((row) => row.kind !== 'done')
    const overdue = tileTasks.filter((row) => row.kind === 'overdue')
    const critical = tileTasks.filter((row) => row.kind === 'critical')
    const done = tileTasks.filter((row) => row.kind === 'done')
    const total = tileTasks.length
    const scopeNote = focused ? `Сотрудник: ${focused}.` : 'Все добавленные сотрудники.'
    return [
      {
        id: 'people',
        label: 'Подчинённые',
        value: String(focused ? 1 : picked.length),
        note: focused ? focused.split(' ')[0] : undefined,
        tone: 'blue',
        icon: 'proj',
        tooltip: focused ? focused : 'Сотрудники, добавленные на эту страницу'
      },
      {
        id: 'open',
        label: 'Открытые',
        value: String(open.length),
        tone: 'neutral',
        icon: 'onec',
        tooltip: `${scopeNote} Задачи, которые ещё не выполнены.`
      },
      {
        id: 'overdue',
        label: 'Просроченные',
        value: String(overdue.length),
        note: `(${percentOf(overdue.length, total)} от всех)`,
        tone: 'red',
        icon: 'day',
        tooltip: `${scopeNote} Открытые задачи, у которых последний срок раньше сегодня. Если срок переносили, считается новая дата. Процент — просроченные от всех задач: ${overdue.length} из ${total}.`
      },
      {
        id: 'critical',
        label: 'Подходит срок',
        value: String(critical.length),
        tone: 'orange',
        icon: 'meet-today',
        tooltip: `${scopeNote} Открытые задачи со сроком сегодня или в ближайшие ${CRITICAL_DAYS} дня. Утверждённый перенос берётся как последний срок той же задачи.`
      },
      {
        id: 'done',
        label: 'Выполненные',
        value: String(done.length),
        note: `(${percentOf(done.length, total)} от всех)`,
        tone: 'green',
        icon: 'meet-done',
        tooltip: `${scopeNote} Процент — выполненные от всех задач: ${done.length} из ${total}.`
      }
    ]
  }, [focusFio, picked.length, pickedSet, scopedTasks])

  const globalSearchEntries = useMemo<GlobalSearchEntry[]>(
    () =>
      visibleTasks.slice(0, 80).map((row, index) => ({
        id: `subordinate_tasks:${row.fio}:${row.number}:${index}`,
        source: 'grid:subordinate_tasks',
        pageKey: 'subordinate_tasks',
        kind: 'entity',
        targetId: row.number || row.title,
        title: row.title,
        subtitle: `${row.fio} · ${formatDue(row.dueAt)}`,
        keywords: [row.number, row.fio, statusLabel(row)]
      })),
    [visibleTasks]
  )
  useRegisterGlobalSearch('grid:subordinate_tasks', globalSearchEntries)

  function toggleSort(col: TaskColumn) {
    setSort((current) => {
      if (current?.col !== col) return { col, dir: 'asc' }
      if (current.dir === 'asc') return { col, dir: 'desc' }
      return null
    })
  }

  function assignGroup(fio: string, groupId: string) {
    setGroups((current) =>
      current.map((group) => ({
        ...group,
        members:
          group.id === groupId
            ? [...group.members.filter((item) => item !== fio), fio]
            : group.members.filter((item) => item !== fio)
      }))
    )
  }

  function createGroup() {
    const id = `g-${Date.now()}`
    setGroups((current) => [...current, { id, name: `Группа ${current.length + 1}`, members: [] }])
    setRenameId(id)
  }

  function renameGroup(id: string, name: string) {
    const next = name.replace(/\s+/g, ' ').trim()
    if (!next) return
    setGroups((current) => current.map((group) => (group.id === id ? { ...group, name: next } : group)))
  }

  function loadRow(row: PersonLoad) {
    return (
      <tr
        key={row.fio}
        draggable
        className={focusFio === row.fio ? 'is-selected' : ''}
        onClick={() => setFocusFio((current) => (current === row.fio ? '' : row.fio))}
        onDragStart={(event) => {
          event.dataTransfer.setData('text/plain', row.fio)
          event.dataTransfer.effectAllowed = 'move'
          setDraggingFio(row.fio)
        }}
        onDragEnd={() => setDraggingFio('')}
      >
        <td>
          <span className="sub-tasks-fio">{row.fio}</span>
        </td>
        <td>{row.open}</td>
        <td className={row.overdue > 0 ? 'is-late' : ''}>{row.overdue}</td>
        <td>{row.done}</td>
        <td>
          <button
            type="button"
            className="sub-tasks-remove"
            aria-label={`Убрать ${row.fio}`}
            onClick={(event) => {
              event.stopPropagation()
              setPicked((current) => current.filter((fio) => fio !== row.fio))
              setFocusFio((current) => (current === row.fio ? '' : current))
            }}
          >
            Убрать
          </button>
        </td>
      </tr>
    )
  }

  function applyPreset(next: PeriodPreset) {
    const range = rangeFor(next)
    setPreset(next)
    setDateFrom(range.from)
    setDateTo(range.to)
  }

  function exportTasks() {
    downloadCsv(
      `задачи-подчиненным-${dateFrom}-${dateTo}.csv`,
      ['Подчиненный', 'Должность', 'Подразделение', 'Номер', 'Задача', 'Срок', 'Статус', 'Согласование', 'Источник'],
      visibleTasks.map((row) => [
        row.fio,
        row.position,
        row.department,
        row.number,
        row.title,
        formatDue(row.dueAt),
        statusLabel(row),
        row.approval,
        originLabel(row)
      ])
    )
  }

  function exportKpi() {
    downloadCsv(
      `kpi-загрузка-подчиненных-${dateFrom}-${dateTo}.csv`,
      [
        'Подчиненный',
        'Должность',
        'Подразделение',
        'Открытые',
        'Просроченные',
        'Критический срок',
        'Выполненные',
        'Выполнено к наступившему сроку',
        'Срок наступил',
        'Доля выполненных к сроку'
      ],
      visibleLoads.map((row) => [
        row.fio,
        row.position,
        row.department,
        String(row.open),
        String(row.overdue),
        String(row.critical),
        String(row.done),
        String(row.doneOfDue),
        String(row.dueReached),
        percentOf(row.doneOfDue, row.dueReached)
      ])
    )
  }

  if (!allowed) {
    return (
      <OrchSlotMain spanAll heavyEmbed>
        <div className="sub-tasks">
          <p className="sub-tasks-empty">Вкладка доступна руководителям подразделений.</p>
        </div>
      </OrchSlotMain>
    )
  }

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <div className="sub-tasks">
        <div className="sub-tasks-toolbar">
          <div className="sub-tasks-presets" role="group" aria-label="Период">
            {(
              [
                ['span', 'Прошлый и текущий'],
                ['month', 'Текущий месяц'],
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
              value={dateFrom}
              onChange={(event) => {
                setPreset('custom')
                setDateFrom(event.target.value)
              }}
            />
          </label>
          <label className="sub-tasks-date">
            по
            <input
              type="date"
              value={dateTo}
              onChange={(event) => {
                setPreset('custom')
                setDateTo(event.target.value)
              }}
            />
          </label>
          <span className="sub-tasks-meta">
            {loading ? 'Загрузка из 1С…' : `${visibleTasks.length} задач · ${formatPeriod(dateFrom, dateTo)}`}
            {source ? ` · ${sourceLabel(source)}` : ''}
          </span>
          <div className="sub-tasks-actions">
            <button type="button" className="sub-tasks-btn" onClick={() => setKpiOpen(true)} disabled={picked.length === 0}>
              Сводка KPI
            </button>
            <button type="button" className="sub-tasks-btn" onClick={exportTasks} disabled={visibleTasks.length === 0}>
              Список задач
            </button>
          </div>
        </div>

        <p className="sub-tasks-lead">
          Здесь задачи, где исполнителем в общей базе 1С указан подчинённый. Свой рабочий стол 1С в этот список не
          входит: каскадную задачу можно контролировать по сроку исполнителя, не держа дубль у себя.
        </p>

        <SpecSummaryTiles
          tiles={tiles}
          activeId={filter === 'all' ? null : filter}
            onSelect={(id) => {
            if (id === 'people') {
              setFilter('all')
              setFocusFio('')
              return
            }
            setFilter((current) => (current === id ? 'all' : (id as TaskFilter)))
          }}
        />

        {error ? <p className="sub-tasks-alert">{error}</p> : null}
        {warning ? <p className="sub-tasks-warn">{warning}</p> : null}
        {turboNote ? <p className="sub-tasks-warn">{turboNote}</p> : null}
        {source === 'stub' ? (
          <p className="sub-tasks-warn">Связь с 1С сейчас недоступна, поэтому список пустой.</p>
        ) : null}

        <div className="sub-tasks-body">
          <section className="sub-tasks-pane" aria-label="Загрузка подчинённых">
            <header className="sub-tasks-pane-head">Подчинённые</header>
            <div className="sub-tasks-add">
              <input
                type="search"
                value={nameQuery}
                placeholder="Добавить по фамилии"
                aria-label="Добавить подчинённого"
                onChange={(event) => setNameQuery(event.target.value)}
              />
              {nameQuery.trim().length >= 2 ? (
                <ul className="sub-tasks-suggest">
                  {suggestions.length === 0 ? (
                    <li className="sub-tasks-suggest-empty">Нет такого подчинённого</li>
                  ) : (
                    suggestions.map((row) => (
                      <li key={row.fio}>
                        <button
                          type="button"
                          onClick={() => {
                            setPicked((current) => (current.includes(row.fio) ? current : [...current, row.fio]))
                            setNameQuery('')
                          }}
                        >
                          {row.fio}
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              ) : null}
            </div>
            <div className="sub-tasks-view-switch">
              <div className="sub-tasks-presets" role="group" aria-label="Вид списка">
                {(
                  [
                    ['people', 'Сотрудники'],
                    ['groups', 'Группы']
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`sub-tasks-preset${staffView === id ? ' is-active' : ''}`}
                    aria-pressed={staffView === id}
                    onClick={() => setStaffView(id)}
                    onDragOver={(event) => {
                      if (!draggingFio) return
                      event.preventDefault()
                      setStaffView(id)
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {staffView === 'groups' ? (
                <button type="button" className="sub-kpi-plus" aria-label="Новая группа" onClick={createGroup}>
                  <Plus size={18} strokeWidth={2.25} />
                </button>
              ) : null}
            </div>
            {staffView === 'people' || draggingFio ? (
              visibleLoads.length === 0 ? (
                <p className="sub-tasks-empty">
                  {loading
                    ? 'Читаем оргструктуру и задачи…'
                    : 'Страница пустая. Найдите подчинённого по фамилии и добавьте его.'}
                </p>
              ) : (
                <table className={`sub-tasks-table sub-tasks-load${staffView === 'people' ? '' : ' is-drag-source'}`}>
                  <thead>
                    <tr>
                      <th>Подчинённый</th>
                      <th>Откр.</th>
                      <th>Проср.</th>
                      <th>Выполн.</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>{visibleLoads.map((row) => loadRow(row))}</tbody>
                </table>
              )
            ) : null}
            {staffView === 'groups' ? (
              groups.length === 0 ? (
              <p className="sub-tasks-empty">Групп пока нет. Нажмите «+», чтобы создать первую.</p>
            ) : (
              groups.map((group) => {
                const members = visibleLoads.filter((row) => group.members.includes(row.fio))
                return (
                  <div
                    key={group.id}
                    className={`sub-tasks-folder${overId === group.id ? ' is-over' : ''}`}
                    onDragOver={(event) => {
                      event.preventDefault()
                      setOverId(group.id)
                    }}
                    onDragLeave={() => setOverId((current) => (current === group.id ? '' : current))}
                    onDrop={(event) => {
                      event.preventDefault()
                      setOverId('')
                      const fio = event.dataTransfer.getData('text/plain')
                      if (fio) assignGroup(fio, group.id)
                    }}
                  >
                    <div className="sub-tasks-folder-head">
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
                        <button type="button" onClick={() => setRenameId(group.id)}>
                          {group.name}
                        </button>
                      )}
                      <span>{members.length}</span>
                      <button
                        type="button"
                        className="sub-kpi-plus"
                        aria-label={`Добавить в ${group.name}`}
                        aria-expanded={pickGroupId === group.id}
                        onClick={() => setPickGroupId((current) => (current === group.id ? '' : group.id))}
                      >
                        <Plus size={18} strokeWidth={2.25} />
                      </button>
                      <button
                        type="button"
                        className="sub-tasks-remove"
                        onClick={() => setGroups((current) => current.filter((item) => item.id !== group.id))}
                      >
                        Удалить
                      </button>
                    </div>
                    {pickGroupId === group.id ? (
                      <ul className="sub-tasks-suggest sub-tasks-group-pick">
                        {loads.filter((row) => row.fio && !group.members.includes(row.fio)).length === 0 ? (
                          <li className="sub-tasks-suggest-empty">Все подчинённые уже в группе</li>
                        ) : (
                          loads
                            .filter((row) => row.fio && !group.members.includes(row.fio))
                            .map((row) => (
                              <li key={row.fio}>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setPicked((current) => (current.includes(row.fio) ? current : [...current, row.fio]))
                                    assignGroup(row.fio, group.id)
                                    setPickGroupId('')
                                  }}
                                >
                                  {row.fio}
                                </button>
                              </li>
                            ))
                        )}
                      </ul>
                    ) : null}
                    <table className="sub-tasks-table sub-tasks-load">
                      <thead>
                        <tr>
                          <th>Подчинённый</th>
                          <th>Откр.</th>
                          <th>Проср.</th>
                          <th>Выполн.</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {members.length === 0 ? (
                          <tr>
                            <td colSpan={5}>В группе никого нет. Нажмите «+» и выберите сотрудника.</td>
                          </tr>
                        ) : (
                          members.map((row) => loadRow(row))
                        )}
                      </tbody>
                    </table>
                  </div>
                )
              })
            )
            ) : null}
          </section>

          <section className="sub-tasks-pane" aria-label="Задачи подчинённых">
            <header className="sub-tasks-pane-head">
              Задачи
              <span className="sub-tasks-legend">
                <i className="is-overdue" /> просроченные
                <i className="is-critical" /> подходит срок
                <i className="is-open" /> поставленные
              </span>
            </header>
            {picked.length === 0 ? (
              <p className="sub-tasks-empty">Добавьте подчинённых слева — здесь появятся только их задачи.</p>
            ) : visibleTasks.length === 0 ? (
              <p className="sub-tasks-empty">
                {loading ? 'Читаем задачи…' : 'У выбранных сотрудников в этом периоде и фильтре задач нет.'}
              </p>
            ) : (
              <table className="sub-tasks-table">
                <thead>
                  <tr>
                    {TASK_COLUMNS.map((col) => {
                      const active = sort?.col === col.id
                      const filtered = Boolean(columnFilters[col.id])
                      return (
                        <th key={col.id} className={filtered ? 'is-filtered' : ''}>
                          <span className="sub-tasks-th">
                            <span>{col.label}</span>
                            {filtered ? <small>{columnFilters[col.id]}</small> : null}
                            <span className="sub-tasks-th-tools">
                              {col.filter === false ? null : (
                              <button
                                type="button"
                                className={filtered ? 'is-active' : ''}
                                aria-label={`Фильтр: ${col.label}`}
                                onClick={() => setFilterMenu((current) => (current === col.id ? null : col.id))}
                              >
                                <Filter size={13} aria-hidden />
                              </button>
                              )}
                              <button
                                type="button"
                                className={active ? 'is-active' : ''}
                                aria-label={`Сортировка: ${col.label}`}
                                onClick={() => toggleSort(col.id)}
                              >
                                {active && sort?.dir === 'desc' ? <ArrowDown size={13} /> : <ArrowUp size={13} />}
                              </button>
                            </span>
                          </span>
                          {col.filter !== false && filterMenu === col.id ? (
                            <div className="sub-tasks-filter">
                              <button
                                type="button"
                                className={!columnFilters[col.id] ? 'is-active' : ''}
                                onClick={() => {
                                  setColumnFilters((current) => ({ ...current, [col.id]: '' }))
                                  setFilterMenu(null)
                                }}
                              >
                                Все
                              </button>
                              {filterOptions[col.id].map((option) => (
                                <button
                                  key={option}
                                  type="button"
                                  className={columnFilters[col.id] === option ? 'is-active' : ''}
                                  onClick={() => {
                                    setColumnFilters((current) => ({ ...current, [col.id]: option }))
                                    setFilterMenu(null)
                                  }}
                                >
                                  {option}
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {visibleTasks.map((row, index) => (
                    <tr key={`${row.fio}:${row.number}:${row.title}:${index}`} className={`is-${row.kind}`}>
                      <td>
                        <span className="sub-tasks-fio">{row.fio || '—'}</span>
                      </td>
                      <td>
                        <span className="sub-tasks-title" title={row.comment || row.title}>
                          {row.title}
                        </span>
                        {row.approval ? <span className="sub-tasks-role">{row.approval}</span> : null}
                      </td>
                      <td>{kindLabel(row)}</td>
                      <td>{formatDue(row.dueAt)}</td>
                      <td>{statusLabel(row)}</td>
                      <td>{originLabel(row)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
      {kpiOpen ? (
        <SubordinateKpiDialog
          tasks={kpiTasks}
          people={picked}
          directory={loads.map((row) => row.fio)}
          ownerId={user.id}
          onAddPerson={(fio) => setPicked((current) => (current.includes(fio) ? current : [...current, fio]))}
          dateFrom={dateFrom}
          dateTo={dateTo}
          person={focusedFio}
          onClose={() => setKpiOpen(false)}
          onDownload={exportKpi}
          onApply={(slice) => {
            setPreset('custom')
            if (slice.from) setDateFrom(slice.from)
            if (slice.to) setDateTo(slice.to)
            setFocusFio(slice.person)
            setFilter(slice.status)
            setKpiOpen(false)
          }}
        />
      ) : null}
    </OrchSlotMain>
  )
}
