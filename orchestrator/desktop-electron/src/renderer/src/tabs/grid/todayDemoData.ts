import type { SpecMailRow, SpecPillTone } from '../../workplace/specV04DemoData'

export type TodayPlanLane = 'meetings' | 'ai' | 'lunch'

/** Полные поля для модалки «План на день». */
export type TodayPlanBlockDetail = {
  timeRange: string
  typeLabel: string
  location?: string
  format?: string
  organizer?: string
  participants?: string
  workflowId?: string
  runId?: string
  status?: string
  source?: string
  agentName?: string
  note?: string
}

export type TodayPlanBlock = {
  id: string
  startHour: number
  endHour: number
  title: string
  subtitle?: string
  tone: 'pink' | 'sky' | 'mint' | 'orange' | 'purple' | 'teal' | 'blue'
  who: 'employee' | 'ai' | 'both'
  kind: 'meet' | 'onec' | 'reg' | 'mail' | 'proj' | 'doc'
  lane?: TodayPlanLane
  detail?: TodayPlanBlockDetail
}

/** Совещания — короткие и длинные названия, пересечения по времени. */
export const TODAY_PLAN_MEETING_MOCKS: TodayPlanBlock[] = [
  {
    id: 'mock-m1',
    startHour: 9,
    endHour: 9.5,
    title: 'Синх',
    tone: 'pink',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: {
      timeRange: '09:00 – 09:30',
      typeLabel: 'Совещание',
      format: 'Онлайн',
      participants: '4 чел.'
    }
  },
  {
    id: 'mock-m2',
    startHour: 9.25,
    endHour: 10.25,
    title: 'Еженедельное планирование архитектуры системы и обсуждение квартальных KPI',
    tone: 'purple',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: {
      timeRange: '09:15 – 10:15',
      typeLabel: 'Совещание',
      location: 'Переговорная 301',
      format: 'Очно',
      organizer: 'Петрова А.С.',
      participants: '8 чел.'
    }
  },
  {
    id: 'mock-m3',
    startHour: 10,
    endHour: 11,
    title: 'Стендап',
    tone: 'sky',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: { timeRange: '10:00 – 11:00', typeLabel: 'Совещание', format: 'Teams' }
  },
  {
    id: 'mock-m4',
    startHour: 10.5,
    endHour: 11.5,
    title: 'Согласование бюджета закупок и контрактов на следующий квартал с финансовым департаментом',
    tone: 'orange',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: {
      timeRange: '10:30 – 11:30',
      typeLabel: 'Совещание',
      location: 'Teams',
      format: 'Онлайн'
    }
  },
  {
    id: 'mock-m5',
    startHour: 14,
    endHour: 15,
    title: 'CRM',
    tone: 'teal',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: { timeRange: '14:00 – 15:00', typeLabel: 'Совещание', format: 'Офис 204' }
  },
  {
    id: 'mock-m6',
    startHour: 14.5,
    endHour: 16,
    title: 'Разбор инцидентов интеграции 1С и TurboProject с участием службы поддержки и разработки',
    tone: 'pink',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: {
      timeRange: '14:30 – 16:00',
      typeLabel: 'Совещание',
      format: 'Гибрид',
      participants: '12 чел.'
    }
  },
  {
    id: 'mock-m7',
    startHour: 16.5,
    endHour: 17.5,
    title: '1:1',
    tone: 'purple',
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: { timeRange: '16:30 – 17:30', typeLabel: 'Совещание', format: 'Очно' }
  }
]

