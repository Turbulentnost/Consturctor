import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { onecGatewayInvokeArgs } from './userContext'

const TOOL = 'onec.docflow_document_create'
const LAST_VALUES_KEY = 'orch.docflowCreate.last'

export type DocflowKindId =
  | 'incoming'
  | 'assignment'
  | 'outgoing'
  | 'memo'
  | 'payment'
  | 'forwarding'
  | 'order'
  | 'directive'
  | 'incentive'
  | 'service_1c'
  | 'service_it'
  | 'service_exploitation'
  | 'service_development'
  | 'service_nomenclature'
  | 'service_market'
  | 'service_pr'
  | 'service_aho'

export type DocflowFieldType = 'text' | 'textarea' | 'date' | 'number' | 'ref' | 'enum' | 'bool'

export type DocflowFieldOption = { value: string; label: string }

export type DocflowField = {
  key: string
  label: string
  type: DocflowFieldType
  required?: boolean
  catalog?: string
  default?: string
  hint?: string
  side?: 'left' | 'right' | 'wide'
  options?: DocflowFieldOption[]
  /** Показывать поле, только если подпись вида заявки содержит одну из этих строк. */
  for_kinds?: string[]
}

export type DocflowTable = {
  key: string
  label: string
  columns: DocflowField[]
}

export type DocflowKindSchema = {
  id: DocflowKindId
  title: string
  journal: string
  base: 'erp' | 'do'
  fields: DocflowField[]
  edit_fields?: DocflowField[]
  tables: DocflowTable[]
  files?: boolean
  max_file_mb?: number
  max_files?: number
  copy?: boolean
  basis_targets?: { id: DocflowKindId; title: string }[]
  recipient_emails?: string[]
}

export type DocflowUploadFile = { name: string; size: number; base64: string }

export type DocflowCreateResult =
  | { ok: true; summary: string; number: string; refKey: string; failedFiles: string[] }
  | { ok: false; error: string }

/** Строка табличной части: значения для показа и GUID ссылок, прочитанных из 1С. */
export type DocflowTableRow = { cells: Record<string, string>; keys: Record<string, string> }

export type DocflowCard = {
  kind: DocflowKindId
  refKey: string
  number: string
  date: string
  status: string
  posted: boolean
  deleted: boolean
  editable: boolean
  readonlyReason: string
  editWarning: string
  values: Record<string, string>
  keys: Record<string, string>
  tables: Record<string, DocflowTableRow[]>
  files: { id: string; name: string; extension: string; size: string }[]
  basisLabel: string
  webUrl: string
}

export type DocflowPrefill = {
  values: Record<string, string>
  keys: Record<string, string>
  tables: Record<string, DocflowTableRow[]>
  basis: { kind: DocflowKindId; ref_key: string } | null
  label: string
  copy: boolean
}

/** Уже отправленное письмо Outlook: зарегистрировать исходящую, не отправляя его ещё раз. */
export type OutgoingMailSource = {
  entryId: string
}

/** Что открыть в форме: новый документ (возможно, на основании другого) или уже записанный. */
export type DocflowFormRequest =
  | { mode: 'create'; kind: DocflowKindId; prefill?: DocflowPrefill; outgoingMail?: OutgoingMailSource }
  | { mode: 'edit'; kind: DocflowKindId; refKey: string }

export type DocflowWriteResult =
  | { ok: true; summary: string; failedFiles: string[] }
  | { ok: false; error: string }

let schemaLoad: Promise<DocflowKindSchema[]> | null = null

function errorText(response: { ok: boolean; error?: string }, fallback: string): string {
  return (response.error || '').trim() || fallback
}

export function loadDocflowCreateSchema(user: UserProfile | null): Promise<DocflowKindSchema[]> {
  if (schemaLoad) return schemaLoad
  const load = api
    .invokeServerTool(TOOL, onecGatewayInvokeArgs(user, { action: 'schema' }), 60_000)
    .then((response) => {
      if (!response.ok) throw new Error(errorText(response, 'Не удалось получить формы 1С'))
      const payload = (response.result || {}) as { kinds?: DocflowKindSchema[] }
      return Array.isArray(payload.kinds) ? payload.kinds : []
    })
  schemaLoad = load
  load.catch(() => {
    if (schemaLoad === load) schemaLoad = null
  })
  return load
}

