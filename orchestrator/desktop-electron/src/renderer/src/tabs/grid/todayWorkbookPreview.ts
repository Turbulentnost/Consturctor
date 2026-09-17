export type WorkbookKpi = {
  label: string
  value: string
}

export type WorkbookSheet = {
  name: string
  title: string
  subtitle: string
  kpis: WorkbookKpi[]
  notes: string[]
  headers: string[]
  rows: string[][]
}

export type WorkbookPreview = {
  kind: 'workbook'
  sheets: WorkbookSheet[]
  fallbackText?: string
}

export function isUsefulWorkbook(preview: WorkbookPreview | null | undefined): boolean {
  if (!preview?.sheets?.length) return false
  return preview.sheets.some(
    (sheet) =>
      (Array.isArray(sheet?.kpis) && sheet.kpis.length > 0) ||
      (Array.isArray(sheet?.headers) &&
        sheet.headers.length >= 2 &&
        Array.isArray(sheet?.rows) &&
        sheet.rows.length >= 1)
  )
}

const SHEET_RE = /^={3,}\s*SHEET:\s*(.+?)\s*={3,}\s*$/i
const HEADER_HINT =
  /^(id|код|источник|дата|поручен|заказчик|владелец|срок|приоритет|статус|комментар|риск|ссылка|исполнитель|тема|название|результат|артефакт|документ|ответств|описание|номер)/i
const KPI_HINT = /карточек|строк|срок|всего|открыт|просроч|сегодня|закрыт|выполн|итог|kpi/i
const NUMERIC_RE = /^[+-]?(?:\d{1,3}(?:[\s\u00a0]\d{3})*|\d+)(?:[.,]\d+)?%?$/

function cleanCell(value: string): string {
  return value.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim()
}

function filledCells(cells: string[]): string[] {
  return cells.map(cleanCell).filter(Boolean)
}

function trimRow(cells: string[]): string[] {
  const next = cells.map(cleanCell)
  while (next.length && !next[next.length - 1]) next.pop()
  return next
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"'
        i += 1
        continue
      }
      quoted = !quoted
      continue
    }
    if (ch === ',' && !quoted) {
      cells.push(current)
      current = ''
      continue
    }
    current += ch
  }
  cells.push(current)
  return trimRow(cells)
}

function splitCells(line: string, delimiter: string): string[] {
  if (delimiter === ',') return splitCsvLine(line)
  if (delimiter === '|') {
    return trimRow(
      line
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
    )
  }
  if (delimiter === '  ') return trimRow(line.split(/\s{2,}/))
  return trimRow(line.split(delimiter))
}

function detectDelimiter(lines: string[], preferCsv: boolean): string | null {
  const sample = lines.filter((line) => line.trim()).slice(0, 30)
  if (!sample.length) return null
  const score = (test: (line: string) => boolean): number => sample.filter(test).length
  if (score((line) => line.includes('\t')) >= 1) return '\t'
  if (score((line) => (line.match(/\|/g) || []).length >= 2) >= 2) return '|'
  if (score((line) => line.includes(';')) >= 2) return ';'
  if (preferCsv && score((line) => line.includes(',')) >= 2) return ','
  if (score((line) => /\s{2,}/.test(line)) >= 2) return '  '
  return null
}

function looksLikeHeader(cells: string[]): boolean {
  const filled = filledCells(cells)
  if (filled.length < 2) return false
  const hits = filled.filter((cell) => HEADER_HINT.test(cell)).length
  if (hits >= 2) return true
  return (
    filled.length >= 4 &&
    filled.every((cell) => cell.length <= 48 && !NUMERIC_RE.test(cell) && !/^ACT/i.test(cell))
  )
}

function looksLikeKpiLabels(cells: string[]): boolean {
  const filled = filledCells(cells)
  if (filled.length < 2 || filled.length > 8) return false
  if (filled.some((cell) => cell.length > 42 || /^ACT/i.test(cell))) return false
  return filled.some((cell) => KPI_HINT.test(cell))
}

function looksLikeKpiValues(cells: string[]): boolean {
  const filled = filledCells(cells)
  if (!filled.length) return false
  const numeric = filled.filter((cell) => NUMERIC_RE.test(cell)).length
  return numeric >= Math.max(1, Math.ceil(filled.length * 0.6))
}

function looksLikeBannerRow(cells: string[]): boolean {
  const filled = filledCells(cells)
  if (!filled.length || filled.length > 4) return false
  if (looksLikeHeader(cells) || looksLikeKpiLabels(cells) || looksLikeKpiValues(cells)) return false
  const text = filled.join(' ')
  return text.length >= 6 && !NUMERIC_RE.test(text)
}

function splitSheets(text: string): { name: string; body: string; fromMarker: boolean }[] {
  const lines = text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').split('\n')
  const sheets: { name: string; body: string[]; fromMarker: boolean }[] = []
  let current = { name: 'Лист', body: [] as string[], fromMarker: false }
  for (const line of lines) {
    const match = SHEET_RE.exec(line.trim())
    if (match) {
      if (current.fromMarker || current.body.some((item) => item.trim())) sheets.push(current)
      current = { name: cleanCell(match[1]) || 'Лист', body: [], fromMarker: true }
      continue
    }
    current.body.push(line)
  }
  if (current.fromMarker || current.body.some((item) => item.trim())) sheets.push(current)
  return sheets.map((sheet) => ({
    name: sheet.name,
    body: sheet.body.join('\n'),
    fromMarker: sheet.fromMarker
  }))
}

