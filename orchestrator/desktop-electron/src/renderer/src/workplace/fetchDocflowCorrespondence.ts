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
  БизнесПроцессЗапущен: 'Процесс запущен',
  ИсточникПоступления: 'Источник поступления',
  Претензия: 'Претензия',
  Subject: 'Тема',
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

function humanizeIdentifier(value: string): string {
  const spaced = value
    .replace(/_/g, ' ')
    .replace(/([а-яёa-z])([А-ЯЁA-Z])/g, '$1 $2')
    .replace(/([А-ЯЁA-Z])([А-ЯЁA-Z][а-яёa-z])/g, '$1 $2')
    .trim()
  return spaced
    .split(/\s+/)
    .map((word, index) => (index === 0 ? word : word.charAt(0).toLowerCase() + word.slice(1)))
    .join(' ')
}

function looksLikeEnum(value: string): boolean {
  return value.length > 2 && value.length < 48 && !/[\s\-«»]/.test(value) && /[а-яёa-z]/.test(value) && /[А-ЯЁA-Z]/.test(value.slice(1))
}

function displayValue(key: string, value: string): string {
  if (key === 'Date' || key.startsWith('Дата') || key.startsWith('Срок') || key.startsWith('Время')) {
    return formatCorrespondenceDate(value)
  }
  if (value === 'true') return 'Да'
  if (value === 'false') return 'Нет'
  if (key === 'ТекстСлужебнойЗаписки' || key === 'ТекстHTML') return stripHtml(value)
  if (looksLikeEnum(value)) return humanizeIdentifier(value)
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
    const label = labels[key] || FIELD_LABELS[key] || humanizeIdentifier(key)
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

/** Страницы по одной: три параллельных журнала по 200 строк занимали все потоки 1С и роняли соседние запросы. */
async function loadJournalPages(
  user: UserProfile | null,
  base: Record<string, unknown>
): Promise<{ rows: Record<string, unknown>[]; error: string }> {
  const rows: Record<string, unknown>[] = []
  let error = ''
  for (let index = 0; index < PAGE_COUNT; index += 1) {
    const page = await loadJournalPage(user, base, index * PAGE_SIZE)
    if (page.rows.length) rows.push(...page.rows)
    if (page.error && !page.rows.length) {
      error = page.error
      break
    }
    if (page.rows.length < PAGE_SIZE) break
  }
  return { rows, error: rows.length ? '' : error }
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

export function forgetDocflowCorrespondenceSession(user: UserProfile | null, kind: CorrespondenceKind): void {
  sessionCache.delete(cacheKey(user, kind))
}

const INCOMING_FILES_ENTITY = 'Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы'
const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Письмо, из которого зарегистрирована входящая: .msg в присоединённых файлах документа.
 * Тома 1С (\\srv2\erp_file) пользователям закрыты, поэтому байты идут через hs/dtw/files backend.
 */
export async function openIncomingLetter(user: UserProfile | null, row: CorrespondenceRow): Promise<void> {
  if (!GUID_RE.test(row.id)) throw new Error('У документа нет ссылки 1С')
  const res = await api.invokeServerTool(
    'onec.odata_get',
    onecGatewayInvokeArgs(user, {
      entity: INCOMING_FILES_ENTITY,
      filter: `ВладелецФайла_Key eq guid'${row.id}' and Расширение eq 'msg' and DeletionMark eq false`,
      select: 'Ref_Key,Description,Расширение,ДатаСоздания',
      orderby: 'ДатаСоздания desc',
      top: 1
    }),
    60_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать файлы документа в 1С')
  const file = rowsFromResult(res.result)[0]
  const fileId = String(file?.Ref_Key || '')
  if (!fileId) throw new Error('К документу не приложено письмо (.msg)')
  const name = String(file?.Description || row.number || 'letter').replace(/[\\/:*?"<>|]+/g, '_')
  const result = await window.api.download({
    url: `/api/v1/tools/onec-artifacts/${encodeURIComponent(fileId)}`,
    defaultName: `${name}.msg`,
    token: api.getToken(),
    temporary: true,
    openAfter: true
  })
  if (!result.ok) throw new Error(result.error || 'Не удалось открыть письмо')
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

/** Колонки журнала. Без «Содержания» и без $expand: полный документ с тремя справочниками не успевает вернуться, пока 1С занята выгрузкой задач. */
const ORDER_LIST_SELECT = [
  'Ref_Key',
  'Number',
  'Date',
  'Posted',
  'DeletionMark',
  'Статус',
  'ТемаСлужебнойЗаписки',
  'Комментарий',
  'Организация_Key',
  'Ответственный_Key',
  'ГрифДоступа_Key'
].join(',')

const ORDER_NAME_FIELDS: { key: string; entity: string }[] = [
  { key: 'Организация_Key', entity: 'Catalog_Организации' },
  { key: 'Ответственный_Key', entity: 'Catalog_Пользователи' },
  { key: 'ГрифДоступа_Key', entity: 'Catalog_ТД_ГрифыДоступа' }
]

const NAME_CHUNK = 20

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

function isMarkedDeleted(row: Record<string, unknown>): boolean {
  return row.DeletionMark === true || String(row.DeletionMark || '').toLowerCase() === 'true'
}

function orderGuid(value: unknown): string {
  const text = String(value || '').trim()
  if (!GUID_RE.test(text) || text === '00000000-0000-0000-0000-000000000000') return ''
  return text.toLowerCase()
}

/** Фильтр DeletionMark eq false на этих документах возвращает единицы строк при сотнях непомеченных. Пометку отсекаем по полю. */
async function loadOrderRaw(
  user: UserProfile | null,
  spec: (typeof ORDER_ENTITIES)[number]
): Promise<{ rows: Record<string, unknown>[]; error: string }> {
  const query = {
    entity: spec.entity,
    select: ORDER_LIST_SELECT,
    resolve_navigation: false
  }
  let page = await loadJournalPages(user, query)
  if (!page.rows.length && /timed out/i.test(page.error)) {
    page = await loadJournalPages(user, query)
  }
  const rows = page.rows.filter((row) => !isMarkedDeleted(row))
  if (!rows.length && page.error) return { rows: [], error: `${spec.label}: ${page.error}` }
  return { rows, error: '' }
}

async function namesByKeys(
  user: UserProfile | null,
  entity: string,
  keys: string[]
): Promise<Map<string, string>> {
  const names = new Map<string, string>()
  const unique = [...new Set(keys.map(orderGuid).filter(Boolean))]
  for (let index = 0; index < unique.length; index += NAME_CHUNK) {
    const chunk = unique.slice(index, index + NAME_CHUNK)
    const filter = chunk.map((key) => `Ref_Key eq guid'${key}'`).join(' or ')
    const res = await api.invokeServerTool(
      'onec.odata_get',
      onecGatewayInvokeArgs(user, {
        entity,
        filter,
        select: 'Ref_Key,Description',
        top: chunk.length,
        resolve_navigation: false
      }),
      60_000
    )
    if (!res.ok) continue
    for (const row of rowsFromResult(res.result)) {
      const key = orderGuid(row.Ref_Key)
      const name = textOf(row.Description)
      if (key && name) names.set(key, name)
    }
  }
  return names
}

async function fillOrderNames(user: UserProfile | null, rows: Record<string, unknown>[]): Promise<void> {
  if (!rows.length) return
  for (const spec of ORDER_NAME_FIELDS) {
    const names = await namesByKeys(
      user,
      spec.entity,
      rows.map((row) => String(row[spec.key] || ''))
    )
    const fieldName = spec.key.slice(0, -'_Key'.length)
    for (const row of rows) {
      const name = names.get(orderGuid(row[spec.key]))
      if (!name) continue
      row[fieldName] = name
      row[`${fieldName}_Name`] = name
    }
  }
}

const orderCache = new Map<string, { rows: OrderRow[]; error: string }>()
const orderLoads = new Map<string, Promise<{ rows: OrderRow[]; error: string }>>()

export function forgetDocflowOrdersSession(user: UserProfile | null): void {
  orderCache.delete(cacheKey(user, 'orders'))
}

/** Приказы и распоряжения из документов 1С. Виды читаются по очереди, имена справочников — отдельными пачками. */
export function loadDocflowOrdersSession(user: UserProfile | null): Promise<{ rows: OrderRow[]; error: string }> {
  const key = cacheKey(user, 'orders')
  const cached = orderCache.get(key)
  if (cached) return Promise.resolve(cached)
  const pending = orderLoads.get(key)
  if (pending) return pending
  const load = (async () => {
    const parts: { spec: (typeof ORDER_ENTITIES)[number]; rows: Record<string, unknown>[]; error: string }[] = []
    for (const spec of ORDER_ENTITIES) {
      const part = await loadOrderRaw(user, spec)
      parts.push({ spec, ...part })
    }
    const raw = parts.flatMap((part) => part.rows)
    await fillOrderNames(user, raw)
    const seen = new Set<string>()
    const rows = parts
      .flatMap((part) => part.rows.map((row) => mapOrder(row, part.spec.kind, part.spec.label)))
      .filter((row) => row.date || row.number || row.subject)
      .filter((row) => (seen.has(row.id) ? false : seen.add(row.id) !== undefined))
    rows.sort((left, right) => right.date.localeCompare(left.date))
    const errors = parts.map((part) => part.error).filter(Boolean)
    const error = rows.length
      ? errors.join(' ')
      : errors.join(' ') || 'Не удалось прочитать приказы и распоряжения из 1С'
    if (rows.length && !error) orderCache.set(key, { rows, error: '' })
    return { rows, error }
  })()
    .finally(() => {
      orderLoads.delete(key)
    })
  orderLoads.set(key, load)
  return load
}

/** Содержание карточки — отдельным чтением одного документа, не в списке журнала. */
export async function loadOrderBody(user: UserProfile | null, row: OrderRow): Promise<OrderRow | null> {
  if (!GUID_RE.test(row.id)) return row
  const spec = ORDER_ENTITIES.find((item) => item.kind === row.kind)
  if (!spec) return null
  const res = await api.invokeServerTool(
    'onec.odata_get',
    onecGatewayInvokeArgs(user, {
      entity: spec.entity,
      ref_key: row.id,
      resolve_navigation: false
    }),
    60_000
  )
  if (!res.ok) return null
  const raw = rowsFromResult(res.result)[0]
  if (!raw) return null
  const content = stripHtml(field(raw, 'Содержание'))
  const fields = row.fields.filter((item) => item.label !== 'Содержание')
  if (content) fields.push({ label: 'Содержание', value: content })
  return { ...row, content, fields }
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
