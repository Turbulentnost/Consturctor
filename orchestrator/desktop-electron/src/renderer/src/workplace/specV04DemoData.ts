/** Демо-данные по макетам v0.4 до подключения Task/Project/Mail/Knowledge API. */

export type SpecPillTone = 'green' | 'blue' | 'orange' | 'red' | 'purple' | 'gray' | 'yellow'

export interface SpecProcessRow {
  id: string
  name: string
  code: string
  type: string
  typeTone: SpecPillTone
  source: string
  project: string
  taskToday: string
  status: string
  statusTone: SpecPillTone
  deadline: string
  deadlineUrgent?: boolean
  progress: number
}

export const DEMO_PROCESS_ROWS: SpecProcessRow[] = [
  {
    id: '1',
    name: 'Подготовка совещания',
    code: 'REG-01',
    type: 'Регламент',
    typeTone: 'green',
    source: 'Оркестратор',
    project: '—',
    taskToday: 'Согласовать повестку',
    status: 'В работе',
    statusTone: 'blue',
    deadline: 'Сегодня',
    deadlineUrgent: true,
    progress: 80
  },
  {
    id: '2',
    name: 'Согласование договора',
    code: 'REG-02',
    type: 'Регламент',
    typeTone: 'green',
    source: '1С',
    project: 'Офис 2024',
    taskToday: 'Проверить приложения',
    status: 'Ожидает',
    statusTone: 'orange',
    deadline: 'Завтра',
    progress: 45
  },
  {
    id: '3',
    name: 'Обработка входящей почты',
    code: 'ML-06',
    type: 'Письмо',
    typeTone: 'orange',
    source: 'Outlook',
    project: 'CRM',
    taskToday: 'Ответить клиенту',
    status: 'В работе',
    statusTone: 'blue',
    deadline: 'Сегодня',
    deadlineUrgent: true,
    progress: 62
  },
  {
    id: '4',
    name: 'Внедрение CRM',
    code: 'PRJ-001',
    type: 'Проект',
    typeTone: 'purple',
    source: 'TurboProject',
    project: 'CRM',
    taskToday: 'Проверить ТЗ',
    status: 'В работе',
    statusTone: 'blue',
    deadline: '30.09',
    progress: 65
  },
  {
    id: '5',
    name: 'Еженедельный отчёт KPI',
    code: 'REG-05',
    type: 'Регламент',
    typeTone: 'green',
    source: 'Оркестратор',
    project: '—',
    taskToday: 'Сформировать отчёт',
    status: 'Не начат',
    statusTone: 'gray',
    deadline: '25.09',
    progress: 0
  }
]

export interface SpecTaskRow {
  id: string
  title: string
  source: string
  sourceTone: SpecPillTone
  process: string
  project: string
  deadline: string
  urgent?: boolean
  priority: string
  priorityTone: SpecPillTone
  status: string
  statusTone: SpecPillTone
  executor: string
  who: string
  progress: number
}

export const DEMO_TASK_ROWS: SpecTaskRow[] = [
  {
    id: 't1',
    title: 'Подготовить повестку совещания по бюджету',
    source: 'Регламент',
    sourceTone: 'green',
    process: 'Совещания',
    project: 'Планирование',
    deadline: 'Сегодня 16:00',
    urgent: true,
    priority: 'Высокий',
    priorityTone: 'red',
    status: 'В работе',
    statusTone: 'blue',
    executor: 'Иванов И.И.',
    who: 'Я',
    progress: 70
  },
  {
    id: 't2',
    title: 'Согласовать спецификацию с юристами',
    source: '1С',
    sourceTone: 'blue',
    process: 'Закупки',
    project: 'Офис 2024',
    deadline: '14.08',
    priority: 'Средний',
    priorityTone: 'orange',
    status: 'На проверке',
    statusTone: 'purple',
    executor: 'Петрова А.С.',
    who: 'Сотрудник',
    progress: 90
  },
  {
    id: 't3',
    title: 'Ответить на КП по CRM',
    source: 'Outlook',
    sourceTone: 'orange',
    process: 'Письма',
    project: 'CRM',
    deadline: 'Сегодня 18:00',
    urgent: true,
    priority: 'Высокий',
    priorityTone: 'red',
    status: 'К выполнению',
    statusTone: 'gray',
    executor: 'Иванов И.И.',
    who: 'Я',
    progress: 20
  }
]

