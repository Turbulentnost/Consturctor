import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

export type CorrespondenceKind = 'incoming' | 'outgoing'

export type CorrespondenceField = {
  label: string
  value: string
}

export type CorrespondenceRow = {
  id: string
  date: string
  number: string
  organization: string
  emailFrom: string
  emailTo: string
  partner: string
  addressee: string
  department: string
  direction: string
  incomingNumber: string
  comment: string
  fields: CorrespondenceField[]
}

const INCOMING_ENTITY = 'Document_ТД_ВходящаяКорреспонденция'
const OUTGOING_ENTITY = 'Document_ТД_ИсходящаяКорреспонденция'

const FIELD_LABELS: Record<string, string> = {
  Number: 'Номер',
  Date: 'Дата',
  Posted: 'Проведён',
  Комментарий: 'Комментарий',
  Направление: 'Направление',
  Партнер: 'Партнёр',
  ПлательщикНаправление: 'Плательщик / направление',
  EmailОтправителяПисьма: 'Email отправителя',
  EmailПолучателяПисьма: 'Email получателя',
  Кому: 'Кому',
  Организация: 'Организация',
  Контрагент: 'Контрагент',
  КомуПодразделениеСсылка: 'Подразделение',
  Содержание: 'Содержание',
  НомерВходящий: 'Номер входящий',
  НомерИсходящий: 'Номер исходящий',
  ДатаИсходящая: 'Дата исходящая',
  ДатаВходящая: 'Дата входящая',
  Статус: 'Статус',
  ТемаСлужебнойЗаписки: 'Тема',
  ТемаСовещания: 'Тема совещания',
  Ответственный: 'Кому назначена',
  МенеджерКому: 'Менеджер (кому)',
  МенеджерОтКого: 'От кого',
  ИсполнительУД: 'Исполнитель УД',
  Подразделение: 'Подразделение',
  Приоритет: 'Приоритет',
  СрокИсполнения: 'Срок исполнения',
  ТекстСлужебнойЗаписки: 'Текст',
  БизнесПроцессСтартован: 'Процесс запущен',
  УтвержденоНачальникомУД: 'Утверждено начальником УД',
  ТекстHTML: 'Текст',
  ГрифДоступа: 'Гриф доступа'
}

const SKIP_FIELD = /(_Key|_Type|@|DataVersion|DeletionMark|Ref_Key|odata|Base64|Расписание)/i

type SessionCache = {
  rows: CorrespondenceRow[]
  error: string
}

const sessionCache = new Map<string, SessionCache>()
const sessionLoads = new Map<string, Promise<SessionCache>>()

function cacheKey(user: UserProfile | null, kind: string): string {
  return `${kind}:${user?.id || user?.fio || 'session'}`
}

function textOf(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text || text.startsWith('0001-01-01')) return ''
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(text)) return ''
    if (text === '00000000-0000-0000-0000-000000000000') return ''
    return text
  }
  if (typeof value === 'object') {
    const rec = value as Record<string, unknown>
    return (
      textOf(rec.Description) ||
      textOf(rec.Наименование) ||
      textOf(rec.Presentation) ||
      textOf(rec.FullName)
    )
  }
  return ''
}

function field(row: Record<string, unknown>, key: string): string {
  return textOf(row[`${key}_Name`]) || textOf(row[key])
}

function displayValue(key: string, value: string): string {
  if (key === 'Date' || key.startsWith('Дата') || key.startsWith('Срок') || key.startsWith('Время')) {
    return formatCorrespondenceDate(value)
  }
  if (value === 'true') return 'Да'
  if (value === 'false') return 'Нет'
  if (key === 'ТекстСлужебнойЗаписки' || key === 'ТекстHTML') return stripHtml(value)
  return value
}

function stripHtml(value: string): string {
  return value
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/\s+/g, ' ')
    .trim()
}

function detailFields(
  row: Record<string, unknown>,
  labels: Record<string, string> = FIELD_LABELS
): CorrespondenceField[] {
  const seen = new Set<string>()
  const fields: CorrespondenceField[] = []
  for (const key of Object.keys(row)) {
    if (SKIP_FIELD.test(key) || key.endsWith('_Name')) continue
    const value = field(row, key)
    if (!value) continue
    const label = labels[key] || FIELD_LABELS[key] || key
    if (seen.has(label)) continue
    seen.add(label)
    fields.push({ label, value: displayValue(key, value) })
  }
  return fields
}

