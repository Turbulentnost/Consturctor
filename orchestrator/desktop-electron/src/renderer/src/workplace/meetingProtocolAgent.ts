import { api } from '../api/client'
import { formatMeetingStamp, meetingOutlookMarker, type MeetingEvent } from '../utils/outlookMeetings'
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

export type ExistingProtocol = {
  number: string
  refKey: string
  /** Черновик «Подготовлен»: перезаписывается целиком; проведённый — только задачи в регистр. */
  editable: boolean
  form: Record<string, unknown>
}

function protocolSnapshot(form: Record<string, unknown>): string {
  const pick = (key: string): unknown => form[key]
  return JSON.stringify(
    {
      topic: pick('topic'),
      date: pick('date'),
      time_start: pick('time_start'),
      time_end: pick('time_end'),
      room: pick('room'),
      leader: pick('leader'),
      responsible: pick('responsible'),
      next_meeting_date: pick('next_meeting_date'),
      participants: pick('participants'),
      agenda: pick('agenda'),
      decisions: pick('decisions'),
      tasks: pick('tasks'),
      comment: pick('comment')
    },
    null,
    2
  )
}

/** Task for supplementing an existing 1С protocol with one more meeting recording. */
export function buildSupplementMessage(
  meeting: MeetingEvent,
  audioPath: string,
  protocol: ExistingProtocol
): string {
  const when = formatMeetingStamp(meeting.start)
  const steps = protocol.editable
    ? [
        '2. Сверь расшифровку с текущим протоколом:',
        '   — задачи: дополни недостающие поручения; исправь исполнителя, срок и формулировку, если в записи прозвучало иначе; существующие задачи без оснований не удаляй;',
        '   — решения и повестка: добавь новые пункты, уточни формулировки;',
        '   — участники, руководитель, дата следующего совещания: дополни и исправь по записи.',
        '   Бери только прозвучавшее в записи, не домысливай.',
        '3. Покажи человеку список изменений: что добавлено, что исправлено (было → стало), что оставлено без изменений.',
        `4. После подтверждения вызови onec.meeting_protocol_write action="update" ref_key="${protocol.refKey}" один раз. Табличные части перезаписываются целиком, поэтому передай ПОЛНЫЕ списки participants, agenda, decisions, tasks: существующие строки из текущего содержимого плюс добавленные и исправленные. Остальные поля шапки передай как в текущем содержимом, с исправлениями. В comment сохрани прежний текст (включая строку outlook:…) и добавь строку «Дополнено ИИ-агентом по аудиозаписи <имя файла>».`
      ]
    : [
        '2. Протокол уже проведён: документ не перезаписывается, задачи живут в регистре задач протоколов (tasks в текущем содержимом, у каждой id). Сверь расшифровку с задачами:',
        '   — новые поручения из записи, которых нет в протоколе, — добавить;',
        '   — у задачи с sent=false или process_started=false исполнитель, срок или формулировка прозвучали иначе — исправить по её id;',
        '   — задачи с sent=true / process_started=true не трогай, расхождения по ним только перечисли человеку.',
        '   Решения, повестку и участников в проведённом протоколе не меняй — изменения по ним перечисли человеку, их вносят в 1С.',
        '   Бери только прозвучавшее в записи, не домысливай.',
        '3. Покажи человеку список: какие задачи добавятся, какие исправятся (было → стало), что надо поправить в 1С вручную.',
        `4. После подтверждения вызови onec.meeting_protocol_write action="add_tasks" ref_key="${protocol.refKey}" один раз. В tasks передай ТОЛЬКО новые задачи {text, executor, due} и правки {id, text?, executor?, due?}; задачи без изменений не передавай. Проверь в ответе added / changed / errors / unresolved и сообщи человеку.`
      ]
  return [
    `Дополни существующий протокол совещания ${protocol.number || ''} в 1С по новой аудиозаписи. Новый протокол не создавай.`,
    '',
    `Совещание: ${field(meeting.subject)}, ${when}`,
    'Участники из Outlook:',
    attendeesList(meeting),
    '',
    `Абсолютный путь к аудиофайлу: ${audioPath}`,
    `Ref_Key протокола в 1С: ${protocol.refKey}`,
    '',
    'Текущее содержимое протокола (прочитано из 1С перед запуском):',
    '```json',
    protocolSnapshot(protocol.form),
    '```',
    '',
    'Порядок работы:',
    '1. audio.transcribe один раз для приложенного аудио (names — участники из Outlook), прочитай расшифровку.',
    ...steps,
    '5. notify.send — только исполнителям новых или изменённых задач (суть, срок, номер протокола).',
    '6. Файл протокола пересобери через report.export_document (protocol-<дата>.docx) по обновлённому содержимому, раздел «Диалоги» — по новой записи.'
  ].join('\n')
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
    `Идентификатор совещания Outlook: ${meeting.id || '—'}`,
    '',
    `Абсолютный путь к аудиофайлу: ${audioPath}`,
    '',
    'Используй данные календаря для темы протокола и сопоставления говорящих.',
    'Итоговый отчёт сохрани в формате docx через report.export_document.',
    meetingOutlookMarker(meeting)
      ? `В comment протокола 1С (onec.meeting_protocol_write) отдельной строкой добавь метку ${meetingOutlookMarker(meeting)} — по ней совещание в календаре связывается с документом (дата в метке обязательна).`
      : ''
  ]
    .filter((line, index, all) => line !== '' || index === 0 || all[index - 1] !== '')
    .join('\n')
    .trimEnd()
}
