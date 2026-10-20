import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'
import { clearDocflowPages, readDocflowPage, writeDocflowPage } from './docflowPageCache'

/** Строка журнала протоколов (onec.docflow_protocols). Конфиденциальные приходят только свои. */
export type ProtocolRow = {
  id: string
  number: string
  date: string
  time: string
  timeStart: string
  timeEnd: string
  status: string
  statusCode: string
  closed: boolean
  kind: string
  kindCode: string
  topic: string
  head: string
  preparedBy: string
  responsible: string
  department: string
  room: string
  project: string
  access: string
  secret: boolean
  nextMeeting: string
  tasksSent: boolean
  posted: boolean
  comment: string
  participants: string[]
}

export type ProtocolOption = { code: string; label: string }

export type ProtocolPage = {
  rows: ProtocolRow[]
  nextSkip: number
  hasMore: boolean
  hiddenSecret: number
  ownSecret: number
  statuses: ProtocolOption[]
  kinds: ProtocolOption[]
}

export type ProtocolPlanRow = {
  n: number
  text: string
  responsible: string
  plan: string
  fact: string
  deviation: string
  unit: string
  comment: string
  done: boolean
}

export type ProtocolFile = {
  id: string
  name: string
  extension: string
  size: number
  created: string
  signed: boolean
}

/** Отметки о выполнении у задач протокола в 1С нет: есть срок, из него и статус. */
export type ProtocolTask = {
  /** LineNumber строки в 1С — по нему сервер узнаёт строку при правке. */
  line: number
  n: number
  text: string
  responsible: string
  responsibleKey: string
  author: string
  setAt: string
  due: string
  overdue: boolean
  status: string
  priority: string
  sent: boolean
  note: string
  files: ProtocolFile[]
  /** docflow — задача Документооборота (только чтение), erp — строка таблицы протокола, register — ТД_ЗадачиПротоколов. */
  source: 'docflow' | 'erp' | 'register'
  executed: boolean
  /** Дата исполнения из регистра задач протоколов. */
  doneAt: string
}

/** Карандаш видит только тот, кто подготовил протокол; reason — почему правка сейчас закрыта. */
export type ProtocolEditAccess = {
  author: boolean
  allowed: boolean
  reason: string
  controlBlock: string
  assignedBlock: string
  accessOptions: string[]
}

export type ProtocolCard = {
  protocol: ProtocolRow
  agenda: { n: number; text: string; responsible: string; attachments: string; files: ProtocolFile[] }[]
  decisions: {
    n: number
    text: string
    result: string
    start: string
    finish: string
    doneAt: string
    sent: boolean
    cancelled: boolean
    cancelReason: string
    cancelledBy: string
  }[]
  controlTasks: ProtocolTask[]
  assignedTasks: ProtocolTask[]
  /** Задачи ДО по протоколу-основанию — верхний список вкладки «Задачи для контроля» в 1С. */
  controlDocflow: ProtocolTask[]
  /** Задачи ДО по этому протоколу. */
  assignedDocflow: ProtocolTask[]
  /** Регистр ТД_ЗадачиПротоколов протокола-основания и этого протокола — то, что видно во вкладках формы 1С. */
  controlRegister: ProtocolTask[]
  assignedRegister: ProtocolTask[]
  baseProtocol: { id: string; number: string } | null
  docflowNote: string
  files: ProtocolFile[]
  periodDone: ProtocolPlanRow[]
  periodPlan: ProtocolPlanRow[]
  planFact: ProtocolPlanRow[]
  edit: ProtocolEditAccess
  stats: {
    decisions: number
    decisionsDone: number
    decisionsCancelled: number
    controlTasks: number
    controlOverdue: number
    controlDone: number
    assignedTasks: number
    assignedOverdue: number
    assignedDone: number
    files: number
  }
}

export const PROTOCOL_PAGE_SIZE = 40

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function list(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(rec) : []
}

function options(value: unknown): ProtocolOption[] {
  return list(value).map((item) => ({ code: str(item.code), label: str(item.label) }))
}

