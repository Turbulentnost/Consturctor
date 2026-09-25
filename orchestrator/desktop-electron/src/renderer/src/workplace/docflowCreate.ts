import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

export type DocflowProcessId = 'performance' | 'acquaintance' | 'consideration'

export interface DocflowDocType {
  id: string
  name: string
}

export interface DocflowBasisKind {
  id: string
  label: string
  hint: string
  types: DocflowDocType[]
  processes: DocflowProcessId[]
}

export interface DocflowProcessDef {
  id: DocflowProcessId
  label: string
  hint: string
  multiple: boolean
  verifier: boolean
}

export interface DocflowBasisDocument {
  id: string
  type: string
  name: string
  title: string
  reg_number: string
  reg_date: string
  author: string
  document_type: string
  summary: string
}

export type DocflowPriority = 'high' | 'normal' | 'low'

export const DOCFLOW_PRIORITY_LABEL: Record<DocflowPriority, string> = {
  high: 'Высокий',
  normal: 'Обычный',
  low: 'Низкий'
}

/** Одна строка шага 3 = одна задача (отдельный процесс в ДО). */
export interface DocflowTaskRowDraft {
  key: string
  fio: string
  description: string
  dueDate: string
  dueTime: string
  priority: DocflowPriority
  /** Дата постановки: момент, когда строку добавили. */
  postedAt: Date
}

export interface DocflowLaunchDraft {
  kind: string
  process: DocflowProcessId
  document: DocflowBasisDocument
  title: string
  row: DocflowTaskRowDraft
  verifier: string
  sampleTaskIds: string[]
}

/** +N рабочих дней: суббота и воскресенье не считаются (праздники — нет). */
export function addWorkingDays(from: Date, days: number): Date {
  const result = new Date(from)
  let left = days
  while (left > 0) {
    result.setDate(result.getDate() + 1)
    const weekday = result.getDay()
    if (weekday !== 0 && weekday !== 6) left -= 1
  }
  return result
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

export function isoDay(value: Date): string {
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

export function clockTime(value: Date): string {
  return `${pad(value.getHours())}:${pad(value.getMinutes())}`
}

export function newTaskRow(now = new Date()): DocflowTaskRowDraft {
  const due = addWorkingDays(now, 2)
  return {
    key: `t-${now.getTime()}-${Math.random().toString(36).slice(2, 7)}`,
    fio: '',
    description: '',
    dueDate: isoDay(due),
    dueTime: clockTime(now),
    priority: 'normal',
    postedAt: now
  }
}

/** Название задачи в ДО: первая строка описания, иначе название из заготовки процесса. */
export function taskTitle(row: DocflowTaskRowDraft, fallback: string): string {
  const first = row.description.trim().split('\n')[0]?.trim() || ''
  return (first || fallback).slice(0, 150)
}

type Result<T> = { ok: true; value: T } | { ok: false; error: string }

async function call<T>(
  user: UserProfile,
  args: Record<string, unknown>,
  timeoutMs: number
): Promise<Result<T>> {
  const res = await api.invokeServerTool('onec.docflow_create', onecGatewayInvokeArgs(user, args), timeoutMs)
  if (!res.ok) return { ok: false, error: res.error || 'Документооборот не ответил' }
  return { ok: true, value: (res.result ?? {}) as T }
}

/** Совпадает с DOC_KINDS / PROCESSES в backend/app/services/docflow_create.py. */
export const DOCFLOW_BASIS_KINDS: DocflowBasisKind[] = [
  { id: 'protocol', label: 'Протокол', hint: 'Решения совещаний и заседаний', types: [], processes: ['performance', 'acquaintance'] },
  {
    id: 'memo',
    label: 'Служебная записка',
    hint: 'Внутренние обращения и запросы',
    types: [],
    processes: ['performance', 'acquaintance', 'consideration']
  },
  { id: 'order', label: 'Приказ', hint: 'Приказы по основной деятельности', types: [], processes: ['acquaintance', 'performance'] },
  { id: 'directive', label: 'Распоряжение', hint: 'Распоряжения руководства', types: [], processes: ['acquaintance', 'performance'] },
  { id: 'contract', label: 'Договор', hint: 'Договоры, доп. соглашения, спецификации', types: [], processes: ['performance'] },
  { id: 'request', label: 'Заявка', hint: 'Заявки и заказы', types: [], processes: ['performance', 'consideration'] },
  { id: 'incoming', label: 'Входящий документ', hint: 'Письма, поступившие в компанию', types: [], processes: ['consideration', 'performance'] },
  { id: 'outgoing', label: 'Исходящий документ', hint: 'Письма, отправленные из компании', types: [], processes: ['performance'] }
]

export const DOCFLOW_PROCESSES: DocflowProcessDef[] = [
  {
    id: 'performance',
    label: 'Исполнение',
    hint: 'Исполнители получат задачу «Исполнить», проверяющий — «Проверить исполнение».',
    multiple: true,
    verifier: true
  },
  { id: 'acquaintance', label: 'Ознакомление', hint: 'Каждый участник получит задачу «Ознакомиться».', multiple: true, verifier: false },
  {
    id: 'consideration',
    label: 'Рассмотрение',
    hint: 'Сотрудник получит «Рассмотреть», вы — «Обработать резолюцию».',
    multiple: false,
    verifier: false
  }
]

let catalogSession: Promise<Result<{ kinds: DocflowBasisKind[]; processes: DocflowProcessDef[] }>> | null = null

/** Точные виды документов из ДО (для уточняющего списка). Один запрос на сеанс. */
export function loadDocflowCatalog(
  user: UserProfile
): Promise<Result<{ kinds: DocflowBasisKind[]; processes: DocflowProcessDef[] }>> {
  if (!catalogSession) {
    catalogSession = call<{ kinds: DocflowBasisKind[]; processes: DocflowProcessDef[] }>(
      user,
      { action: 'catalog' },
      90_000
    ).then((res) => {
      if (!res.ok) catalogSession = null
      return res
    })
  }
  return catalogSession
}

/** Все пользователи ДО (кому можно поставить задачу). */
export async function loadDocflowUsers(user: UserProfile): Promise<Result<{ users: string[] }>> {
  return call(user, { action: 'users' }, 180_000)
}

export async function searchDocflowDocuments(
  user: UserProfile,
  params: {
    kind: string
    documentTypeId: string
    query: string
    onlyMine: boolean
    dateFrom: string
    dateTo: string
  }
): Promise<Result<{ documents: DocflowBasisDocument[] }>> {
  return call(
    user,
    {
      action: 'search_documents',
      kind: params.kind,
      document_type_id: params.documentTypeId,
      query: params.query,
      only_mine: params.onlyMine,
      date_from: params.dateFrom,
      date_to: params.dateTo
    },
    180_000
  )
}

export async function prepareDocflowProcess(
  user: UserProfile,
  params: { kind: string; process: DocflowProcessId; document: DocflowBasisDocument }
): Promise<Result<{ name: string; description: string; author: string; target: string }>> {
  return call(
    user,
    {
      action: 'prepare',
      kind: params.kind,
      process: params.process,
      document: { id: params.document.id, type: params.document.type }
    },
    90_000
  )
}

export async function launchDocflowProcess(
  user: UserProfile,
  draft: DocflowLaunchDraft
): Promise<Result<{ summary: string; performers: string[] }>> {
  const due = `${draft.row.dueDate}T${draft.row.dueTime || '18:00'}`
  return call(
    user,
    {
      action: 'launch',
      confirm: true,
      kind: draft.kind,
      process: draft.process,
      document: { id: draft.document.id, type: draft.document.type },
      title: draft.title.trim(),
      description: draft.row.description.trim(),
      due,
      priority: draft.row.priority,
      verifier: draft.verifier.trim(),
      sample_task_ids: draft.sampleTaskIds,
      performers: [{ fio: draft.row.fio.trim(), due, note: '' }]
    },
    180_000
  )
}

export function formatRuDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '')
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value || '—'
}

