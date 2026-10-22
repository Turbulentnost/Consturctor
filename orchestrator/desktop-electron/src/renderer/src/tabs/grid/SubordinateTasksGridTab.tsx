import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Filter, Plus, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import { canUseSubordinateTasks } from '../../extensions/extensionAccess'
import { OrchSlotMain } from '../../layout/GridSlots'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'
import { textMatchesPageSearch, usePageSearchOptional } from '../../layout/pageSearchContext'
import { onecGatewayInvokeArgs } from '../../workplace/userContext'
import { SpecSummaryTiles } from '../../workplace/specV04Components'
import { SubordinateKpiDialog } from './SubordinateKpiDialog'
import type { SubordinateKpiNav } from '../../workplace/workplaceNav'
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

type SchemeLayout = {
  order: string[]
  parent: Record<string, string>
  /** Люди, которых убрали со схемы. Повторная загрузка из 1С их не возвращает. */
  removed: string[]
}

type SchemeDrop = 'before' | 'after' | 'inside'

function orgRoots(nodes: PersonNode[]): PersonNode[] {
  const nested = new Set<string>()
  const mark = (list: PersonNode[]) => {
    for (const node of list) {
      for (const child of node.subordinates) nested.add(child.fio)
      mark(node.subordinates)
    }
  }
  mark(nodes)
  const seen = new Set<string>()
  return nodes.filter((node) => {
    if (!node.fio || nested.has(node.fio) || seen.has(node.fio)) return false
    seen.add(node.fio)
    return true
  })
}

function cardGlow(load: PersonLoad | undefined): 'overdue' | 'critical' | 'open' | 'done' | 'idle' {
  if (!load) return 'idle'
  if (load.overdue > 0) return 'overdue'
  if (load.critical > 0) return 'critical'
  if (load.open > 0) return 'open'
  if (load.done > 0) return 'done'
  return 'idle'
}

function suggestionRank(row: PersonLoad, needle: string): number {
  const fio = normName(row.fio)
  const position = normName(row.position)
  const department = normName(row.department)
  const parts = fio.split(' ').filter(Boolean)
  if (parts.some((part) => part.startsWith(needle)) || fio.startsWith(needle)) return 0
  if (fio.includes(needle)) return 1
  if (position.includes(needle)) return 2
  if (department.includes(needle)) return 3
  return 9
}

function buildSchemeFromOrg(roots: PersonNode[]): SchemeLayout {
  const parent: Record<string, string> = {}
  const order: string[] = []
  const seen = new Set<string>()
  const walk = (nodes: PersonNode[], parentFio: string) => {
    for (const node of nodes) {
      if (!node.fio || seen.has(node.fio)) continue
      seen.add(node.fio)
      parent[node.fio] = parentFio
      order.push(node.fio)
      walk(node.subordinates, node.fio)
    }
  }
  walk(roots, '')
  return { order, parent, removed: [] }
}

function schemeStorageKey(userId: string): string {
  return `orch.subordinate-tasks.scheme:${userId || 'local'}`
}