/** ИИ-агенты — короткие и длинные названия, несколько одновременно. */
export const TODAY_PLAN_AI_MOCKS: TodayPlanBlock[] = [
  {
    id: 'mock-a1',
    startHour: 9.5,
    endHour: 10.5,
    title: '1С',
    tone: 'sky',
    who: 'ai',
    kind: 'onec',
    lane: 'ai',
    detail: {
      timeRange: '09:30 – 10:30',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент задач 1С',
      status: 'Завершён'
    }
  },
  {
    id: 'mock-a2',
    startHour: 10,
    endHour: 11,
    title: 'Обработка входящих заявок на закупку оборудования и согласование бюджета',
    tone: 'teal',
    who: 'ai',
    kind: 'reg',
    lane: 'ai',
    detail: {
      timeRange: '10:00 – 11:00',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент закупок',
      status: 'Выполняется'
    }
  },
  {
    id: 'mock-a3',
    startHour: 10,
    endHour: 10.75,
    title: 'Отчёт',
    tone: 'orange',
    who: 'ai',
    kind: 'doc',
    lane: 'ai',
    detail: {
      timeRange: '10:00 – 10:45',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент отчётности',
      status: 'Выполняется'
    }
  },
  {
    id: 'mock-a4',
    startHour: 11,
    endHour: 12,
    title: 'Регламент',
    tone: 'mint',
    who: 'both',
    kind: 'reg',
    lane: 'ai',
    detail: {
      timeRange: '11:00 – 12:00',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Регламентный агент'
    }
  },
  {
    id: 'mock-a5',
    startHour: 13.5,
    endHour: 14.5,
    title: 'Подготовка сравнительного анализа коммерческих предложений поставщиков по проекту CRM',
    tone: 'blue',
    who: 'ai',
    kind: 'doc',
    lane: 'ai',
    detail: {
      timeRange: '13:30 – 14:30',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент аналитики',
      status: 'Запланирован'
    }
  },
  {
    id: 'mock-a6',
    startHour: 15,
    endHour: 16,
    title: 'Почта',
    tone: 'orange',
    who: 'ai',
    kind: 'mail',
    lane: 'ai',
    detail: {
      timeRange: '15:00 – 16:00',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент Outlook'
    }
  },
  {
    id: 'mock-a7',
    startHour: 16,
    endHour: 17,
    title: 'ТЗ',
    tone: 'purple',
    who: 'both',
    kind: 'proj',
    lane: 'ai',
    detail: {
      timeRange: '16:00 – 17:00',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент проектов'
    }
  },
  {
    id: 'mock-a8',
    startHour: 16.5,
    endHour: 17.5,
    title: 'Формирование проекта решения по согласованию акта выполненных работ с контрагентом',
    tone: 'sky',
    who: 'ai',
    kind: 'doc',
    lane: 'ai',
    detail: {
      timeRange: '16:30 – 17:30',
      typeLabel: 'Запуск ИИ-агента',
      agentName: 'Агент решений',
      status: 'Запланирован'
    }
  }
]

/** @deprecated используйте TODAY_PLAN_MEETING_MOCKS / TODAY_PLAN_AI_MOCKS */
export const TODAY_PLAN_BLOCKS: TodayPlanBlock[] = [
  ...TODAY_PLAN_MEETING_MOCKS,
  ...TODAY_PLAN_AI_MOCKS
]

export type TodayResultFile = {
  id: string
  name: string
  kind: 'doc' | 'pdf' | 'xls' | 'csv'
  tag: string
  tagTone: SpecPillTone
}

export const TODAY_RESULT_FILES: TodayResultFile[] = [
  { id: 'f1', name: 'Повестка_совещания_CRM.docx', kind: 'doc', tag: 'ИИ', tagTone: 'purple' },
  { id: 'f2', name: 'Сравнение_КП_поставщиков.pdf', kind: 'pdf', tag: 'ИИ', tagTone: 'purple' },
  { id: 'f3', name: 'Отчёт_по_задачам_1С.xlsx', kind: 'xls', tag: 'ИИ', tagTone: 'purple' },
  { id: 'f4', name: 'Проект_решения_акт_работ.docx', kind: 'doc', tag: 'ИИ', tagTone: 'purple' },
  { id: 'f5', name: 'Лог_вызовов_агентов.csv', kind: 'csv', tag: 'ИИ', tagTone: 'purple' }
]