export interface SpecProjectRow {
  id: string
  name: string
  code: string
  role: string
  tasks: number
  status: string
  statusTone: SpecPillTone
  deadline: string
  progress: number
  risk: string
  riskTone: SpecPillTone
}

export const DEMO_PROJECT_ROWS: SpecProjectRow[] = [
  {
    id: 'p1',
    name: 'Внедрение CRM',
    code: 'PRJ-001',
    role: 'Руководитель',
    tasks: 3,
    status: 'В работе',
    statusTone: 'blue',
    deadline: '30.09.2024',
    progress: 65,
    risk: 'Нет',
    riskTone: 'green'
  },
  {
    id: 'p2',
    name: 'Модернизация склада',
    code: 'PRJ-004',
    role: 'Участник',
    tasks: 2,
    status: 'В работе',
    statusTone: 'blue',
    deadline: '15.10.2024',
    progress: 42,
    risk: 'Есть риск',
    riskTone: 'orange'
  },
  {
    id: 'p3',
    name: 'Офис 2024',
    code: 'PRJ-007',
    role: 'Куратор',
    tasks: 1,
    status: 'На паузе',
    statusTone: 'gray',
    deadline: '01.12.2024',
    progress: 28,
    risk: 'Высокий',
    riskTone: 'red'
  }
]

export interface SpecMailAttachment {
  name: string
}

export interface SpecMailRow {
  id: string
  sender: string
  subject: string
  category: string
  catTone: SpecPillTone
  link: string
  time: string
  priority: string
  priTone: SpecPillTone
  status: string
  stTone: SpecPillTone
  assignee: string
  to?: string
  body?: string
  preview?: string
  receivedLabel?: string
  unread?: boolean
  attachments?: SpecMailAttachment[]
}

export const DEMO_MAIL_ROWS: SpecMailRow[] = [
  {
    id: 'm1',
    sender: 'Смирнов А.В.',
    subject: 'Коммерческое предложение по проекту CRM',
    category: 'Коммерция',
    catTone: 'blue',
    link: 'CRM / Письма',
    time: '10:24',
    priority: 'Высокий',
    priTone: 'red',
    status: 'К обработке',
    stTone: 'orange',
    assignee: 'Иванов И.И.'
  },
  {
    id: 'm2',
    sender: 'Бухгалтерия',
    subject: 'Согласование акта выполненных работ',
    category: 'Договоры',
    catTone: 'purple',
    link: 'Офис 2024',
    time: '09:15',
    priority: 'Средний',
    priTone: 'orange',
    status: 'В работе',
    stTone: 'blue',
    assignee: 'Иванов И.И.'
  }
]

export interface SpecMeetingRow {
  time: string
  title: string
  format: string
  participants: string
  prep: string
  prepTone: SpecPillTone
  status: string
  stTone: SpecPillTone
}

export const DEMO_MEETING_ROWS: SpecMeetingRow[] = [
  {
    time: '10:00',
    title: 'Обсуждение статуса проекта',
    format: 'Онлайн',
    participants: '6 чел.',
    prep: 'Готово',
    prepTone: 'green',
    status: 'В работе',
    stTone: 'blue'
  },
  {
    time: '12:00',
    title: 'Совещание по бюджету',
    format: 'Офис 301',
    participants: '8 чел.',
    prep: 'Требуется',
    prepTone: 'orange',
    status: 'Запланировано',
    stTone: 'gray'
  }
]

export interface SpecDecisionRow {
  id: string
  title: string
  basis: string
  process: string
  project: string
  prepared: string
  deadline: string
  overdue?: boolean
  priority: string
  priTone: SpecPillTone
  status: string
  stTone: SpecPillTone
}

