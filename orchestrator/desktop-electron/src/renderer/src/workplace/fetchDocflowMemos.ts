import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

/** Строка журнала служебных записок (onec.docflow_memos). Конфиденциальные сервер не отдаёт. */
export type MemoRow = {
  id: string
  number: string
  date: string
  subject: string
  status: string
  approved: boolean
  posted: boolean
  fromWhom: string
  department: string
  direction: string
  assignees: string[]
  due: string
  openTasks: number
}

export type MemoPage = {
  rows: MemoRow[]
  nextSkip: number
  hasMore: boolean
  hiddenSecret: number
}

export type MemoTask = {
  id: string
  performer: string
  author: string
  step: string
  name: string
  description: string
  begin: string
  due: string
  doneAt: string
  executed: boolean
  executionMark: string
  source: 'docflow' | 'erp'
}

export type MemoCard = {
  memo: {
    id: string
    number: string
    date: string
    subject: string
    status: string
    approved: boolean
    posted: boolean
    fromWhom: string
    text: string
    fields: { key: string; label: string; value: string }[]
  }
  tasks: MemoTask[]
  route: { assignees: string[]; due: string; openTasks: number; total: number; executed: number; historyComplete: boolean }
}

export const MEMO_PAGE_SIZE = 40

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function mapRow(raw: Record<string, unknown>): MemoRow {
  return {
    id: str(raw.id),
    number: str(raw.number),
    date: str(raw.date),
    subject: str(raw.subject),
    status: str(raw.status),
    approved: Boolean(raw.approved),
    posted: Boolean(raw.posted),
    fromWhom: str(raw.from_whom),
    department: str(raw.department),
    direction: str(raw.direction),
    assignees: Array.isArray(raw.assignees) ? raw.assignees.map(str).filter(Boolean) : [],
    due: str(raw.due),
    openTasks: Number(raw.open_tasks) || 0
  }
}

function mapTask(raw: Record<string, unknown>): MemoTask {
  return {
    id: str(raw.id),
    performer: str(raw.performer),
    author: str(raw.author),
    step: str(raw.step),
    name: str(raw.name),
    description: str(raw.description),
    begin: str(raw.begin),
    due: str(raw.due),
    doneAt: str(raw.done_at),
    executed: Boolean(raw.executed),
    executionMark: str(raw.execution_mark),
    source: raw.source === 'erp' ? 'erp' : 'docflow'
  }
}

export async function loadMemoPage(
  user: UserProfile | null,
  opts: { from: string; to: string; skip: number }
): Promise<MemoPage> {
  const res = await api.invokeServerTool(
    'onec.docflow_memos',
    onecGatewayInvokeArgs(user, {
      top: MEMO_PAGE_SIZE,
      skip: opts.skip,
      date_from: opts.from,
      date_to: opts.to
    }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать служебные записки из 1С')
  const payload = asRecord(res.result)
  const rows = Array.isArray(payload.rows) ? payload.rows.map((row) => mapRow(asRecord(row))) : []
  return {
    rows,
    nextSkip: Number(payload.next_skip) || opts.skip + rows.length,
    hasMore: Boolean(payload.has_more),
    hiddenSecret: Number(payload.hidden_secret) || 0
  }
}

const cardCache = new Map<string, MemoCard>()

/** Подробный запрос по одной служебной записке: документ, маршрут ДО и задачи ERP. */
export async function loadMemoCard(user: UserProfile | null, id: string): Promise<MemoCard> {
  const cached = cardCache.get(id)
  if (cached) return cached
  const res = await api.invokeServerTool(
    'onec.docflow_memo_card',
    onecGatewayInvokeArgs(user, { ref_key: id }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось открыть служебную записку')
  const payload = asRecord(res.result)
  const memo = asRecord(payload.memo)
  const route = asRecord(payload.route)
  const card: MemoCard = {
    memo: {
      id: str(memo.id),
      number: str(memo.number),
      date: str(memo.date),
      subject: str(memo.subject),
      status: str(memo.status),
      approved: Boolean(memo.approved),
      posted: Boolean(memo.posted),
      fromWhom: str(memo.from_whom),
      text: str(memo.text),
      fields: Array.isArray(memo.fields)
        ? memo.fields.map((item) => {
            const field = asRecord(item)
            return { key: str(field.key), label: str(field.label), value: str(field.value) }
          })
        : []
    },
    tasks: Array.isArray(payload.tasks) ? payload.tasks.map((task) => mapTask(asRecord(task))) : [],
    route: {
      assignees: Array.isArray(route.assignees) ? route.assignees.map(str) : [],
      due: str(route.due),
      openTasks: Number(route.open_tasks) || 0,
      total: Number(route.total) || 0,
      executed: Number(route.executed) || 0,
      historyComplete: Boolean(route.history_complete)
    }
  }
  cardCache.set(id, card)
  return card
}