function readScheme(userId: string): SchemeLayout | null {
  try {
    const raw = localStorage.getItem(schemeStorageKey(userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as { order?: unknown; parent?: unknown }
    if (!Array.isArray(parsed.order) || !parsed.parent || typeof parsed.parent !== 'object') return null
    const order: string[] = []
    for (const item of parsed.order) {
      const fio = String(item || '').trim()
      if (fio && !order.includes(fio)) order.push(fio)
    }
    const parent: Record<string, string> = {}
    const stored = parsed.parent as Record<string, unknown>
    for (const fio of order) {
      const value = stored[fio]
      parent[fio] = typeof value === 'string' ? value.trim() : ''
    }
    const removed: string[] = []
    const rawRemoved = (parsed as { removed?: unknown }).removed
    if (Array.isArray(rawRemoved)) {
      for (const item of rawRemoved) {
        const fio = String(item || '').trim()
        if (fio && !order.includes(fio) && !removed.includes(fio)) removed.push(fio)
      }
    }
    return { order, parent, removed }
  } catch {
    return null
  }
}

function writeScheme(userId: string, layout: SchemeLayout | null): void {
  try {
    const key = schemeStorageKey(userId)
    if (!layout) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(layout))
  } catch {
    /* переполненное хранилище — схема останется до закрытия вкладки */
  }
}

function personIsUnder(layout: SchemeLayout, fio: string, ancestor: string): boolean {
  let current = layout.parent[fio] || ''
  const seen = new Set<string>()
  while (current) {
    if (current === ancestor) return true
    if (seen.has(current)) return false
    seen.add(current)
    current = layout.parent[current] || ''
  }
  return false
}

function lastInSubtree(order: string[], parent: Record<string, string>, root: string): number {
  const inside = (fio: string) => personIsUnder({ order, parent }, fio, root)
  let last = order.indexOf(root)
  for (let index = last + 1; index < order.length; index += 1) {
    if (inside(order[index])) last = index
  }
  return last
}

function relocatePerson(layout: SchemeLayout, fio: string, target: string, place: SchemeDrop): SchemeLayout | null {
  if (!fio || !target || fio === target || !layout.order.includes(fio) || !layout.order.includes(target)) return null
  const nextParentFio = place === 'inside' ? target : layout.parent[target] || ''
  if (nextParentFio === fio || (nextParentFio && personIsUnder(layout, nextParentFio, fio))) return null
  const order = layout.order.filter((item) => item !== fio)
  const parent = { ...layout.parent, [fio]: nextParentFio }
  let index = order.indexOf(target)
  if (index < 0) return null
  if (place === 'after') index += 1
  if (place === 'inside') index = lastInSubtree(order, parent, target) + 1
  order.splice(index, 0, fio)
  return { order, parent, removed: layout.removed }
}

function schemeToTree(layout: SchemeLayout, directory: Map<string, PersonNode>): PersonNode[] {
  const children = new Map<string, string[]>()
  const present = new Set(layout.order)
  for (const fio of layout.order) {
    const declared = layout.parent[fio] || ''
    const key = declared && present.has(declared) ? declared : ''
    const list = children.get(key) || []
    list.push(fio)
    children.set(key, list)
  }
  const build = (fio: string, stack: Set<string>): PersonNode => {
    const source = directory.get(fio)
    const next = new Set(stack)
    next.add(fio)
    const kids = (children.get(fio) || [])
      .filter((child) => !next.has(child))
      .map((child) => build(child, next))
    return {
      fio,
      position: source?.position || '',
      department: source?.department || '',
      level: stack.size + 1,
      tasks: source?.tasks || [],
      subordinates: kids
    }
  }
  return (children.get('') || []).map((fio) => build(fio, new Set()))
}

type SchemeRow = {
  id: string
  name: string
  parentFio: string
  members: PersonNode[]
}

function branchPeople(node: PersonNode): PersonNode[] {
  const people: PersonNode[] = []
  const walk = (current: PersonNode) => {
    if (current.fio) people.push(current)
    for (const child of current.subordinates) walk(child)
  }
  walk(node)
  return people
}

function schemeRows(roots: PersonNode[]): SchemeRow[] {
  return roots
    .filter((node) => node.fio)
    .map((node, index) => ({
      id: `scheme-manager-${node.fio}`,
      name: `Группа ${index + 1}`,
      parentFio: node.fio,
      members: branchPeople(node)
    }))
}

function personInitials(fio: string): string {
  const parts = fio.split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase()
}

function OrgTree({
  roots,
  loads,
  focusFio,
  onSelect,
  onRemove,
  onMove
}: {
  roots: PersonNode[]
  loads: Map<string, PersonLoad>
  focusFio: string
  onSelect: (fio: string) => void
  onRemove: (fio: string) => void
  onMove: (fio: string, target: string, place: SchemeDrop) => void
}): React.JSX.Element {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set())
  const [dragFio, setDragFio] = useState('')
  const dragRef = useRef('')
  const [dropHint, setDropHint] = useState<{ fio: string; place: SchemeDrop } | null>(null)
  const suppressClick = useRef(false)

  function dropPlace(event: React.DragEvent<HTMLElement>): SchemeDrop {
    const rect = event.currentTarget.getBoundingClientRect()
    const offset = event.clientY - rect.top
    if (offset < rect.height * 0.28) return 'before'
    if (offset > rect.height * 0.72) return 'after'
    return 'inside'
  }

  function toggle(fio: string) {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(fio)) next.delete(fio)
      else next.add(fio)
      return next
    })
  }

  function branch(node: PersonNode): React.JSX.Element {
    const load = loads.get(node.fio)
    const glow = cardGlow(load)
    const role = node.position || node.department
    const kids = node.subordinates
    const open = !collapsed.has(node.fio)
    const hint = dropHint?.fio === node.fio ? dropHint.place : ''
    return (
      <li key={node.fio || role}>
        <div
          className={`sub-org-card is-${glow}${focusFio === node.fio ? ' is-selected' : ''}${dragFio === node.fio ? ' is-dragging' : ''}${hint ? ` is-drop-${hint}` : ''}`}
          draggable
          onClick={() => {
            if (suppressClick.current) {
              suppressClick.current = false
              return
            }
            onSelect(node.fio)
          }}
          onDragStart={(event) => {
            suppressClick.current = true
            event.dataTransfer.setData('text/plain', node.fio)
            event.dataTransfer.effectAllowed = 'move'
            dragRef.current = node.fio
            setDragFio(node.fio)
          }}
          onDragEnd={() => {
            dragRef.current = ''
            setDragFio('')
            setDropHint(null)
          }}
          onDragOver={(event) => {
            const moving = dragRef.current
            if (!moving || moving === node.fio) return
            event.preventDefault()
            event.stopPropagation()
            event.dataTransfer.dropEffect = 'move'
            const place = dropPlace(event)
            setDropHint((current) => (current?.fio === node.fio && current.place === place ? current : { fio: node.fio, place }))
          }}
          onDrop={(event) => {
            event.preventDefault()
            event.stopPropagation()
            const fio = event.dataTransfer.getData('text/plain') || dragRef.current
            const place = dropPlace(event)
            if (fio && fio !== node.fio) {
              if (place === 'inside') {
                setCollapsed((current) => {
                  if (!current.has(node.fio)) return current
                  const next = new Set(current)
                  next.delete(node.fio)
                  return next
                })
              }
              onMove(fio, node.fio, place)
            }
            dragRef.current = ''
            setDragFio('')
            setDropHint(null)
          }}
        >
          <span className={`sub-org-avatar is-${glow}`}>{personInitials(node.fio)}</span>
          <strong>{node.fio}</strong>
          {role ? <em>{role}</em> : null}
          <span className="sub-org-pills">
            {load && load.overdue > 0 ? <i className="is-late">{load.overdue} проср.</i> : null}
            {load && load.critical > 0 ? <i className="is-soon">{load.critical} срок</i> : null}
            {load && load.open > 0 ? <i>{load.open} откр.</i> : null}
            {load && load.open === 0 && load.done > 0 ? <i className="is-done">{load.done} выполн.</i> : null}
          </span>
          <button
            type="button"
            className="sub-org-remove"
            aria-label={`Убрать ${node.fio}`}
            draggable={false}
            onMouseDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onRemove(node.fio)
            }}
          >
            ×
          </button>
          {kids.length > 0 ? (
            <button
              type="button"
              className="sub-org-fold"
              aria-label={open ? 'Свернуть ветку' : 'Развернуть ветку'}
              aria-expanded={open}
              draggable={false}
              onMouseDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation()
                toggle(node.fio)
              }}
            >
              {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <span>{kids.length}</span>
            </button>
          ) : null}
        </div>
        {open && kids.length > 0 ? <ul>{kids.map((child) => branch(child))}</ul> : null}
      </li>
    )
  }

  return (
    <div className="sub-org-board" aria-label="Иерархия подчинённых">
      <ul className="sub-org-tree">{roots.map((node) => branch(node))}</ul>
    </div>
  )
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

