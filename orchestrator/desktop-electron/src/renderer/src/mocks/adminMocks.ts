export type MetricIconVariant =
  | 'agents_total'
  | 'agents_used'
  | 'active_runs'
  | 'users'
  | 'success_rate'
  | 'errors'
  | 'queue'
  | 'system_load'

export type MetricTrendTone = 'positive' | 'negative' | 'neutral'

export interface AdminMetricMock {
  id: string
  label: string
  value: string
  trend?: string
  trendTone?: MetricTrendTone
  icon: MetricIconVariant
}

export interface AdminChartSeriesMock {
  id: string
  label: string
  color: string
  points: number[]
}

export interface AdminLaunchDynamicsMock {
  title: string
  yMax: number
  yTicks: number[]
  xLabels: string[]
  series: AdminChartSeriesMock[]
  legend: Array<{ id: string; label: string; color: string }>
}

export interface AdminAgentStatusSliceMock {
  id: string
  label: string
  value: number
  color: string
}

export interface AdminAgentStatusesMock {
  title: string
  total: number
  slices: AdminAgentStatusSliceMock[]
}

export interface AdminIntegrationMock {
  id: string
  label: string
  online: boolean
}

export interface AdminOverviewMock {
  breadcrumb: string
  dashboardTitle: string
  dashboardSubtitle: string
  periodLabel: string
  dateRange: string
  refreshLabel: string
  metrics: AdminMetricMock[]
  launchDynamics: AdminLaunchDynamicsMock
  agentStatuses: AdminAgentStatusesMock
  integrations: AdminIntegrationMock[]
}

export const adminOverviewMock: AdminOverviewMock = {
  breadcrumb: 'Обзор — Сводная панель администратора',
  dashboardTitle: 'Сводная панель',
  dashboardSubtitle: 'Ключевые показатели системы ИИ-агентов',
  periodLabel: 'Период: Неделя',
  dateRange: '08.09.2026 — 14.09.2026',
  refreshLabel: 'Обновить',
  metrics: [
    {
      id: 'agents_total',
      label: 'Всего агентов',
      value: '37',
      trend: '+2',
      trendTone: 'positive',
      icon: 'agents_total'
    },
    {
      id: 'agents_used',
      label: 'Используются',
      value: '29 (78%)',
      trend: '+12%',
      trendTone: 'positive',
      icon: 'agents_used'
    },
    {
      id: 'active_runs',
      label: 'Активных запусков',
      value: '24',
      icon: 'active_runs'
    },
    {
      id: 'users',
      label: 'Пользователей',
      value: '142',
      trend: '+5%',
      trendTone: 'positive',
      icon: 'users'
    },
    {
      id: 'success_rate',
      label: 'Успешных запусков',
      value: '92%',
      icon: 'success_rate'
    },
    {
      id: 'errors',
      label: 'Ошибок',
      value: '3%',
      icon: 'errors'
    },
    {
      id: 'queue',
      label: 'В очереди',
      value: '12',
      icon: 'queue'
    },
    {
      id: 'system_load',
      label: 'Загрузка системы',
      value: '68%',
      icon: 'system_load'
    }
  ],
  launchDynamics: {
    title: 'Динамика запусков агентов',
    yMax: 200,
    yTicks: [0, 50, 100, 150, 200],
    xLabels: ['08.09', '09.09', '10.09', '11.09', '12.09', '13.09', '14.09'],
    series: [
      {
        id: 'success',
        label: 'Успешные',
        color: '#2f9e44',
        points: [118, 128, 142, 138, 168, 152, 145]
      },
      {
        id: 'processing',
        label: 'В обработке',
        color: '#1a73e8',
        points: [92, 98, 108, 112, 128, 118, 110]
      },
      {
        id: 'errors',
        label: 'С ошибками',
        color: '#e55353',
        points: [48, 52, 58, 55, 62, 54, 50]
      }
    ],
    legend: [
      { id: 'success', label: 'Успешные', color: '#2f9e44' },
      { id: 'processing', label: 'В обработке', color: '#1a73e8' },
      { id: 'errors', label: 'С ошибками', color: '#e55353' }
    ]
  },
  agentStatuses: {
    title: 'Статусы агентов',
    total: 37,
    slices: [
      { id: 'active', label: 'Активные', value: 29, color: '#1a73e8' },
      { id: 'pause', label: 'Пауза', value: 4, color: '#2f9e44' },
      { id: 'setup', label: 'На настройке', value: 2, color: '#f0b429' },
      { id: 'error', label: 'Ошибка', value: 2, color: '#e8943a' }
    ]
  },
  integrations: [
    { id: 'onec', label: '1С', online: true },
    { id: 'outlook', label: 'Outlook', online: true },
    { id: 'sed', label: 'СЭД', online: true },
    { id: 'kb', label: 'База знаний', online: true },
    { id: 'gateway', label: 'Agent Gateway', online: true }
  ]
}

export type AdminBadgeTone = 'success' | 'warning' | 'error' | 'info' | 'neutral'
export type AdminSlaTone = 'ok' | 'warn' | 'fail'

export interface AdminFilterMock {
  id: string
  options: string[]
  defaultValue?: string
}

export interface AdminPeriodOptionMock {
  id: string
  label: string
}

export const ADMIN_PERIOD_OPTIONS: AdminPeriodOptionMock[] = [
  { id: 'day', label: 'Период: День' },
  { id: 'week', label: 'Период: Неделя' },
  { id: 'month', label: 'Период: Месяц' },
  { id: 'quarter', label: 'Период: Квартал' },
  { id: 'year', label: 'Период: Год' }
]

export const HISTORY_FILTERS: AdminFilterMock[] = [
  { id: 'status', options: ['Все статусы', 'Завершен', 'В работе', 'Ошибка', 'Отменен'] },
  { id: 'agent', options: ['Все агенты', 'Агент_Совещания', 'Агент_Аналитика', 'Агент_Корреспонденция', 'Агент_КП', 'Агент_Финансы', 'Агент_Закупки'] },
  { id: 'process', options: ['Все процессы', 'Подготовка совещания', 'Анализ рынка', 'Обработка корреспонденции', 'Формирование КП', 'Финансовый анализ'] },
  { id: 'user', options: ['Все пользователи', 'Иванов И.И.', 'Петров А.А.', 'Сидоров В.В.', 'Кузнецова Е.Е.', 'Михайлов Д.Д.'] }
]

export const USERS_FILTERS: AdminFilterMock[] = [
  { id: 'department', options: ['Все подразделения', 'IT', 'Продажи', 'Аналитика', 'Документооборот', 'Финансы', 'HR', 'Закупки'] },
  { id: 'role', options: ['Все роли', 'Администратор', 'Пользователь', 'Аудитор', 'Оператор'] },
  { id: 'status', options: ['Все статусы', 'Активен', 'Заблокирован', 'Приглашен', 'Неактивен'] }
]

