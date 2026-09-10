import type { AgentPassport, AgentSuggestion, PassportSession } from './types'

const AUTONOMY = {
  canAutonomous: 'Генерация текста и чтение календаря Outlook — без подтверждения человека.',
  needsHumanApproval: 'Запись в календарь руководителя и прочие операции — только после подтверждения.',
  forbidden:
    'Писать в календарь без подтверждения. Готовить письменный план дня, справку или комплект материалов. Делать ручную рассылку приглашений. Повторять поиск писем. Спрашивать «что должен делать агент» на рабочем прогоне.'
}

const SD_AUTONOMY = {
  canAutonomous:
    'Читать 1С (темы, карточки, служебные записки) и календарь Outlook, сверять комплект по ПЛ-34-242, готовить черновики резюме и протокола — без подтверждения.',
  needsHumanApproval:
    'Утверждать материалы, рассылать официальный пакет, писать в 1С и создавать встречи в Outlook — только после подтверждения.',
  forbidden:
    'Выдумывать протокол, решения и поручения без текстовой расшифровки Word. Утверждать материалы. Подставлять цифры, которых нет во вложениях или 1С.'
}

const RK_AUTONOMY = {
  canAutonomous:
    'Читать 1С, Outlook, Excel-реестр и папку планов РК, собирать черновик повестки и перечни, готовить черновик протокола из Word-расшифровки — без подтверждения.',
  needsHumanApproval:
    'Утверждать повестку у Руководителя РК, рассылать пакет, писать в 1С, создавать встречи в Outlook и править реестр Excel — только после подтверждения.',
  forbidden:
    'Выдумывать дату заседания, повестку, протокол, решения, предписания и сроки. Утверждать повестку. Исправлять расхождения 1С и Excel. Готовить протокол без текстовой расшифровки Word.'
}

const PSD_FIELDS: Omit<
  AgentPassport,
  'missingFields' | 'questions' | 'source' | 'text' | 'autonomyLevel'
> = {
  name: 'Подготовка ПСД к рабочему дню и контроль календаря',
  goal:
    'Держать календарь Председателя совета директоров в Outlook без окон в рабочее время (кроме обеда 12:00–13:00), без выходных и праздников, и готовить его к дню устными указаниями участникам и устным списком встреч. Письменный план дня, справку и комплект материалов не готовить.',
  trigger:
    'Будни 08:30 — устный список совещаний на сегодня для планёрки. Будни 16:00 — проверка календаря на завтра и закрытие окон. По кнопке — то же по текущему времени Москвы. Письменный план дня не готовить.',
  receives:
    'Календарь руководителя в Microsoft Outlook: дата, время, тема, участники, статус. Устные указания руководителя. Отсутствия — одно письмо кадров в Outlook (query=отпуск) или устно от коллег. Перечень подготовки не брать из темы или описания встречи.',
  checks:
    'Календарь руководителя в Outlook: утром только сегодня, вечером завтра; один поиск отсутствий; окна 09:00–18:00 кроме обеда 12:00–13:00; хвост после последней встречи окном не считать; выходные и праздники РФ.',
  decisions:
    'До 16:00 — только устный список, в календарь не писать, search_mail не повторять, не спрашивать «что должен делать агент». После 16:00 — если есть окно, сдвинуть уже стоящие совещания (не выдумывать новые). Если названа незапланированная встреча — внести в тот же календарь после HITL. Если участник отсутствует — учесть. Приглашения уходят автоматически из Outlook.',
  canAutonomous: AUTONOMY.canAutonomous,
  needsHumanApproval: AUTONOMY.needsHumanApproval,
  forbidden: AUTONOMY.forbidden,
  result:
    'Утром — устный список совещаний в чате и карточка keep. Вечером — карточка сдвигов и запись в Outlook только после подтверждения. Файла плана дня нет.'
}

const SD_FIELDS: Omit<
  AgentPassport,
  'missingFields' | 'questions' | 'source' | 'text' | 'autonomyLevel'
