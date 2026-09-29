import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

/** Строка журнала протоколов (onec.docflow_protocols). Конфиденциальные приходят только свои. */
export type ProtocolRow = {
  id: string
  number: string
  date: string
  time: string
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
  n: number
  text: string
  responsible: string
  author: string
  setAt: string
  due: string
  overdue: boolean
  status: string
  priority: string
  sent: boolean
  note: string
  files: ProtocolFile[]
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
  files: ProtocolFile[]
  periodDone: ProtocolPlanRow[]
  periodPlan: ProtocolPlanRow[]
  planFact: ProtocolPlanRow[]
  stats: {
    decisions: number
    decisionsDone: number
    decisionsCancelled: number
    controlTasks: number
    controlOverdue: number
    assignedTasks: number
    assignedOverdue: number
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
    n: Number(item.n) || 0,
    text: str(item.text),
    responsible: str(item.responsible),
    author: str(item.author),
    setAt: str(item.set_at),
    due: str(item.due),
    overdue: Boolean(item.overdue),
    status: str(item.status),
    priority: str(item.priority),
    sent: Boolean(item.sent),
    note: str(item.note),
    files: mapFiles(item.files)
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
  return {
    rows,
    nextSkip: Number(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    hiddenSecret: Number(payload.hidden_secret) || 0,
    ownSecret: Number(payload.own_secret) || 0,
    statuses: options(payload.statuses),
    kinds: options(payload.kinds)
  }
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
    files: mapFiles(payload.files),
    periodDone: list(payload.period_done).map(mapPlan),
    periodPlan: list(payload.period_plan).map(mapPlan),
    planFact: list(payload.plan_fact).map(mapPlan),
    stats: {
      decisions: Number(stats.decisions) || 0,
      decisionsDone: Number(stats.decisions_done) || 0,
      decisionsCancelled: Number(stats.decisions_cancelled) || 0,
      controlTasks: Number(stats.control_tasks) || 0,
      controlOverdue: Number(stats.control_overdue) || 0,
      assignedTasks: Number(stats.assigned_tasks) || 0,
      assignedOverdue: Number(stats.assigned_overdue) || 0,
      files: Number(stats.files) || 0
    }
  }
  cardCache.set(id, card)
  return card
}