function foldUnit(value: string): string {
  return value.toLowerCase().replace(/ё/g, 'е')
}

function textHitsUnit(text: string, unit: string): boolean {
  const query = foldUnit(unit)
  if (!query) return true
  const hay = foldUnit(text)
  if (hay.includes(query)) return true
  return /искусствен|сектор ии|\bии\b/.test(query) && /искусствен/.test(hay)
}

export function SubordinateTasksGridTab({
  user,
  navKpi = null
}: {
  user: UserProfile
  navKpi?: SubordinateKpiNav | null
}): React.JSX.Element {
  const allowed = canUseSubordinateTasks(user)
  const initial = spanRange()
  const [preset, setPreset] = useState<PeriodPreset>('span')
  const [dateFrom, setDateFrom] = useState(initial.from)
  const [dateTo, setDateTo] = useState(initial.to)
  const [filter, setFilter] = useState<TaskFilter>('all')
  const [picked, setPicked] = useState<string[]>(() => readPicked(user.id))
  const [focusFio, setFocusFio] = useState('')
  const [focusGroupId, setFocusGroupId] = useState('')
  const [kpiOpen, setKpiOpen] = useState(false)
  const [kpiMode, setKpiMode] = useState<'all' | 'groups' | 'people'>('all')
  const appliedKpi = useRef('')
  const [nameQuery, setNameQuery] = useState('')
  const [sort, setSort] = useState<SortState>(null)
  const [columnFilters, setColumnFilters] = useState<Partial<Record<TaskColumn, string>>>({})
  const [filterMenu, setFilterMenu] = useState<TaskColumn | null>(null)
  const [staffView, setStaffView] = useState<'scheme' | 'people' | 'groups'>('scheme')
  const [draggingFio, setDraggingFio] = useState('')
  const [groups, setGroups] = useState<StaffGroup[]>(() => readGroups(user.id))
  const [renameId, setRenameId] = useState('')
  const [pickGroupId, setPickGroupId] = useState('')
  const [overId, setOverId] = useState('')
  const [turboTasks, setTurboTasks] = useState<FlatTask[]>([])
  const [turboNote, setTurboNote] = useState('')
  const [people, setPeople] = useState<PersonNode[]>([])
  const [scheme, setScheme] = useState<SchemeLayout | null>(() => readScheme(user.id))
  const [source, setSource] = useState('')
  const [warning, setWarning] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(0)
  const pickedOwner = useRef(user.id)
  const schemeOwner = useRef(user.id)
  const pageSearch = usePageSearchOptional()
  const pageQuery = pageSearch?.query ?? ''

  useEffect(() => {
    if (!navKpi || !people.length) return
    const token = `${navKpi.mode}|${navKpi.unit}|${people.map((person) => person.fio).join('|')}`
    if (appliedKpi.current === token) return
    appliedKpi.current = token
    const named = groups.find((group) => textHitsUnit(group.name, navKpi.unit))
    const names = named
      ? named.members
      : people.filter((person) => textHitsUnit(`${person.department} ${person.position}`, navKpi.unit)).map((person) => person.fio)
    if (names.length) setPicked(names)
    else if (navKpi.unit) setWarning(`Среди подчинённых нет подразделения «${navKpi.unit}».`)
    setStaffView('people')
    setKpiMode(navKpi.mode)
    setKpiOpen(true)
  }, [groups, navKpi, people])

  useEffect(() => {
    if (!allowed || !dateFrom || !dateTo) return
    const id = ++requestId.current
    setLoading(true)
    setError('')
    void api
      .invokeServerTool(
        'onec.erp_subordinate_tasks',
        onecGatewayInvokeArgs(user, {
          include_done: true,
          include_self: false,
          limit_per_person: 150,
          date_from: fetchFrom(dateFrom),
          date_to: dateTo
        }),
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
  }, [allowed, dateFrom, dateTo, user])

  useEffect(() => {
    if (pickedOwner.current !== user.id) {
      pickedOwner.current = user.id
      setPicked(readPicked(user.id))
      return
    }
    writePicked(user.id, picked)
  }, [user.id, picked])

  useEffect(() => {
    if (schemeOwner.current !== user.id) {
      schemeOwner.current = user.id
      setScheme(readScheme(user.id))
      return
    }
    writeScheme(user.id, scheme)
  }, [user.id, scheme])

  useEffect(() => {
    if (!people.length) return
    const org = buildSchemeFromOrg(orgRoots(people))
    setScheme((current) => {
      if (!current) return org
      const removed = new Set(current.removed)
      const have = new Set(current.order)
      const missing = org.order.filter((fio) => fio && !have.has(fio) && !removed.has(fio))
      if (!missing.length) return current
      const order = [...current.order]
      const parent = { ...current.parent }
      for (const fio of missing) {
        order.push(fio)
        have.add(fio)
      }
      for (const fio of missing) {
        const orgParent = org.parent[fio] || ''
        parent[fio] = orgParent && have.has(orgParent) ? orgParent : ''
      }
      return { order, parent, removed: current.removed }
    })
  }, [people])

  useEffect(() => {
    localStorage.setItem(groupsKey(user.id), JSON.stringify(groups))
  }, [groups, user.id])

  const turboFios = useMemo(
    () => [...new Set(people.map((person) => person.fio).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru')),
    [people]
  )

  useEffect(() => {
    if (!allowed || turboFios.length === 0) {
      setTurboTasks([])
      setTurboNote('')
      return
    }
    let cancelled = false
    setTurboNote('Читаю задачи Турбопроекта…')
    const chunks: string[][] = []
    for (let index = 0; index < turboFios.length; index += 40) chunks.push(turboFios.slice(index, index + 40))
    void Promise.all(
      chunks.map((fios) =>
        api.invokeServerTool('turboproject.tasks_for_people', { fios, limit_projects: 24 }, 120_000)
      )
    )
      .then((responses) => {
        if (cancelled) return
        const failed = responses.find((response) => !response.ok)
        if (failed && responses.every((response) => !response.ok)) {
          setTurboTasks([])
          setTurboNote(failed.error || 'Не удалось прочитать задачи Турбопроекта')
          return
        }
        const byFio = new Map(people.map((person) => [person.fio, person]))
        const flat: FlatTask[] = []
        let scanned = 0
        let matched = 0
        for (const response of responses) {
          if (!response.ok) continue
          const payload = rec(response.result)
          scanned += Number(payload.projects_scanned) || 0
          matched += Number(payload.matched_projects_count) || 0
          const rows = Array.isArray(payload.tasks) ? payload.tasks : []
          for (const item of rows) {
            const task = readTask(item)
            if (!task) continue
            const fio = str(rec(item).performer)
            if (!fio) continue
            const known = byFio.get(fio)
            flat.push({
              ...task,
              fio,
              position: known?.position || '',
              department: known?.department || '',
              kind: taskKind(task)
            })
          }
        }
        setTurboTasks(flat)
        setTurboNote(
          matched > scanned
            ? `Турбопроект: открыто ${scanned} из ${matched} проектов, где есть эти сотрудники.`
            : ''
        )
      })
      .catch(() => {
        if (!cancelled) {
          setTurboTasks([])
          setTurboNote('Не удалось прочитать задачи Турбопроекта')
        }
      })
    return () => {
      cancelled = true
    }
  }, [allowed, turboFios])

  const tasks = useMemo(() => {
    const base = flattenTasks(people)
    const seen = new Set(base.map((row) => `${row.fio}\n${row.source}\n${row.number}\n${row.title}`))
    const extra = turboTasks.filter((row) => !seen.has(`${row.fio}\n${row.source}\n${row.number}\n${row.title}`))
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
  const focusedFio = focusFio && pickedSet.has(focusFio) ? focusFio : ''

  const suggestions = useMemo(() => {
    const needle = normName(nameQuery)
    if (needle.length < 2) return []
    return loads
      .filter((row) => row.fio && !pickedSet.has(row.fio) && suggestionRank(row, needle) < 9)
      .sort((left, right) => suggestionRank(left, needle) - suggestionRank(right, needle) || left.level - right.level || left.fio.localeCompare(right.fio, 'ru'))
      .slice(0, 10)
  }, [loads, nameQuery, pickedSet])
  const loadByFio = useMemo(() => new Map(loads.map((row) => [row.fio, row])), [loads])
  const peopleByFio = useMemo(() => new Map(people.map((person) => [person.fio, person])), [people])
  const orgLayout = useMemo(() => buildSchemeFromOrg(orgRoots(people)), [people])
  const activeScheme = scheme ?? orgLayout
  const schemeFios = useMemo(() => new Set(activeScheme.order), [activeScheme])
  const schemeRoots = useMemo(() => schemeToTree(activeScheme, peopleByFio), [activeScheme, peopleByFio])
  const derivedRows = useMemo(() => schemeRows(schemeRoots), [schemeRoots])

  useEffect(() => {
    if (!people.length) return
    setGroups(
      derivedRows.map((row) => ({
        id: row.id,
        name: row.name,
        members: row.members.map((node) => node.fio)
      }))
    )
  }, [derivedRows, people.length])
  const focusedTasks = useMemo(
    () => (focusFio ? periodTasks.filter((row) => row.fio === focusFio && matchesFilter(row, filter)) : []),
    [periodTasks, focusFio, filter]
  )
  const focusedPerson = focusFio ? peopleByFio.get(focusFio) : undefined
  const schemeSuggestions = useMemo(() => {
    const needle = normName(nameQuery)
    if (needle.length < 2) return []
    return loads
      .filter((row) => row.fio && !schemeFios.has(row.fio) && suggestionRank(row, needle) < 9)
      .sort((left, right) => suggestionRank(left, needle) - suggestionRank(right, needle) || left.level - right.level || left.fio.localeCompare(right.fio, 'ru'))
      .slice(0, 10)
  }, [loads, nameQuery, schemeFios])

  const visibleLoads = useMemo(() => {
    const rows = activeScheme.order.map((fio) => {
      const known = loadByFio.get(fio)
      if (known) return known
      const person = peopleByFio.get(fio)
      return {
        fio,
        position: person?.position || '',
        department: person?.department || '',
        level: person?.level || 1,
        open: 0,
        overdue: 0,
        critical: 0,
        done: 0,
        doneOfDue: 0,
        dueReached: 0
      }
    })
    return rows.filter((row) => textMatchesPageSearch(row.fio, pageQuery))
  }, [activeScheme, loadByFio, peopleByFio, pageQuery])

  const focusGroup = focusGroupId ? groups.find((group) => group.id === focusGroupId) : undefined
  const allFios = useMemo(() => new Set(people.map((person) => person.fio).filter(Boolean)), [people])
  const taskRoster = useMemo(() => {
    if (focusGroup) return new Set(focusGroup.members)
    if (focusFio) return new Set([focusFio])
    return allFios
  }, [focusGroup, focusFio, allFios])
  const visibleTasks = useMemo(() => {
    const filtered = periodTasks.filter((row) => {
      if (!taskRoster.has(row.fio)) return false
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
  }, [periodTasks, taskRoster, filter, pageQuery, columnFilters, sort])

  const filterOptions = useMemo(() => {
    const pool = periodTasks.filter((row) => {
      if (!taskRoster.has(row.fio)) return false
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
  }, [periodTasks, taskRoster, filter])

  const tiles = useMemo<SpecSummaryTile[]>(() => {
    const focused = !focusGroup && focusFio ? focusFio : ''
    const tileTasks = periodTasks.filter((row) => taskRoster.has(row.fio))
    const open = tileTasks.filter((row) => row.kind !== 'done')
    const overdue = tileTasks.filter((row) => row.kind === 'overdue')
    const critical = tileTasks.filter((row) => row.kind === 'critical')
    const done = tileTasks.filter((row) => row.kind === 'done')
    const total = tileTasks.length
    const scopeNote = focusGroup
      ? `${focusGroup.name}.`
      : focused
        ? `Сотрудник: ${focused}.`
        : 'Все подчинённые из оргструктуры.'
    return [
      {
        id: 'people',
        label: 'Подчинённые',
        value: String(taskRoster.size),
        note: focusGroup ? focusGroup.name : focused ? focused.split(' ')[0] : undefined,
        tone: 'blue',
        icon: 'proj',
        tooltip: focusGroup ? focusGroup.name : focused ? focused : 'Подчинённые из оргструктуры'
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
  }, [focusFio, focusGroup, periodTasks, taskRoster])

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

  function selectPerson(fio: string) {
    if (!fio) return
    setFocusGroupId('')
    setFocusFio((current) => (current === fio ? '' : fio))
    setPicked((current) => (current.includes(fio) ? current : [...current, fio]))
  }

  function selectGroup(id: string) {
    const group = groups.find((item) => item.id === id)
    if (!group) return
    setFocusFio('')
    setFocusGroupId((current) => (current === id ? '' : id))
    setPicked((current) => {
      const next = [...current]
      for (const fio of group.members) {
        if (fio && !next.includes(fio)) next.push(fio)
      }
      return next.length === current.length ? current : next
    })
  }

  function addPerson(fio: string) {
    if (!fio) return
    setPicked((current) => (current.includes(fio) ? current : [...current, fio]))
    setScheme((current) => {
      const base = current ?? buildSchemeFromOrg(orgRoots(people))
      const removed = base.removed.filter((item) => item !== fio)
      if (base.order.includes(fio)) return removed.length === base.removed.length ? current : { ...base, removed }
      return { order: [...base.order, fio], parent: { ...base.parent, [fio]: '' }, removed }
    })
  }

  function removePerson(fio: string) {
    if (!fio) return
    setPicked((current) => current.filter((item) => item !== fio))
    setFocusFio((current) => (current === fio ? '' : current))
    setScheme((current) => {
      const base = current ?? buildSchemeFromOrg(orgRoots(people))
      const removed = base.removed.includes(fio) ? base.removed : [...base.removed, fio]
      if (!base.order.includes(fio)) return { ...base, removed }
      const parentFio = base.parent[fio] || ''
      const parent = { ...base.parent }
      delete parent[fio]
      for (const [child, owner] of Object.entries(parent)) {
        if (owner === fio) parent[child] = parentFio
      }
      return { order: base.order.filter((item) => item !== fio), parent, removed }
    })
  }

  function movePerson(fio: string, target: string, place: SchemeDrop) {
    setScheme((current) => {
      const base = current ?? buildSchemeFromOrg(orgRoots(people))
      return relocatePerson(base, fio, target, place) ?? current
    })
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
              removePerson(row.fio)
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
            <button
              type="button"
              className="sub-tasks-btn"
              onClick={() => {
                setKpiMode('all')
                setKpiOpen(true)
              }}
              disabled={picked.length === 0}
            >
              Сводка KPI
            </button>
            <button type="button" className="sub-tasks-btn" onClick={exportTasks} disabled={visibleTasks.length === 0}>
              Список задач
            </button>
          </div>
        </div>

        <p className="sub-tasks-lead">
          Здесь задачи подчинённых из 1С и Турбопроекта. Свой рабочий стол 1С в этот список не
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

        <div className={`sub-tasks-body${staffView === 'scheme' ? ' is-scheme' : ''}`}>
          <section className="sub-tasks-pane" aria-label="Загрузка подчинённых">
            <header className="sub-tasks-pane-head">
              Подчинённые
              {staffView === 'scheme' ? (
                <span className="sub-tasks-legend">
                  <i className="is-overdue" /> просрочка
                  <i className="is-critical" /> срок
                  <i className="is-open" /> открытые
                </span>
              ) : null}
            </header>
            <div className="sub-tasks-add">
              <input
                type="search"
                value={nameQuery}
                placeholder="Фамилия, должность или отдел"
                aria-label="Добавить подчинённого"
                onChange={(event) => setNameQuery(event.target.value)}
              />
              {nameQuery.trim().length >= 2 ? (
                <ul className="sub-tasks-suggest">
                  {(staffView === 'groups' ? suggestions : schemeSuggestions).length === 0 ? (
                    <li className="sub-tasks-suggest-empty">
                      {staffView !== 'groups' &&
                      loads.some((row) => schemeFios.has(row.fio) && suggestionRank(row, normName(nameQuery)) < 9)
                        ? 'Уже в списке'
                        : 'Нет такого подчинённого'}
                    </li>
                  ) : (
                    (staffView === 'groups' ? suggestions : schemeSuggestions).map((row) => (
                      <li key={row.fio}>
                        <button
                          type="button"
                          onClick={() => {
                            addPerson(row.fio)
                            setNameQuery('')
                          }}
                        >
                          <span>{row.fio}</span>
                          {[row.position, row.department].filter(Boolean).length > 0 ? (
                            <small>{[row.position, row.department].filter(Boolean).join(' · ')}</small>
                          ) : null}
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
                    ['scheme', 'Схема'],
                    ['people', 'Сотрудники'],
                    ['groups', 'Группы']
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={`sub-tasks-preset${staffView === id ? ' is-active' : ''}`}
                    aria-pressed={staffView === id}
                    onClick={() => {
                      setStaffView(id)
                      if (id !== 'groups') setFocusGroupId('')
                      if (id === 'scheme') setFocusFio('')
                    }}
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
              {staffView === 'scheme' && scheme ? (
                <button
                  type="button"
                  className="sub-tasks-remove"
                  title="Вернуть иерархию из оргструктуры"
                  onClick={() => setScheme(null)}
                >
                  Сбросить
                </button>
              ) : null}
            </div>
            {staffView === 'scheme' ? (
              <>
                <p className="sub-tree-hint">
                  Перетащите карточку на сотрудника, чтобы подчинить, или к краю карточки, чтобы поставить рядом.
                </p>
                <div className="sub-org-field">
                  {schemeRoots.length === 0 ? (
                    <p className="sub-tasks-empty">
                      {loading ? 'Читаем оргструктуру и задачи…' : 'На схеме никого нет. Добавьте сотрудника по фамилии.'}
                    </p>
                  ) : (
                    <OrgTree
                      roots={schemeRoots}
                      loads={loadByFio}
                      focusFio={focusFio}
                      onSelect={selectPerson}
                      onRemove={removePerson}
                      onMove={movePerson}
                    />
                  )}
                </div>
              </>
            ) : null}
            {staffView === 'people' || draggingFio ? (
              visibleLoads.length === 0 ? (
                <p className="sub-tasks-empty">
                  {loading
                    ? 'Читаем оргструктуру и задачи…'
                    : 'Список пуст. Добавьте сотрудника по фамилии — он появится и на схеме.'}
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
                const memberByFio = new Map(visibleLoads.map((row) => [row.fio, row]))
                const members = group.members.flatMap((fio) => {
                  const row = memberByFio.get(fio)
                  return row ? [row] : []
                })
                return (
                  <div
                    key={group.id}
                    className={`sub-tasks-folder${overId === group.id ? ' is-over' : ''}${focusGroupId === group.id ? ' is-selected' : ''}`}
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
                        <button
                          type="button"
                          title="Показать задачи группы. Двойной щелчок — переименовать."
                          onClick={(event) => {
                            if (event.detail > 1) return
                            selectGroup(group.id)
                          }}
                          onDoubleClick={() => {
                            setFocusGroupId(group.id)
                            setRenameId(group.id)
                          }}
                        >
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
                        className="sub-kpi-plus sub-group-delete"
                        aria-label={`Удалить ${group.name}`}
                        title="Удалить"
                        onClick={() => {
                          setFocusGroupId((current) => (current === group.id ? '' : current))
                          setGroups((current) => current.filter((item) => item.id !== group.id))
                        }}
                      >
                        <Trash2 size={16} strokeWidth={2.25} aria-hidden />
                      </button>
                    </div>
                    {pickGroupId === group.id ? (
                      <ul className="sub-tasks-suggest sub-tasks-group-pick">
                        {loads.filter((row) => row.fio && !group.members.includes(row.fio)).length === 0 ? (
                          <li className="sub-tasks-suggest-empty">Все подчинённые уже в группе</li>
                        ) : (
                          loads
                            .filter((row) => row.fio && !group.members.includes(row.fio))
                            .sort((left, right) => left.level - right.level || left.fio.localeCompare(right.fio, 'ru'))
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
                                  <span>{row.fio}</span>
                                  {[row.position, row.department].filter(Boolean).length > 0 ? (
                                    <small>{[row.position, row.department].filter(Boolean).join(' · ')}</small>
                                  ) : null}
                                </button>
                              </li>
                            ))
                        )}
                      </ul>
                    ) : null}
                    {members.length === 0 ? (
                      <p className="sub-tasks-empty">В группе никого нет. Нажмите «+» и выберите сотрудника.</p>
                    ) : (
                      <div className="sub-group-line">
                        {members.map((row) => (
                          <button
                            key={row.fio}
                            type="button"
                            className={`sub-group-person${focusFio === row.fio ? ' is-selected' : ''}`}
                            onClick={() => selectPerson(row.fio)}
                          >
                            <strong>{row.fio}</strong>
                            {row.position || row.department ? <em>{row.position || row.department}</em> : null}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })
            )
            ) : null}
          </section>

          {staffView === 'scheme' ? null : (
          <section className="sub-tasks-pane" aria-label="Задачи подчинённых">
            <header className="sub-tasks-pane-head">
              {focusGroup ? `Задачи · ${focusGroup.name}` : 'Задачи'}
              <span className="sub-tasks-legend">
                <i className="is-overdue" /> просроченные
                <i className="is-critical" /> подходит срок
                <i className="is-open" /> поставленные
              </span>
            </header>
            {people.length === 0 ? (
              <p className="sub-tasks-empty">Подчинённых из оргструктуры нет — задачи появятся вместе с сотрудниками.</p>
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
          )}
        </div>
      </div>
      {staffView === 'scheme' && focusFio ? (
        <div className="sub-org-dialog" role="dialog" aria-modal="true" aria-label={`Задачи: ${focusFio}`}>
          <button type="button" className="sub-org-dialog-backdrop" aria-label="Закрыть" onClick={() => setFocusFio('')} />
          <section className="sub-org-dialog-card">
            <header className="sub-org-dialog-head">
              <div>
                <strong>{focusFio}</strong>
                {focusedPerson?.position || focusedPerson?.department ? (
                  <em>{focusedPerson.position || focusedPerson.department}</em>
                ) : null}
              </div>
              <button type="button" className="sub-tasks-btn" onClick={() => setFocusFio('')}>
                Закрыть
              </button>
            </header>
            {focusedTasks.length === 0 ? (
              <p className="sub-tasks-empty">
                {loading ? 'Читаем задачи…' : 'В этом периоде и фильтре задач нет.'}
              </p>
            ) : (
              <div className="sub-org-dialog-table">
                <table className="sub-tasks-table">
                  <thead>
                    <tr>
                      <th>Задача</th>
                      <th>Вид</th>
                      <th>Срок</th>
                      <th>Статус</th>
                      <th>Откуда</th>
                    </tr>
                  </thead>
                  <tbody>
                    {focusedTasks.map((row, index) => (
                      <tr key={`${row.number}:${row.title}:${index}`} className={`is-${row.kind}`}>
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
              </div>
            )}
          </section>
        </div>
      ) : null}
      {kpiOpen ? (
        <SubordinateKpiDialog
          tasks={tasks}
          people={activeScheme.order}
          directory={loads.map((row) => row.fio)}
          ownerId={user.id}
          onAddPerson={addPerson}
          dateFrom={dateFrom}
          dateTo={dateTo}
          person={focusedFio}
          initialMode={kpiMode}
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