export async function lookupDocflowCatalog(
  user: UserProfile | null,
  kind: DocflowKindId,
  catalog: string,
  query: string
): Promise<{ key: string; name: string }[]> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, { action: 'lookup', kind, catalog, query }),
    30_000
  )
  if (!response.ok) return []
  const payload = (response.result || {}) as { items?: { key: string; name: string }[] }
  return Array.isArray(payload.items) ? payload.items : []
}

export function readUploadFile(file: File): Promise<DocflowUploadFile> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const url = String(reader.result || '')
      resolve({ name: file.name, size: file.size, base64: url.slice(url.indexOf(',') + 1) })
    }
    reader.onerror = () => reject(new Error(`Не удалось прочитать «${file.name}»`))
    reader.readAsDataURL(file)
  })
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

export type OutgoingSender = {
  fio: string
  position: string
  from_email: string
  work_phone: string
  mobile_phone: string
}

/** Телефоны сотрудника из контактной информации 1С. */
export async function loadOutgoingPhones(user: UserProfile | null): Promise<{ work_phone: string; mobile_phone: string }> {
  const response = await api.invokeServerTool(TOOL, onecGatewayInvokeArgs(user, { action: 'signature', kind: 'outgoing' }), 60_000)
  if (!response.ok) return { work_phone: '', mobile_phone: '' }
  const payload = (response.result || {}) as Record<string, unknown>
  return {
    work_phone: String(payload.work_phone || '').trim(),
    mobile_phone: String(payload.mobile_phone || '').trim()
  }
}

/** Сохранить уже существующее письмо Outlook файлом .msg, без повторной отправки. */
export async function saveOutlookMessageFile(
  user: UserProfile | null,
  entryId: string
): Promise<{ ok: true; file: DocflowUploadFile } | { ok: false; error: string }> {
  const response = await invokeLocalAcTool(
    'outlook.save_message',
    { entry_id: entryId, include_base64: true },
    120_000,
    user
  )
  if (!response.ok || !response.result) {
    return { ok: false, error: response.error || 'Outlook не сохранил письмо' }
  }
  const base64 = String(response.result.msg_base64 || '').trim()
  const name = String(response.result.file_name || response.result.msg_filename || 'Письмо.msg').trim() || 'Письмо.msg'
  if (!base64) return { ok: false, error: 'Письмо не сохранилось файлом .msg' }
  const size = Math.floor((base64.length * 3) / 4)
  return {
    ok: true,
    file: { name: name.toLowerCase().endsWith('.msg') ? name : `${name}.msg`, size, base64 }
  }
}

/** Отправить письмо исходящей через Outlook и получить его файл .msg. */
export async function sendOutgoingLetter(
  user: UserProfile | null,
  letter: { to: string; subject: string; body: string; sender: OutgoingSender }
): Promise<{ ok: true; file: DocflowUploadFile; fromEmail: string } | { ok: false; error: string }> {
  const sender = letter.sender
  const response = await invokeLocalAcTool(
    'outlook.send_outgoing_letter',
    {
      to: letter.to.trim(),
      subject: letter.subject.trim(),
      body: letter.body.trim(),
      fio: sender.fio,
      position: sender.position,
      from_email: sender.from_email,
      work_phone: sender.work_phone,
      mobile_phone: sender.mobile_phone
    },
    120_000,
    user
  )
  if (!response.ok || !response.result) {
    return { ok: false, error: response.error || 'Outlook не отправил письмо' }
  }
  const base64 = String(response.result.msg_base64 || '').trim()
  const name = String(response.result.file_name || response.result.msg_filename || 'Письмо.msg').trim() || 'Письмо.msg'
  if (!base64) return { ok: false, error: 'Письмо отправлено, но файл .msg не получен' }
  const size = Math.floor((base64.length * 3) / 4)
  return {
    ok: true,
    fromEmail: String(response.result.from_email || sender.from_email || '').trim(),
    file: { name: name.toLowerCase().endsWith('.msg') ? name : `${name}.msg`, size, base64 }
  }
}