export const AI_AGENTS_FILTERS: AdminFilterMock[] = [
  { id: 'status', options: ['Все статусы', 'Активен', 'На настройке', 'Остановлен', 'Ошибка'] },
  { id: 'process', options: ['Все процессы', 'Подготовка совещания', 'Обработка корреспонденции', 'Анализ рынка', 'Формирование КП', 'Финансовый анализ'] },
  { id: 'owner', options: ['Все владельцы', 'Иванов И.И.', 'Кузнецова Е.Е.', 'Сидоров В.В.', 'Петров А.А.', 'Михайлов Д.Д.'] }
]

export const KNOWLEDGE_FILTERS: AdminFilterMock[] = [
  { id: 'type', options: ['Все типы', 'Регламент', 'Шаблон', 'Справочник', 'FAQ', 'Инструкция'] },
  { id: 'agent', options: ['Все агенты', 'Агент_Закупки', 'Агент_КП', 'Агент_Совещания', 'Агент_Аналитика', 'Агент_Финансы'] },
  { id: 'status', options: ['Все статусы', 'Актуален', 'Требует обновления', 'Архив', 'На проверке'] }
]

export interface AdminPeriodMock {
  periodLabel: string
  dateRange: string
}

export interface AdminHistoryRowMock {
  id: string
  process: string
  agent: string
  user: string
  status: string
  statusTone: AdminBadgeTone
  launchedAt: string
  duration: string
  sla: AdminSlaTone
  tab?: string
}

export interface AdminHistoryMock extends AdminPeriodMock {
  breadcrumb: string
  title: string
  subtitle: string
  tabs: Array<{ id: string; label: string }>
  activeTab: string
  filters: AdminFilterMock[]
  rows: AdminHistoryRowMock[]
  pagination: { pageSize: number; total: number }
}

export interface AdminCalendarEventMock {
  id: string
  dayIndex: number
  startHour: number
  endHour: number
  title: string
  tone: 'green' | 'blue' | 'purple' | 'yellow' | 'red'
  agentId: string
}

export interface AdminLaunchCalendarMock extends AdminPeriodMock {
  breadcrumb: string
  title: string
  subtitle: string
  createLabel: string
  viewModes: string[]
  activeView: string
  weekRange: string
  days: string[]
  hours: string[]
  events: AdminCalendarEventMock[]
  agentFilters: Array<{ id: string; label: string; color: string; checked: boolean }>
  miniMonth: string
  miniDays: Array<{ day: number; active?: boolean; muted?: boolean }>
  unscheduled: Array<{ id: string; title: string; subtitle: string; tone: 'purple' | 'green' }>
  scheduleAllLabel: string
}

export interface AdminKpiSummaryMock {
  id: string
  label: string
  value: string
  trend?: string
  trendTone?: MetricTrendTone
  tint?: 'orange' | 'green' | 'red' | 'none'
  icon?: 'target' | 'none'
}

export interface AdminKpiAgentCardMock {
  id: string
  name: string
  process: string
  status: string
  statusTone: AdminBadgeTone
  efficiency: number
  summaries: AdminKpiSummaryMock[]
}

export interface AdminKpiMock extends AdminPeriodMock {
  breadcrumb: string
  title: string
  subtitle: string
  tabs: Array<{ id: string; label: string }>
  activeTab: string
  summaries: AdminKpiSummaryMock[]
  agentCards: AdminKpiAgentCardMock[]
  dynamics: AdminLaunchDynamicsMock
  topAgents: Array<{ label: string; value: number }>
  gauges: Array<{ id: string; label: string; value: string; tone: 'green' | 'orange' | 'cyan' }>
}

export interface AdminUserRowMock {
  fio: string
  position: string
  department: string
  role: string
  status: string
  agentsAccess: number
  agentsUsed: number
  lastActivity: string
}

export interface AdminUsersMock {
  breadcrumb: string
  title: string
  subtitle: string
  addLabel: string
  filters: AdminFilterMock[]
  rows: AdminUserRowMock[]
  pagination: { pageSize: number; total: number }
}

export interface AdminAgentRowMock {
  name: string
  process: string
  owner: string
  version: string
  status: string
  statusTone: AdminBadgeTone
  runs: number
  successRate: string
  used: boolean
}

export interface AdminAgentDetailMock {
  name: string
  status: string
  statusTone: AdminBadgeTone
  description: string
  tabs: string[]
  activeTab: string
  info: Array<{ label: string; value: string }>
  metrics: Array<{ label: string; value: string }>
  processes: Array<{ title: string; time: string; status: string; statusTone: AdminBadgeTone; tone: 'green' | 'grey' }>
}

export interface AdminAiAgentsMock {
  breadcrumb: string
  title: string
  subtitle: string
  createLabel: string
  importLabel: string
  filters: AdminFilterMock[]
  rows: AdminAgentRowMock[]
  pagination: { pageSize: number; total: number }
  detail: AdminAgentDetailMock
}

export interface AdminKnowledgeRowMock {
  name: string
  type: string
  agents: string
  version: string
  status: string
  statusTone: AdminBadgeTone
  updatedAt: string
}

export interface AdminKnowledgeDocumentDetail {
  title: string
  status: string
  statusTone: AdminBadgeTone
  meta: string
  text: string
  format: string
  author: string
  category: string
  tags: string[]
  usageTotal: string
  usageTrend: string
  usageBars: number[]
  agentsShare: Array<{ label: string; value: number }>
  related: Array<{ title: string; type: string }>
  relatedCount: number
}

export interface AdminKnowledgeBaseMock {
  breadcrumb: string
  title: string
  subtitle: string
  addLabel: string
  filters: AdminFilterMock[]
  rows: AdminKnowledgeRowMock[]
  pagination: { pageSize: number; total: number }
  document: AdminKnowledgeDocumentDetail
}

const ADMIN_PERIOD: AdminPeriodMock = {
  periodLabel: 'Период: Неделя',
  dateRange: '08.09.2026 — 14.09.2026'
}