function normalizeTable(headers: string[], rows: string[][]): { headers: string[]; rows: string[][] } {
  const width = Math.max(headers.length, ...rows.map((row) => row.length), 0)
  if (!width) return { headers, rows }
  const nextHeaders = [...headers]
  while (nextHeaders.length < width) nextHeaders.push('')
  const nextRows = rows.map((row) => {
    const copy = [...row]
    while (copy.length < width) copy.push('')
    return copy.slice(0, width)
  })
  for (let col = width - 1; col >= 0; col -= 1) {
    const header = nextHeaders[col] || ''
    const empty = !header && nextRows.every((row) => !row[col])
    if (!empty) break
    nextHeaders.pop()
    nextRows.forEach((row) => row.pop())
  }
  return { headers: nextHeaders.map((cell, index) => cell || `Колонка ${index + 1}`), rows: nextRows }
}

function parseSheet(name: string, body: string, opts: { fromMarker: boolean; preferCsv: boolean }): WorkbookSheet | null {
  const rawLines = body.replace(/\r\n/g, '\n').split('\n')
  const lines = rawLines.map((line) => line.replace(/\s+$/, '')).filter((line) => line.trim())
  const delimiter = detectDelimiter(lines, opts.preferCsv)
  const rows = lines.map((line) => (delimiter ? splitCells(line, delimiter) : [cleanCell(line)]))
  let index = 0
  let title = ''
  let subtitle = ''
  const kpis: WorkbookKpi[] = []
  const notes: string[] = []

  if (rows[index] && looksLikeBannerRow(rows[index])) {
    title = filledCells(rows[index]).join(' ')
    index += 1
  }
  if (rows[index] && looksLikeBannerRow(rows[index])) {
    subtitle = filledCells(rows[index]).join(' ')
    index += 1
  }
  if (rows[index] && rows[index + 1] && looksLikeKpiLabels(rows[index]) && looksLikeKpiValues(rows[index + 1])) {
    const labels = filledCells(rows[index])
    const values = filledCells(rows[index + 1])
    const count = Math.min(labels.length, values.length)
    for (let i = 0; i < count; i += 1) kpis.push({ label: labels[i], value: values[i] })
    index += 2
  }

  let headerIndex = rows.findIndex((row, rowIndex) => rowIndex >= index && looksLikeHeader(row))
  if (headerIndex < 0) {
    const wide = rows
      .map((row, rowIndex) => ({ row, rowIndex, width: filledCells(row).length }))
      .filter((item) => item.rowIndex >= index && item.width >= 3)
    if (wide.length >= 2) {
      const topWidth = Math.max(...wide.map((item) => item.width))
      headerIndex = wide.find((item) => item.width === topWidth)?.rowIndex ?? -1
    }
  }

  let headers: string[] = []
  let data: string[][] = []
  if (headerIndex >= 0) {
    for (let i = index; i < headerIndex; i += 1) {
      const note = filledCells(rows[i]).join(' — ')
      if (note) notes.push(note)
    }
    headers = rows[headerIndex].map(cleanCell)
    data = rows.slice(headerIndex + 1).filter((row) => filledCells(row).length)
    const table = normalizeTable(headers, data)
    headers = table.headers
    data = table.rows
  } else {
    for (let i = index; i < rows.length; i += 1) {
      const note = filledCells(rows[i]).join(' — ')
      if (note) notes.push(note)
    }
  }

  const sheet: WorkbookSheet = {
    name,
    title,
    subtitle,
    kpis,
    notes,
    headers,
    rows: data
  }
  const useful = Boolean(title || subtitle || kpis.length || headers.length || notes.length)
  if (!useful) return null
  if (!opts.fromMarker && !headers.length && !kpis.length) return null
  return sheet
}

export function tableToWorkbook(headers: string[], rows: string[][]): WorkbookPreview {
  return {
    kind: 'workbook',
    sheets: [
      {
        name: 'Лист',
        title: '',
        subtitle: '',
        kpis: [],
        notes: [],
        headers,
        rows
      }
    ]
  }
}

export function workbookRowCount(preview: WorkbookPreview): number {
  return preview.sheets.reduce((sum, sheet) => sum + sheet.rows.length, 0)
}

export function parseWorkbookPreview(text: string, opts?: { preferCsv?: boolean }): WorkbookPreview | null {
  const raw = (text || '').replace(/^\uFEFF/, '').trim()
  if (!raw) return null
  const preferCsv = Boolean(opts?.preferCsv)
  const chunks = splitSheets(raw)
  const sheets = chunks
    .map((chunk) => parseSheet(chunk.name, chunk.body, { fromMarker: chunk.fromMarker, preferCsv }))
    .filter((sheet): sheet is WorkbookSheet => Boolean(sheet))
  if (!sheets.length) return null
  const preview = { kind: 'workbook' as const, sheets }
  if (!isUsefulWorkbook(preview)) return null
  return preview
}