export const TODAY_MAIL_ROWS: SpecMailRow[] = [
  {
    id: 'tm1',
    sender: 'Иванов И.И.',
    subject: 'Запрос на отпуск',
    category: 'Кадры',
    catTone: 'blue',
    link: '—',
    time: '08:42',
    priority: 'Высокий',
    priTone: 'red',
    status: 'Прочитано',
    stTone: 'gray',
    assignee: '—',
    to: 'Отдел кадров',
    receivedLabel: 'Ср 16.09.2026 08:42',
    unread: false,
    preview: 'Прошу согласовать отпуск с 5 по 18 октября. Заявление во вложении.',
    body: 'Добрый день!\n\nПрошу согласовать ежегодный оплачиваемый отпуск с 5 по 18 октября 2026 года.\n\nНа период отсутствия обязанности передаю Смирнову А.В. Заявление прилагаю.\n\nС уважением,\nИванов Иван Иванович',
    attachments: [{ name: 'Заявление_на_отпуск.docx' }]
  },
  {
    id: 'tm2',
    sender: 'Смирнов А.В.',
    subject: 'Коммерческое предложение по проекту CRM — требуется согласование условий и сроков поставки',
    category: 'Коммерция',
    catTone: 'blue',
    link: 'CRM',
    time: '09:15',
    priority: 'Высокий',
    priTone: 'red',
    status: 'К обработке',
    stTone: 'orange',
    assignee: 'Иванов И.И.',
    to: 'Иванов И.И.; Коммерческий отдел',
    receivedLabel: 'Ср 16.09.2026 09:15',
    unread: true,
    preview: 'Направляю КП по внедрению CRM. Нужно согласовать сроки и стоимость до пятницы.',
    body: 'Добрый день, коллеги!\n\nНаправляю коммерческое предложение по проекту CRM. Поставщик готов начать работы с 1 октября при условии согласования спецификации до пятницы.\n\nПрошу проверить сроки поставки, стоимость лицензий и условия сопровождения. Смета и PDF с КП во вложении.\n\nЕсли замечаний нет — подготовлю протокол согласования.\n\nС уважением,\nСмирнов Андрей Викторович',
    attachments: [{ name: 'КП_CRM.pdf' }, { name: 'Смета_CRM.xlsx' }]
  },
  {
    id: 'tm3',
    sender: 'Бухгалтерия',
    subject: 'Акт',
    category: 'Договоры',
    catTone: 'purple',
    link: 'Офис 2024',
    time: '10:24',
    priority: 'Средний',
    priTone: 'orange',
    status: 'В работе',
    stTone: 'blue',
    assignee: 'Иванов И.И.',
    to: 'Иванов И.И.',
    receivedLabel: 'Ср 16.09.2026 10:24',
    unread: false,
    preview: 'Просим подписать акт выполненных работ по договору сопровождения 1С.',
    body: 'Добрый день!\n\nНаправляем акт выполненных работ за август по договору сопровождения 1С. Просим проверить объём и подписать до конца дня.\n\nПри расхождениях ответьте на это письмо с комментарием.\n\nБухгалтерия',
    attachments: [{ name: 'Акт_работ_август.docx' }]
  },
  {
    id: 'tm4',
    sender: 'Петрова А.С.',
    subject: 'Согласование спецификации оборудования для серверной инфраструктуры офиса',
    category: 'Закупки',
    catTone: 'green',
    link: 'Офис 2024',
    time: '11:03',
    priority: 'Средний',
    priTone: 'orange',
    status: 'Прочитано',
    stTone: 'gray',
    assignee: '—',
    to: 'Иванов И.И.; ИТ-отдел',
    receivedLabel: 'Ср 16.09.2026 11:03',
    unread: false,
    preview: 'Нужно согласовать спецификацию серверного оборудования до закупки.',
    body: 'Добрый день!\n\nПрошу согласовать спецификацию оборудования для серверной. Закупка запланирована на следующую неделю, без визы ИТ заявку не отправим.\n\nФайл спецификации во вложении. Если нужно заменить позиции — отметьте в таблице.\n\nС уважением,\nПетрова Анна Сергеевна',
    attachments: [{ name: 'Спецификация_оборудования.xlsx' }]
  },
  {
    id: 'tm5',
    sender: 'Соловьёва А.Н.',
    subject: 'Собираемся желающих вакцинироваться от гриппа',
    category: 'Кадры',
    catTone: 'blue',
    link: '—',
    time: '11:40',
    priority: 'Средний',
    priTone: 'orange',
    status: 'Непрочитано',
    stTone: 'orange',
    assignee: '—',
    to: 'Все сотрудники',
    receivedLabel: 'Ср 16.09.2026 11:40',
    unread: true,
    preview: 'С приходом осени увеличивается количество заболеваний. Предлагаем вакцинироваться от гриппа.',
    body: 'Добрый день. Уважаемые коллеги!\n\nС приходом осени увеличивается количество заболеваний. Какие принять меры профилактики — читайте во вложении.\n\nА также предлагаем вакцинироваться от гриппа. Запись — у офис-менеджера до пятницы.\n\nС уважением,\nСоловьёва Анастасия Николаевна',
    attachments: [{ name: 'Памятка_вакцинация.pdf' }]
  },
  {
    id: 'tm6',
    sender: 'ИТ-поддержка',
    subject: 'Плановые работы с VPN в четверг',
    category: 'ИТ',
    catTone: 'purple',
    link: '—',
    time: '12:05',
    priority: 'Средний',
    priTone: 'orange',
    status: 'Прочитано',
    stTone: 'gray',
    assignee: '—',
    to: 'Все сотрудники',
    receivedLabel: 'Ср 16.09.2026 12:05',
    unread: false,
    preview: 'В четверг с 19:00 до 21:00 VPN будет недоступен из-за обновления шлюза.',
    body: 'Добрый день!\n\nВ четверг с 19:00 до 21:00 проводим обновление VPN-шлюза. Удалённый доступ в это время будет недоступен.\n\nРегламент работ и контакты дежурного во вложении.\n\nИТ-поддержка',
    attachments: [{ name: 'Регламент_работ_VPN.docx' }]
  }
]

