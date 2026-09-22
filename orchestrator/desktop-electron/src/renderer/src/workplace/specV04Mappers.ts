import type { WorkplaceAgent } from './WorkplaceBoard'
import type { SpecMailRow, SpecPillTone, SpecProcessRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { parseIso, sameDay } from '../utils/calendar'
import { personNameMatches } from './turboAssigneeMatch'

function toneForStatus(text: string): SpecPillTone {
  const key = text.toLowerCase()
  if (key.includes('просроч') || key.includes('ошиб')) return 'red'
  if (key.includes('ожид') || key.includes('провер')) return 'orange'
  if (key.includes('выполн') || key.includes('готов')) return 'green'
  if (key.includes('работ')) return 'blue'
  return 'gray'
}

function whoFromDocflowRole(role: string): string {
  if (role === 'author') return 'от меня'
  if (role === 'both') return 'Я / от меня'
  return 'Я'
}

function looksLikeDocflowNumber(text: string): boolean {
  const value = text.trim()
  if (!value) return false
  return /^(до|do)[-.\s]?\d/i.test(value) || /^\d{5,}$/.test(value)
}

function stripDocflowNumber(text: string, number: string): string {
  let value = text.trim()
  if (number) {
    const escaped = number.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    value = value.replace(new RegExp(`^${escaped}\\s*[·•\\-:]*\\s*`, 'i'), '').trim()
  }
  return value.replace(/^(до|do)[-.\s]?\d[\d.\-]*\s*[·•\-:]*\s*/i, '').trim()
}

function isGenericDocflowStub(text: string): boolean {
  return /^(не согласовано|завершена|выполнена|открыта)$/i.test(text.trim())
}

/** Текст задачи без номера ДО-…: description / comment / step. */
export function erpTaskContentTitle(task: Record<string, unknown>): string {
  const number = String(task.number || '').trim()
  const candidates = [
    String(task.title || '').trim(),
    String(task.comment || '').trim(),
    String(task.approval || '').trim()
  ]
  for (const raw of candidates) {
    const cleaned = stripDocflowNumber(raw, number)
    if (cleaned && !looksLikeDocflowNumber(cleaned) && !isGenericDocflowStub(cleaned)) {
      return cleaned
    }
  }
  for (const raw of candidates) {
    const cleaned = stripDocflowNumber(raw, number)
    if (cleaned && !looksLikeDocflowNumber(cleaned)) return cleaned
  }
  return 'Задача 1С'
}

export function erpTaskToRow(task: Record<string, unknown>, actorFio: string): SpecTaskRow {
  const refKey = String(task.ref_key || task.refKey || '').trim()
  const number = String(task.number || '').trim()
  const title = erpTaskContentTitle(task)
  const due = String(task.due_at || task.due || task.dueDate || '').trim()
  const done = Boolean(task.done)
  const late = Boolean(task.late)
  const taskSource = String(task.source || 'erp_pm').trim().toLowerCase()
  const role = String(task.role || '').trim().toLowerCase()
  const author = String(task.author || '').trim()
  const performer = String(task.performer || '').trim()
  const channel = String(task.channel || '').trim()
  const isDocflow = taskSource.includes('документооборот') || taskSource.includes('docflow')
  let sourceLabel = '1С ERP'
  if (isDocflow) {
    sourceLabel = taskSource.includes('от меня') || role === 'author' || role === 'both'
      ? '1С ДО (от меня)'
      : '1С ДО'
  } else if (taskSource.includes('odata')) {
    sourceLabel = '1С ERP (OData)'
  }
  const step = String(task.step || task.approval || '').trim()
  return {
    id: refKey || number || title,
    title,
    source: sourceLabel,
    sourceTone: isDocflow ? 'green' : 'blue',
    process: String(task.comment || step || task.approval || '—'),
    project: '—',
    deadline: formatTaskDeadline(due),
    urgent: late,
    priority: late ? 'Высокий' : 'Средний',
    priorityTone: late ? 'red' : 'orange',
    status: done ? 'Выполнена' : 'В работе',
    statusTone: done ? 'green' : 'blue',
    executor: performer || actorFio,
    who: isDocflow ? whoFromDocflowRole(role) : 'Я',
    progress: done ? 100 : 40,
    author: author || undefined,
    performer: performer || undefined,
    channel: channel || (isDocflow ? 'soap' : undefined),
    role: role || undefined,
    sourceKind: isDocflow ? 'docflow' : 'erp',
    refKey: refKey || undefined,
    taskNumber: number || undefined,
    step: step || undefined,
    targetId: String(task.target_id || task.targetId || '').trim() || undefined
  }
}

export function erpTaskToProcessRow(task: SpecTaskRow): SpecProcessRow {
  return {
    id: `erp:${task.id}`,
    name: task.title,
    code: task.id,
    type: 'Задача из 1С',
    typeTone: 'blue',
    source: '1С',
    project: task.project,
    taskToday: task.process,
    status: task.status,
    statusTone: task.statusTone,
    deadline: task.deadline,
    deadlineUrgent: task.urgent,
    progress: task.progress
  }
}

export function turboProjectToProcessRow(project: SpecProjectRow): SpecProcessRow {
  return {
    id: `proj:${project.id}`,
    name: project.name,
    code: project.code,
    type: 'Проект',
    typeTone: 'purple',
    source: 'TurboProject',
    project: project.name,
    taskToday: `${project.tasks} открытых задач`,
    status: project.status,
    statusTone: project.statusTone,
    deadline: project.deadline,
    progress: project.progress
  }
}

export function mailRowToProcessRow(mail: SpecMailRow, index: number): SpecProcessRow {
  return {
    id: `mail:${mail.id || index}`,
    name: mail.subject,
    code: `ML-${String(index + 1).padStart(2, '0')}`,
    type: 'Письмо',
    typeTone: 'orange',
    source: 'Outlook',
    project: '—',
    taskToday: 'Ответить / обработать',
    status: mail.status,
    statusTone: mail.stTone,
    deadline: mail.time ? 'Сегодня' : '—',
    progress: 35
  }
}

export function meetingToProcessRow(meeting: {
  id: string
  subject: string
  start: string
}): SpecProcessRow {
  return {
    id: `meet:${meeting.id}:${meeting.start || ''}`,
    name: meeting.subject,
    code: 'MTG',
    type: 'Совещание',
    typeTone: 'purple',
    source: 'Outlook',
    project: '—',
    taskToday: 'Подготовиться',
    status: 'Не начат',
    statusTone: 'gray',
    deadline: meeting.start ? meeting.start.slice(0, 16) : '—',
    progress: 20
  }
}

export function agentToProcessRow(agent: WorkplaceAgent): SpecProcessRow {
  const progress =
    agent.status === 'COMPLETED' ? 100 : agent.status === 'READY' ? 0 : agent.status === 'ACTIVE' ? 55 : 30
  return {
    id: agent.workflowId,
    name: agent.name,
    code: agent.code || agent.workflowId.slice(0, 8),
    type: 'Регламент',
    typeTone: 'green',
    source: 'Оркестратор',
    project: '—',
    taskToday: agent.stage || '—',
    status:
      agent.status === 'ACTIVE'
        ? 'В работе'
        : agent.status === 'WAITING_HUMAN'
          ? 'Ожидает'
          : agent.status === 'COMPLETED'
            ? 'Выполнен'
            : 'В работе',
    statusTone: agent.status === 'WAITING_HUMAN' ? 'orange' : 'blue',
    deadline: agent.due && agent.due !== 'нет слота' ? agent.due : '—',
    progress
  }
}

function turboOpenTaskCount(item: Record<string, unknown>): number {
  const stats = item.task_stats as Record<string, unknown> | undefined
  if (stats) {
    const nonSummary = Number(stats.non_summary_tasks ?? 0)
    const completed = Number(stats.completed_tasks ?? 0)
    if (Number.isFinite(nonSummary) && nonSummary > 0) {
      return Math.max(0, nonSummary - (Number.isFinite(completed) ? completed : 0))
    }
    const open = Number(stats.open_tasks ?? stats.open_tasks_count ?? 0)
    if (Number.isFinite(open) && open > 0) return open
  }
  const direct = Number(item.open_tasks ?? item.tasks_count ?? 0)
  return Number.isFinite(direct) && direct > 0 ? direct : 0
}

function turboProjectDeadline(item: Record<string, unknown>): string {
  const dates = item.dates as Record<string, unknown> | undefined
  const fromDates = dates?.finish_date || dates?.plan_finish_1c
  if (fromDates) return String(fromDates)
  const data1c = item.data_1c as Record<string, unknown> | undefined
  if (data1c?.planovaya_data_okonchaniya) return String(data1c.planovaya_data_okonchaniya)
  if (data1c?.data_okonchaniya) return String(data1c.data_okonchaniya)
  return String(item.finish_date || item.deadline || '—')
}

function turboProjectRole(item: Record<string, unknown>, actorFio: string): string {
  const actor = actorFio.trim().toLowerCase()
  const owner = String(item.owner || '').trim()
  const curator = String(item.curator || '').trim()
  const customer = String(item.customer || '').trim()
  const match = (value: string, label: string): string | null => {
    if (!value || !actor) return null
    return value.toLowerCase().includes(actor.split(/\s+/)[0] || actor) ? label : null
  }
  return (
    match(owner, 'Руководитель') ||
    match(curator, 'Куратор') ||
    match(customer, 'Заказчик') ||
    String(item.role || item.participant_role || 'Участник')
  )
}

/** Руководитель проекта: роль из 1С/Turbo или совпадение ФИО с полем руководителя. */
export function isTurboProjectManager(
  project: Pick<SpecProjectRow, 'role' | 'manager'>,
  actorFio: string
): boolean {
  if (/руковод/i.test(project.role || '')) return true
  const manager = (project.manager || '').trim()
  const fio = actorFio.trim()
  if (!fio || !manager) return false
  return personNameMatches(fio, manager) || personNameMatches(fio, manager, 'surname')
}

/** Открытая задача Turbo: срок выбранного дня или просрочка (delay_days). */
export function isRawTurboTodayOrOverdue(task: Record<string, unknown>, day: Date): boolean {
  const percent = Number(task.percent_complete ?? 0)
  if (Number.isFinite(percent) && percent >= 1) return false
  const delay = Number(task.delay_days ?? 0)
  if (Number.isFinite(delay) && delay > 0) return true
  const finish = String(task.finish_date || '').trim()
  if (!finish) return false
  const stamp = parseIso(finish) || parseIso(finish.replace(' ', 'T'))
  return stamp ? sameDay(stamp, day) : false
}

export function isOutlookMailFromMe(row: SpecMailRow): boolean {
  return /отправлен/i.test(row.category || '') || row.status === 'Отправлено'
}

export function mailPartyLabel(row: SpecMailRow): string {
  const sent = isOutlookMailFromMe(row)
  const to = (row.to || '').trim()
  if (sent && to) return to
  return row.sender
}

/** Compact deadline for narrow today tiles: `16.09`, not a clipped ISO string. */
function formatTaskDeadline(raw: string): string {
  const value = (raw || '').trim()
  if (!value || value === '—' || value.startsWith('0001-01-01')) return '—'
  const iso = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) return `${iso[3]}.${iso[2]}`
  const stamp = parseIso(value) || parseIso(value.replace(' ', 'T'))
  if (!stamp) return value.length > 10 ? value.slice(0, 10) : value
  const dd = String(stamp.getDate()).padStart(2, '0')
  const mm = String(stamp.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}`
}

function formatTurboTaskDeadline(raw: string): string {
  return formatTaskDeadline(raw)
}

function turboTaskStatusLabel(percent: number, delayDays: number): string {
  if (percent >= 1) return 'Выполнена'
  if (delayDays > 0) return 'Просрочена'
  if (percent > 0) return 'В работе'
  return 'Запланировано'
}

/** Turbo MPP percent_complete is 0–1; some payloads use 0–100. */
export function turboTaskProgressDisplay(task: Record<string, unknown>): number {
  const raw = Number(task.percent_complete ?? 0)
  if (!Number.isFinite(raw)) return 0
  if (raw > 0 && raw <= 1) return Math.round(raw * 100)
  return Math.round(Math.min(100, raw))
}

function turboTaskAssigneeLabel(
  executors: string[],
  actorFio: string
): { label: string; tone: SpecPillTone } {
  const first = (executors[0] || '').trim()
  if (!first) return { label: '—', tone: 'gray' }
  if (/^(ии|ai|агент)/i.test(first)) return { label: 'ИИ', tone: 'purple' }
  const actor = actorFio.trim().toLowerCase()
  if (actor && first.toLowerCase().includes(actor.split(/\s+/)[0] || '')) {
    return { label: 'Сотрудник', tone: 'blue' }
  }
  return { label: first, tone: 'blue' }
}

/** TurboProject open task → row for вкладка «Задачи». */
export function turboProjectTaskToSpecTaskRow(
  task: Record<string, unknown>,
  projectId: string,
  projectName: string,
  actorFio: string,
  turboScope: SpecTaskRow['turboScope'] = 'mine'
): SpecTaskRow {
  const mini = turboProjectTaskToTodayRow(task, projectId, actorFio)
  const delayDays = Number(task.delay_days ?? 0)
  const uid = String(task.uid ?? task.id ?? mini.id).trim()
  return {
    id: `turbo:${projectId}:${mini.id}`,
    title: mini.title,
    source: 'TurboProject',
    sourceTone: 'purple',
    process: projectName || `Проект ${projectId}`,
    project: projectName || projectId,
    deadline: mini.deadline,
    urgent: Number.isFinite(delayDays) && delayDays > 0,
    priority: delayDays > 0 ? 'Высокий' : 'Средний',
    priorityTone: delayDays > 0 ? 'red' : 'orange',
    status: mini.status,
    statusTone: mini.statusTone,
    executor: actorFio,
    who: mini.assignee,
    progress: turboTaskProgressDisplay(task),
    turboScope,
    sourceKind: 'turbo',
    projectId,
    taskUid: uid
  }
}

/** TurboProject open task row for «Сегодня → проектные задачи». */
export function turboProjectTaskToTodayRow(
  task: Record<string, unknown>,
  projectId: string,
  actorFio: string
): {
  id: string
  title: string
  deadline: string
  status: string
  statusTone: SpecPillTone
  assignee: string
  assigneeTone: SpecPillTone
  progress: number
} {
  const percent = Number(task.percent_complete ?? 0)
  const delayDays = Number(task.delay_days ?? 0)
  const status = turboTaskStatusLabel(
    Number.isFinite(percent) ? percent : 0,
    Number.isFinite(delayDays) ? delayDays : 0
  )
  const executors = Array.isArray(task.executors)
    ? task.executors.filter((item): item is string => typeof item === 'string')
    : []
  const { label, tone } = turboTaskAssigneeLabel(executors, actorFio)
  const outline = String(task.outline_number ?? task.wbs ?? '').trim()
  const name = String(task.name || 'Задача').trim()
  const title = outline && !name.includes(outline) ? `${outline} · ${name}` : name
  const uid = String(task.uid ?? task.id ?? `${projectId}:${name}`).trim()
  const id = uid
  return {
    id,
    title,
    deadline: formatTurboTaskDeadline(String(task.finish_date || '')),
    status,
    statusTone: toneForStatus(status),
    assignee: label,
    assigneeTone: tone,
    progress: turboTaskProgressDisplay(task),
    projectId,
    taskUid: uid
  }
}

export function turboProjectToRow(item: Record<string, unknown>, actorFio = ''): SpecProjectRow {
  const name = String(item.project_name || item.title || item.name || 'Проект').trim()
  const fileId = String(item.file_id || item.fileId || '').trim()
  const data1c = item.data_1c as Record<string, unknown> | undefined
  const code =
    String(item.project_code || data1c?.nomer_proekta || fileId || item.id || '').trim() || '—'
  const progressRaw = Number(item.percent_complete ?? item.progress ?? 0)
  const progress = Number.isFinite(progressRaw) ? Math.round(progressRaw) : 0
  const stats = item.task_stats as Record<string, unknown> | undefined
  const overdueCount = Number(stats?.overdue_tasks_count ?? 0)
  const risk = String(item.risk || item.status_risk || '').toLowerCase()
  let riskLabel = 'Нет'
  let riskTone: SpecPillTone = 'green'
  if (overdueCount > 0 || risk.includes('high') || risk.includes('высок')) {
    riskLabel = overdueCount > 0 ? `Просрочек: ${overdueCount}` : 'Высокий'
    riskTone = 'red'
  } else if (risk.includes('risk') || risk.includes('риск')) {
    riskLabel = 'Есть риск'
    riskTone = 'orange'
  }
  const openTasks = turboOpenTaskCount(item)
  const manager = String(item.owner || data1c?.rukovoditel || data1c?.rukovoditel_proekta || '').trim()
  const rawUrl = String(item.url || item.web_url || item.link || item.project_url || '').trim()
  const url = /^https?:\/\//i.test(rawUrl) ? rawUrl : undefined
  return {
    id: fileId || code,
    name,
    code,
    role: turboProjectRole(item, actorFio),
    tasks: openTasks,
    status: String(data1c?.status_proekta || item.status || 'В работе'),
    statusTone: 'blue',
    deadline: turboProjectDeadline(item),
    progress,
    risk: riskLabel,
    riskTone,
    fileId: fileId || undefined,
    manager: manager || undefined,
    url
  }
}

export function outlookMessageToMailRow(msg: Record<string, unknown>, index: number): SpecMailRow {
  const subject = String(msg.subject || 'Без темы')
  const rawTime = String(msg.datetime || msg.received_at || msg.sent_at || '')
  const direction = String(msg.direction || 'inbox')
  const entryId = String(msg.entry_id ?? msg.uid ?? index)
  const unread = Boolean(msg.unread)
  const attachmentNames = Array.isArray(msg.attachment_names)
    ? msg.attachment_names.map((n) => String(n)).filter(Boolean)
    : []
  const bodyPreview = String(msg.body_preview || '').trim()
  const inboxStatus = unread ? 'Непрочитано' : 'Прочитано'
  const to = String(msg.to || msg.recipients || '').trim()
  return {
    id: entryId,
    entryId,
    channel: 'outlook',
    sender: String(msg.sender || msg.from || '—'),
    to: to || undefined,
    subject,
    category: direction === 'sent' ? 'Отправленные' : 'Входящие',
    catTone: 'blue',
    link: attachmentNames.length ? `Вложений: ${attachmentNames.length}` : '—',
    time: rawTime,
    receivedAt: rawTime || undefined,
    priority: unread ? 'Высокий' : 'Средний',
    priTone: unread ? 'red' : 'orange',
    status: direction === 'sent' ? 'Отправлено' : inboxStatus,
    stTone: direction === 'sent' ? 'green' : unread ? 'orange' : 'blue',
    assignee: '—',
    unread,
    bodyPreview: bodyPreview || undefined,
    attachmentNames: attachmentNames.length ? attachmentNames : undefined
  }
}

export function imapMessageToMailRow(msg: Record<string, unknown>, index: number): SpecMailRow {
  const subject = String(msg.subject || 'Без темы')
  const uidRaw = Number(msg.uid)
  const uid = Number.isFinite(uidRaw) && uidRaw > 0 ? uidRaw : 0
  const messageId = String(msg.message_id || msg.messageId || '').trim()
  const unread = Boolean(msg.unread)
  return {
    id: uid ? `imap:${uid}` : `imap:${index}`,
    imapUid: uid || undefined,
    messageId: messageId || undefined,
    channel: 'imap',
    sender: String(msg.from || msg.sender || '—'),
    subject,
    category: 'Входящие',
    catTone: 'blue',
    link: '—',
    time: String(msg.date || msg.received_at || ''),
    receivedAt: String(msg.date || msg.received_at || '') || undefined,
    priority: unread ? 'Высокий' : 'Средний',
    priTone: unread ? 'red' : 'orange',
    status: unread ? 'Непрочитано' : 'К обработке',
    stTone: unread ? 'orange' : 'blue',
    assignee: '—',
    unread
  }
}

export { toneForStatus }
