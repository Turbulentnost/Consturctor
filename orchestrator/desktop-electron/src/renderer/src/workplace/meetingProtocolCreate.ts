import { api } from '../api/client'
import { parseMeetingTime, type MeetingEvent } from '../utils/outlookMeetings'

export type ProtocolQuestionDraft = {
  key: string
  question: string
  responsible: string
}

export type ProtocolDecisionDraft = {
  key: string
  text: string
  due: string
}

export type ProtocolTaskDraft = {
  key: string
  text: string
  executor: string
  due: string
  priority: string
  note: string
}

export type ProtocolCreateDraft = {
  topic: string
  themeKey: string
  date: string
  timeStart: string
  timeEnd: string
  room: string
  nextMeetingDate: string
  leader: string
  responsible: string
  meetingType: string
  reportFrom: string
  reportTo: string
  access: string
  department: string
  project: string
  participants: string
  comment: string
  agenda: ProtocolQuestionDraft[]
  decisions: ProtocolDecisionDraft[]
  tasks: ProtocolTaskDraft[]
}

export type ProtocolCreateResult = {
  ok: boolean
  number?: string
  refKey?: string
  summary?: string
  unresolved?: string[]
  error?: string
}

export function newProtocolRowKey(): string {
  return `row-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function dateInput(raw: string): string {
  const parsed = parseMeetingTime(raw)
  if (!parsed) return ''
  return `${parsed.getFullYear()}-${pad2(parsed.getMonth() + 1)}-${pad2(parsed.getDate())}`
}

function timeInput(raw: string): string {
  const parsed = parseMeetingTime(raw)
  if (!parsed) return ''
  return `${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}`
}

function personName(value: string): string {
  const text = value.trim()
  if (!text || text.includes('@') || text.includes('http')) return ''
  return text
}

export function draftFromMeeting(meeting: MeetingEvent, actorFio: string): ProtocolCreateDraft {
  const organizer = personName(meeting.organizer)
  return {
    topic: (meeting.subject || '').trim(),
    themeKey: '',
    date: dateInput(meeting.start),
    timeStart: timeInput(meeting.start),
    timeEnd: timeInput(meeting.end),
    room: (meeting.location || '').trim(),
    nextMeetingDate: '',
    leader: organizer || actorFio.trim(),
    responsible: '',
    meetingType: 'Отчетное',
    reportFrom: '',
    reportTo: '',
    access: 'Общий',
    department: '',
    project: '',
    participants: (meeting.attendees || '')
      .split(/[,;\n]/)
      .map((part) => personName(part))
      .filter(Boolean)
      .join('\n'),
    comment: '',
    agenda: [{ key: newProtocolRowKey(), question: '', responsible: '' }],
    decisions: [{ key: newProtocolRowKey(), text: '', due: '' }],
    tasks: [{ key: newProtocolRowKey(), text: '', executor: '', due: '', priority: '', note: '' }]
  }
}

function lines(value: string): string[] {
  return value
    .split(/\n/)
    .map((part) => part.trim())
    .filter(Boolean)
}

export async function createProtocolInOneC(
  draft: ProtocolCreateDraft,
  meetingId: string
): Promise<ProtocolCreateResult> {
  const topic = draft.topic.trim()
  const date = draft.date.trim()
  if (!topic) return { ok: false, error: 'Укажите тему совещания' }
  if (!date) return { ok: false, error: 'Укажите дату совещания' }

  const agenda = draft.agenda
    .map((row) => ({ question: row.question.trim(), responsible: row.responsible.trim() }))
    .filter((row) => row.question)
  const decisions = draft.decisions
    .map((row) => ({ text: row.text.trim(), due: row.due.trim() }))
    .filter((row) => row.text)
  const tasks = draft.tasks
    .map((row) => ({
      text: row.text.trim(),
      executor: row.executor.trim(),
      due: row.due.trim(),
      priority: row.priority.trim(),
      note: row.note.trim()
    }))
    .filter((row) => row.text)

  if (!agenda.length && !decisions.length && !tasks.length) {
    return { ok: false, error: 'Добавьте повестку, решение или задачу — пустой протокол в 1С не создаётся' }
  }

  const marker = meetingId.trim() ? `outlook:${meetingId.trim()}` : ''
  const comment = [draft.comment.trim(), marker].filter(Boolean).join('\n')

  const args: Record<string, unknown> = {
    action: 'create',
    topic,
    date,
    meeting_type: draft.meetingType.trim() || 'Отчетное',
    access: draft.access.trim() || 'Общий',
    participants: lines(draft.participants),
    agenda,
    decisions,
    tasks,
    comment
  }
  if (draft.themeKey.trim()) args.theme_key = draft.themeKey.trim()
  if (draft.timeStart.trim()) args.time_start = draft.timeStart.trim()
  if (draft.timeEnd.trim()) args.time_end = draft.timeEnd.trim()
  if (draft.room.trim()) args.room = draft.room.trim()
  if (draft.nextMeetingDate.trim()) args.next_meeting_date = draft.nextMeetingDate.trim()
  if (draft.leader.trim()) args.leader = draft.leader.trim()
  if (draft.responsible.trim()) args.responsible = draft.responsible.trim()
  if (draft.department.trim()) args.department = draft.department.trim()
  if (draft.project.trim()) args.project = draft.project.trim()
  if (draft.reportFrom.trim()) args.report_period_from = draft.reportFrom.trim()
  if (draft.reportTo.trim()) args.report_period_to = draft.reportTo.trim()

  const response = await api.invokeServerTool('onec.meeting_protocol_write', args, 180_000)
  if (!response.ok) {
    return { ok: false, error: response.error || 'Не удалось создать протокол в 1С' }
  }
  const payload =
    response.result && typeof response.result === 'object'
      ? (response.result as Record<string, unknown>)
      : {}
  const unresolved = Array.isArray(payload.unresolved) ? payload.unresolved.map((item) => String(item)) : []
  return {
    ok: true,
    number: String(payload.number || '').trim() || undefined,
    refKey: String(payload.ref_key || payload.erp_document_id || '').trim() || undefined,
    summary: String(payload.summary || '').trim() || undefined,
    unresolved
  }
}

export type ThemeHint = { key: string; title: string }

export async function searchMeetingThemes(query: string): Promise<ThemeHint[]> {
  const text = query.trim().replace(/'/g, "''")
  if (text.length < 3) return []
  const response = await api.invokeServerTool(
    'onec.odata_get',
    {
      entity: 'Catalog_ТД_ТемыСовещаний',
      filter: `substringof('${text}', Description) and DeletionMark eq false`,
      top: 8
    },
    30_000
  )
  if (!response.ok || !response.result || typeof response.result !== 'object') return []
  const root = response.result as Record<string, unknown>
  const nested = root.data && typeof root.data === 'object' ? (root.data as Record<string, unknown>) : root
  const rows = (Array.isArray(nested.value) ? nested.value : Array.isArray(root.value) ? root.value : []) as Record<
    string,
    unknown
  >[]
  return rows
    .map((row) => ({ key: String(row.Ref_Key || '').trim(), title: String(row.Description || '').trim() }))
    .filter((row) => row.title)
    .slice(0, 8)
}