function mapRow(row: Record<string, unknown>, kind: CorrespondenceKind): CorrespondenceRow {
  const direction = field(row, 'ПлательщикНаправление') || field(row, 'Направление')
  return {
    id: String(row.Ref_Key || row.Number || ''),
    date: String(row.Date || ''),
    number: field(row, 'Number'),
    organization: field(row, 'Организация'),
    emailFrom: field(row, 'EmailОтправителяПисьма'),
    emailTo: field(row, 'EmailПолучателяПисьма'),
    partner: field(row, 'Партнер') || field(row, 'Контрагент'),
    addressee: kind === 'incoming' ? field(row, 'Кому') : field(row, 'EmailПолучателяПисьма'),
    department: field(row, 'КомуПодразделениеСсылка'),
    direction,
    incomingNumber: field(row, 'НомерВходящий'),
    comment: field(row, 'Комментарий') || field(row, 'Содержание'),
    fields: detailFields(row)
  }
}

function rowsFromResult(result: unknown): Record<string, unknown>[] {
  if (!result || typeof result !== 'object') return []
  const payload = result as Record<string, unknown>
  const value = payload.value
  if (Array.isArray(value)) return value.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
  const data = payload.data
  if (data && typeof data === 'object') {
    const nested = (data as Record<string, unknown>).value
    if (Array.isArray(nested)) {
      return nested.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
    }
  }
  return []
}

const PAGE_SIZE = 200
/** Сколько страниц журнала тянем за раз. Свежие сверху — этого хватает на месяцы. */
const PAGE_COUNT = 3

/** Страница журнала 1С: сначала с expand, при отказе — без него. */
async function loadJournalPage(
  user: UserProfile | null,
  base: Record<string, unknown>,
  skip: number
): Promise<{ rows: Record<string, unknown>[]; error: string }> {
  const args = onecGatewayInvokeArgs(user, { ...base, top: PAGE_SIZE, skip, orderby: 'Date desc' })
  let res = await api.invokeServerTool('onec.odata_get', args, 180_000)
  if (!res.ok && /expand/i.test(res.error || '')) {
    const { expand: _expand, ...rest } = args
    void _expand
    res = await api.invokeServerTool('onec.odata_get', rest, 180_000)
  }
  if (!res.ok) return { rows: [], error: res.error || '' }
  return { rows: rowsFromResult(res.result), error: '' }
}

/** Страницы журнала параллельно: последовательный обход занимал минуты. */
async function loadJournalPages(
  user: UserProfile | null,
  base: Record<string, unknown>
): Promise<{ rows: Record<string, unknown>[]; error: string }> {
  const skips = Array.from({ length: PAGE_COUNT }, (_, index) => index * PAGE_SIZE)
  const pages = await Promise.all(skips.map((skip) => loadJournalPage(user, base, skip)))
  const rows = pages.flatMap((page) => page.rows)
  const error = rows.length ? '' : pages.map((page) => page.error).find(Boolean) || ''
  return { rows, error }
}

async function loadFromOneC(
  user: UserProfile | null,
  kind: CorrespondenceKind
): Promise<SessionCache> {
  const entity = kind === 'incoming' ? INCOMING_ENTITY : OUTGOING_ENTITY
  const expand =
    kind === 'incoming'
      ? 'Организация,Контрагент,КомуПодразделениеСсылка'
      : 'Организация,Контрагент,Партнер'
  const page = await loadJournalPages(user, {
    entity,
    filter: 'DeletionMark eq false',
    expand
  })
  if (!page.rows.length && page.error) {
    return { rows: [], error: page.error || 'Не удалось прочитать корреспонденцию из 1С' }
  }
  const seen = new Set<string>()
  const rows = page.rows
    .map((row) => mapRow(row, kind))
    .filter((row) => row.date || row.number || row.comment)
    .filter((row) => (seen.has(row.id) ? false : seen.add(row.id) !== undefined))
  rows.sort((left, right) => right.date.localeCompare(left.date))
  return { rows, error: '' }
}

/** Один запрос в 1С на вид журнала за сессию программы. Период режется уже из кэша. */
export function loadDocflowCorrespondenceSession(
  user: UserProfile | null,
  kind: CorrespondenceKind
): Promise<SessionCache> {
  const key = cacheKey(user, kind)
  const cached = sessionCache.get(key)
  if (cached) return Promise.resolve(cached)
  const pending = sessionLoads.get(key)
  if (pending) return pending
  const load = loadFromOneC(user, kind)
    .then((result) => {
      sessionLoads.delete(key)
      if (!result.error) sessionCache.set(key, result)
      return result
    })
    .catch((err: unknown) => {
      sessionLoads.delete(key)
      throw err
    })
  sessionLoads.set(key, load)
  return load
}

export function correspondenceInPeriod<T extends { date: string }>(rows: T[], from: string, to: string): T[] {
  return rows.filter((row) => {
    const day = row.date.slice(0, 10)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false
    return day >= from && day <= to
  })
}

export type OrderKind = 'order' | 'directive'

