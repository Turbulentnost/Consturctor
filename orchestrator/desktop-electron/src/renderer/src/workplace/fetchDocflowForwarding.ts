import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

/** Строка журнала поручений экспедитору (onec.docflow_forwarding). */
export type ForwardingRow = {
  id: string
  number: string
  date: string
  status: string
  statusCode: string
  kind: string
  kindCode: string
  way: string
  wayCode: string
  loading: string
  doneAt: string
  window: string
  address: string
  consigneeAddress: string
  warehouse: string
  responsible: string
  department: string
  shipper: string
  consignee: string
  counterparty: string
  payer: string
  payerDirection: string
  zone: string
  city: string
  terminal: string
  transport: string
  contact: string
  phone: string
  places: number
  weight: number
  volume: number
  size: string
  cargoCost: number
  complete: boolean
  processStarted: boolean
  needsDirector: boolean
  routeFrom: string
  routeTo: string
  passenger: string
  passengerPhone: string
  tripPurpose: string
  deliveryNote: string
  specialTerms: string
  comment: string
  posted: boolean
}

export type ForwardingOption = { code: string; label: string }

export type ForwardingPage = {
  rows: ForwardingRow[]
  nextSkip: number
  hasMore: boolean
  statuses: ForwardingOption[]
  kinds: ForwardingOption[]
  ways: ForwardingOption[]
}

export type ForwardingCargoRow = {
  n: number
  name: string
  feature: string
  serial: string
  order: string
  length: number
  width: number
  height: number
  weight: number
  volume: number
  module: string
}

export type ForwardingDeviceRow = {
  n: number
  name: string
  feature: string
  serial: string
  order: string
  places: number
  delivery: string
  deliveryAmount: number
  module: string
  packingList: string
}

export type ForwardingCard = {
  order: ForwardingRow
  cargo: ForwardingCargoRow[]
  devices: ForwardingDeviceRow[]
  orders: { n: number; order: string; uid: string }[]
  bases: { n: number; kind: string; title: string }[]
  stats: { cargo: number; cargoWeight: number; cargoVolume: number; devices: number }
}

export const FORWARDING_PAGE_SIZE = 40

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

function options(value: unknown): ForwardingOption[] {
  return list(value).map((item) => ({ code: str(item.code), label: str(item.label) }))
}

function mapRow(raw: Record<string, unknown>): ForwardingRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    status: str(raw.status),
    statusCode: str(raw.status_code),
    kind: str(raw.kind),
    kindCode: str(raw.kind_code),
    way: str(raw.way),
    wayCode: str(raw.way_code),
    loading: str(raw.loading),
    doneAt: str(raw.done_at),
    window: str(raw.window),
    address: str(raw.address),
    consigneeAddress: str(raw.consignee_address),
    warehouse: str(raw.warehouse),
    responsible: str(raw.responsible),
    department: str(raw.department),
    shipper: str(raw.shipper),
    consignee: str(raw.consignee),
    counterparty: str(raw.counterparty),
    payer: str(raw.payer),
    payerDirection: str(raw.payer_direction),
    zone: str(raw.zone),
    city: str(raw.city),
    terminal: str(raw.terminal),
    transport: str(raw.transport),
    contact: str(raw.contact),
    phone: str(raw.phone),
    places: num(raw.places),
    weight: num(raw.weight),
    volume: num(raw.volume),
    size: str(raw.size),
    cargoCost: num(raw.cargo_cost),
    complete: Boolean(raw.complete),
    processStarted: Boolean(raw.process_started),
    needsDirector: Boolean(raw.needs_director),
    routeFrom: str(raw.route_from),
    routeTo: str(raw.route_to),
    passenger: str(raw.passenger),
    passengerPhone: str(raw.passenger_phone),
    tripPurpose: str(raw.trip_purpose),
    deliveryNote: str(raw.delivery_note),
    specialTerms: str(raw.special_terms),
    comment: str(raw.comment),
    posted: Boolean(raw.posted)
  }
}

export async function loadForwardingPage(
  user: UserProfile | null,
  opts: { from: string; to: string; skip: number; status: string; kind: string; way: string }
): Promise<ForwardingPage> {
  const res = await api.invokeServerTool(
    'onec.docflow_forwarding',
    onecGatewayInvokeArgs(user, {
      top: FORWARDING_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to,
      ...(opts.status ? { status: opts.status } : {}),
      ...(opts.kind ? { kind: opts.kind } : {}),
      ...(opts.way ? { way: opts.way } : {})
    }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать поручения экспедитору из 1С')
  const payload = rec(res.result)
  const rows = list(payload.rows).map(mapRow)
  return {
    rows,
    nextSkip: num(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    statuses: options(payload.statuses),
    kinds: options(payload.kinds),
    ways: options(payload.ways)
  }
}

const cardCache = new Map<string, ForwardingCard>()

/** Подробный запрос по одному поручению: габариты груза, приборы, заказы и основания. */
export async function loadForwardingCard(user: UserProfile | null, id: string): Promise<ForwardingCard> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_forwarding_card',
    onecGatewayInvokeArgs(user, { ref_key: id }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось открыть поручение')
  const payload = rec(res.result)
  const stats = rec(payload.stats)
  const card: ForwardingCard = {
    order: mapRow(rec(payload.order)),
    cargo: list(payload.cargo).map((item) => ({
      n: num(item.n),
      name: str(item.name),
      feature: str(item.feature),
      serial: str(item.serial),
      order: str(item.order),
      length: num(item.length),
      width: num(item.width),
      height: num(item.height),
      weight: num(item.weight),
      volume: num(item.volume),
      module: str(item.module)
    })),
    devices: list(payload.devices).map((item) => ({
      n: num(item.n),
      name: str(item.name),
      feature: str(item.feature),
      serial: str(item.serial),
      order: str(item.order),
      places: num(item.places),
      delivery: str(item.delivery),
      deliveryAmount: num(item.delivery_amount),
      module: str(item.module),
      packingList: str(item.packing_list)
    })),
    orders: list(payload.orders).map((item) => ({
      n: num(item.n),
      order: str(item.order),
      uid: str(item.uid)
    })),
    bases: list(payload.bases).map((item) => ({
      n: num(item.n),
      kind: str(item.kind),
      title: str(item.title)
    })),
    stats: {
      cargo: num(stats.cargo),
      cargoWeight: num(stats.cargo_weight),
      cargoVolume: num(stats.cargo_volume),
      devices: num(stats.devices)
    }
  }
  cardCache.set(id, card)
  return card
}