function mapRow(raw: Record<string, unknown>): ProtocolRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    time: str(raw.time),
    timeStart: str(raw.time_start),
    timeEnd: str(raw.time_end),
    status: str(raw.status),
    statusCode: str(raw.status_code),
    closed: Boolean(raw.closed),
    kind: str(raw.kind),
    kindCode: str(raw.kind_code),
    topic: str(raw.topic),
    head: str(raw.head),
    preparedBy: str(raw.prepared_by),
    responsible: str(raw.responsible),
    department: str(raw.department),
    room: str(raw.room),
    project: str(raw.project),
    access: str(raw.access),
    secret: Boolean(raw.secret),
    nextMeeting: str(raw.next_meeting),
    tasksSent: Boolean(raw.tasks_sent),
    posted: Boolean(raw.posted),
    comment: str(raw.comment),
    participants: Array.isArray(raw.participants) ? raw.participants.map(str).filter(Boolean) : []
  }
}

function mapFiles(value: unknown): ProtocolFile[] {
  return list(value).map((item) => ({
    id: str(item.id),
    name: str(item.name),
    extension: str(item.extension),
    size: Number(item.size) || 0,
    created: str(item.created),
    signed: Boolean(item.signed)
  }))
}

function mapTask(item: Record<string, unknown>): ProtocolTask {
  return {
    line: Number(item.line) || 0,
    n: Number(item.n) || 0,
    text: str(item.text),
    responsible: str(item.responsible),
    responsibleKey: str(item.responsible_key),
    author: str(item.author),
    setAt: str(item.set_at),
    due: str(item.due),
    overdue: Boolean(item.overdue),
    status: str(item.status),
    priority: str(item.priority),
    sent: Boolean(item.sent),
    note: str(item.note),
    files: mapFiles(item.files),
    source: item.source === 'docflow' ? 'docflow' : item.source === 'register' ? 'register' : 'erp',
    executed: Boolean(item.executed),
    doneAt: str(item.done_at)
  }
}

function mapPlan(item: Record<string, unknown>): ProtocolPlanRow {
  return {
    n: Number(item.n) || 0,
    text: str(item.text),
    responsible: str(item.responsible),
    plan: str(item.plan),
    fact: str(item.fact),
    deviation: str(item.deviation),
    unit: str(item.unit),
    comment: str(item.comment),
    done: Boolean(item.done)
  }
}