> = {
  name: 'Подготовка заседаний Совета директоров',
  goal:
    'Проверять комплект материалов заседания СД ГК по ПЛ-34-242 (версия 03), собирать недостающее из 1С и вложений запуска, готовить краткое резюме и черновик протокола только из текстовой расшифровки Word.',
  trigger:
    'За 2 рабочих дня до заседания СД ГК — когда пакет должен уйти участникам; и по кнопке, когда пользователь приложил материалы этого заседания. После заседания — по кнопке с расшифровкой Word.',
  receives:
    'На каждый запуск: повестка и таблица комплектности этого заседания, при наличии — Word-расшифровка. Из систем: темы и карточки 1С «Совет директоров по ГК», служебные записки, календарь помощника ПСД в Outlook (тема, участники, кто кого замещает). ПЛ-34-242 — знание агента, его не прикладывают каждый раз.',
  checks:
    'Обязательный пакет п. 6.4 ПЛ-34-242: резюме, ОПУ/ДДС, инвестиции, продажи/ДЗ, производство, НИОКР, риски, персонал, статус поручений ПСД, решения класса А, прил. А и Б. Сверяет карточки и записки 1С, состав и замещения в календаре. Без Word-расшифровки протокол не готовит.',
  decisions:
    'Если в комплекте нет пункта пакета — указать пробел, не выдумывать. Если нет расшифровки — не писать протокол, Decision Log и Action Tracker. Решения и поручения брать только из текста Word, не из аудио. Материалы не утверждать.',
  canAutonomous: SD_AUTONOMY.canAutonomous,
  needsHumanApproval: SD_AUTONOMY.needsHumanApproval,
  forbidden: SD_AUTONOMY.forbidden,
  result:
    'Сводка комплектности, список пробелов, карточки для устного доклада (встречи с составом и замещениями), черновик резюме; при наличии расшифровки — черновик протокола, Decision Log и Action Tracker. Получатель — текущий пользователь.'
}

const RK_FIELDS: Omit<
  AgentPassport,
  'missingFields' | 'questions' | 'source' | 'text' | 'autonomyLevel'
> = {
  name: 'Подготовка заседаний Ревизионной комиссии',
  goal:
    'К каждому вторничному заседанию РК собрать проект повестки и фактические перечни: открытые поручения, просрочки, предписания, сроки служебных расследований, документы на закрытие и вопросы Руководителю РК. После заседания — проект протокола только из текстовой расшифровки Word. Не утверждать повестку и не выдумывать даты, решения и отсутствующие документы.',
  trigger:
    'Каждый понедельник 09:00–10:00 — календарный понедельник перед вторничным заседанием РК. И по кнопке. План работ агент берёт из папки РК и 1С сам; файл можно приложить за 30 секунд, иначе продолжает без него. После заседания — по кнопке с расшифровкой.',
  receives:
    'Файл плана на запуск не обязателен: 30 секунд на вложение, иначе агент сам читает 1С ERP (поручения без фильтра по статусам ТЗ), Outlook, папку планов \\\\192.168.1.198\\Files\\24.Ревизионная комиссия\\Отдел\\8. Планы работ и реестр \\\\192.168.1.198\\Files\\24.Ревизионная комиссия\\Отдел\\10. Секретарь РК\\РЕЕСТР ПОРУЧЕНИЙ. Word-расшифровка — только после заседания, если готовят протокол. ПЛ-01-001 — знание агента.',
  checks:
    'Чек-лист ТЗ §15: проект повестки; открытые поручения; просрочки; предписания; сроки расследований; документы на закрытие; вопросы Руководителю РК. Сверяет 1С и Excel без самостоятельной правки расхождений. Дату заседания берёт из Outlook или плана. Без Word-расшифровки протокол не готовит.',
  decisions:
    'Нет подтверждённой даты вторника — статус «Недостаточно данных», повестку с выдуманной датой не выпускать. Нет пункта в источниках — пробел, не подставлять. Расхождение 1С/Excel — показать оба срока, Excel не править. Протокол и решения — только из текста Word после заседания. Повестку и протокол не утверждать.',
  canAutonomous: RK_AUTONOMY.canAutonomous,
  needsHumanApproval: RK_AUTONOMY.needsHumanApproval,
  forbidden: RK_AUTONOMY.forbidden,
  result:
    'Текущему пользователю (Секретарю РК): проект повестки с вопросами, документами, сроками и ответственными; перечни открытых поручений, просрочек, предписаний, сроков расследований и документов на закрытие; вопросы Руководителю РК. После заседания и при Word-расшифровке — черновик протокола. Если фактов нет — «Недостаточно данных» или «Требуется решение Руководителя РК».'
}