export type OrderRow = {
  id: string
  kind: OrderKind
  kindLabel: string
  date: string
  number: string
  subject: string
  status: string
  organization: string
  responsible: string
  access: string
  content: string
  posted: boolean
  fields: CorrespondenceField[]
}

const ORDER_ENTITIES: { kind: OrderKind; label: string; entity: string }[] = [
  { kind: 'order', label: 'Приказ', entity: 'Document_ТД_Приказ' },
  { kind: 'directive', label: 'Распоряжение', entity: 'Document_ТД_Распоряжение' }
]

const ORDER_LABELS: Record<string, string> = {
  Number: 'Номер',
  Date: 'Дата',
  Posted: 'Проведён',
  Статус: 'Статус',
  ТемаСлужебнойЗаписки: 'Тема',
  Содержание: 'Содержание',
  Комментарий: 'Комментарий',
  Организация: 'Организация',
  Ответственный: 'Ответственный',
  ГрифДоступа: 'Гриф доступа',
  ДокументОснование: 'Документ-основание'
}

function mapOrder(row: Record<string, unknown>, kind: OrderKind, kindLabel: string): OrderRow {
  const subject = field(row, 'ТемаСлужебнойЗаписки') || field(row, 'Subject') || field(row, 'Description')
  return {
    id: String(row.Ref_Key || `${kind}-${row.Number || ''}-${row.Date || ''}`),
    kind,
    kindLabel,
    date: String(row.Date || ''),
    number: field(row, 'Number'),
    subject: subject.replace(/\s+/g, ' ').trim(),
    status: field(row, 'Статус'),
    organization: field(row, 'Организация'),
    responsible: field(row, 'Ответственный'),
    access: field(row, 'ГрифДоступа'),
    content: stripHtml(field(row, 'Содержание')),
    posted: row.Posted === true || String(row.Posted || '').toLowerCase() === 'true',
    fields: detailFields(row, ORDER_LABELS)
  }
}

async function loadOrderEntity(
  user: UserProfile | null,
  spec: (typeof ORDER_ENTITIES)[number]
): Promise<{ rows: OrderRow[]; error: string }> {
  const page = await loadJournalPages(user, {
    entity: spec.entity,
    filter: 'DeletionMark eq false',
    expand: 'Организация,Ответственный,ГрифДоступа'
  })
  const seen = new Set<string>()
  const collected = page.rows
    .map((row) => mapOrder(row, spec.kind, spec.label))
    .filter((row) => row.date || row.number || row.subject)
    .filter((row) => (seen.has(row.id) ? false : seen.add(row.id) !== undefined))
  if (!collected.length && page.error) {
    return { rows: [], error: `${spec.label}: ${page.error}` }
  }
  return { rows: collected, error: '' }
}

const orderCache = new Map<string, { rows: OrderRow[]; error: string }>()
const orderLoads = new Map<string, Promise<{ rows: OrderRow[]; error: string }>>()

/** Приказы и распоряжения из документов 1С. Один запрос каждого вида за сессию. */
export function loadDocflowOrdersSession(user: UserProfile | null): Promise<{ rows: OrderRow[]; error: string }> {
  const key = cacheKey(user, 'orders')
  const cached = orderCache.get(key)
  if (cached) return Promise.resolve(cached)
  const pending = orderLoads.get(key)
  if (pending) return pending
  const load = Promise.all(ORDER_ENTITIES.map((spec) => loadOrderEntity(user, spec)))
    .then((parts) => {
      orderLoads.delete(key)
      const rows = parts.flatMap((part) => part.rows)
      rows.sort((left, right) => right.date.localeCompare(left.date))
      const errors = parts.map((part) => part.error).filter(Boolean)
      const result = {
        rows,
        error: rows.length ? '' : errors.join(' ') || 'Не удалось прочитать приказы и распоряжения из 1С'
      }
      if (!result.error) orderCache.set(key, result)
      return result
    })
    .catch((err: unknown) => {
      orderLoads.delete(key)
      throw err
    })
  orderLoads.set(key, load)
  return load
}

export function formatCorrespondenceDate(raw: string): string {
  const text = (raw || '').trim()
  if (!text || text.startsWith('0001-01-01')) return '—'
  const stamp = new Date(text)
  if (Number.isNaN(stamp.getTime())) return text.slice(0, 16).replace('T', ' ')
  const day = String(stamp.getDate()).padStart(2, '0')
  const month = String(stamp.getMonth() + 1).padStart(2, '0')
  const hours = String(stamp.getHours()).padStart(2, '0')
  const minutes = String(stamp.getMinutes()).padStart(2, '0')
  return `${day}.${month}.${stamp.getFullYear()} ${hours}:${minutes}`
}
