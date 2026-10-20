import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

/** Строка журнала заявок на расходование ДС (onec.docflow_payment_requests). */
export type PaymentRequestRow = {
  id: string
  number: string
  date: string
  status: string
  statusCode: string
  operation: string
  operationCode: string
  amount: number
  currency: string
  paymentForm: string
  paymentFormCode: string
  recipient: string
  counterparty: string
  organization: string
  department: string
  requestedBy: string
  decidedBy: string
  author: string
  cfo: string
  cashFlowItem: string
  priority: string
  purpose: string
  wantedDate: string
  paymentDate: string
  comment: string
  overLimit: boolean
  closed: boolean
  forProduction: boolean
  posted: boolean
}

export type PaymentRequestOption = { code: string; label: string }

export type PaymentRequestPage = {
  rows: PaymentRequestRow[]
  nextSkip: number
  hasMore: boolean
  totalAmount: number
  statuses: PaymentRequestOption[]
  operations: PaymentRequestOption[]
  paymentForms: PaymentRequestOption[]
}

export type PaymentBreakdownRow = {
  n: number
  amount: number
  vat: number
  partner: string
  counterparty: string
  department: string
  cashFlowItem: string
  activity: string
  vatRate: string
  expenseItem: string
  comment: string
}

export type PaymentRequestCard = {
  request: PaymentRequestRow
  breakdown: PaymentBreakdownRow[]
  accounts: { n: number; amount: number; date: string }[]
  documents: { n: number; kind: string; number: string; date: string; amount: number }[]
  employees: { n: number; person: string; account: string; amount: number }[]
  stats: { breakdown: number; breakdownAmount: number; vatAmount: number; documents: number }
}

export const PAYMENT_REQUEST_PAGE_SIZE = 40

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

function options(value: unknown): PaymentRequestOption[] {
  return list(value).map((item) => ({ code: str(item.code), label: str(item.label) }))
}

function mapRow(raw: Record<string, unknown>): PaymentRequestRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    status: str(raw.status),
    statusCode: str(raw.status_code),
    operation: str(raw.operation),
    operationCode: str(raw.operation_code),
    amount: num(raw.amount),
    currency: str(raw.currency),
    paymentForm: str(raw.payment_form),
    paymentFormCode: str(raw.payment_form_code),
    recipient: str(raw.recipient),
    counterparty: str(raw.counterparty),
    organization: str(raw.organization),
    department: str(raw.department),
    requestedBy: str(raw.requested_by),
    decidedBy: str(raw.decided_by),
    author: str(raw.author),
    cfo: str(raw.cfo),
    cashFlowItem: str(raw.cash_flow_item),
    priority: str(raw.priority),
    purpose: str(raw.purpose),
    wantedDate: str(raw.wanted_date),
    paymentDate: str(raw.payment_date),
    comment: str(raw.comment),
    overLimit: Boolean(raw.over_limit),
    closed: Boolean(raw.closed),
    forProduction: Boolean(raw.for_production),
    posted: Boolean(raw.posted)
  }
}

export async function loadPaymentRequestPage(
  user: UserProfile | null,
  opts: { from: string; to: string; skip: number; status: string; operation: string; paymentForm: string }
): Promise<PaymentRequestPage> {
  const res = await api.invokeServerTool(
    'onec.docflow_payment_requests',
    onecGatewayInvokeArgs(user, {
      top: PAYMENT_REQUEST_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to,
      ...(opts.status ? { status: opts.status } : {}),
      ...(opts.operation ? { operation: opts.operation } : {}),
      ...(opts.paymentForm ? { payment_form: opts.paymentForm } : {})
    }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать заявки на расходование ДС из 1С')
  const payload = rec(res.result)
  const rows = list(payload.rows).map(mapRow)
  return {
    rows,
    nextSkip: num(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    totalAmount: num(payload.total_amount),
    statuses: options(payload.statuses),
    operations: options(payload.operations),
    paymentForms: options(payload.payment_forms)
  }
}

const cardCache = new Map<string, PaymentRequestCard>()

/** Подробный запрос по одной заявке: расшифровка платежа, счета и подтверждающие документы. */
export async function loadPaymentRequestCard(user: UserProfile | null, id: string): Promise<PaymentRequestCard> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_payment_request_card',
    onecGatewayInvokeArgs(user, { ref_key: id }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось открыть заявку')
  const payload = rec(res.result)
  const stats = rec(payload.stats)
  const card: PaymentRequestCard = {
    request: mapRow(rec(payload.request)),
    breakdown: list(payload.breakdown).map((item) => ({
      n: num(item.n),
      amount: num(item.amount),
      vat: num(item.vat),
      partner: str(item.partner),
      counterparty: str(item.counterparty),
      department: str(item.department),
      cashFlowItem: str(item.cash_flow_item),
      activity: str(item.activity),
      vatRate: str(item.vat_rate),
      expenseItem: str(item.expense_item),
      comment: str(item.comment)
    })),
    accounts: list(payload.accounts).map((item) => ({
      n: num(item.n),
      amount: num(item.amount),
      date: str(item.date)
    })),
    documents: list(payload.documents).map((item) => ({
      n: num(item.n),
      kind: str(item.kind),
      number: str(item.number),
      date: str(item.date),
      amount: num(item.amount)
    })),
    employees: list(payload.employees).map((item) => ({
      n: num(item.n),
      person: str(item.person),
      account: str(item.account),
      amount: num(item.amount)
    })),
    stats: {
      breakdown: num(stats.breakdown),
      breakdownAmount: num(stats.breakdown_amount),
      vatAmount: num(stats.vat_amount),
      documents: num(stats.documents)
    }
  }
  cardCache.set(id, card)
  return card
}

/** Сумма с разделителями разрядов: в журнале суммы читают глазами, а не считают. */
export function formatAmount(value: number, currency = ''): string {
  const text = value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency ? `${text} ${currency}` : text
}
