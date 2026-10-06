import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

const TOOL = 'onec.docflow_document_create'
const LAST_VALUES_KEY = 'orch.docflowCreate.last'

export type DocflowKindId =
  | 'incoming'
  | 'outgoing'
  | 'memo'
  | 'payment'
  | 'forwarding'
  | 'order'
  | 'directive'
  | 'incentive'

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
  tables: DocflowTable[]
  files?: boolean
  max_file_mb?: number
  max_files?: number
}

export type DocflowUploadFile = { name: string; size: number; base64: string }

export type DocflowCreateResult =
  | { ok: true; summary: string; number: string; refKey: string; failedFiles: string[] }
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

export async function createDocflowDocument(
  user: UserProfile | null,
  kind: DocflowKindId,
  values: Record<string, string>,
  tables: Record<string, Record<string, string>[]>,
  files: DocflowUploadFile[] = []
): Promise<DocflowCreateResult> {
  const response = await api.invokeServerTool(
    TOOL,
    onecGatewayInvokeArgs(user, {
      action: 'create',
      kind,
      values,
      tables,
      ...(files.length ? { files: files.map((file) => ({ name: file.name, base64: file.base64 })) } : {})
    }),
    files.length ? 300_000 : 180_000
  )
  if (!response.ok) return { ok: false, error: errorText(response, 'Не удалось создать документ в 1С') }
  const payload = (response.result || {}) as Record<string, unknown>
  const refKey = String(payload.ref_key || '').trim()
  if (!refKey) return { ok: false, error: String(payload.summary || '1С не вернула ссылку на документ') }
  const failed = Array.isArray(payload.failed) ? (payload.failed as { name?: string }[]) : []
  return {
    ok: true,
    summary: String(payload.summary || 'Документ создан в 1С'),
    number: String(payload.number || '').trim(),
    refKey,
    failedFiles: failed.map((item) => String(item.name || '')).filter(Boolean)
  }
}

export function missingFields(schema: DocflowKindSchema, values: Record<string, string>): DocflowField[] {
  return schema.fields.filter((field) => field.required && !(values[field.key] || '').trim())
}

function todayInput(): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
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
