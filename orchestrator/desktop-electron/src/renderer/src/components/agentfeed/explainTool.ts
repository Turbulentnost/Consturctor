import { isTaskTool, resolveToolName, toolLabel } from './labels'

export type ToolExplanation = {
  /** Short noun phrase, e.g. «Поручения в 1С». */
  title: string
  /** Infinitive without «Агент хочет», e.g. «посмотреть открытые поручения в 1С». */
  want: string
  /** What will happen, no raw parameter keys. */
  detail: string
  /** Live feed title, e.g. «Смотрит поручения в 1С». */
  activity: string
  /** Short human facts for the expanded card. */
  facts: string[]
}

const ENTITY_KINDS: Array<[string, string]> = [
  ['Document_', 'документ'],
  ['Catalog_', 'справочник'],
  ['InformationRegister_', 'регистр сведений'],
  ['AccumulationRegister_', 'регистр накопления'],
  ['ChartOfCharacteristicTypes_', 'план видов характеристик'],
  ['Enum_', 'перечисление']
]

function compactName(name: string): string {
  return (name || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

function asText(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

function asBool(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const lower = value.trim().toLowerCase()
    if (lower === 'true' || lower === '1' || lower === 'yes') return true
    if (lower === 'false' || lower === '0' || lower === 'no') return false
  }
  return undefined
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function clip(text: string, max = 180): string {
  const value = (text || '').replace(/\s+/g, ' ').trim()
  if (value.length <= max) return value
  return `${value.slice(0, max - 1).trim()}…`
}

function formatDate(raw: string): string {
  const value = raw.trim()
  const day = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (day) return `${day[3]}.${day[2]}.${day[1]}`
  return value
}

function formatPeople(value: unknown): string {
  if (!value) return ''
  if (typeof value === 'string') return clip(value, 120)
  if (Array.isArray(value)) {
    const names = value
      .map((item) => {
        if (typeof item === 'string') return item.trim()
        if (item && typeof item === 'object') {
          const rec = item as Record<string, unknown>
          return asText(rec.fio || rec.name || rec.email || rec.address)
        }
        return ''
      })
      .filter(Boolean)
    return clip(names.join(', '), 140)
  }
  if (typeof value === 'object') {
    const rec = value as Record<string, unknown>
    return asText(rec.fio || rec.name || rec.email)
  }
  return ''
}

function humanEntity(raw: string): string {
  const value = raw.trim()
  if (!value) return ''
  let kind = 'объект 1С'
  let name = value
  for (const [prefix, label] of ENTITY_KINDS) {
    if (value.startsWith(prefix)) {
      kind = label
      name = value.slice(prefix.length)
      break
    }
  }
  name = name.replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
  return name ? `${kind} «${name}»` : kind
}

function periodFact(from: string, to: string): string {
  if (from && to) return `Период: ${formatDate(from)} — ${formatDate(to)}`
  if (from) return `С ${formatDate(from)}`
  if (to) return `До ${formatDate(to)}`
  return ''
}

function limitFact(limit: number | undefined): string {
  if (!limit || limit <= 0) return ''
  return `Не больше ${limit} записей`
}

function fileFact(args: Record<string, unknown>): string {
  const name = asText(
    args.filename || args.file || args.path || args.file_path || args.target_file || args.targetFile
  )
  if (!name) return ''
  return `Файл: ${clip(name.split(/[\\/]/).pop() || name, 80)}`
}

function joinDetail(parts: string[]): string {
  return parts.filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()
}

function explanation(
  title: string,
  want: string,
  activity: string,
  facts: string[] = [],
  detail = ''
): ToolExplanation {
  const cleanFacts = facts.map((item) => item.trim()).filter(Boolean)
  return {
    title,
    want,
    activity,
    facts: cleanFacts,
    detail: detail || cleanFacts.join('. ') + (cleanFacts.length ? '.' : '')
  }
}

function assignmentRead(args: Record<string, unknown>): ToolExplanation {
  const action = (asText(args.action) || 'list').toLowerCase()
  const number = asText(args.number)
  const customer = asText(args.customer)
  const query = asText(args.query)
  const performer = asText(args.performer)
  const period = periodFact(asText(args.date_from), asText(args.date_to))
  const limit = limitFact(asNumber(args.limit))
  const onlyOpen = asBool(args.only_open)
  const includeLastDay = asBool(args.include_last_day)
  const facts: string[] = []
  if (number) facts.push(`Поручение ${number}`)
  if (customer) facts.push(`Заказчик: ${customer}`)
  if (performer) facts.push(`Исполнитель: ${performer}`)
  if (query) facts.push(`Ищет: «${clip(query, 80)}»`)
  if (period) facts.push(period)
  if (onlyOpen) facts.push('Только открытые')
  else if (includeLastDay !== false && action === 'list') facts.push('Открытые и за сегодня')
  if (limit) facts.push(limit)
  if (asBool(args.include_files)) facts.push('Сразу с файлами')

  if (action === 'get') {
    return explanation(
      'Карточка поручения',
      number ? `открыть карточку поручения ${number}` : 'открыть карточку поручения в 1С',
      'Открывает карточку поручения',
      facts,
      number
        ? `Покажет состав, сроки и исполнителей поручения ${number}.`
        : 'Покажет карточку поручения из журнала 1С.'
    )
  }
  if (action === 'files') {
    return explanation(
      'Файлы поручения',
      number ? `посмотреть файлы поручения ${number}` : 'посмотреть файлы поручения в 1С',
      'Смотрит файлы поручения',
      facts
    )
  }
  if (action === 'download') {
    return explanation(
      'Файл поручения',
      'скачать файл из поручения 1С',
      'Скачивает файл поручения',
      facts
    )
  }
  if (action === 'tasks') {
    return explanation(
      'Задачи по поручениям',
      performer
        ? `посмотреть задачи исполнителя ${performer} по поручениям`
        : 'посмотреть задачи исполнителей по поручениям',
      'Смотрит задачи по поручениям',
      facts
    )
  }
  if (action === 'protocols') {
    return explanation(
      'Протоколы поручений',
      'посмотреть протоколы, связанные с поручениями',
      'Смотрит протоколы поручений',
      facts
    )
  }
  return explanation(
    'Поручения в 1С',
    'посмотреть поручения в журнале 1С',
    'Смотрит поручения в 1С',
    facts,
    joinDetail([
      'Откроет журнал поручений АСТ00.',
      onlyOpen ? 'Только открытые.' : includeLastDay === false ? '' : 'Открытые и записи за сегодня.',
      limit ? `${limit}.` : ''
    ])
  )
}

function assignmentWrite(args: Record<string, unknown>): ToolExplanation {
  const action = (asText(args.action) || 'update').toLowerCase()
  const number = asText(args.number)
  const topic = asText(args.topic)
  const customer = asText(args.customer)
  const status = asText(args.status)
  const due = asText(args.due)
  const comment = asText(args.comment)
  const facts: string[] = []
  if (number) facts.push(`Поручение ${number}`)
  if (topic) facts.push(`О чём: ${clip(topic, 120)}`)
  if (customer) facts.push(`Заказчик: ${customer}`)
  if (status) facts.push(`Статус: ${status}`)
  if (due) facts.push(`Срок: ${formatDate(due)}`)
  if (comment) facts.push(`Комментарий: ${clip(comment, 140)}`)
  if (Array.isArray(args.lines) && args.lines.length) {
    facts.push(`Строк в поручении: ${args.lines.length}`)
  }

  if (action === 'create') {
    return explanation(
      'Новое поручение',
      'создать новое поручение в 1С',
      'Создаёт поручение в 1С',
      facts,
      joinDetail(['Запишет новую карточку в журнал поручений АСТ00.', ...facts.map((item) => `${item}.`)])
    )
  }
  if (action === 'comment_task') {
    return explanation(
      'Комментарий исполнителю',
      number
        ? `написать комментарий исполнителю по поручению ${number}`
        : 'написать комментарий исполнителю поручения',
      'Пишет комментарий в поручение',
      facts,
      'Комментарий попадёт в задачу исполнителя в 1С.'
    )
  }
  return explanation(
    'Изменение поручения',
    number ? `изменить поручение ${number} в 1С` : 'изменить поручение в 1С',
    'Меняет поручение в 1С',
    facts,
    joinDetail([
      number ? `Обновит карточку ${number} в журнале поручений.` : 'Обновит карточку в журнале поручений.',
      ...facts.filter((item) => !number || item !== `Поручение ${number}`).map((item) => `${item}.`)
    ])
  )
}

function odataWrite(tool: string, args: Record<string, unknown>): ToolExplanation {
  const create = tool === 'onec.odata_post'
  const entity = humanEntity(asText(args.entity || args.entitySet))
  const body = args.body && typeof args.body === 'object' ? (args.body as Record<string, unknown>) : {}
  const facts: string[] = []
  if (entity) facts.push(entity.charAt(0).toUpperCase() + entity.slice(1))
  const number = asText(body.Number || body['Номер'] || args.number)
  const date = asText(body.Date || body['Дата'])
  const comment = asText(body.Comment || body['Комментарий'])
  if (number) facts.push(`Номер ${number}`)
  if (date) facts.push(`Дата ${formatDate(date)}`)
  if (body.Posted === false) facts.push('Черновик, без проведения')
  if (body.Posted === true) facts.push('С проведением')
  if (comment) facts.push(`Комментарий: ${clip(comment, 140)}`)
  return explanation(
    create ? 'Запись в 1С' : 'Изменение в 1С',
    create
      ? entity
        ? `создать ${entity} в 1С`
        : 'создать запись в 1С'
      : entity
        ? `изменить ${entity} в 1С`
        : 'изменить запись в 1С',
    create ? 'Создаёт запись в 1С' : 'Меняет запись в 1С',
    facts,
    joinDetail([
      create ? 'Это создание объекта в базе 1С, не только чтение.' : 'Указанные поля в 1С будут перезаписаны.',
      ...facts.map((item) => `${item}.`)
    ])
  )
}

function outlookEvent(args: Record<string, unknown>): ToolExplanation {
  const batch = Array.isArray(args.events) ? args.events : []
  const subject = asText(args.subject || args.title)
  const start = asText(args.start || args.start_at || args.startDate)
  const organizer = asText(args.organizer || args.organizer_fio)
  const people = formatPeople(args.attendees || args.people || args.required_attendees)
  const facts: string[] = []
  if (batch.length > 1) facts.push(`Встреч: ${batch.length}`)
  if (subject) facts.push(`Тема: ${clip(subject, 120)}`)
  if (start) facts.push(`Начало: ${formatDate(start)}`)
  if (organizer) facts.push(`Организатор: ${organizer}`)
  if (people) facts.push(`Участники: ${people}`)
  return explanation(
    'Встреча в Outlook',
    batch.length > 1 ? `поставить ${batch.length} встреч в Outlook` : 'поставить встречу в календарь Outlook',
    'Ставит встречу в Outlook',
    facts,
    'Событие появится в календаре Outlook. В теме будет пометка, что его создал ИИ-агент.'
  )
}

function mailWrite(tool: string, args: Record<string, unknown>): ToolExplanation {
  const draft = tool === 'email.create_draft'
  const to = formatPeople(args.to || args.recipients || args.email)
  const subject = asText(args.subject || args['тема'])
  const facts: string[] = []
  if (to) facts.push(`Кому: ${to}`)
  if (subject) facts.push(`Тема: ${clip(subject, 120)}`)
  return explanation(
    draft ? 'Черновик письма' : 'Отправка письма',
    draft ? 'создать черновик письма в Outlook' : 'отправить письмо через Outlook',
    draft ? 'Готовит черновик письма' : 'Отправляет письмо',
    facts,
    draft ? 'Письмо ещё не уйдёт, пока его не отправят.' : 'Получатели увидят письмо сразу.'
  )
}

function excelWrite(tool: string, args: Record<string, unknown>): ToolExplanation {
  const create = tool === 'excel.create_workbook'
  const file = fileFact(args)
  const facts = file ? [file] : []
  return explanation(
    create ? 'Создание Excel' : 'Изменение Excel',
    create ? 'создать книгу Excel в папке агента' : 'изменить книгу Excel в папке агента',
    create ? 'Создаёт Excel' : 'Правит Excel',
    facts
  )
}

function byKnownName(name: string, args: Record<string, unknown>): ToolExplanation | null {
  if (name === 'onec.erp_assignments') return assignmentRead(args)
  if (name === 'onec.erp_assignments_write') return assignmentWrite(args)
  if (name === 'onec.odata_post' || name === 'onec.odata_patch') return odataWrite(name, args)
  if (name === 'outlook.create_event') return outlookEvent(args)
  if (name === 'outlook.send_mail' || name === 'email.send' || name === 'email.create_draft') {
    return mailWrite(name, args)
  }
  if (name === 'excel.create_workbook' || name === 'excel.edit_workbook') return excelWrite(name, args)

  const file = fileFact(args)
  const query = asText(args.query || args.pattern || args.filter)
  const url = asText(args.url)
  const people = formatPeople(args.people || args.attendees || args.mailbox || args.fio)
  const period = periodFact(
    asText(args.date_from || args.start || args.from),
    asText(args.date_to || args.end || args.to)
  )
  const number = asText(args.number)
  const extra = [file, people && `Кто: ${people}`, period, number && `Номер ${number}`, query && `Ищет: «${clip(query, 80)}»`, url && `Адрес: ${clip(url, 80)}`].filter(
    Boolean
  ) as string[]

  const catalog: Record<string, [string, string, string, string?]> = {
    'onec.odata_get': ['Чтение 1С', 'прочитать данные из 1С', 'Читает данные 1С'],
    'onec.odata_catalog': ['Каталог 1С', 'посмотреть список сущностей 1С', 'Смотрит каталог 1С'],
    'onec.search_documents': ['Поиск документов', 'найти документы в 1С', 'Ищет документы в 1С'],
    'onec.get_document_card': ['Карточка документа', 'открыть карточку документа 1С', 'Открывает документ 1С'],
    'onec.search_tasks': ['Поиск задач', 'найти задачи в 1С', 'Ищет задачи в 1С'],
    'onec.get_task_card': ['Карточка задачи', 'открыть карточку задачи 1С', 'Открывает задачу 1С'],
    'onec.meeting_service_notes': [
      'Служебные записки',
      'посмотреть служебные записки на совещания',
      'Смотрит служебные записки'
    ],
    'onec.meeting_protocols': ['Протоколы совещаний', 'посмотреть протоколы совещаний в 1С', 'Смотрит протоколы'],
    'onec.sql_query': ['Запрос 1С', 'выполнить запрос к данным 1С', 'Запрашивает данные 1С'],
    'onec.erp_tasks_current': ['Текущие задачи', 'посмотреть текущие задачи в 1С', 'Смотрит текущие задачи'],
    'onec.erp_tasks_period': ['Задачи за период', 'посмотреть задачи 1С за период', 'Смотрит задачи за период'],
    'onec.erp_subordinate_tasks': [
      'Задачи подчинённых',
      'посмотреть задачи подчинённых в 1С',
      'Смотрит задачи подчинённых'
    ],
    'onec.docflow_tasks': ['Документооборот', 'посмотреть задачи документооборота', 'Смотрит задачи документооборота'],
    'onec.download_artifact': ['Файл из 1С', 'скачать файл из 1С', 'Скачивает файл из 1С'],
    'onec.erp_write_probe': [
      'Проба записи 1С',
      'проверить, как писать в 1С, на тестовой карточке',
      'Проверяет запись в 1С',
      'Создаст тестовую карточку, проверит изменение и сразу удалит её. Боевые документы не трогает.'
    ],
    'onec.attach_file': ['Файл в 1С', 'прикрепить файл к документу в 1С', 'Прикрепляет файл в 1С'],
    'outlook.search_mail': ['Поиск писем', 'найти письма в Outlook', 'Ищет письма'],
    'outlook.read_calendar': ['Календарь Outlook', 'посмотреть календарь Outlook', 'Смотрит календарь Outlook'],
    'calendar.show_meetings': ['План совещаний', 'показать план совещаний', 'Собирает план совещаний'],
    'web_search': ['Поиск в интернете', 'найти информацию в интернете', 'Ищет в интернете'],
    site_browser: ['Просмотр сайта', 'открыть страницу в интернете', 'Открывает сайт'],
    'browser.search_web': ['Поиск в интернете', 'найти информацию в интернете', 'Ищет в интернете'],
    'browser.open_page': ['Чтение страницы', 'прочитать страницу в браузере', 'Читает страницу'],
    'browser.navigate': ['Переход в браузере', 'открыть страницу в браузере', 'Открывает страницу'],
    'browser.click': ['Клик в браузере', 'нажать элемент на странице', 'Нажимает на странице'],
    'browser.type_text': ['Ввод в браузере', 'ввести текст на странице', 'Вводит текст на странице'],
    'excel.read_workbook': ['Чтение Excel', 'прочитать книгу Excel', 'Читает Excel'],
    'excel.list_files': ['Файлы агента', 'посмотреть файлы в папке агента', 'Смотрит файлы агента'],
    'office.format_document': [
      'Оформление документа',
      'оформить Excel или Word по корпоративному шаблону',
      'Оформляет документ'
    ],
    'report.export_document': ['Отчёт в файл', 'сохранить отчёт файлом в папке агента', 'Сохраняет отчёт'],
    'report.build_task_report': ['Отчёт по поручениям', 'собрать отчёт по поручениям', 'Собирает отчёт по поручениям'],
    'report.build_meeting_summary': ['Сводка совещания', 'собрать сводку совещания', 'Собирает сводку совещания'],
    'code.write_python': ['Запись кода', 'сохранить Python-файл в папке агента', 'Пишет код'],
    'code.run_python': ['Запуск кода', 'запустить Python-скрипт на этом компьютере', 'Запускает код'],
    'workspace.powershell_run': ['Команда на компьютере', 'выполнить команду в папке агента', 'Выполняет команду'],
    'notify.send': ['Уведомление', 'отправить уведомление', 'Отправляет уведомление'],
    'users.current': ['Текущий пользователь', 'узнать, кто сейчас в системе', 'Смотрит текущего пользователя'],
    'users.list': ['Список сотрудников', 'посмотреть список сотрудников', 'Смотрит список сотрудников'],
    'users.subordinates': ['Подчинённые', 'посмотреть подчинённых', 'Смотрит подчинённых'],
    turboproject: ['Проекты', 'посмотреть проекты в TurboProject', 'Смотрит проекты'],
    'agent.schedule': ['Расписание агента', 'поставить агента на расписание', 'Настраивает расписание'],
    'agent.schedule.cancel': ['Отмена расписания', 'снять агента с расписания', 'Снимает расписание'],
    'agent.wait': ['Пауза', 'подождать перед следующим шагом', 'Ждёт'],
    write: ['Запись файла', 'записать файл в папку агента', 'Пишет файл'],
    Write: ['Запись файла', 'записать файл в папку агента', 'Пишет файл'],
    Edit: ['Правка файла', 'править файл в папке агента', 'Правит файл'],
    edit: ['Правка файла', 'править файл в папке агента', 'Правит файл'],
    Delete: ['Удаление файла', 'удалить файл в папке агента', 'Удаляет файл'],
    read: ['Чтение файла', 'прочитать файл', 'Читает файл'],
    Read: ['Чтение файла', 'прочитать файл', 'Читает файл'],
    grep: ['Поиск в файлах', 'найти текст в файлах агента', 'Ищет в файлах'],
    Grep: ['Поиск в файлах', 'найти текст в файлах агента', 'Ищет в файлах'],
    glob: ['Поиск файлов', 'найти файлы в папке агента', 'Ищет файлы'],
    Glob: ['Поиск файлов', 'найти файлы в папке агента', 'Ищет файлы'],
    Shell: ['Команда на компьютере', 'выполнить команду на этом компьютере', 'Выполняет команду'],
    shell: ['Команда на компьютере', 'выполнить команду на этом компьютере', 'Выполняет команду']
  }

  const known = catalog[name]
  if (!known) return null
  return explanation(known[0], known[1], known[2], extra, known[3])
}

export function explainTool(tool: string, args?: Record<string, unknown>): ToolExplanation {
  const rawArgs = args && typeof args === 'object' ? args : {}
  const name = resolveToolName(tool, rawArgs)
  if (isTaskTool(name) || isTaskTool(tool)) {
    const description =
      asText(rawArgs.description) || asText(rawArgs.title) || asText(rawArgs.subagent_type)
    return explanation(
      'Вложенный агент',
      description ? `поручить вложенному агенту: ${clip(description, 100)}` : 'запустить вложенного агента',
      description ? `Агент: ${clip(description, 80)}` : 'Вложенный агент'
    )
  }

  const compact = compactName(name)
  const direct = byKnownName(name, rawArgs)
  if (direct) return direct
  for (const key of [
    'onec.erp_assignments',
    'onec.erp_assignments_write',
    'onec.odata_post',
    'onec.odata_patch',
    'outlook.create_event'
  ]) {
    if (compactName(key) === compact) {
      const matched = byKnownName(key, rawArgs)
      if (matched) return matched
    }
  }

  const label = toolLabel(name)
  const looksTechnical = compactName(label) === compact
  const title = looksTechnical ? 'Действие агента' : label
  const want = looksTechnical ? 'выполнить действие во внешней системе' : label.charAt(0).toLowerCase() + label.slice(1)
  return explanation(
    title,
    want,
    looksTechnical ? 'Выполняет действие' : title,
    [],
    looksTechnical
      ? 'Агент хочет выполнить действие во внешней системе. Без вашего подтверждения оно не пройдёт.'
      : ''
  )
}

export function agentWantsText(tool: string, args?: Record<string, unknown>): string {
  return `Агент хочет ${explainTool(tool, args).want}`
}

export function toolIntent(tool: string, args?: Record<string, unknown>): string {
  const explained = explainTool(tool, args)
  return joinDetail([explained.detail || `Агент хочет ${explained.want}.`])
}

export function toolCardTitle(tool: string, args?: Record<string, unknown>): string {
  return explainTool(tool, args).activity
}
