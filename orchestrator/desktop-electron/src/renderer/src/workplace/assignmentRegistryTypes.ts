export type AssignmentRegistryLine = {
  line: number
  text: string
  due: string
  executor: string
  priority: string
}

export type AssignmentRegistryRowTone = 'done' | 'overdue' | 'due_soon' | 'neutral'

export type AssignmentRegistryRow = {
  id: string
  refKey: string
  date: string
  number: string
  topic: string
  basis: string
  weeklyReportDate: string
  fullRemediationDue: string
  reporter: string
  secretary: string
  finalReportDate: string
  status: string
  organization: string
  manager: string
  open: boolean
  overdue: boolean
  dueSoon: boolean
  tone: AssignmentRegistryRowTone
  lines: AssignmentRegistryLine[]
}

export type AssignmentRegistryTileId = 'done' | 'overdue' | 'due_soon' | 'report' | 'ai'

export type AssignmentRegistryColumnId =
  | 'date'
  | 'number'
  | 'topic'
  | 'basis'
  | 'weeklyReportDate'
  | 'fullRemediationDue'
  | 'reporter'
  | 'secretary'
  | 'finalReportDate'
  | 'status'
  | 'organization'
  | 'manager'

export const ASSIGNMENT_REGISTRY_COLUMNS: {
  id: AssignmentRegistryColumnId
  label: string
  compact?: boolean
}[] = [
  { id: 'date', label: 'Дата', compact: true },
  { id: 'number', label: 'Номер', compact: true },
  { id: 'topic', label: 'О чём' },
  { id: 'basis', label: 'Основание' },
  { id: 'weeklyReportDate', label: 'Дата еженедельного', compact: true },
  { id: 'fullRemediationDue', label: 'Срок полного устранения нарушений', compact: true },
  { id: 'reporter', label: 'Кто доложит' },
  { id: 'secretary', label: 'Секретарь' },
  { id: 'finalReportDate', label: 'Дата итогового доклада', compact: true },
  { id: 'status', label: 'Статус', compact: true },
  { id: 'organization', label: 'Организация' },
  { id: 'manager', label: 'Руководитель' }
]
