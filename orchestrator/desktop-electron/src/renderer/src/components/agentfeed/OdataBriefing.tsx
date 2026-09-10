import { useState } from 'react'

export interface OdataField {
  label: string
  value: string
}

export interface OdataRecord {
  title: string
  subtitle: string
  fields: OdataField[]
  people: string[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

const SKIP_KEYS = new Set([
  'odata.metadata',
  'odata.type',
  'odata.id',
  'odata.etag',
  'odata.editlink',
  'ref_key',
  'dataversion',
  'deletionmark',
  'predefined',
  'predefineddataName',
  'predefineddataname'
])

const TITLE_KEYS = [
  'Description',
  'Наименование',
  'Тема',
  'Subject',
  'Содержание',
  'Комментарий',
  'Number',
  'Номер',
  'Code',
  'Код'
]

const FIELD_LABELS: Record<string, string> = {
  Description: 'Название',
  Наименование: 'Название',
  Number: 'Номер',
  Номер: 'Номер',
  Date: 'Дата',
  Дата: 'Дата',
  Posted: 'Проведён',
  Subject: 'Тема',
  Тема: 'Тема',
  Author: 'Автор',
  Автор: 'Автор',
  Responsible: 'Ответственный',
  Ответственный: 'Ответственный',
  Organization: 'Организация',
  Организация: 'Организация',
  Comment: 'Комментарий',
  Комментарий: 'Комментарий',
  Status: 'Статус',
  Состояние: 'Статус',
  Code: 'Код',
  Код: 'Код',
  Содержание: 'Содержание'
}

const EMPTY_GUID = /^0{8}-0{4}-0{4}-0{4}-0{12}$/i
const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const PEOPLE_KEY = /участник|состав|присутств|attendee|participant|замещ|сотрудник/i

function isSkippedKey(key: string): boolean {
  const lower = key.toLowerCase()
  if (SKIP_KEYS.has(lower)) return true
  if (key.startsWith('odata.') || key.startsWith('@odata.')) return true
  if (lower.endsWith('_type') || lower.endsWith('@odata.type')) return true
  return false
}

function formatValue(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'boolean') return value ? 'да' : 'нет'
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text || EMPTY_GUID.test(text)) return ''
    if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
      const stamp = new Date(text)
      if (!Number.isNaN(stamp.getTime())) {
        return stamp.toLocaleString('ru-RU', {
          day: '2-digit',
          month: '2-digit',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit'
        })
      }
    }
    return text
  }
  if (Array.isArray(value)) return ''
  const row = asRecord(value)
  if (!row) return String(value)
  for (const key of TITLE_KEYS) {
    const inner = row[key]
    if (typeof inner === 'string' && inner.trim()) return inner.trim()
  }
  return ''
}

function fieldLabel(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]
  return key.replace(/_Key$/i, '').replace(/_/g, ' ')
}

function peopleFromRow(row: Record<string, unknown>): string[] {
  const out: string[] = []
  for (const [key, value] of Object.entries(row)) {
    if (!PEOPLE_KEY.test(key) || !Array.isArray(value)) continue
    for (const item of value) {
      const name = formatValue(item)
      if (name && !GUID_RE.test(name)) out.push(name)
    }
  }
  return unique(out)
}

function unique(items: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const item of items) {
    const key = item.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
  }
  return out
}

function recordTitle(row: Record<string, unknown>): string {
  for (const key of TITLE_KEYS) {
    const text = formatValue(row[key])
    if (text) return text
  }
  for (const value of Object.values(row)) {
    const text = formatValue(value)
    if (text && !GUID_RE.test(text)) return text
  }
  return 'Запись 1С'
}

function recordSubtitle(row: Record<string, unknown>, title: string): string {
  const parts: string[] = []
  for (const key of ['Number', 'Номер', 'Date', 'Дата', 'Posted']) {
    const text = formatValue(row[key])
    if (text && text !== title) parts.push(text)
  }
  return parts.slice(0, 3).join(' · ')
}

