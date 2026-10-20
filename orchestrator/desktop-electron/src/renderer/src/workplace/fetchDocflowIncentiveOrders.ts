import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

/** Строка журнала приказов о мерах материального стимулирования (onec.docflow_incentive_orders). */
export type IncentiveOrderRow = {
  id: string
  number: string
  date: string
  /** Состояние документа в ДО — последняя пройденная стадия. */
  status: string
  registration: string
  approval: string
  confirmation: string
  performance: string
  organization: string
  department: string
  responsible: string
  author: string
  title: string
  summary: string
  comment: string
  employee: string
  employeeDepartment: string
  percent: number
  amount: number
  salaryPeriod: string
  approver: string
  controller: string
  task: string
  taskAuthor: string
  discipline: string
  cancelled: boolean
  cancelReason: string
  cancelledBy: string
  cancelledAt: string
}

export type IncentiveOrderOption = { code: string; label: string }

export type IncentiveOrderPage = {
  rows: IncentiveOrderRow[]
  total: number
  nextSkip: number
  hasMore: boolean
  statuses: IncentiveOrderOption[]
}

export const INCENTIVE_ORDER_PAGE_SIZE = 40

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function num(value: unknown): number {
  return Number(value) || 0
}

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function list(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(rec) : []
}

function mapRow(raw: Record<string, unknown>): IncentiveOrderRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    status: str(raw.status),
    registration: str(raw.registration),
    approval: str(raw.approval),
    confirmation: str(raw.confirmation),
    performance: str(raw.performance),
    organization: str(raw.organization),
    department: str(raw.department),
    responsible: str(raw.responsible),
    author: str(raw.author),
    title: str(raw.title),
    summary: str(raw.summary),
    comment: str(raw.comment),
    employee: str(raw.employee),
    employeeDepartment: str(raw.employee_department),
    percent: num(raw.percent),
    amount: num(raw.amount),
    salaryPeriod: str(raw.salary_period),
    approver: str(raw.approver),
    controller: str(raw.controller),
    task: str(raw.task),
    taskAuthor: str(raw.task_author),
    discipline: str(raw.discipline),
    cancelled: Boolean(raw.cancelled),
    cancelReason: str(raw.cancel_reason),
    cancelledBy: str(raw.cancelled_by),
    cancelledAt: str(raw.cancelled_at)
  }
}

export async function loadIncentiveOrderPage(
  user: UserProfile | null,
  opts: { from: string; to: string; skip: number; status: string }
): Promise<IncentiveOrderPage> {
  const res = await api.invokeServerTool(
    'onec.docflow_incentive_orders',
    onecGatewayInvokeArgs(user, {
      top: INCENTIVE_ORDER_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to,
      ...(opts.status ? { status: opts.status } : {})
    }),
    120_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать приказы из Документооборота')
  const payload = rec(res.result)
  const rows = list(payload.rows).map(mapRow)
  return {
    rows,
    total: num(payload.total) || rows.length,
    nextSkip: num(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    statuses: list(payload.statuses).map((item) => ({ code: str(item.code), label: str(item.label) }))
  }
}

const cardCache = new Map<string, IncentiveOrderRow>()

/** Карточка приказа: те же доп. реквизиты, но по одному документу. */
export async function loadIncentiveOrderCard(
  user: UserProfile | null,
  id: string
): Promise<IncentiveOrderRow> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_incentive_order_card',
    onecGatewayInvokeArgs(user, { ref_key: id }),
    120_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось открыть приказ')
  const card = mapRow(rec(rec(res.result).order))
  cardCache.set(id, card)
  return card
}
