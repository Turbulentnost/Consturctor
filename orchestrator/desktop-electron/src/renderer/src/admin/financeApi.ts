import { api } from '../api/client'

export type FinanceImportKind = 'salary' | 'material_incentive'
export type FinanceRow = Record<string, string | number | boolean | null>

export interface FinanceEmployee {
  id: string
  fio: string
  position: string
}

export interface FinancePosition {
  id: string
  name: string
}

export interface FinanceKpiItem {
  id: string
  name: string
  value: string
  period: string
  status: string
}

export interface FinanceSalary {
  id: string
  period: string
  amount: string
  currency: string
  reason: string
}

export interface FinanceImport {
  id: string
  kind: FinanceImportKind
  fileName: string
  status: string
  createdAt: string
  author: string
  rowsCount: number
  rows: FinanceRow[]
  errors: string[]
  draft: Record<string, unknown>
  effectiveFrom: string
}

export function financeStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: 'Загружен',
    parsing: 'Обрабатывается',
    review: 'Ожидает подтверждения',
    confirmed: 'Записан в БД',
    error: 'Ошибка'
  }
  return labels[status] || status || '—'
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function records(value: unknown, ...keys: string[]): Record<string, unknown>[] {
  if (Array.isArray(value)) return value.map(record)
  const source = record(value)
  for (const key of keys) {
    if (Array.isArray(source[key])) return (source[key] as unknown[]).map(record)
  }
  return []
}

function text(source: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = source[key]
    if (value !== undefined && value !== null) return String(value)
  }
  return ''
}

function primitiveRow(value: Record<string, unknown>): FinanceRow {
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      item === null || typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
        ? item
        : JSON.stringify(item)
    ])
  )
}

export async function fetchFinanceEmployees(): Promise<FinanceEmployee[]> {
  return records(await api.adminFinanceEmployees(), 'items', 'employees', 'rows').map((item) => ({
    id: text(item, 'id', 'employee_id', 'employeeId'),
    fio: text(item, 'fio', 'full_name', 'fullName', 'name'),
    position: text(item, 'position', 'job_title', 'jobTitle')
  }))
}

export async function fetchFinancePositions(): Promise<FinancePosition[]> {
  return records(await api.adminFinancePositions(), 'items', 'positions', 'rows').map((item) => ({
    id: text(item, 'id', 'position_id', 'positionId'),
    name: text(item, 'name', 'position_name', 'positionName', 'position')
  }))
}

export async function fetchFinanceEmployeeKpi(employeeId: string): Promise<FinanceKpiItem[]> {
  const raw = await api.adminFinanceEmployeeKpi(employeeId)
  const source = record(raw)
  const items = records(raw, 'items', 'kpi', 'metrics', 'rows', 'tiles')
  if (!items.length && Object.keys(source).length) {
    return Object.entries(source)
      .filter(([, value]) => value === null || ['string', 'number', 'boolean'].includes(typeof value))
      .map(([key, value]) => ({ id: key, name: key, value: String(value ?? ''), period: '', status: '' }))
  }
  return items.map((item, index) => ({
    id: text(item, 'id', 'metric_id') || String(index),
    name: text(item, 'name', 'title', 'label', 'metric'),
    value: text(item, 'value', 'result', 'score', 'contrib', 'fact'),
    period: text(item, 'period', 'date', 'month') ||
      [text(source, 'period_from'), text(source, 'period_to')].filter(Boolean).join(' — '),
    status: text(item, 'status', 'evidence')
  }))
}

export async function fetchFinanceEmployeeSalaries(employeeId: string): Promise<FinanceSalary[]> {
  return records(await api.adminFinanceEmployeeSalaries(employeeId), 'items', 'salaries', 'history', 'rows').map(
    (item, index) => ({
      id: text(item, 'id') || String(index),
      period: text(item, 'period', 'effective_from', 'effectiveFrom', 'date'),
      amount: text(item, 'amount', 'salary', 'value'),
      currency: text(item, 'currency') || '₽',
      reason: text(item, 'reason', 'comment', 'note')
    })
  )
}