export const DEMO_DECISION_ROWS: SpecDecisionRow[] = [
  {
    id: 'd1',
    title: 'Утвердить выбор поставщика ООО «ТехноСервис»',
    basis: 'Сравнительный анализ предложений',
    process: 'Закупки',
    project: 'Офис 2024',
    prepared: 'ИИ-агент',
    deadline: 'Сегодня 17:00',
    priority: 'Высокий',
    priTone: 'red',
    status: 'Ожидает решения',
    stTone: 'orange'
  },
  {
    id: 'd2',
    title: 'Согласовать изменение сроков этапа CRM',
    basis: 'Отчёт о рисках интеграции',
    process: 'Проекты',
    project: 'CRM',
    prepared: 'Сотрудник',
    deadline: '15.08',
    priority: 'Средний',
    priTone: 'orange',
    status: 'На доработке',
    stTone: 'yellow'
  }
]

export interface SpecKnowledgeRow {
  id: string
  name: string
  type: string
  typeTone: SpecPillTone
  section: string
  process: string
  project: string
  version: string
  updated: string
  author: string
}

export const DEMO_KNOWLEDGE_ROWS: SpecKnowledgeRow[] = [
  {
    id: 'k1',
    name: 'Регламент проведения совещаний',
    type: 'Регламент',
    typeTone: 'green',
    section: 'Совещания',
    process: 'Совещания',
    project: '—',
    version: 'v3.2',
    updated: '12.08.2024',
    author: 'HR'
  },
  {
    id: 'k2',
    name: 'Шаблон протокола совещания',
    type: 'Шаблон',
    typeTone: 'orange',
    section: 'Документы',
    process: 'Совещания',
    project: '—',
    version: 'v1.0',
    updated: '05.08.2024',
    author: 'Оркестратор'
  }
]

export interface SpecHistoryRow {
  id: string
  at: string
  event: string
  object: string
  process: string
  project: string
  initiator: string
  result: string
  resultTone: SpecPillTone
  comment: string
}

export const DEMO_HISTORY_ROWS: SpecHistoryRow[] = [
  {
    id: 'h1',
    at: '12.08.2025 16:42',
    event: 'Создана задача',
    object: 'Задача #1245',
    process: 'Согласование',
    project: 'Внедрение CRM',
    initiator: 'Иванов И.И.',
    result: 'Успешно',
    resultTone: 'green',
    comment: 'Из письма Outlook'
  },
  {
    id: 'h2',
    at: '12.08.2025 15:10',
    event: 'Запуск агента',
    object: 'REG-01',
    process: 'Совещания',
    project: '—',
    initiator: 'ИИ-агент',
    result: 'Успешно',
    resultTone: 'green',
    comment: 'Подготовка повестки'
  }
]

export const ASK_CHIPS: Record<string, string[]> = {
  today: [
    'Какие регламентные процессы просрочены?',
    'Покажи задачи по проекту внедрения CRM',
    'Подготовь черновик письма по совещанию'
  ],
  processes: [
    'Какие регламентные процессы просрочены?',
    'Покажи задачи по проекту внедрения CRM',
    'Подготовь черновик письма по совещанию'
  ],
  tasks: [
    'Покажи мои просроченные задачи',
    'Какие задачи из 1С на сегодня?',
    'Сформируй план на завтра'
  ],
  projects: [
    'Какой статус проекта CRM?',
    'Покажи мои задачи на сегодня',
    'Сформируй краткий отчёт по рискам'
  ],
  mail: [
    'Покажи письма от ключевых клиентов',
    'Что важного по проекту CRM?',
    'Создай дайджест за неделю'
  ],
  meetings: [
    'Сформировать проект решения',
    'Найти все связанные документы',
    'Подготовить краткое резюме совещания'
  ],
  decisions: [
    'В чём суть этого решения?',
    'Показать похожие решения',
    'Какие риски, если не утвердить?'
  ],
  knowledge: [
    'Найти регламент по совещаниям',
    'Показать шаблоны протоколов',
    'Какие материалы обновлялись на этой неделе?'
  ],
  history: [
    'Покажи историю по проекту CRM',
    'Какие ошибки были за неделю?',
    'Действия ИИ-агентов за сегодня'
  ]
}
