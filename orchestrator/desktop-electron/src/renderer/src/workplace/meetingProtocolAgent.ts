import { api } from '../api/client'
import { formatMeetingStamp, meetingOutlookMarker, type MeetingEvent } from '../utils/outlookMeetings'
import { adoptAgentFromLibrary, fetchAgentLibrary } from './agentLibraryApi'

export const PROTOCOL_SOURCE_WORKFLOW_ID = '599eaf4e-3b0c-4a6f-a370-c719e11a44ce'
export const PROTOCOL_AGENT_TITLE = 'Формирование протокола по аудиозаписи совещания'
export const PROTOCOL_AUDIO_EXTENSIONS = ['wav', 'mp3', 'm4a', 'aac', 'ogg', 'opus', 'flac', 'wma', 'amr', 'webm', 'mp4', 'mkv']

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
      base_ref_key: pick('base_ref_key'),
      control_tasks: pick('control_tasks'),
      comment: pick('comment')
    },
    null,
    2
  )
}

function executionCheckStep(protocol: ExistingProtocol): string[] {
  const baseRef = String(protocol.form.base_ref_key || '').trim()
  const control = Array.isArray(protocol.form.control_tasks) ? protocol.form.control_tasks.length : 0
  const scope = [
    baseRef && control
      ? `control_tasks — задачи для контроля с прошлого протокола (их владелец — протокол ${baseRef})`
      : '',
    protocol.editable ? '' : 'tasks — поставленные задачи этого протокола'
  ].filter(Boolean)
  if (!scope.length) {
    return ['3. Проверка выполнения: задач на контроле у протокола нет — шаг пропусти и скажи об этом человеку.']
  }
  return [
    `3. Проверка выполнения: ${scope.join('; ')}. По каждой задаче найди в расшифровке отчёт о ней и отнеси к одному из вариантов: «выполнено» (прямо сказано, что сделано/закрыто, — с таймкодом цитаты), «не выполнено / перенесено» (с новым сроком, если назван), «не обсуждалась». Уже done=true не перепроверяй. Отметку «выполнено» ставь только по прямому подтверждению в записи, не по догадке.`
  ]
}

function executionWriteStep(protocol: ExistingProtocol): string {
  const baseRef = String(protocol.form.base_ref_key || '').trim()
  const owners = [baseRef ? `ref_key="${baseRef}" для control_tasks` : '', protocol.editable ? '' : `ref_key="${protocol.refKey}" для tasks`]
    .filter(Boolean)
    .join(' и ')
  return owners
    ? `   Затем отметь выполненные: onec.meeting_protocol_write action="check_tasks" — по одному вызову на протокол-владелец задач (${owners}), tasks=[{id, done_date YYYY-MM-DD — дата совещания, comment «Выполнение подтверждено на совещании <дата> по аудиозаписи, [мм:сс]»}] только для «выполнено». Задачи с запущенным процессом в Документообороте сервер пропустит (skipped) — перечисли их человеку, их закрывают в ДО. «Не выполнено / перенесено» в регистр не пиши: для проведённого протокола новый срок — правка {id, due} через add_tasks, если задача ещё не отправлена.`
    : ''
}