export function parseFinanceImport(value: unknown): FinanceImport {
  const source = record(value)
  const nested = record(source.import)
  const item = Object.keys(nested).length ? nested : source
  const kind = text(item, 'kind', 'import_kind', 'importKind')
  const draft = record(item.draft)
  const rawRows = records(
    item.rows ??
      item.extracted_rows ??
      item.extractedRows ??
      (kind === 'material_incentive' ? draft.profiles : draft.rows),
    'items',
    'rows',
    'profiles'
  )
  const validation = record(item.validation)
  const rawErrors = Array.isArray(item.errors) ? item.errors : validation.errors
  return {
    id: text(item, 'id', 'import_id', 'importId'),
    kind: kind === 'material_incentive' ? 'material_incentive' : 'salary',
    fileName: text(item, 'file_name', 'fileName', 'filename', 'original_name', 'originalName'),
    status: text(item, 'status'),
    createdAt: text(item, 'created_at', 'createdAt', 'uploaded_at', 'uploadedAt'),
    author: text(item, 'author', 'created_by_fio', 'createdByFio', 'created_by', 'createdBy', 'user'),
    rowsCount: Number(item.rows_total ?? item.rows_count ?? item.rowsCount ?? rawRows.length),
    rows: rawRows.map(primitiveRow),
    errors: Array.isArray(rawErrors)
      ? rawErrors.map((error) => {
          const detail = record(error)
          const row = detail.row === undefined ? '' : `Строка ${Number(detail.row) + 1}: `
          return row + (text(detail, 'message', 'detail') || String(error))
        })
      : [],
    draft,
    effectiveFrom: text(draft, 'effective_from', 'effectiveFrom')
  }
}

export async function uploadFinanceImport(kind: FinanceImportKind, filePath: string): Promise<FinanceImport> {
  return parseFinanceImport(await api.uploadAdminFinanceImport(kind, filePath))
}

export async function fetchFinanceImports(): Promise<FinanceImport[]> {
  return records(await api.adminFinanceImports(), 'items', 'imports', 'rows').map(parseFinanceImport)
}

export async function fetchFinanceImport(importId: string): Promise<FinanceImport> {
  return parseFinanceImport(await api.adminFinanceImport(importId))
}

function restoreStructuredRow(row: FinanceRow): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(row).map(([key, value]) => {
      if (typeof value !== 'string' || !['metrics', 'sources', 'formula_json'].includes(key)) {
        return [key, value]
      }
      try {
        return [key, JSON.parse(value)]
      } catch {
        return [key, value]
      }
    })
  )
}

export async function saveFinanceImportRows(
  item: FinanceImport,
  rows: FinanceRow[],
  effectiveFrom = item.effectiveFrom
): Promise<FinanceImport> {
  const draft =
    item.kind === 'material_incentive'
      ? { ...item.draft, effective_from: effectiveFrom, profiles: rows.map(restoreStructuredRow) }
      : { ...item.draft, rows: rows.map(restoreStructuredRow) }
  return parseFinanceImport(await api.patchAdminFinanceImport(item.id, draft))
}

export async function confirmFinanceImport(importId: string): Promise<FinanceImport> {
  return parseFinanceImport(await api.confirmAdminFinanceImport(importId))
}

export async function downloadFinanceImport(item: FinanceImport): Promise<void> {
  const result = await api.downloadAdminFinanceImport(item.id, item.fileName || `finance-import-${item.id}.xlsx`)
  if (!result.ok && !result.canceled) throw new Error(result.error || 'Не удалось скачать файл')
}

export async function openFinanceImport(item: FinanceImport): Promise<void> {
  const result = await window.api.download({
    url: `/api/v1/admin/finance/imports/${encodeURIComponent(item.id)}/file`,
    defaultName: item.fileName || `finance-import-${item.id}`,
    token: api.getToken(),
    temporary: true,
    openAfter: true
  })
  if (!result.ok) throw new Error(result.error || 'Не удалось открыть файл')
}
