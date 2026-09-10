function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0
}

function countNamedArrays(row: Record<string, unknown>, keys: string[]): number {
  for (const key of keys) {
    const n = arrayLength(row[key])
    if (n > 0) return n
  }
  return 0
}

export function countOdataRows(result: unknown): number {
  const row = asRecord(result)
  if (!row) return 0
  const nested = asRecord(row.data) || asRecord(row.result) || row
  const fromValue = arrayLength(nested.value)
  if (fromValue > 0) return fromValue
  const fromRows = countNamedArrays(nested, ['rows', 'items', 'records', 'documents'])
  if (fromRows > 0) return fromRows
  if (nested.Ref_Key || nested.Description || nested.Number) return 1
  return 0
}

export function countCalendarEvents(result: unknown): number {
  const row = asRecord(result)
  if (!row) return 0
  const n = countNamedArrays(row, ['events', 'meetings', 'items'])
  if (n > 0) return n
  const nested = asRecord(row.data) || asRecord(row.result)
  if (!nested) return 0
  return countNamedArrays(nested, ['events', 'meetings', 'items'])
}

const GENERIC_SUMMARY = /^(odata get ok|ok|success|done|данные получены\.?)$/i

/** Compact one-line status for a finished tool. Prefer counts over raw "ok". */
export function summarizeToolResult(result: Record<string, unknown> | null): string {
  if (!result || typeof result !== 'object') return 'Данные получены.'
  if (typeof result.result_file === 'string' && result.result_file.trim()) {
    return `Файл: ${result.result_file}`
  }
  if (result.skipped) return 'Пропущено пользователем'
  if (result.rejected) return 'Отклонено пользователем'

  const events = countCalendarEvents(result)
  if (events === 1) return '1 встреча — раскройте состав'
  if (events > 1) return `${events} встреч — раскройте состав`

  const rows = countOdataRows(result)
  if (rows === 1) return '1 запись 1С'
  if (rows > 1) return `${rows} записей 1С`

  const summary = result.summary
  if (typeof summary === 'string' && summary.trim() && !GENERIC_SUMMARY.test(summary.trim())) {
    return summary.trim()
  }
  for (const key of ['items', 'rows', 'results', 'messages', 'events', 'files', 'records', 'documents', 'tasks']) {
    const value = result[key]
    if (Array.isArray(value) && value.length) return `Получено записей: ${value.length}`
  }
  if (typeof result.text === 'string' && result.text.trim()) return result.text.trim().slice(0, 200)
  if (typeof result.value === 'string' && result.value.trim()) return result.value.trim().slice(0, 200)
  return 'Данные получены.'
}
