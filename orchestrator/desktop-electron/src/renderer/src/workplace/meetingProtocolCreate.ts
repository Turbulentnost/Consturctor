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

/** Protocol card as returned by onec.meeting_protocols {ref_key} (backend read_protocol_form). */
export type OnecProtocolForm = {
  refKey: string
  number: string
  status: string
  posted: boolean
  editable: boolean
  form: {
    topic: string
    theme_key: string
    date: string
    time_start: string
    time_end: string
    room: string
    next_meeting_date: string
    leader: string
    responsible: string
    prepared_by: string
    meeting_type: string
    report_period_from: string
    report_period_to: string
    access: string
    department: string
    project: string
    participants: string[]
    agenda: { question: string; responsible: string }[]
    decisions: { text: string; due: string }[]
    tasks: { text: string; executor: string; due: string; priority: string; note: string; item?: string }[]
    comment: string
  }
}

function str(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function list(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map((item) => record(item)) : []
}

export function parseOnecProtocolForm(payload: unknown): OnecProtocolForm | null {
  const root = record(payload)
  const card = record(root.protocol && typeof root.protocol === 'object' ? root.protocol : root)
  const form = record(card.form)
  const refKey = str(card.ref_key)
  if (!refKey) return null
  return {
    refKey,
    number: str(card.number),
    status: str(card.status),
    posted: Boolean(card.posted),
    editable: card.editable === undefined ? !card.posted : Boolean(card.editable),
    form: {
      topic: str(form.topic),
      theme_key: str(form.theme_key),
      date: str(form.date),
      time_start: str(form.time_start),
      time_end: str(form.time_end),
      room: str(form.room),
      next_meeting_date: str(form.next_meeting_date),
      leader: str(form.leader),
      responsible: str(form.responsible),
      prepared_by: str(form.prepared_by),
      meeting_type: str(form.meeting_type),
      report_period_from: str(form.report_period_from),
      report_period_to: str(form.report_period_to),
      access: str(form.access),
      department: str(form.department),
      project: str(form.project),
      participants: Array.isArray(form.participants) ? form.participants.map((item) => str(item)).filter(Boolean) : [],
      agenda: list(form.agenda).map((row) => ({ question: str(row.question), responsible: str(row.responsible) })),
      decisions: list(form.decisions).map((row) => ({ text: str(row.text), due: str(row.due) })),
      tasks: list(form.tasks).map((row) => ({
        text: str(row.text),
        executor: str(row.executor),
        due: str(row.due),
        priority: str(row.priority),
        note: str(row.note),
        item: str(row.item) || undefined
      })),
      comment: str(form.comment)
    }
  }
}

export async function fetchProtocolForm(refKey: string): Promise<{ ok: true; card: OnecProtocolForm } | { ok: false; error: string }> {
  const key = refKey.trim()
  if (!key) return { ok: false, error: 'Нет ссылки на протокол в 1С' }
  const response = await api.invokeServerTool('onec.meeting_protocols', { meeting_kind: 'any', ref_key: key }, 60_000)
  if (!response.ok) return { ok: false, error: response.error || 'Не удалось прочитать протокол из 1С' }
  const card = parseOnecProtocolForm(response.result)
  if (!card) return { ok: false, error: 'Протокол не найден в 1С' }
  return { ok: true, card }
}

/** Strip the Outlook link marker so it is not shown / duplicated in the editable comment. */
export function stripOutlookMarker(comment: string): string {
  return comment
    .split(/\r?\n/)
    .filter((line) => !/^\s*outlook:\S+\s*$/.test(line))
    .join('\n')
    .replace(/\s*outlook:\S+/g, '')
    .trim()
}

export function draftFromOnecForm(card: OnecProtocolForm): ProtocolCreateDraft {
  const form = card.form
  const agenda = form.agenda
    .filter((row) => row.question)
    .map((row) => ({ key: newProtocolRowKey(), question: row.question, responsible: row.responsible }))
  const decisions = form.decisions
    .filter((row) => row.text)
    .map((row) => ({ key: newProtocolRowKey(), text: row.text, due: row.due }))
  const tasks = form.tasks
    .filter((row) => row.text)
    .map((row) => ({
      key: newProtocolRowKey(),
      text: row.text,
      executor: row.executor,
      due: row.due,
      priority: row.priority,
      note: row.note
    }))
  return {
    topic: form.topic,
    themeKey: form.theme_key,
    date: form.date,
    timeStart: form.time_start,
    timeEnd: form.time_end,
    room: form.room,
    nextMeetingDate: form.next_meeting_date,
    leader: form.leader,
    responsible: form.responsible,
    meetingType: form.meeting_type || 'Отчетное',
    reportFrom: form.report_period_from,
    reportTo: form.report_period_to,
    access: form.access,
    department: form.department,
    project: form.project,
    participants: form.participants.join('\n'),
    comment: stripOutlookMarker(form.comment),
    agenda: agenda.length ? agenda : [{ key: newProtocolRowKey(), question: '', responsible: '' }],
    decisions: decisions.length ? decisions : [{ key: newProtocolRowKey(), text: '', due: '' }],
    tasks: tasks.length
      ? tasks
      : [{ key: newProtocolRowKey(), text: '', executor: '', due: '', priority: '', note: '' }]
  }
}

type WriteArgs = { ok: true; args: Record<string, unknown> } | { ok: false; error: string }

function buildWriteArgs(draft: ProtocolCreateDraft, meetingId: string): WriteArgs {
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
  const comment = [stripOutlookMarker(draft.comment), marker].filter(Boolean).join('\n')

  const args: Record<string, unknown> = {
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
  return { ok: true, args }
}

async function invokeProtocolWrite(args: Record<string, unknown>, failMessage: string): Promise<ProtocolCreateResult> {
  const response = await api.invokeServerTool('onec.meeting_protocol_write', args, 180_000)
  if (!response.ok) {
    return { ok: false, error: response.error || failMessage }
  }
  const payload = record(response.result)
  const unresolved = Array.isArray(payload.unresolved) ? payload.unresolved.map((item) => String(item)) : []
  return {
    ok: true,
    number: str(payload.number) || undefined,
    refKey: str(payload.ref_key || payload.erp_document_id) || undefined,
    summary: str(payload.summary) || undefined,
    unresolved
  }
}

export async function createProtocolInOneC(
  draft: ProtocolCreateDraft,
  meetingId: string
): Promise<ProtocolCreateResult> {
  const built = buildWriteArgs(draft, meetingId)
  if (!built.ok) return { ok: false, error: built.error }
  return invokeProtocolWrite({ action: 'create', ...built.args }, 'Не удалось создать протокол в 1С')
}

export async function updateProtocolInOneC(
  draft: ProtocolCreateDraft,
  refKey: string,
  meetingId: string
): Promise<ProtocolCreateResult> {
  const key = refKey.trim()
  if (!key) return { ok: false, error: 'Нет ссылки на протокол в 1С' }
  const built = buildWriteArgs(draft, meetingId)
  if (!built.ok) return { ok: false, error: built.error }
  return invokeProtocolWrite({ action: 'update', ref_key: key, ...built.args }, 'Не удалось сохранить протокол в 1С')
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
