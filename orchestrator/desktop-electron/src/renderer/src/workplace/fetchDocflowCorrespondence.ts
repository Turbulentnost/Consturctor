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
  Ответственный: 'Ответственный',
  ТекстHTML: 'Текст'
}

const SKIP_FIELD = /(_Key|_Type|@|DataVersion|DeletionMark|Ref_Key|odata)/i

type SessionCache = {
  rows: CorrespondenceRow[]
  error: string
}

const sessionCache = new Map<string, SessionCache>()
const sessionLoads = new Map<string, Promise<SessionCache>>()

function cacheKey(user: UserProfile | null, kind: CorrespondenceKind): string {
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
  if (key === 'Date' || key.startsWith('Дата')) return formatCorrespondenceDate(value)
  if (value === 'true') return 'Да'
  if (value === 'false') return 'Нет'
  return value
}

function detailFields(row: Record<string, unknown>): CorrespondenceField[] {
  const seen = new Set<string>()
  const fields: CorrespondenceField[] = []
  for (const key of Object.keys(row)) {
    if (SKIP_FIELD.test(key) || key.endsWith('_Name')) continue
    const value = field(row, key)
    if (!value) continue
    const label = FIELD_LABELS[key] || key
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

async function loadFromOneC(
  user: UserProfile | null,
  kind: CorrespondenceKind
): Promise<SessionCache> {
  const entity = kind === 'incoming' ? INCOMING_ENTITY : OUTGOING_ENTITY
  const expand =
    kind === 'incoming'
      ? 'Организация,Контрагент,КомуПодразделениеСсылка'
      : 'Организация,Контрагент,Партнер'
  const args = onecGatewayInvokeArgs(user, {
    entity,
    top: 200,
    filter: 'DeletionMark eq false',
    expand
  })
  let res = await api.invokeServerTool('onec.odata_get', args, 180_000)
  if (!res.ok && /expand/i.test(res.error || '')) {
    const { expand: _expand, ...rest } = args
    void _expand
    res = await api.invokeServerTool('onec.odata_get', rest, 180_000)
  }
  if (!res.ok) {
    return { rows: [], error: res.error || 'Не удалось прочитать корреспонденцию из 1С' }
  }
  const rows = rowsFromResult(res.result)
    .map((row) => mapRow(row, kind))
    .filter((row) => row.date || row.number || row.comment)
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

export function correspondenceInPeriod(
  rows: CorrespondenceRow[],
  from: string,
  to: string
): CorrespondenceRow[] {
  return rows.filter((row) => {
    const day = row.date.slice(0, 10)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false
    return day >= from && day <= to
  })
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