const QUESTIONS: { field: keyof AgentPassport; prompt: string }[] = [
  { field: 'goal', prompt: 'Какая главная цель агента? Что он должен улучшить или не допустить?' },
  { field: 'trigger', prompt: 'Когда запускать агента: по кнопке, по расписанию или по событию?' },
  { field: 'receives', prompt: 'Откуда брать исходные данные и что именно нужно на входе?' },
  { field: 'checks', prompt: 'Где агент должен сверять данные?' },
  { field: 'decisions', prompt: 'Какие решения агент может принимать сам и по каким правилам (если / то)?' },
  { field: 'result', prompt: 'Что должно получиться в итоге работы агента?' }
]

function isSdMeeting(item: AgentSuggestion): boolean {
  const hay = `${item.title} ${item.description}`.toLowerCase()
  return (
    hay.includes('заседаний совета') ||
    hay.includes('заседания совета') ||
    hay.includes('совета директоров') ||
    hay.includes('пл-34-242') ||
    hay.includes('пл 34-242')
  )
}

function isRkMeeting(item: AgentSuggestion): boolean {
  const hay = `${item.title} ${item.description}`.toLowerCase()
  return (
    hay.includes('ревизионной комиссии') ||
    hay.includes('заседаний ревизион') ||
    hay.includes('заседания ревизион') ||
    hay.includes('пл-01-001') ||
    hay.includes('пл 01-001')
  )
}

function isPsd(item: AgentSuggestion): boolean {
  const hay = `${item.title} ${item.description}`.toLowerCase()
  if (isSdMeeting(item) || isRkMeeting(item)) return false
  return hay.includes('псд') || hay.includes('подготовка псд')
}

function oneLine(text: string, max = 420): string {
  return text.replace(/\s+/g, ' ').trim().slice(0, max)
}

function finishPassport(
  fields: Omit<AgentPassport, 'missingFields' | 'questions' | 'source' | 'text' | 'autonomyLevel'>,
  source: string
): AgentPassport {
  const filled = { ...AUTONOMY, ...fields }
  const missing = QUESTIONS.map((item) => item.field).filter((field) => !String(filled[field] || '').trim())
  return {
    ...filled,
    missingFields: missing,
    questions: QUESTIONS.filter((item) => missing.includes(item.field)).map((item) => ({
      id: `q_${item.field}`,
      field: item.field,
      prompt: item.prompt
    })),
    source,
    text: '',
    autonomyLevel: 1
  }
}

export function localPassportFromSuggestion(
  item: AgentSuggestion,
  draftId = ''
): PassportSession {
  const title = (item.title || 'ИИ-агент').replace(/^ИИ-агент:\s*/i, '').trim() || 'ИИ-агент'
  const description = (item.description || '').trim()
  const fields = isSdMeeting(item)
    ? { ...SD_FIELDS }
    : isRkMeeting(item)
    ? { ...RK_FIELDS }
    : isPsd(item)
    ? { ...PSD_FIELDS }
    : {
        name: title,
        goal: oneLine(description) || title,
        trigger: description.toLowerCase().includes('16:00')
          ? 'По расписанию и по событиям из описания процесса'
          : '',
        receives: description.toLowerCase().includes('outlook')
          ? 'Календарь Microsoft Outlook и устные указания'
          : oneLine(description, 280),
        checks: '',
        decisions: '',
        canAutonomous: AUTONOMY.canAutonomous,
        needsHumanApproval: AUTONOMY.needsHumanApproval,
        forbidden: AUTONOMY.forbidden,
        result: ''
      }
  const passport = finishPassport({ ...fields, name: fields.name || title }, 'local')
  return {
    passport,
    bpName: title,
    excerpt: description,
    functions: [
      {
        name: title,
        description,
        actionLevel: 'read',
        requiresHumanApproval: true,
        automationKind: 'assisted'
      }
    ],
    draftId,
    llmError: '',
    qaHistory: []
  }
}

export function applyLocalPassportAnswers(
  session: PassportSession,
  answers: Record<string, string>
): PassportSession {
  const next = {
    name: session.passport.name,
    goal: session.passport.goal,
    trigger: session.passport.trigger,
    receives: session.passport.receives,
    checks: session.passport.checks,
    decisions: session.passport.decisions,
    canAutonomous: session.passport.canAutonomous,
    needsHumanApproval: session.passport.needsHumanApproval,
    forbidden: session.passport.forbidden,
    result: session.passport.result
  }
  for (const [key, value] of Object.entries(answers)) {
    const field = key.startsWith('q_') ? key.slice(2) : key
    if (field in next && value.trim()) {
      next[field as keyof typeof next] = value.trim()
    }
  }
  return {
    ...session,
    passport: finishPassport(next, 'local'),
    llmError: ''
  }
}