export const adminHistoryMock: AdminHistoryMock = {
  ...ADMIN_PERIOD,
  breadcrumb: 'История — Процессы, задачи, письма, задачи по проектам',
  title: 'История',
  subtitle: 'Просмотр выполненных процессов, задач, писем и проектных задач',
  tabs: [
    { id: 'processes', label: 'Процессы' },
    { id: 'tasks', label: 'Задачи' },
    { id: 'letters', label: 'Письма' },
    { id: 'project_tasks', label: 'Задачи по проектам' }
  ],
  activeTab: 'processes',
  filters: HISTORY_FILTERS,
  rows: [
    { id: 'P-458', process: 'Подготовка совещания', agent: 'Агент_Совещания', user: 'Петров А.А.', status: 'Завершен', statusTone: 'success', launchedAt: '14.09.2026 10:15', duration: '12 мин', sla: 'ok' },
    { id: 'P-459', process: 'Анализ рынка', agent: 'Агент_Аналитика', user: 'Сидоров В.В.', status: 'В работе', statusTone: 'warning', launchedAt: '14.09.2026 09:30', duration: '25 мин', sla: 'warn' },
    { id: 'P-460', process: 'Обработка корреспонденции', agent: 'Агент_Корреспонденция', user: 'Кузнецова Е.Е.', status: 'Завершен', statusTone: 'success', launchedAt: '14.09.2026 08:45', duration: '8 мин', sla: 'ok' },
    { id: 'P-461', process: 'Формирование КП', agent: 'Агент_КП', user: 'Иванов И.И.', status: 'Завершен', statusTone: 'success', launchedAt: '13.09.2026 16:20', duration: '18 мин', sla: 'ok' },
    { id: 'P-462', process: 'Финансовый анализ', agent: 'Агент_Финансы', user: 'Михайлов Д.Д.', status: 'Ошибка', statusTone: 'error', launchedAt: '13.09.2026 14:10', duration: '5 мин', sla: 'fail' },
    { id: 'P-463', process: 'Отчет по закупкам', agent: 'Агент_Закупки', user: 'Николаев С.С.', status: 'Завершен', statusTone: 'success', launchedAt: '13.09.2026 11:00', duration: '22 мин', sla: 'ok' },
    { id: 'P-464', process: 'Анализ Базы знаний', agent: 'Агент_Аналитика', user: 'Орлова М.М.', status: 'В работе', statusTone: 'warning', launchedAt: '12.09.2026 15:40', duration: '31 мин', sla: 'warn' },
    { id: 'P-465', process: 'Сверка данных', agent: 'Агент_Финансы', user: 'Волков П.П.', status: 'Завершен', statusTone: 'success', launchedAt: '12.09.2026 10:05', duration: '14 мин', sla: 'ok' },
    { id: 'P-466', process: 'Подготовка материалов', agent: 'Агент_Совещания', user: 'Лебедев А.А.', status: 'Завершен', statusTone: 'success', launchedAt: '11.09.2026 09:15', duration: '9 мин', sla: 'ok' },
    { id: 'P-467', process: 'Экспорт отчетов', agent: 'Агент_Финансы', user: 'Смирнова К.К.', status: 'Завершен', statusTone: 'success', launchedAt: '10.09.2026 17:30', duration: '6 мин', sla: 'ok' }
  ],
  pagination: { pageSize: 10, total: 248 }
}

export const adminLaunchCalendarMock: AdminLaunchCalendarMock = {
  ...ADMIN_PERIOD,
  breadcrumb: 'Календарь запуска — Планирование и контроль выполнения',
  title: 'Календарь запусков',
  subtitle: 'Планирование, автозапуски и контроль выполнения агентов',
  createLabel: 'Создать запуск',
  viewModes: ['День', 'Неделя', 'Месяц', 'Сегодня'],
  activeView: 'Неделя',
  weekRange: '08.09.2025 — 14.09.2025',
  days: ['Пн 08.09', 'Вт 09.09', 'Ср 10.09', 'Чт 11.09', 'Пт 12.09', 'Сб 13.09', 'Вс 14.09'],
  hours: ['08:00', '09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00'],
  events: [
    { id: 'e1', dayIndex: 0, startHour: 9, endHour: 10, title: 'Подготовка совещаний', tone: 'green', agentId: 'meet' },
    { id: 'e2', dayIndex: 0, startHour: 11, endHour: 12, title: 'Анализ рынка', tone: 'blue', agentId: 'analytics' },
    { id: 'e3', dayIndex: 0, startHour: 15, endHour: 16, title: 'Обработка корреспонденции', tone: 'purple', agentId: 'mail' },
    { id: 'e4', dayIndex: 2, startHour: 11, endHour: 12, title: 'Подготовка КП', tone: 'yellow', agentId: 'sales' },
    { id: 'e5', dayIndex: 2, startHour: 13, endHour: 14, title: 'Финансовый анализ', tone: 'red', agentId: 'fin' },
    { id: 'e6', dayIndex: 4, startHour: 13, endHour: 14, title: 'Отчет по закупкам', tone: 'blue', agentId: 'proc' },
    { id: 'e7', dayIndex: 4, startHour: 15, endHour: 16, title: 'Анализ Базы знаний', tone: 'green', agentId: 'analytics' },
    { id: 'e8', dayIndex: 4, startHour: 16, endHour: 17, title: 'Сверка данных', tone: 'yellow', agentId: 'fin' },
    { id: 'e9', dayIndex: 8, startHour: 9, endHour: 10, title: 'HR-анализ кандидатов', tone: 'yellow', agentId: 'hr' },
    { id: 'e10', dayIndex: 13, startHour: 8, endHour: 9, title: 'Планерное совещание', tone: 'blue', agentId: 'meet' },
    { id: 'e11', dayIndex: 13, startHour: 10, endHour: 11, title: 'Сводка KPI', tone: 'green', agentId: 'analytics' },
    { id: 'e12', dayIndex: 13, startHour: 14, endHour: 15, title: 'Обработка входящих', tone: 'purple', agentId: 'mail' },
    { id: 'e13', dayIndex: 20, startHour: 11, endHour: 12, title: 'Контроль закупок', tone: 'blue', agentId: 'proc' },
    { id: 'e14', dayIndex: 24, startHour: 15, endHour: 16, title: 'Квартальный отчёт', tone: 'red', agentId: 'fin' }
  ],
  agentFilters: [
    { id: 'all', label: 'Все агенты', color: '#1a73e8', checked: true },
    { id: 'meet', label: 'Агент. Совещания', color: '#1a73e8', checked: true },
    { id: 'mail', label: 'Агент. Корреспонденция', color: '#1a73e8', checked: true },
    { id: 'analytics', label: 'Агент. Аналитика', color: '#8a9a5b', checked: true },
    { id: 'sales', label: 'Агент. Коммерческий', color: '#e8943a', checked: true },
    { id: 'proc', label: 'Агент. Закупки', color: '#2f9e44', checked: true },
    { id: 'hr', label: 'Агент. HR', color: '#f0b429', checked: true },
    { id: 'fin', label: 'Агент. Финансы', color: '#e55353', checked: true }
  ],
  miniMonth: 'Сентябрь 2025',
  miniDays: [
    { day: 1, muted: true }, { day: 2, muted: true }, { day: 3, muted: true }, { day: 4, muted: true }, { day: 5, muted: true }, { day: 6, muted: true }, { day: 7, muted: true },
    { day: 8 }, { day: 9 }, { day: 10 }, { day: 11, active: true }, { day: 12 }, { day: 13 }, { day: 14 }
  ],
  unscheduled: [
    { id: 'u1', title: 'Анализ отзывов клиентов', subtitle: 'Агент. Аналитика • Подготовить сводный отчет по отзывам за август', tone: 'purple' },
    { id: 'u2', title: 'Экспорт отчетов', subtitle: 'Агент. Финансы • Выгрузка ежемесячных отчетов', tone: 'green' }
  ],
  scheduleAllLabel: 'Запланировать все'
}

