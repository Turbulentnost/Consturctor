import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import type { DocflowKindId } from './docflowDocumentCreate'
import { onecGatewayInvokeArgs } from './userContext'

/** Строка журнала заявок в службы (onec.docflow_service_requests). */
export type ServiceRequestId =
  | 'service_1c'
  | 'service_it'
  | 'service_exploitation'
  | 'service_development'
  | 'service_nomenclature'
  | 'service_market'
  | 'service_pr'

export type ServiceRequestRow = {
  id: string
  number: string
  date: string
  status: string
  statusCode: string
  kind: string
  kindPath: string
  documentType: string
  formKind: DocflowKindId
  text: string
  room: string
  building: string
  phone: string
  due: string
  organization: string
  responsible: string
  department: string
  executorDepartment: string
  executor: string
  resolution: string
  hours: string
  acceptedAt: string
  plannedAt: string
  doneAt: string
  confirmed: boolean
  confirmedAt: string
  person: string
  position: string
  priority: string
  accounts: string
  posted: boolean
  technical: boolean
}

export type ServiceRequestOption = { code: string; label: string }

export type ServiceRequestPage = {
  rows: ServiceRequestRow[]
  nextSkip: number
  hasMore: boolean
  statuses: ServiceRequestOption[]
  title: string
}

export const SERVICE_REQUEST_PAGE_SIZE = 40

export const SERVICE_REQUESTS: { id: ServiceRequestId; kind: DocflowKindId; title: string; hint: string; create: string }[] = [
  { id: 'service_1c', kind: 'service_1c', title: 'Заявки в службу сопровождения 1С', hint: 'Служба 1С', create: 'В службу 1С' },
  { id: 'service_it', kind: 'service_it', title: 'Заявки в службу IT', hint: 'Служба IT', create: 'В службу IT' },
  { id: 'service_exploitation', kind: 'service_exploitation', title: 'Заявки в Эксплуатационную службу', hint: 'Эксплуатация', create: 'В эксплуатацию' },
  { id: 'service_development', kind: 'service_development', title: 'Заявки в службу развития', hint: 'Служба развития', create: 'В службу развития' },
  { id: 'service_nomenclature', kind: 'service_nomenclature', title: 'Заявки на создание номенклатуры', hint: 'Номенклатура', create: 'Номенклатура' },
  { id: 'service_market', kind: 'service_market', title: 'Заявки о потребности рынка', hint: 'Потребность рынка', create: 'Потребность рынка' },
  { id: 'service_pr', kind: 'service_pr', title: 'Заявки в сектор рекламы и PR', hint: 'Реклама и PR', create: 'Реклама и PR' }
]

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

function mapRow(raw: Record<string, unknown>): ServiceRequestRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    status: str(raw.status),
    statusCode: str(raw.status_code),
    kind: str(raw.kind),
    kindPath: str(raw.kind_path),
    documentType: str(raw.document_type),
    formKind: (str(raw.form_kind) || 'service_1c') as DocflowKindId,
    text: str(raw.text),
    room: str(raw.room),
    building: str(raw.building),
    phone: str(raw.phone),
    due: str(raw.due),
    organization: str(raw.organization),
    responsible: str(raw.responsible),
    department: str(raw.department),
    executorDepartment: str(raw.executor_department),
    executor: str(raw.executor),
    resolution: str(raw.resolution),
    hours: str(raw.hours),
    acceptedAt: str(raw.accepted_at),
    plannedAt: str(raw.planned_at),
    doneAt: str(raw.done_at),
    confirmed: Boolean(raw.confirmed),
    confirmedAt: str(raw.confirmed_at),
    person: str(raw.person),
    position: str(raw.position),
    priority: str(raw.priority),
    accounts: str(raw.accounts),
    posted: Boolean(raw.posted),
    technical: Boolean(raw.technical)
  }
}

export async function loadServiceRequestPage(
  user: UserProfile | null,
  opts: { service: ServiceRequestId; from: string; to: string; skip: number; status: string }
): Promise<ServiceRequestPage> {
  const res = await api.invokeServerTool(
    'onec.docflow_service_requests',
    onecGatewayInvokeArgs(user, {
      service: opts.service,
      top: SERVICE_REQUEST_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to,
      ...(opts.status ? { status: opts.status } : {})
    }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать заявки из 1С')
  const payload = rec(res.result)
  const rows = list(payload.rows).map(mapRow)
  return {
    rows,
    nextSkip: num(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    statuses: list(payload.statuses).map((item) => ({ code: str(item.code), label: str(item.label) })),
    title: str(payload.title)
  }
}