export type TodayProjectTaskRow = {
  id: string
  title: string
  deadline: string
  status: string
  statusTone: SpecPillTone
  assignee: string
  assigneeTone: SpecPillTone
}

export const TODAY_PROJECT_TASK_ROWS: TodayProjectTaskRow[] = [
  {
    id: 'pt1',
    title: 'Интеграция API CRM',
    deadline: '16.09',
    status: 'В работе',
    statusTone: 'blue',
    assignee: 'Сотрудник',
    assigneeTone: 'blue'
  },
  {
    id: 'pt2',
    title: 'Тестирование модуля отчётности и сверка выгрузок с эталонными данными за август',
    deadline: '18.09',
    status: 'Запланировано',
    statusTone: 'gray',
    assignee: 'ИИ',
    assigneeTone: 'purple'
  },
  {
    id: 'pt3',
    title: 'Согласование ТЗ',
    deadline: 'Сегодня',
    status: 'Ожидание',
    statusTone: 'orange',
    assignee: 'Сотрудник',
    assigneeTone: 'blue'
  },
  {
    id: 'pt4',
    title: 'Настройка прав доступа',
    deadline: '17.09',
    status: 'В работе',
    statusTone: 'blue',
    assignee: 'ИИ',
    assigneeTone: 'purple'
  }
]

export type TodayPreparedDecision = {
  id: string
  title: string
  status: string
  statusTone: SpecPillTone
  tag: string
  tagTone: SpecPillTone
}

export const TODAY_PREPARED_DECISIONS: TodayPreparedDecision[] = [
  {
    id: 'pd1',
    title: 'Решение #402 — Утвердить поставщика ООО «ТехноСервис»',
    status: 'Согласовано',
    statusTone: 'green',
    tag: 'ИИ',
    tagTone: 'purple'
  },
  {
    id: 'pd2',
    title: 'Решение #405 — Согласовать перенос этапа внедрения CRM на следующий квартал с учётом рисков по ресурсам',
    status: 'В работе',
    statusTone: 'blue',
    tag: 'ИИ',
    tagTone: 'purple'
  },
  {
    id: 'pd3',
    title: 'Решение #408 — Подписать акт',
    status: 'На проверке',
    statusTone: 'orange',
    tag: 'Сотрудник',
    tagTone: 'blue'
  },
  {
    id: 'pd4',
    title: 'Решение #411 — Утвердить график закупок оборудования для модернизации серверной инфраструктуры',
    status: 'Черновик',
    statusTone: 'gray',
    tag: 'ИИ',
    tagTone: 'purple'
  }
]

export const TODAY_TIMELINE_HOURS = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18]

/** В dev всегда показываем демо-план (скрин/фокус не сбивает раскладку). */
export const TODAY_PLAN_PREFER_MOCKS = import.meta.env.DEV