export function formatRuDateTime(value: Date): string {
  return `${formatRuDate(isoDay(value))} ${clockTime(value)}`
}

export function documentLabel(doc: DocflowBasisDocument): string {
  return doc.name || doc.title || doc.reg_number || 'Документ'
}

export interface DocflowApprovalItem {
  name: string
  position: string
  date: string
  result: string
  comment: string
}

export interface DocflowApprovalSheet {
  found: boolean
  documentName: string
  regNumber: string
  items: DocflowApprovalItem[]
  message: string
}

const approvalCache = new Map<string, DocflowApprovalSheet>()
const approvalLoads = new Map<string, Promise<DocflowApprovalSheet>>()
let approvalBlocked = ''

function emptySheet(message: string): DocflowApprovalSheet {
  return { found: false, documentName: '', regNumber: '', items: [], message }
}

/** Лист согласования документа ДО. Один запрос на документ за сеанс. */
export function loadDocflowApprovalSheet(
  user: UserProfile,
  params: { id: string; kind: 'order' | 'directive'; regNumber: string; title: string }
): Promise<DocflowApprovalSheet> {
  if (approvalBlocked) return Promise.resolve(emptySheet(approvalBlocked))
  const cached = approvalCache.get(params.id)
  if (cached) return Promise.resolve(cached)
  const pending = approvalLoads.get(params.id)
  if (pending) return pending
  const load = call<{
    found?: boolean
    document_name?: string
    reg_number?: string
    items?: DocflowApprovalItem[]
  }>(
    user,
    {
      action: 'approval_sheet',
      kind: params.kind,
      reg_number: params.regNumber,
      title: params.title
    },
    120_000
  )
    .then((res) => {
      approvalLoads.delete(params.id)
      if (!res.ok) {
        if (/парол|учётн|учетн|401|403/i.test(res.error)) approvalBlocked = res.error
        const sheet = emptySheet(res.error)
        approvalCache.set(params.id, sheet)
        return sheet
      }
      const value = res.value
      const sheet: DocflowApprovalSheet = {
        found: value.found === true,
        documentName: value.document_name || '',
        regNumber: value.reg_number || '',
        items: Array.isArray(value.items) ? value.items : [],
        message: value.found === true ? '' : 'В документообороте нет листа согласования по этому номеру'
      }
      approvalCache.set(params.id, sheet)
      return sheet
    })
    .catch((err: unknown) => {
      approvalLoads.delete(params.id)
      const sheet = emptySheet(err instanceof Error ? err.message : 'Лист согласования не загрузился')
      approvalCache.set(params.id, sheet)
      return sheet
    })
  approvalLoads.set(params.id, load)
  return load
}