export async function loadProtocolPage(
  user: UserProfile | null,
  opts: { from: string; to: string; skip: number; status: string; kind: string }
): Promise<ProtocolPage> {
  const cacheKey = `protocols:${user?.id || user?.fio || ''}:${opts.from}:${opts.to}:${opts.skip}:${opts.status}:${opts.kind}`
  const cached = readDocflowPage<ProtocolPage>(cacheKey)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_protocols',
    onecGatewayInvokeArgs(user, {
      top: PROTOCOL_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to,
      ...(opts.status ? { status: opts.status } : {}),
      ...(opts.kind ? { kind: opts.kind } : {})
    }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать протоколы из 1С')
  const payload = rec(res.result)
  const rows = list(payload.rows).map(mapRow)
  const page: ProtocolPage = {
    rows,
    nextSkip: Number(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    hiddenSecret: Number(payload.hidden_secret) || 0,
    ownSecret: Number(payload.own_secret) || 0,
    statuses: options(payload.statuses),
    kinds: options(payload.kinds)
  }
  writeDocflowPage(cacheKey, page)
  return page
}

const cardCache = new Map<string, ProtocolCard>()

/** Подробный запрос по одному протоколу: повестка, решения, задачи, план-факт и участники. */
export async function loadProtocolCard(user: UserProfile | null, id: string): Promise<ProtocolCard> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_protocol_card',
    onecGatewayInvokeArgs(user, { ref_key: id }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось открыть протокол')
  const payload = rec(res.result)
  const stats = rec(payload.stats)
  const edit = rec(payload.edit)
  const card: ProtocolCard = {
    protocol: mapRow(rec(payload.protocol)),
    agenda: list(payload.agenda).map((item) => ({
      n: Number(item.n) || 0,
      text: str(item.text),
      responsible: str(item.responsible),
      attachments: str(item.attachments),
      files: mapFiles(item.files)
    })),
    decisions: list(payload.decisions).map((item) => ({
      n: Number(item.n) || 0,
      text: str(item.text),
      result: str(item.result),
      start: str(item.start),
      finish: str(item.finish),
      doneAt: str(item.done_at),
      sent: Boolean(item.sent),
      cancelled: Boolean(item.cancelled),
      cancelReason: str(item.cancel_reason),
      cancelledBy: str(item.cancelled_by)
    })),
    controlTasks: list(payload.control_tasks).map(mapTask),
    assignedTasks: list(payload.assigned_tasks).map(mapTask),
    controlDocflow: list(payload.control_docflow).map(mapTask),
    assignedDocflow: list(payload.assigned_docflow).map(mapTask),
    controlRegister: list(payload.control_register).map(mapTask),
    assignedRegister: list(payload.assigned_register).map(mapTask),
    baseProtocol: payload.base_protocol
      ? { id: str(rec(payload.base_protocol).id), number: str(rec(payload.base_protocol).number) }
      : null,
    docflowNote: str(payload.docflow_note),
    files: mapFiles(payload.files),
    periodDone: list(payload.period_done).map(mapPlan),
    periodPlan: list(payload.period_plan).map(mapPlan),
    planFact: list(payload.plan_fact).map(mapPlan),
    edit: {
      author: Boolean(edit.author),
      allowed: Boolean(edit.allowed),
      reason: str(edit.reason),
      controlBlock: str(edit.control_block),
      assignedBlock: str(edit.assigned_block),
      accessOptions: Array.isArray(edit.access_options) ? edit.access_options.map(str).filter(Boolean) : []
    },
    stats: {
      decisions: Number(stats.decisions) || 0,
      decisionsDone: Number(stats.decisions_done) || 0,
      decisionsCancelled: Number(stats.decisions_cancelled) || 0,
      controlTasks: Number(stats.control_tasks) || 0,
      controlOverdue: Number(stats.control_overdue) || 0,
      controlDone: Number(stats.control_done) || 0,
      assignedTasks: Number(stats.assigned_tasks) || 0,
      assignedOverdue: Number(stats.assigned_overdue) || 0,
      assignedDone: Number(stats.assigned_done) || 0,
      files: Number(stats.files) || 0
    }
  }
  cardCache.set(id, card)
  return card
}

export function forgetProtocolCard(id: string): void {
  cardCache.delete(id)
}

/** Поля шапки в том виде, как их принимает onec.meeting_protocol_write action=edit. */
export type ProtocolEditFields = Partial<
  Record<
    | 'topic'
    | 'meeting_type'
    | 'time_start'
    | 'time_end'
    | 'next_meeting_date'
    | 'leader'
    | 'responsible'
    | 'room'
    | 'access'
    | 'department'
    | 'project'
    | 'comment',
    string
  >
>

/** line = 0 — новая строка; отправленные исполнителю строки сервер оставляет как есть. */
export type ProtocolEditTask = {
  line: number
  n: number
  text: string
  responsible: string
  responsible_key?: string
  due: string
  priority: string
  note: string
}

/** Правку сервер пропускает только автору черновика (ФИО из токена = «Подготовил»). */
export async function saveProtocolEdit(
  id: string,
  change: { fields: ProtocolEditFields; controlTasks?: ProtocolEditTask[]; assignedTasks?: ProtocolEditTask[] }
): Promise<string> {
  const res = await api.invokeServerTool(
    'onec.meeting_protocol_write',
    {
      action: 'edit',
      ref_key: id,
      fields: change.fields,
      ...(change.controlTasks ? { control_tasks: change.controlTasks } : {}),
      ...(change.assignedTasks ? { assigned_tasks: change.assignedTasks } : {})
    },
    180_000
  )
  forgetProtocolCard(id)
  clearDocflowPages()
  if (!res.ok) throw new Error(res.error || 'Не удалось сохранить протокол в 1С')
  return str(rec(res.result).summary) || 'Протокол сохранён в 1С'
}