export const adminKpiMock: AdminKpiMock = {
  periodLabel: 'Период: Месяц',
  dateRange: '01.09.2026 — 14.09.2026',
  breadcrumb: 'KPI — Анализ эффективности и загрузки системы',
  title: 'KPI',
  subtitle: 'Анализ эффективности и загрузки системы',
  tabs: [
    { id: 'general', label: 'Общее' },
    { id: 'agents', label: 'Агенты' },
    { id: 'users', label: 'Пользователи' },
    { id: 'processes', label: 'Процессы' },
    { id: 'system', label: 'Система' }
  ],
  activeTab: 'general',
  summaries: [
    { id: 's1', label: 'Успешность задач', value: '92%', trend: '(+3%)', trendTone: 'positive', tint: 'none' },
    { id: 's2', label: 'Среднее время', value: '1,8 мин', trend: '(-12%)', trendTone: 'positive', tint: 'none' },
    { id: 's3', label: 'Загрузка агентов', value: '68%', tint: 'orange' },
    { id: 's4', label: 'Активные пользователи', value: '142', tint: 'none' },
    { id: 's5', label: 'Доступность системы', value: '99,7%', tint: 'green' },
    { id: 's6', label: 'Статус системы', value: '', icon: 'target', tint: 'green' },
    { id: 's7', label: 'Критические ошибки', value: '3', trend: '(-2)', trendTone: 'negative', tint: 'red' }
  ],
  agentCards: [
    {
      id: 'meet',
      name: 'Агент_Совещания',
      process: 'Подготовка совещания',
      status: 'Активен',
      statusTone: 'success',
      efficiency: 96,
      summaries: [
        { id: 's1', label: 'Успешность задач', value: '96%', trend: '(+2%)', trendTone: 'positive', tint: 'none' },
        { id: 's2', label: 'Среднее время', value: '1,4 мин', trend: '(-8%)', trendTone: 'positive', tint: 'none' },
        { id: 's3', label: 'Загрузка агента', value: '74%', tint: 'orange' },
        { id: 's4', label: 'Запусков', value: '1 245', tint: 'none' },
        { id: 's5', label: 'Пользователей', value: '28', tint: 'none' },
        { id: 's6', label: 'Статус', value: '', icon: 'target', tint: 'green' },
        { id: 's7', label: 'Ошибки', value: '1', trend: '(-1)', trendTone: 'negative', tint: 'red' }
      ]
    },
    {
      id: 'kp',
      name: 'Агент_КП',
      process: 'Формирование КП',
      status: 'Активен',
      statusTone: 'success',
      efficiency: 92,
      summaries: [
        { id: 's1', label: 'Успешность задач', value: '93%', trend: '(+1%)', trendTone: 'positive', tint: 'none' },
        { id: 's2', label: 'Среднее время', value: '2,1 мин', trend: '(-5%)', trendTone: 'positive', tint: 'none' },
        { id: 's3', label: 'Загрузка агента', value: '61%', tint: 'orange' },
        { id: 's4', label: 'Запусков', value: '678', tint: 'none' },
        { id: 's5', label: 'Пользователей', value: '19', tint: 'none' },
        { id: 's6', label: 'Статус', value: '', icon: 'target', tint: 'green' },
        { id: 's7', label: 'Ошибки', value: '2', trend: '(0)', trendTone: 'negative', tint: 'red' }
      ]
    },
    {
      id: 'proc',
      name: 'Агент_Закупки',
      process: 'Отчет по закупкам',
      status: 'Активен',
      statusTone: 'success',
      efficiency: 88,
      summaries: [
        { id: 's1', label: 'Успешность задач', value: '90%', trend: '(+4%)', trendTone: 'positive', tint: 'none' },
        { id: 's2', label: 'Среднее время', value: '2,6 мин', trend: '(-9%)', trendTone: 'positive', tint: 'none' },
        { id: 's3', label: 'Загрузка агента', value: '55%', tint: 'orange' },
        { id: 's4', label: 'Запусков', value: '412', tint: 'none' },
        { id: 's5', label: 'Пользователей', value: '14', tint: 'none' },
        { id: 's6', label: 'Статус', value: '', icon: 'target', tint: 'green' },
        { id: 's7', label: 'Ошибки', value: '4', trend: '(+1)', trendTone: 'negative', tint: 'red' }
      ]
    },
    {
      id: 'analytics',
      name: 'Агент_Аналитика',
      process: 'Анализ рынка',
      status: 'На настройке',
      statusTone: 'warning',
      efficiency: 85,
      summaries: [
        { id: 's1', label: 'Успешность задач', value: '87%', trend: '(-2%)', trendTone: 'negative', tint: 'none' },
        { id: 's2', label: 'Среднее время', value: '3,2 мин', trend: '(+6%)', trendTone: 'negative', tint: 'none' },
        { id: 's3', label: 'Загрузка агента', value: '42%', tint: 'orange' },
        { id: 's4', label: 'Запусков', value: '456', tint: 'none' },
        { id: 's5', label: 'Пользователей', value: '11', tint: 'none' },
        { id: 's6', label: 'Статус', value: '', icon: 'target', tint: 'green' },
        { id: 's7', label: 'Ошибки', value: '6', trend: '(+2)', trendTone: 'negative', tint: 'red' }
      ]
    },
    {
      id: 'fin',
      name: 'Агент_Финансы',
      process: 'Финансовый анализ',
      status: 'Активен',
      statusTone: 'success',
      efficiency: 82,
      summaries: [
        { id: 's1', label: 'Успешность задач', value: '89%', trend: '(0%)', trendTone: 'positive', tint: 'none' },
        { id: 's2', label: 'Среднее время', value: '2,9 мин', trend: '(-3%)', trendTone: 'positive', tint: 'none' },
        { id: 's3', label: 'Загрузка агента', value: '48%', tint: 'orange' },
        { id: 's4', label: 'Запусков', value: '534', tint: 'none' },
        { id: 's5', label: 'Пользователей', value: '16', tint: 'none' },
        { id: 's6', label: 'Статус', value: '', icon: 'target', tint: 'green' },
        { id: 's7', label: 'Ошибки', value: '5', trend: '(+1)', trendTone: 'negative', tint: 'red' }
      ]
    }
  ],
  dynamics: {
    title: 'Динамика KPI',
    yMax: 100,
    yTicks: [0, 25, 50, 75, 100],
    xLabels: ['08.09', '09.09', '10.09', '11.09', '12.09', '13.09', '14.09'],
    series: [
      { id: 'success', label: 'Успешность', color: '#2f9e44', points: [28, 32, 35, 33, 38, 36, 34] },
      { id: 'time', label: 'Среднее время', color: '#1a73e8', points: [72, 78, 82, 80, 88, 84, 81] },
      { id: 'load', label: 'Загрузка системы', color: '#e8943a', points: [58, 60, 62, 61, 66, 64, 63] }
    ],
    legend: [
      { id: 'success', label: 'Успешность', color: '#2f9e44' },
      { id: 'time', label: 'Среднее время', color: '#1a73e8' },
      { id: 'load', label: 'Загрузка системы', color: '#e8943a' }
    ]
  },
  topAgents: [
    { label: 'Агент_Совещания', value: 96 },
    { label: 'Агент_КП', value: 92 },
    { label: 'Агент_Закупки', value: 88 },
    { label: 'Агент_Аналитика', value: 85 },
    { label: 'Агент_Финансы', value: 82 }
  ],
  gauges: [
    { id: 'cpu', label: 'CPU', value: '32%', tone: 'green' },
    { id: 'mem', label: 'Память', value: '68%', tone: 'orange' },
    { id: 'queue', label: 'Очередь', value: '12', tone: 'cyan' },
    { id: 'avail', label: 'Доступность', value: '99,7%', tone: 'green' }
  ]
}