/** Task for supplementing an existing 1С protocol with one more meeting recording. */
export function buildSupplementMessage(
  meeting: MeetingEvent | null,
  audioPath: string | string[],
  protocol: ExistingProtocol,
  opts: { extra?: boolean; previousAudio?: string[] } = {}
): string {
  const participants = Array.isArray(protocol.form.participants)
    ? protocol.form.participants.map((name) => String(name || '').trim()).filter(Boolean)
    : []
  const meetingLines = meeting
    ? [`Совещание: ${field(meeting.subject)}, ${formatMeetingStamp(meeting.start)}`, 'Участники из Outlook:', attendeesList(meeting)]
    : [
        `Совещание: ${field(String(protocol.form.topic || ''))}, ${field(String(protocol.form.date || ''))}`,
        'Присутствующие по протоколу:',
        participants.length ? participants.map((name) => `- ${name}`).join('\n') : '—'
      ]
  const namesHint = meeting ? 'участники из Outlook' : 'присутствующие по протоколу'
  const writeExecution = executionWriteStep(protocol)
  const steps = protocol.editable
    ? [
        '2. Сверь расшифровку с текущим протоколом:',
        '   — задачи: дополни недостающие поручения; исправь исполнителя, срок и формулировку, если в записи прозвучало иначе; существующие задачи без оснований не удаляй;',
        '   — решения и повестка: добавь новые пункты, уточни формулировки;',
        '   — участники, руководитель, дата следующего совещания: дополни и исправь по записи.',
        '   Бери только прозвучавшее в записи, не домысливай.',
        ...executionCheckStep(protocol),
        '4. Покажи человеку список изменений: что добавлено, что исправлено (было → стало), что оставлено без изменений, и итог проверки выполнения по каждой задаче.',
        `5. После подтверждения вызови onec.meeting_protocol_write action="update" ref_key="${protocol.refKey}" один раз. Табличные части перезаписываются целиком, поэтому передай ПОЛНЫЕ списки participants, agenda, decisions, tasks: существующие строки из текущего содержимого плюс добавленные и исправленные. Остальные поля шапки передай как в текущем содержимом, с исправлениями. В comment сохрани прежний текст (включая строку outlook:…) и добавь строку «Дополнено ИИ-агентом по аудиозаписи <имя файла>».`,
        writeExecution
      ]
    : [
        '2. Протокол уже проведён: документ не перезаписывается, задачи живут в регистре задач протоколов (tasks в текущем содержимом, у каждой id). Сверь расшифровку с задачами:',
        '   — новые поручения из записи, которых нет в протоколе, — добавить;',
        '   — у задачи с sent=false или process_started=false исполнитель, срок или формулировка прозвучали иначе — исправить по её id;',
        '   — задачи с sent=true / process_started=true не трогай, расхождения по ним только перечисли человеку.',
        '   Решения, повестку и участников в проведённом протоколе не меняй — изменения по ним перечисли человеку, их вносят в 1С.',
        '   Бери только прозвучавшее в записи, не домысливай.',
        ...executionCheckStep(protocol),
        '4. Покажи человеку список: какие задачи добавятся, какие исправятся (было → стало), итог проверки выполнения по каждой задаче и что надо поправить в 1С вручную.',
        `5. После подтверждения вызови onec.meeting_protocol_write action="add_tasks" ref_key="${protocol.refKey}" один раз (если новых задач и правок нет — не вызывай). В tasks передай ТОЛЬКО новые задачи {text, executor, due} и правки {id, text?, executor?, due?}; задачи без изменений не передавай. Проверь в ответе added / changed / errors / unresolved и сообщи человеку.`,
        writeExecution
      ]
  const paths = (Array.isArray(audioPath) ? audioPath : [audioPath]).filter(Boolean)
  const previous = (opts.previousAudio || []).filter(Boolean)
  const intro = opts.extra
    ? `Догрузка голосовых сообщений к протоколу совещания ${protocol.number || ''} в 1С: по ним дополни протокол и проверь выполнение задач. Новый протокол не создавай.`
    : `Дополни существующий протокол совещания ${protocol.number || ''} в 1С по новой аудиозаписи и проверь по ней выполнение задач. Новый протокол не создавай.`
  return [
    intro,
    '',
    ...meetingLines,
    '',
    ...(paths.length > 1
      ? ['Абсолютные пути к аудиофайлам:', ...paths.map((item) => `- ${item}`)]
      : [`Абсолютный путь к аудиофайлу: ${paths[0] || ''}`]),
    ...(previous.length
      ? [
          `Протокол уже дополняли по записям: ${previous.join(', ')} — их изменения уже в текущем содержимом ниже. Повторно эти задачи не добавляй и не отмечай.`
        ]
      : []),
    `Ref_Key протокола в 1С: ${protocol.refKey}`,
    '',
    'Текущее содержимое протокола (прочитано из 1С перед запуском):',
    '```json',
    protocolSnapshot(protocol.form),
    '```',
    '',
    'Порядок работы:',
    paths.length > 1
      ? `1. audio.transcribe ровно один раз на КАЖДЫЙ приложенный файл (names — ${namesHint}), прочитай все расшифровки; дальше работай с ними вместе, указывая в цитатах файл и таймкод.`
      : `1. audio.transcribe один раз для приложенного аудио (names — ${namesHint}), прочитай расшифровку.`,
    ...steps.filter(Boolean),
    '6. notify.send — только исполнителям новых или изменённых задач (суть, срок, номер протокола).',
    '7. Файл протокола пересобери через report.export_document (protocol-<дата>.docx) по обновлённому содержимому: раздел «Диалоги» — по новой записи, раздел «Проверка выполнения» — таблица Задача | Исполнитель | Итог | Цитата [мм:сс].',
    '8. Итоговый ответ — пояснение по изменениям для человека: по каждому изменению в 1С (добавлена / исправлена задача, отмечено выполнение) — что сделано, почему, и цитата из записи с таймкодом [мм:сс]; отдельно — что не записано и почему (отправлено в ДО, не прозвучало явно, не найден исполнитель). Пиши markdown-списком, без служебных GUID.'
  ].join('\n')
}

