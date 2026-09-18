import type {
  AssignmentRegistryLine,
  AssignmentRegistryRow,
  AssignmentRegistryRowTone
} from './assignmentRegistryTypes'
function isBusinessDay(date: Date): boolean {
  const day = date.getDay()
  return day >= 1 && day <= 5
}

function endOfBusinessDaysWindow(today: Date, businessDays: number): Date {
  let cursor = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  let left = businessDays
  while (left > 0) {
    if (isBusinessDay(cursor)) left -= 1
    if (left > 0) cursor.setDate(cursor.getDate() + 1)
  }
  return cursor
}

function formatOneCDate(raw: string): string {
  const text = (raw || '').trim()
  if (!text || text.startsWith('0001-01-01')) return '—'
  const iso = text.slice(0, 10)
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [y, m, d] = iso.split('-')
    return `${d}.${m}.${y}`
  }
  return text
}

function mapLine(raw: Record<string, unknown>): AssignmentRegistryLine {
  return {
    line: Number(raw.line) || 0,
    text: String(raw.text || '').trim() || '—',
    due: formatOneCDate(String(raw.due || '')),
    executor: String(raw.executor || '').trim() || '—',
    priority: String(raw.priority || '').trim() || '—'
  }
}

export function parseRegistryDay(value: string): Date | null {
  const text = (value || '').trim()
  if (!text || text === '—') return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    const [y, m, d] = text.split('-').map(Number)
    return new Date(y, m - 1, d)
  }
  const dot = text.match(/^(\d{2})\.(\d{2})\.(\d{4})$/)
  if (dot) return new Date(Number(dot[3]), Number(dot[2]) - 1, Number(dot[1]))
  return null
}

export function isDueWithinDays(row: AssignmentRegistryRow, days: number, today = new Date()): boolean {
  if (!row.open || row.overdue) return false
  const due = parseRegistryDay(row.fullRemediationDue)
  if (!due) return false
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const end = endOfBusinessDaysWindow(today, days)
  return due >= start && due <= end
}

export function resolveRegistryRowTone(
  row: Pick<AssignmentRegistryRow, 'open' | 'overdue' | 'fullRemediationDue'>,
  today = new Date()
): AssignmentRegistryRowTone {
  if (!row.open) return 'done'
  if (row.overdue) return 'overdue'
  const due = parseRegistryDay(row.fullRemediationDue)
  if (due) {
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
    const end = endOfBusinessDaysWindow(today, 3)
    if (due >= start && due <= end) return 'due_soon'
  }
  return 'neutral'
}

export function mapAssignmentFromApi(row: Record<string, unknown>): AssignmentRegistryRow {
  const number = String(row.number || '').trim()
  const ref = String(row.ref_key || '').trim()
  const status = String(row.status || '').trim() || '—'
  const open = row.open !== false && !/принято|закрыто|исполнено|отменено/i.test(status)
  const overdue = Boolean(row.overdue)
  const linesRaw = Array.isArray(row.lines) ? row.lines : []
  const lines = linesRaw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(mapLine)
    .sort((a, b) => a.line - b.line)

  const base = {
    date: formatOneCDate(String(row.date || '')),
    number: number || '—',
    topic: String(row.topic || '').trim() || '—',
    basis: String(row.basis || '').trim() || '—',
    weeklyReportDate: formatOneCDate(String(row.weekly_report_date || '')),
    fullRemediationDue: formatOneCDate(String(row.due || '')),
    reporter: String(row.reporter || '').trim() || '—',
    secretary: String(row.secretary || '').trim() || '—',
    finalReportDate: formatOneCDate(String(row.final_report_date || '')),
    status,
    organization: String(row.organization || '').trim() || '—',
    manager: String(row.customer || '').trim() || '—',
    open,
    overdue
  }

  const dueSoon = open && !overdue && resolveRegistryRowTone({ ...base, open, overdue }) === 'due_soon'
  const tone = resolveRegistryRowTone({ ...base, open, overdue })

  return {
    id: ref || number || `row-${Math.random().toString(36).slice(2, 9)}`,
    refKey: ref,
    ...base,
    dueSoon,
    tone,
    lines
  }
}

export function rowDateSortKey(row: AssignmentRegistryRow, field: keyof AssignmentRegistryRow): number {
  const parsed = parseRegistryDay(String(row[field] || ''))
  return parsed ? parsed.getTime() : 0
}