export const adminUsersMock: AdminUsersMock = {
  breadcrumb: 'Пользователи — Управление доступом и активностью',
  title: 'Пользователи',
  subtitle: 'Управление учетными записями, ролями и использованием ИИ-агентов',
  addLabel: 'Добавить пользователя',
  filters: USERS_FILTERS,
  rows: [
    { fio: 'Иванов И.И.', position: 'Системный администратор', department: 'IT', role: 'Администратор', status: 'Активен', agentsAccess: 37, agentsUsed: 12, lastActivity: '14.09.2026 12:45' },
    { fio: 'Петров А.А.', position: 'Руководитель отдела', department: 'Продажи', role: 'Пользователь', status: 'Активен', agentsAccess: 8, agentsUsed: 5, lastActivity: '14.09.2026 11:20' },
    { fio: 'Сидоров В.В.', position: 'Аналитик', department: 'Аналитика', role: 'Пользователь', status: 'Активен', agentsAccess: 6, agentsUsed: 4, lastActivity: '14.09.2026 10:05' },
    { fio: 'Кузнецова Е.Е.', position: 'Специалист', department: 'Документооборот', role: 'Пользователь', status: 'Активен', agentsAccess: 5, agentsUsed: 3, lastActivity: '13.09.2026 18:10' },
    { fio: 'Михайлов Д.Д.', position: 'Финансовый контролер', department: 'Финансы', role: 'Пользователь', status: 'Активен', agentsAccess: 7, agentsUsed: 6, lastActivity: '13.09.2026 16:40' }
  ],
  pagination: { pageSize: 5, total: 142 }
}

export const adminAiAgentsMock: AdminAiAgentsMock = {
  breadcrumb: 'ИИ-агенты — Создание, настройка, версии и мониторинг',
  title: 'ИИ-агенты',
  subtitle: 'Создание, настройка, версии и мониторинг всех ИИ-агентов',
  createLabel: 'Создать агента',
  importLabel: 'Импорт',
  filters: AI_AGENTS_FILTERS,
  rows: [
    { name: 'Агент_Совещания', process: 'Подготовка совещания', owner: 'Иванов И.И.', version: '1.3.2', status: 'Активен', statusTone: 'success', runs: 1245, successRate: '94%', used: true },
    { name: 'Агент_Корреспонденция', process: 'Обработка корреспонденции', owner: 'Кузнецова Е.Е.', version: '1.1.0', status: 'Активен', statusTone: 'success', runs: 892, successRate: '91%', used: true },
    { name: 'Агент_Аналитика', process: 'Анализ рынка', owner: 'Сидоров В.В.', version: '2.0.1', status: 'На настройке', statusTone: 'warning', runs: 456, successRate: '87%', used: false },
    { name: 'Агент_КП', process: 'Формирование КП', owner: 'Петров А.А.', version: '1.0.5', status: 'Активен', statusTone: 'success', runs: 678, successRate: '93%', used: true },
    { name: 'Агент_Финансы', process: 'Финансовый анализ', owner: 'Михайлов Д.Д.', version: '1.2.0', status: 'Активен', statusTone: 'success', runs: 534, successRate: '89%', used: true }
  ],
  pagination: { pageSize: 5, total: 37 },
  detail: {
    name: 'Агент_Совещания',
    status: 'Активен',
    statusTone: 'success',
    description: 'Автоматизирует подготовку материалов, формирование повестки и рассылку приглашений для совещаний.',
    tabs: ['Обзор', 'Текущие процессы', 'История запусков', 'Настройки', 'Версии'],
    activeTab: 'Обзор',
    info: [
      { label: 'Владелец', value: 'Иванов И.И.' },
      { label: 'Версия', value: '1.3.2' },
      { label: 'Статус', value: 'Активен' },
      { label: 'Используется', value: 'Да' },
      { label: 'Создан', value: '12.03.2024, 10:24' },
      { label: 'Обновлен', value: '18.04.2024, 14:12' }
    ],
    metrics: [
      { label: 'Всего запусков', value: '1 245' },
      { label: 'Успешных запусков', value: '1 170' },
      { label: 'Успешность', value: '94%' },
      { label: 'Среднее время выполнения', value: '2 мин 14 сек' },
      { label: 'Экономия времени', value: '~ 312 часов' },
      { label: 'Охват пользователей', value: '28' }
    ],
    processes: [
      { title: 'Подготовка материалов', time: 'Запущено 14.09.2026 10:15', status: 'Выполняется', statusTone: 'success', tone: 'green' },
      { title: 'Формирование повестки', time: 'Завершено 14.09.2026 09:40', status: 'Успешно', statusTone: 'success', tone: 'grey' },
      { title: 'Рассылка приглашений', time: 'Завершено 14.09.2026 09:55', status: 'Успешно', statusTone: 'success', tone: 'grey' }
    ]
  }
}

