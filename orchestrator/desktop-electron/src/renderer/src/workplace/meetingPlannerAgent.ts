import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { ILCHENKO_USER_IDS } from '../orchestrator/kpi'
import { adoptAgentFromLibrary, fetchAgentLibrary } from './agentLibraryApi'

export const PLANNER_SOURCE_WORKFLOW_ID = '678eb16e-7421-48e9-a487-5c1138bb31e4'
export const PLANNER_AGENT_TITLE = 'Планировщик совещаний по служебным запискам'

export interface MemoRequest {
  ref: string
  number: string
  date: string
  status: string
  topic: string
  purpose: string
  text: string
  kind: string
  psdLevel: boolean
  desiredDate: string
  desiredInPast: boolean
  startTime: string
  endTime: string
  durationMinutes: number | null
  place: string
  leader: string
  author: string
  participants: string[]
  agenda: string[]
  planned: { subject: string; start: string; end: string; location: string } | null
}

/** Агент только у помощника ПСД: он создаёт совещания от служебного ящика. */
export function isMeetingPlannerUser(user: Pick<UserProfile, 'id' | 'fio'>): boolean {
  if (ILCHENKO_USER_IDS.has((user.id || '').trim())) return true
  return (user.fio || '').toLowerCase().includes('ильченко')
}

/** Своя копия по названию → уже добавленная из библиотеки → добавить из каталога. */
export async function resolvePlannerAgentWorkflowId(): Promise<string> {
  const workflows = await api.listWorkflows()
  const own = workflows.find((item) => item.title.trim() === PLANNER_AGENT_TITLE)
  if (own?.id) return own.id

  const library = await fetchAgentLibrary({ force: true })
  const adopted = library.adopted.find((entry) => entry.title.trim() === PLANNER_AGENT_TITLE)
  const adoptedId = (adopted?.adoptedWorkflowId || adopted?.workflowId || '').trim()
  if (adoptedId) return adoptedId

  const catalog = library.catalog.find(
    (entry) => entry.workflowId === PLANNER_SOURCE_WORKFLOW_ID || entry.title.trim() === PLANNER_AGENT_TITLE
  )
  if (catalog?.workflowId) {
    if (catalog.alreadyAdded && catalog.adoptedWorkflowId?.trim()) return catalog.adoptedWorkflowId.trim()
    const copy = await adoptAgentFromLibrary(catalog.workflowId)
    const id = (copy.workflowId || '').trim()
    if (id) return id
  }

  throw new Error(`Агент «${PLANNER_AGENT_TITLE}» не найден. Обратитесь к администратору.`)
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : []
}

function parseMemo(raw: Record<string, unknown>): MemoRequest {
  const planned = raw.planned && typeof raw.planned === 'object' ? (raw.planned as Record<string, unknown>) : null
  const duration = Number(raw.duration_minutes)
  return {
    ref: text(raw.ref),
    number: text(raw.number),
    date: text(raw.date),
    status: text(raw.status),
    topic: text(raw.topic),
    purpose: text(raw.purpose),
    text: text(raw.text),
    kind: text(raw.kind),
    psdLevel: raw.psd_level === true,
    desiredDate: text(raw.desired_date),
    desiredInPast: raw.desired_in_past === true,
    startTime: text(raw.start_time),
    endTime: text(raw.end_time),
    durationMinutes: Number.isFinite(duration) && duration > 0 ? duration : null,
    place: text(raw.place),
    leader: text(raw.leader),
    author: text(raw.author),
    participants: list(raw.participants),
    agenda: list(raw.agenda),
    planned: planned
      ? {
          subject: text(planned.subject),
          start: text(planned.start),
          end: text(planned.end),
          location: text(planned.location)
        }
      : null
  }
}

export async function fetchMemoRequests(): Promise<{ ok: true; memos: MemoRequest[] } | { ok: false; error: string }> {
  const res = await api.invokeServerTool('meetings.memo_requests', {}, 180_000)
  if (!res.ok) return { ok: false, error: res.error || 'Не удалось загрузить служебные записки' }
  const rows = (res.result as { memos?: unknown } | undefined)?.memos
  const memos = Array.isArray(rows)
    ? rows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object').map(parseMemo)
    : []
  return { ok: true, memos }
}

export function formatDay(iso: string): string {
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return match ? `${match[3]}.${match[2]}.${match[1]}` : iso
}

export function memoWhen(memo: MemoRequest): string {
  const day = memo.desiredDate ? formatDay(memo.desiredDate) : 'дата не указана'
  const time = [memo.startTime, memo.endTime].filter(Boolean).join('–')
  return time ? `${day}, ${time}` : day
}

/** Задание агенту: номера выбранных записок и их данные, чтобы он не искал заново. */
export function buildPlannerMessage(memos: MemoRequest[]): string {
  const lines = [
    `Спланируй совещания по служебным запискам: ${memos.map((memo) => `№${memo.number}`).join(', ')}.`,
    '',
    'Выбранные записки:'
  ]
  for (const memo of memos) {
    lines.push(
      `- №${memo.number} от ${formatDay(memo.date)} — «${memo.topic || memo.purpose || 'без темы'}»; ` +
        `желаемое время: ${memoWhen(memo)}; место: ${memo.place || 'не указано'}; ` +
        `руководитель: ${memo.leader || 'не указан'}; участники: ${memo.participants.join(', ') || 'не указаны'}`
    )
  }
  lines.push(
    '',
    'Для каждой проверь занятость Амураля И.Б.: свободен — ставь на желаемое время, занят — предложи другое удобное время. ' +
      'Совещания создавай в календаре «Совещания» с участниками из записки и Амуралем И.Б.'
  )
  return lines.join('\n')
}
