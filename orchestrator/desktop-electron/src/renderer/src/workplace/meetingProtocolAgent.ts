import { api } from '../api/client'
import type { MeetingEvent } from '../utils/outlookMeetings'
import { formatMeetingStamp } from '../utils/outlookMeetings'
import { adoptAgentFromLibrary, fetchAgentLibrary } from './agentLibraryApi'

export const PROTOCOL_SOURCE_WORKFLOW_ID = '599eaf4e-3b0c-4a6f-a370-c719e11a44ce'
export const PROTOCOL_AGENT_TITLE = 'Формирование протокола по аудиозаписи совещания'

/**
 * Resolve the workflow id to run for meeting-protocol generation:
 * adopted copy by title → catalog source → adopt → listWorkflows by title.
 */
export async function resolveProtocolAgentWorkflowId(): Promise<string> {
  const library = await fetchAgentLibrary({ force: true })

  const adopted = library.adopted.find((entry) => entry.title.trim() === PROTOCOL_AGENT_TITLE)
  const adoptedId = (adopted?.adoptedWorkflowId || adopted?.workflowId || '').trim()
  if (adoptedId && adoptedId !== PROTOCOL_SOURCE_WORKFLOW_ID) return adoptedId
  if (adoptedId) return adoptedId

  const catalog = library.catalog.find((entry) => entry.workflowId === PROTOCOL_SOURCE_WORKFLOW_ID)
  if (catalog?.workflowId) {
    if (catalog.alreadyAdded && catalog.adoptedWorkflowId?.trim()) {
      return catalog.adoptedWorkflowId.trim()
    }
    const adoptedCopy = await adoptAgentFromLibrary(PROTOCOL_SOURCE_WORKFLOW_ID)
    const id = (adoptedCopy.workflowId || '').trim()
    if (id) return id
  }

  const workflows = await api.listWorkflows()
  const byTitle = workflows.find((item) => item.title.trim() === PROTOCOL_AGENT_TITLE)
  if (byTitle?.id) return byTitle.id

  throw new Error(
    `Агент «${PROTOCOL_AGENT_TITLE}» не найден в библиотеке. Добавьте его из каталога или обратитесь к администратору.`
  )
}

function field(value: string | undefined): string {
  const text = (value || '').trim()
  return text || '—'
}

function attendeesList(meeting: MeetingEvent): string {
  const parts = (meeting.attendees || '')
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)
  return parts.length ? parts.map((name) => `- ${name}`).join('\n') : '—'
}

/** Russian task message with Outlook meeting fields and absolute audio path. */
export function buildProtocolMessage(meeting: MeetingEvent, audioPath: string): string {
  const when = formatMeetingStamp(meeting.start)
  const end = meeting.end ? formatMeetingStamp(meeting.end) : ''
  const period = end ? `${when} – ${end}` : when
  return [
    'Сформируй протокол совещания по приложенной аудиозаписи.',
    '',
    'Данные совещания из календаря Outlook:',
    `Тема: ${field(meeting.subject)}`,
    `Дата / время: ${period}`,
    `Организатор: ${field(meeting.organizer)}`,
    'Участники:',
    attendeesList(meeting),
    '',
    `Абсолютный путь к аудиофайлу: ${audioPath}`,
    '',
    'Используй данные календаря для темы протокола и сопоставления говорящих.',
    'Итоговый отчёт сохрани в формате docx через report.export_document.'
  ].join('\n')
}