export const adminKnowledgeBaseMock: AdminKnowledgeBaseMock = {
  breadcrumb: 'База знаний — Управление источниками знаний',
  title: 'База знаний',
  subtitle: 'Документы, справочники и источники знаний для ИИ-агентов',
  addLabel: 'Добавить документ',
  filters: KNOWLEDGE_FILTERS,
  rows: [
    { name: 'Регламент по закупкам', type: 'Регламент', agents: 'Агент_Закупки', version: '2.1', status: 'Актуален', statusTone: 'success', updatedAt: '12.09.2026' },
    { name: 'Шаблоны КП', type: 'Шаблон', agents: 'Агент_КП', version: '1.3', status: 'Актуален', statusTone: 'success', updatedAt: '11.09.2026' },
    { name: 'Реестр поставщиков', type: 'Справочник', agents: 'Агент_Закупки', version: '1.0', status: 'Актуален', statusTone: 'success', updatedAt: '10.09.2026' },
    { name: 'Частые вопросы (FAQ)', type: 'FAQ', agents: 'Агент_Совещания', version: '1.2', status: 'Актуален', statusTone: 'success', updatedAt: '05.09.2026' },
    { name: 'Инструкции по 1С', type: 'Инструкция', agents: 'Агент_Аналитика', version: '1.1', status: 'Требует обновления', statusTone: 'error', updatedAt: '01.09.2026' }
  ],
  pagination: { pageSize: 5, total: 257 },
  document: {
    title: 'Регламент по закупкам',
    status: 'Актуален',
    statusTone: 'success',
    meta: 'Регламент • v2.1 • Обновлен 12.09.2026',
    text: 'Документ описывает порядок закупок компании: инициирование заявки, согласование, выбор поставщика, оформление договора и контроль исполнения.',
    format: 'PDF (1.4 MB)',
    author: 'Иванов И.И.',
    category: 'Закупки',
    tags: ['закупки', 'регламент', 'поставщики'],
    usageTotal: '428',
    usageTrend: '+12%',
    usageBars: [12, 18, 15, 22, 19, 24, 28, 26, 30, 27, 32, 35, 31, 29],
    agentsShare: [
      { label: 'Агент_Закупки', value: 65 },
      { label: 'Агент_Аналитика', value: 20 },
      { label: 'Агент_КП', value: 10 },
      { label: 'Агент_Совещания', value: 5 }
    ],
    related: [
      { title: 'Шаблоны КП', type: 'Шаблон' },
      { title: 'Реестр поставщиков', type: 'Справочник' },
      { title: 'Критерии оценки поставщиков', type: 'Регламент' },
      { title: 'Договор поставки (шаблон)', type: 'Шаблон' },
      { title: 'Частые вопросы (FAQ)', type: 'FAQ' }
    ],
    relatedCount: 12
  }
}

const HISTORY_TEMPLATES = adminHistoryMock.rows
const USERS_TEMPLATES = adminUsersMock.rows
const AGENTS_TEMPLATES = adminAiAgentsMock.rows
const KNOWLEDGE_TEMPLATES = adminKnowledgeBaseMock.rows

const EXTRA_USERS = [
  { fio: 'Орлова М.М.', position: 'Менеджер проектов', department: 'Аналитика', role: 'Пользователь', status: 'Активен', agentsAccess: 9, agentsUsed: 4, lastActivity: '12.09.2026 09:20' },
  { fio: 'Николаев С.С.', position: 'Специалист по закупкам', department: 'Закупки', role: 'Пользователь', status: 'Активен', agentsAccess: 4, agentsUsed: 3, lastActivity: '12.09.2026 08:55' },
  { fio: 'Волков П.П.', position: 'Бухгалтер', department: 'Финансы', role: 'Пользователь', status: 'Активен', agentsAccess: 3, agentsUsed: 2, lastActivity: '11.09.2026 17:10' },
  { fio: 'Лебедев А.А.', position: 'HR-менеджер', department: 'HR', role: 'Пользователь', status: 'Приглашен', agentsAccess: 2, agentsUsed: 0, lastActivity: '11.09.2026 15:30' },
  { fio: 'Смирнова К.К.', position: 'Юрист', department: 'Юридический', role: 'Аудитор', status: 'Активен', agentsAccess: 5, agentsUsed: 1, lastActivity: '10.09.2026 14:05' }
]

const EXTRA_AGENTS = [
  { name: 'Агент_Закупки', process: 'Отчет по закупкам', owner: 'Николаев С.С.', version: '1.4.0', status: 'Активен', statusTone: 'success' as AdminBadgeTone, runs: 412, successRate: '90%', used: true },
  { name: 'Агент_HR', process: 'Подбор кандидатов', owner: 'Лебедев А.А.', version: '0.9.2', status: 'На настройке', statusTone: 'warning' as AdminBadgeTone, runs: 98, successRate: '81%', used: false },
  { name: 'Агент_Отчетность', process: 'Сверка данных', owner: 'Волков П.П.', version: '1.1.3', status: 'Активен', statusTone: 'success' as AdminBadgeTone, runs: 267, successRate: '88%', used: true },
  { name: 'Агент_Юрист', process: 'Проверка договоров', owner: 'Смирнова К.К.', version: '1.0.1', status: 'Остановлен', statusTone: 'error' as AdminBadgeTone, runs: 54, successRate: '76%', used: false },
  { name: 'Агент_Кадры', process: 'Кадровый аудит', owner: 'Орлова М.М.', version: '2.2.0', status: 'Активен', statusTone: 'success' as AdminBadgeTone, runs: 189, successRate: '91%', used: true }
]

const EXTRA_KNOWLEDGE = [
  { name: 'Политика безопасности', type: 'Регламент', agents: 'Агент_HR', version: '1.0', status: 'Актуален', statusTone: 'success' as AdminBadgeTone, updatedAt: '09.09.2026' },
  { name: 'Матрица компетенций', type: 'Справочник', agents: 'Агент_Кадры', version: '3.2', status: 'Актуален', statusTone: 'success' as AdminBadgeTone, updatedAt: '08.09.2026' },
  { name: 'Шаблон договора поставки', type: 'Шаблон', agents: 'Агент_Юрист', version: '2.0', status: 'На проверке', statusTone: 'warning' as AdminBadgeTone, updatedAt: '07.09.2026' },
  { name: 'Глоссарий терминов', type: 'FAQ', agents: 'Агент_Аналитика', version: '1.4', status: 'Актуален', statusTone: 'success' as AdminBadgeTone, updatedAt: '06.09.2026' },
  { name: 'Инструкция по Outlook', type: 'Инструкция', agents: 'Агент_Корреспонденция', version: '1.2', status: 'Архив', statusTone: 'neutral' as AdminBadgeTone, updatedAt: '01.09.2026' }
]