export async function createDocflowDocument(
  user: UserProfile | null,
  kind: DocflowKindId,
  values: Record<string, string>,
  tables: Record<string, Record<string, string>[]>,
  files: DocflowUploadFile[] = [],
  basis: DocflowPrefill['basis'] = null,
  post = false,
  letterhead = false,
  sender: OutgoingSender | null = null
): Promise<DocflowCreateResult> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, {
      action: 'create',
      kind,
      values,
      tables,
      ...(basis ? { basis } : {}),
      ...(post ? { post: true } : {}),
      ...(letterhead ? { letterhead: true } : {}),
      ...(sender ? { sender } : {}),
      ...(files.length ? { files: uploadPayload(files) } : {})
    }),
    files.length || letterhead ? 300_000 : 180_000
  )
  if (!response.ok) return { ok: false, error: errorText(response, 'Не удалось создать документ в 1С') }
  const payload = (response.result || {}) as Record<string, unknown>
  const refKey = String(payload.ref_key || '').trim()
  if (!refKey) return { ok: false, error: String(payload.summary || '1С не вернула ссылку на документ') }
  return {
    ok: true,
    summary: String(payload.summary || 'Документ создан в 1С'),
    number: String(payload.number || '').trim(),
    refKey,
    failedFiles: failedNames(payload)
  }
}

function uploadPayload(files: DocflowUploadFile[]): { name: string; base64: string }[] {
  return files.map((file) => ({ name: file.name, base64: file.base64 }))
}

function failedNames(payload: Record<string, unknown>): string[] {
  const failed = Array.isArray(payload.failed) ? (payload.failed as { name?: string }[]) : []
  return failed.map((item) => String(item.name || '')).filter(Boolean)
}

function textMap(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== 'object') return {}
  return Object.fromEntries(Object.entries(raw as Record<string, unknown>).map(([k, v]) => [k, String(v ?? '')]))
}

function tableMap(raw: unknown): Record<string, DocflowTableRow[]> {
  if (!raw || typeof raw !== 'object') return {}
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).map(([key, rows]) => [
      key,
      (Array.isArray(rows) ? rows : []).map((row) => {
        const { __keys, ...rest } = (row || {}) as Record<string, unknown>
        return { cells: textMap(rest), keys: textMap(__keys) }
      })
    ])
  )
}

export async function readDocflowDocument(
  user: UserProfile | null,
  kind: DocflowKindId,
  refKey: string
): Promise<DocflowCard> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, { action: 'read', kind, ref_key: refKey }),
    90_000
  )
  if (!response.ok) throw new Error(errorText(response, 'Не удалось открыть документ 1С'))
  const p = (response.result || {}) as Record<string, unknown>
  return {
    kind,
    refKey,
    number: String(p.number || ''),
    date: String(p.date || ''),
    status: String(p.status || ''),
    posted: Boolean(p.posted),
    deleted: Boolean(p.deleted),
    editable: Boolean(p.editable),
    readonlyReason: String(p.readonly_reason || ''),
    editWarning: String(p.edit_warning || ''),
    values: textMap(p.values),
    keys: textMap(p.keys),
    tables: tableMap(p.tables),
    files: Array.isArray(p.files) ? (p.files as DocflowCard['files']) : [],
    basisLabel: String(p.basis_label || ''),
    webUrl: String(p.web_url || '')
  }
}

export async function updateDocflowDocument(
  user: UserProfile | null,
  kind: DocflowKindId,
  refKey: string,
  values: Record<string, string>,
  changed: string[],
  tables: Record<string, Record<string, string>[]>
): Promise<DocflowWriteResult> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, { action: 'update', kind, ref_key: refKey, values, changed, tables }),
    180_000
  )
  if (!response.ok) return { ok: false, error: errorText(response, 'Не удалось записать изменения в 1С') }
  const payload = (response.result || {}) as Record<string, unknown>
  return { ok: true, summary: String(payload.summary || 'Изменения записаны в 1С'), failedFiles: failedNames(payload) }
}

