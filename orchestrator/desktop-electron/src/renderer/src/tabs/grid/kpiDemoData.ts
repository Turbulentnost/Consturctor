import type { SpecPillTone } from '../../workplace/specV04DemoData'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'

export type KpiAgentStatus = 'ok' | 'warn' | 'risk'

export interface KpiAgentRowMock {
  id: string
  agent: string
  process: string
  completion: number
  sla: number
  load: number
  automation: number
  status: KpiAgentStatus
}

export interface KpiProblemZoneMock {
  id: string
  zone: string
  indicator: string
  value: string
  recommendation: string
}

export interface KpiLoadCompareMock {
  id: string
  label: string
  employeeHours: number
  aiHours: number
}

export const KPI_SUMMARY_TILES: SpecSummaryTile[] = [
  {
    id: 'day',
    label: 'Выполнение задач',
    value: '78%',
    hint: '(+12%)',
    tone: 'orange',
    progress: 78,
    ring: true
  },
  {
    id: 'onec',
    label: 'SLA',
    value: '92%',
    tone: 'blue',
    progress: 92,
    ring: true
  },
  {
    id: 'reg',
    label: 'Загрузка',
    value: '76%',
    tone: 'purple',
    progress: 76,
    ring: true
  },
  {
    id: 'proj',
    label: 'Эффективность ИИ',
    value: '94%',
    tone: 'green',
    progress: 94,
    ring: true
  },
  {
    id: 'mail',
    label: 'Доля автоматизации',
    value: '62%',
    tone: 'yellow',
    progress: 62,
    ring: true
  },
  {
    id: 'meet',
    label: 'Качество',
    value: '4.7 из 5',
    tone: 'lilac'
  }
]

export const KPI_AGENT_ROWS: KpiAgentRowMock[] = [
  {
    id: 'a1',
    agent: 'Ежедневный контроль поручений по 1C ERP и Excel',
    process: 'Регламентные работы',
    completion: 91,
    sla: 96,
    load: 72,
    automation: 65,
    status: 'ok'
  },
  {
    id: 'a2',
    agent: 'Обработка регламентных отчётов и сопоставление с данными',
    process: 'Закупки',
    completion: 88,
    sla: 94,
    load: 68,
    automation: 58,
    status: 'ok'
  },
  {
    id: 'a3',
    agent: 'Ежедневная обработка входящей корреспонденции',
    process: 'Входящие письма',
    completion: 84,
    sla: 89,
    load: 81,
    automation: 52,
    status: 'warn'
  },
  {
    id: 'a4',
    agent: 'Анализ базы данных и формирование сводного отчёта',
    process: 'База знаний',
    completion: 76,
    sla: 82,
    load: 88,
    automation: 48,
    status: 'risk'
  },
  {
    id: 'a5',
    agent: 'Планирование совещания председателя',
    process: 'Совещания',
    completion: 93,
    sla: 97,
    load: 64,
    automation: 41,
    status: 'ok'
  },
  {
    id: 'a6',
    agent: 'Методика расчёта Коэффициента влияния на ценообразование',
    process: 'Закупки',
    completion: 79,
    sla: 86,
    load: 74,
    automation: 55,
    status: 'warn'
  },
  {
    id: 'a7',
    agent: 'Формирование Техзаданий',
    process: 'Задачи',
    completion: 90,
    sla: 95,
    load: 70,
    automation: 60,
    status: 'ok'
  }
]

export const KPI_PROBLEM_ZONES: KpiProblemZoneMock[] = [
  {
    id: 'p1',
    zone: 'Согласование договоров',
    indicator: 'SLA',
    value: '88%',
    recommendation: 'Ускорить согласование с юридическим отделом'
  },
  {
    id: 'p2',
    zone: 'Обработка писем',
    indicator: 'SLA',
    value: '91%',
    recommendation: 'Перераспределить нагрузку между агентами'
  },
  {
    id: 'p3',
    zone: 'Планирование совещаний',
    indicator: 'Загрузка',
    value: '95%',
    recommendation: 'Зафиксировать окна подготовки в календаре'
  }
]

export const KPI_LOAD_COMPARE: KpiLoadCompareMock[] = [
  { id: 'l1', label: 'Регламенты', employeeHours: 12, aiHours: 28 },
  { id: 'l2', label: 'Письма', employeeHours: 18, aiHours: 22 },
  { id: 'l3', label: 'Планирование', employeeHours: 8, aiHours: 14 },
  { id: 'l4', label: 'Закупки', employeeHours: 10, aiHours: 16 },
  { id: 'l5', label: 'Отчётность', employeeHours: 14, aiHours: 26 },
  { id: 'l6', label: 'Решения', employeeHours: 6, aiHours: 9 }
]

/** Точки для графика «Динамика показателей» (0–100). */
export const KPI_DYNAMICS_SERIES = {
  completion: [62, 65, 68, 71, 74, 76, 78],
  sla: [86, 87, 88, 90, 91, 92, 92]
}

export function kpiStatusLabel(status: KpiAgentStatus): string {
  if (status === 'ok') return 'В норме'
  if (status === 'warn') return 'Внимание'
  return 'Риск'
}

export function kpiStatusTone(status: KpiAgentStatus): SpecPillTone {
  if (status === 'ok') return 'green'
  if (status === 'warn') return 'orange'
  return 'red'
}

export function kpiMetricTone(value: number): 'green' | 'blue' | 'orange' | 'red' {
  if (value >= 90) return 'green'
  if (value >= 80) return 'blue'
  if (value >= 70) return 'orange'
  return 'red'
}