function recordFields(row: Record<string, unknown>, title: string): OdataField[] {
  const fields: OdataField[] = []
  for (const [key, value] of Object.entries(row)) {
    if (isSkippedKey(key)) continue
    if (Array.isArray(value)) continue
    if (GUID_RE.test(String(value || '')) && /key$/i.test(key)) continue
    const text = formatValue(value)
    if (!text || text === title) continue
    fields.push({ label: fieldLabel(key), value: text })
    if (fields.length >= 12) break
  }
  return fields
}

function rowsFromPayload(payload: unknown): Record<string, unknown>[] {
  const row = asRecord(payload)
  if (!row) return []
  const data = asRecord(row.data) || asRecord(row.result) || row
  for (const key of ['value', 'rows', 'items', 'records', 'documents']) {
    const list = data[key]
    if (Array.isArray(list)) {
      return list.filter((item): item is Record<string, unknown> => Boolean(asRecord(item)))
    }
  }
  if (data.Ref_Key || data.Description || data.Number || data.Наименование) return [data]
  return []
}

export function odataRecordsFromResult(result: unknown): OdataRecord[] {
  return rowsFromPayload(result).map((row) => {
    const title = recordTitle(row)
    return {
      title,
      subtitle: recordSubtitle(row, title),
      fields: recordFields(row, title),
      people: peopleFromRow(row)
    }
  })
}

export function odataEntityHint(args: Record<string, unknown> | undefined, result: unknown): string {
  const fromArgs =
    (typeof args?.entity === 'string' && args.entity.trim()) ||
    (typeof args?.path === 'string' && args.path.trim()) ||
    ''
  const row = asRecord(result)
  const fromResult = typeof row?.path === 'string' ? row.path.trim() : ''
  const raw = fromArgs || fromResult
  if (!raw) return ''
  const path = raw.split('?')[0]
  return path.replace(/\(guid'[^']+'\)/i, '')
}

function OdataCard({ item }: { item: OdataRecord }): React.JSX.Element {
  const [open, setOpen] = useState(true)
  return (
    <button type="button" className={`odata-card${open ? ' open' : ''}`} onClick={() => setOpen((v) => !v)}>
      <div className="odata-card-head">
        <div className="odata-card-title">{item.title}</div>
        <span className="odata-card-toggle">{open ? 'Свернуть' : 'Карточка'}</span>
      </div>
      {item.subtitle && <div className="odata-card-sub">{item.subtitle}</div>}
      {!open && item.people.length > 0 && (
        <div className="odata-card-preview">Участники: {item.people.join(', ')}</div>
      )}
      {open && (
        <div className="odata-card-body">
          {item.fields.map((field) => (
            <div key={field.label} className="odata-field">
              <div className="odata-field-label">{field.label}</div>
              <div className="odata-field-value">{field.value}</div>
            </div>
          ))}
          {item.people.length > 0 && (
            <div className="odata-field">
              <div className="odata-field-label">Участники / состав</div>
              <ul className="odata-people">
                {item.people.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </button>
  )
}

export function OdataBriefing({
  records,
  entityHint
}: {
  records: OdataRecord[]
  entityHint?: string
}): React.JSX.Element | null {
  if (!records.length) return null
  const extra = records.length > 8 ? records.length - 8 : 0
  const shown = records.slice(0, 8)
  return (
    <div className="odata-brief">
      <div className="odata-brief-head">
        <span className="odata-brief-name">{entityHint || 'Записи 1С'}</span>
        <span className="odata-brief-count">
          {records.length === 1 ? '1 запись' : `${records.length} записей`}
        </span>
      </div>
      {shown.map((item, index) => (
        <OdataCard key={`${item.title}-${index}`} item={item} />
      ))}
      {extra > 0 && <div className="odata-brief-more">ещё {extra}</div>}
    </div>
  )
}