export async function postDocflowDocument(
  user: UserProfile | null,
  kind: DocflowKindId,
  refKey: string
): Promise<DocflowWriteResult> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, { action: 'post', kind, ref_key: refKey }),
    180_000
  )
  if (!response.ok) return { ok: false, error: errorText(response, 'Не удалось провести документ в 1С') }
  const payload = (response.result || {}) as Record<string, unknown>
  return { ok: true, summary: String(payload.summary || 'Документ проведён'), failedFiles: [] }
}

export async function attachDocflowFiles(
  user: UserProfile | null,
  kind: DocflowKindId,
  refKey: string,
  files: DocflowUploadFile[]
): Promise<DocflowWriteResult> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, { action: 'attach', kind, ref_key: refKey, files: uploadPayload(files) }),
    300_000
  )
  if (!response.ok) return { ok: false, error: errorText(response, 'Не удалось прикрепить файлы в 1С') }
  const payload = (response.result || {}) as Record<string, unknown>
  const failed = failedNames(payload)
  if (failed.length === files.length) return { ok: false, error: String(payload.summary || 'Файлы не прикрепились') }
  return { ok: true, summary: String(payload.summary || 'Файлы прикреплены'), failedFiles: failed }
}

export async function docflowBasisValues(
  user: UserProfile | null,
  kind: DocflowKindId,
  refKey: string,
  target: DocflowKindId
): Promise<DocflowPrefill> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, { action: 'basis', kind, ref_key: refKey, target }),
    90_000
  )
  if (!response.ok) throw new Error(errorText(response, 'Не удалось заполнить документ на основании'))
  const p = (response.result || {}) as Record<string, unknown>
  const basis = p.basis as DocflowPrefill['basis']
  return {
    values: textMap(p.values),
    keys: textMap(p.keys),
    tables: tableMap(p.tables),
    basis: basis && basis.ref_key ? basis : null,
    label: String(p.basis_label || ''),
    copy: kind === target
  }
}

export function missingFields(fields: DocflowField[], values: Record<string, string>): DocflowField[] {
  return fields.filter((field) => field.required && !(values[field.key] || '').trim())
}

function todayInput(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(new Date())
}

export function initialValues(schema: DocflowKindSchema, actorFio: string): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of schema.fields) {
    if (field.default === 'me') values[field.key] = actorFio
    else if (field.type === 'enum' && field.default) {
      const hit = field.options?.find((item) => item.value === field.default || item.label === field.default)
      values[field.key] = hit?.value || ''
    } else if (field.default) values[field.key] = field.default
    else if (field.type === 'date' && field.required) values[field.key] = todayInput()
    else values[field.key] = ''
  }
  return values
}

/** Справочники и списки повторяются от документа к документу — их и подставляем в следующий раз. */
function rememberable(field: DocflowField): boolean {
  return (field.type === 'ref' || field.type === 'enum') && field.default !== 'me'
}

function lastStore(): Record<string, Record<string, string>> {
  try {
    const parsed = JSON.parse(localStorage.getItem(LAST_VALUES_KEY) || '{}')
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function rememberLastValues(
  userId: string,
  schema: DocflowKindSchema,
  values: Record<string, string>
): void {
  const store = lastStore()
  const kept: Record<string, string> = {}
  for (const field of schema.fields) {
    const value = (values[field.key] || '').trim()
    if (rememberable(field) && value) kept[field.key] = value
  }
  store[`${userId}:${schema.id}`] = kept
  try {
    localStorage.setItem(LAST_VALUES_KEY, JSON.stringify(store))
  } catch {
    /* переполненный localStorage — автозаполнение просто не сохранится */
  }
}

export function recallLastValues(userId: string, schema: DocflowKindSchema): Record<string, string> {
  const saved = lastStore()[`${userId}:${schema.id}`] || {}
  const out: Record<string, string> = {}
  for (const field of schema.fields) {
    const value = saved[field.key]
    if (!value || !rememberable(field)) continue
    if (field.type === 'enum' && !field.options?.some((item) => item.value === value)) continue
    out[field.key] = value
  }
  return out
}

export function displayValue(field: DocflowField, value: string): string {
  if (field.type === 'enum') return field.options?.find((item) => item.value === value)?.label || value
  return value
}