function clonePageRows<T>(templates: T[], page: number, pageSize: number, mapper: (item: T, index: number, offset: number) => T): T[] {
  const offset = (page - 1) * pageSize
  return Array.from({ length: pageSize }, (_, index) => mapper(templates[(offset + index) % templates.length], index, offset))
}

const HISTORY_TAB_TEMPLATES: Record<string, AdminHistoryRowMock[]> = {
  processes: HISTORY_TEMPLATES,
  tasks: [
    { id: 'T-101', process: 'Согласовать бюджет', agent: 'Агент_Финансы', user: 'Михайлов Д.Д.', status: 'Завершен', statusTone: 'success', launchedAt: '14.09.2026 11:00', duration: '18 мин', sla: 'ok' },
    { id: 'T-102', process: 'Подготовить отчет', agent: 'Агент_Аналитика', user: 'Сидоров В.В.', status: 'В работе', statusTone: 'warning', launchedAt: '14.09.2026 10:20', duration: '22 мин', sla: 'warn' },
    { id: 'T-103', process: 'Проверить входящие', agent: 'Агент_Корреспонденция', user: 'Кузнецова Е.Е.', status: 'Завершен', statusTone: 'success', launchedAt: '13.09.2026 16:40', duration: '9 мин', sla: 'ok' },
    { id: 'T-104', process: 'Обновить KPI', agent: 'Агент_Аналитика', user: 'Орлова М.М.', status: 'Ошибка', statusTone: 'error', launchedAt: '13.09.2026 14:05', duration: '4 мин', sla: 'fail' },
    { id: 'T-105', process: 'Сформировать повестку', agent: 'Агент_Совещания', user: 'Петров А.А.', status: 'Завершен', statusTone: 'success', launchedAt: '12.09.2026 09:30', duration: '11 мин', sla: 'ok' }
  ],
  letters: [
    { id: 'L-201', process: 'Ответ клиенту', agent: 'Агент_Корреспонденция', user: 'Кузнецова Е.Е.', status: 'Завершен', statusTone: 'success', launchedAt: '14.09.2026 08:50', duration: '6 мин', sla: 'ok' },
    { id: 'L-202', process: 'Рассылка уведомлений', agent: 'Агент_Совещания', user: 'Петров А.А.', status: 'Завершен', statusTone: 'success', launchedAt: '13.09.2026 17:10', duration: '7 мин', sla: 'ok' },
    { id: 'L-203', process: 'Обработка претензии', agent: 'Агент_Корреспонденция', user: 'Смирнова К.К.', status: 'В работе', statusTone: 'warning', launchedAt: '13.09.2026 12:15', duration: '15 мин', sla: 'warn' },
    { id: 'L-204', process: 'Архивация переписки', agent: 'Агент_Корреспонденция', user: 'Иванов И.И.', status: 'Завершен', statusTone: 'success', launchedAt: '12.09.2026 15:00', duration: '5 мин', sla: 'ok' },
    { id: 'L-205', process: 'Подготовка шаблона', agent: 'Агент_КП', user: 'Петров А.А.', status: 'Завершен', statusTone: 'success', launchedAt: '11.09.2026 10:45', duration: '8 мин', sla: 'ok' }
  ],
  project_tasks: [
    { id: 'PT-301', process: 'Этап: анализ требований', agent: 'Агент_Аналитика', user: 'Орлова М.М.', status: 'Завершен', statusTone: 'success', launchedAt: '14.09.2026 09:10', duration: '26 мин', sla: 'ok' },
    { id: 'PT-302', process: 'Этап: согласование', agent: 'Агент_Совещания', user: 'Петров А.А.', status: 'В работе', statusTone: 'warning', launchedAt: '13.09.2026 13:20', duration: '19 мин', sla: 'warn' },
    { id: 'PT-303', process: 'Этап: закупки', agent: 'Агент_Закупки', user: 'Николаев С.С.', status: 'Завершен', statusTone: 'success', launchedAt: '12.09.2026 11:40', duration: '21 мин', sla: 'ok' },
    { id: 'PT-304', process: 'Этап: финансы', agent: 'Агент_Финансы', user: 'Михайлов Д.Д.', status: 'Ошибка', statusTone: 'error', launchedAt: '11.09.2026 16:05', duration: '7 мин', sla: 'fail' },
    { id: 'PT-305', process: 'Этап: документооборот', agent: 'Агент_Корреспонденция', user: 'Кузнецова Е.Е.', status: 'Завершен', statusTone: 'success', launchedAt: '10.09.2026 14:30', duration: '13 мин', sla: 'ok' }
  ]
}

export const HISTORY_TAB_TOTALS: Record<string, number> = {
  processes: 248,
  tasks: 186,
  letters: 92,
  project_tasks: 64
}

export function getHistoryPageRows(
  tabId: string,
  page: number,
  pageSize = adminHistoryMock.pagination.pageSize
): AdminHistoryRowMock[] {
  const templates = HISTORY_TAB_TEMPLATES[tabId] || HISTORY_TEMPLATES
  const prefix = tabId === 'tasks' ? 'T' : tabId === 'letters' ? 'L' : tabId === 'project_tasks' ? 'PT' : 'P'
  return clonePageRows(templates, page, pageSize, (item, index, offset) => ({
    ...item,
    id: `${prefix}-${100 + offset + index}`,
    duration: `${6 + ((offset + index) % 27)} мин`,
    launchedAt: `${String(14 - ((offset + index) % 5)).padStart(2, '0')}.09.2026 ${String(8 + ((offset + index) % 10)).padStart(2, '0')}:${String((index * 7) % 60).padStart(2, '0')}`
  }))
}

export function getUsersPageRows(page: number, pageSize = adminUsersMock.pagination.pageSize): AdminUserRowMock[] {
  const pool = [...USERS_TEMPLATES, ...EXTRA_USERS]
  return clonePageRows(pool, page, pageSize, (item, index, offset) => ({
    ...item,
    lastActivity: `${String(14 - ((offset + index) % 6)).padStart(2, '0')}.09.2026 ${String(8 + ((offset + index) % 11)).padStart(2, '0')}:${String((index * 5) % 60).padStart(2, '0')}`
  }))
}

export function getAiAgentsPageRows(page: number, pageSize = adminAiAgentsMock.pagination.pageSize): AdminAgentRowMock[] {
  const pool = [...AGENTS_TEMPLATES, ...EXTRA_AGENTS]
  return clonePageRows(pool, page, pageSize, (item, index, offset) => ({
    ...item,
    runs: item.runs + offset * 3 + index,
    successRate: `${Math.max(75, 94 - ((offset + index) % 8))}%`
  }))
}