function isoDay(raw: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec((raw || '').trim())
  return match ? match[1] : ''
}

/** Russian task message with Outlook meeting fields and absolute audio path. */
export function buildProtocolMessage(
  meeting: MeetingEvent,
  audioPath: string,
  opts: { nextMeetingStart?: string } = {}
): string {
  const when = formatMeetingStamp(meeting.start)
  const end = meeting.end ? formatMeetingStamp(meeting.end) : ''
  const period = end ? `${when} – ${end}` : when
  const nextDay = isoDay(opts.nextMeetingStart || '')
  return [
    'Сформируй протокол совещания по приложенной аудиозаписи.',
    '',
    'Данные совещания из календаря Outlook:',
    `Тема: ${field(meeting.subject)}`,
    `Дата / время: ${period}`,
    `Место: ${field(meeting.location)}`,
    `Организатор: ${field(meeting.organizer)}`,
    'Участники:',
    attendeesList(meeting),
    `Идентификатор совещания Outlook: ${meeting.id || '—'}`,
    nextDay
      ? `Следующее совещание этой серии в Outlook: ${formatMeetingStamp(opts.nextMeetingStart || '')} (${nextDay})`
      : 'Следующее совещание этой серии в Outlook: на 45 дней вперёд не найдено',
    '',
    `Абсолютный путь к аудиофайлу: ${audioPath}`,
    '',
    'Используй данные календаря для темы протокола и сопоставления говорящих.',
    `В onec.meeting_protocol_write action="create" передай room — «Место» из Outlook${
      meeting.location?.trim() ? '' : ' (здесь не указано — не передавай)'
    }${
      nextDay
        ? ` и next_meeting_date="${nextDay}", если в записи не названа другая дата следующего совещания.`
        : '; next_meeting_date передай, только если дата следующего совещания прозвучала в записи.'
    } Чего нет — сервер возьмёт кабинет и периодичность из прошлого протокола этой темы.`,
    'Итоговый отчёт сохрани в формате docx через report.export_document.',
    meetingOutlookMarker(meeting)
      ? `В comment протокола 1С (onec.meeting_protocol_write) отдельной строкой добавь метку ${meetingOutlookMarker(meeting)} — по ней совещание в календаре связывается с документом (дата в метке обязательна).`
      : ''
  ]
    .filter((line, index, all) => line !== '' || index === 0 || all[index - 1] !== '')
    .join('\n')
    .trimEnd()
}