export function getKnowledgePageRows(page: number, pageSize = adminKnowledgeBaseMock.pagination.pageSize): AdminKnowledgeRowMock[] {
  const pool = [...KNOWLEDGE_TEMPLATES, ...EXTRA_KNOWLEDGE]
  return clonePageRows(pool, page, pageSize, (item, index, offset) => ({
    ...item,
    version: `${Number(item.version.split('.')[0])}.${(offset + index) % 9}`,
    updatedAt: `${String(14 - ((offset + index) % 10)).padStart(2, '0')}.09.2026`
  }))
}

function getAllPagedRows<T>(
  total: number,
  pageSize: number,
  loader: (page: number, size: number) => T[]
): T[] {
  const pageCount = Math.ceil(total / pageSize)
  return Array.from({ length: pageCount }, (_, index) => loader(index + 1, pageSize)).flat()
}

export function getAllHistoryRows(tabId: string): AdminHistoryRowMock[] {
  const total = HISTORY_TAB_TOTALS[tabId] || adminHistoryMock.pagination.total
  const pageSize = adminHistoryMock.pagination.pageSize
  return getAllPagedRows(total, pageSize, (page, size) => getHistoryPageRows(tabId, page, size))
}

export function getAllUsersRows(): AdminUserRowMock[] {
  const { total, pageSize } = adminUsersMock.pagination
  return getAllPagedRows(total, pageSize, getUsersPageRows)
}

export function getAllAiAgentsRows(): AdminAgentRowMock[] {
  const { total, pageSize } = adminAiAgentsMock.pagination
  return getAllPagedRows(total, pageSize, getAiAgentsPageRows)
}

export function getAllKnowledgeRows(): AdminKnowledgeRowMock[] {
  const { total, pageSize } = adminKnowledgeBaseMock.pagination
  return getAllPagedRows(total, pageSize, getKnowledgePageRows)
}

const KNOWLEDGE_DOC_TEXT: Record<string, string> = {
  'Регламент по закупкам':
    'Документ описывает порядок закупок компании: инициирование заявки, согласование, выбор поставщика, оформление договора и контроль исполнения.',
  'Шаблоны КП':
    'Набор шаблонов коммерческих предложений для быстрой подготовки КП по типовым сценариям продаж и закупок.',
  'Реестр поставщиков':
    'Справочник проверенных поставщиков с рейтингами, контактами, условиями поставки и историей сотрудничества.',
  'Частые вопросы (FAQ)':
    'Свод ответов на типовые вопросы сотрудников по процессам, регламентам и работе с ИИ-агентами.',
  'Инструкции по 1С':
    'Пошаговые инструкции по работе в 1С для ключевых операций: закупки, финансы, отчётность и документооборот.',
  'Политика безопасности':
    'Правила информационной безопасности, доступа к данным и работы с конфиденциальной информацией.',
  'Матрица компетенций':
    'Справочник компетенций сотрудников и требований к ролям для HR и кадровых процессов.',
  'Шаблон договора поставки':
    'Типовой шаблон договора поставки с обязательными условиями и блоками для юридической проверки.',
  'Глоссарий терминов':
    'Словарь терминов компании и предметной области для единообразной работы агентов и сотрудников.',
  'Инструкция по Outlook':
    'Руководство по работе с почтой и календарём Outlook: правила, шаблоны и типовые сценарии переписки.'
}

const KNOWLEDGE_AUTHORS = ['Иванов И.И.', 'Петрова А.С.', 'Сидоров В.В.', 'Кузнецова Е.Е.', 'Михайлов Д.Д.']
const KNOWLEDGE_FORMATS = ['PDF (1.4 MB)', 'DOCX (820 KB)', 'PDF (980 KB)', 'XLSX (640 KB)', 'MD (120 KB)']

function knowledgeSeed(name: string): number {
  return name.split('').reduce((sum, char, index) => sum + char.charCodeAt(0) * (index + 1), 0)
}

function buildUsageBars(seed: number): number[] {
  return Array.from({ length: 14 }, (_, index) => 10 + ((seed + index * 17) % 26))
}

function buildAgentsShare(row: AdminKnowledgeRowMock, seed: number): Array<{ label: string; value: number }> {
  const primary = row.agents.split(',')[0].trim()
  const primaryShare = 45 + (seed % 25)
  const remaining = 100 - primaryShare
  const secondary = Math.round(remaining * 0.55)
  const tertiary = Math.round(remaining * 0.3)
  const rest = 100 - primaryShare - secondary - tertiary
  return [
    { label: primary, value: primaryShare },
    { label: 'Агент_Аналитика', value: secondary },
    { label: 'Агент_КП', value: tertiary },
    { label: 'Агент_Совещания', value: rest }
  ]
}

export function getKnowledgeDocumentDetail(
  row: AdminKnowledgeRowMock,
  pool: AdminKnowledgeRowMock[] = [...KNOWLEDGE_TEMPLATES, ...EXTRA_KNOWLEDGE]
): AdminKnowledgeDocumentDetail {
  const seed = knowledgeSeed(row.name)
  const relatedPool = pool.filter((item) => item.name !== row.name)
  const relatedStart = relatedPool.length ? seed % relatedPool.length : 0
  const related = Array.from({ length: Math.min(5, relatedPool.length) }, (_, index) => relatedPool[(relatedStart + index) % relatedPool.length])
  const usageTotal = 180 + (seed % 420)
  const trend = (seed % 2 === 0 ? '+' : '-') + `${8 + (seed % 15)}%`
  const category = row.type === 'FAQ' ? 'Справочная информация' : row.type
  const tags = [
    row.type.toLowerCase(),
    row.agents.replace('Агент_', '').toLowerCase(),
    row.status === 'Требует обновления' ? 'обновление' : 'актуальный'
  ]

  return {
    title: row.name,
    status: row.status,
    statusTone: row.statusTone,
    meta: `${row.type} • v${row.version} • Обновлен ${row.updatedAt}`,
    text:
      KNOWLEDGE_DOC_TEXT[row.name] ||
      `Документ «${row.name}» используется агентами ${row.agents} для типовых сценариев категории «${row.type}».`,
    format: KNOWLEDGE_FORMATS[seed % KNOWLEDGE_FORMATS.length],
    author: KNOWLEDGE_AUTHORS[seed % KNOWLEDGE_AUTHORS.length],
    category,
    tags,
    usageTotal: String(usageTotal),
    usageTrend: trend,
    usageBars: buildUsageBars(seed),
    agentsShare: buildAgentsShare(row, seed),
    related: related.map((item) => ({ title: item.name, type: item.type })),
    relatedCount: 8 + (seed % 9)
  }
}
