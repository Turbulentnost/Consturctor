import * as XLSX from 'xlsx'
import * as mammoth from 'mammoth'

export type SpreadsheetPreviewTable = {
  headers: string[]
  rows: string[][]
  sheetName: string
}

function cellText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return String(value).trim()
}

export function isSpreadsheetFileName(fileName: string): boolean {
  return /\.(xlsx?|xlsm|xlsb|csv)$/i.test((fileName || '').trim())
}

export function isDocxFileName(fileName: string): boolean {
  return /\.docx$/i.test((fileName || '').trim())
}

function toUint8Array(buffer: ArrayBuffer | Uint8Array | Buffer): Uint8Array {
  return buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer)
}

function toArrayBuffer(buffer: ArrayBuffer | Uint8Array | Buffer): ArrayBuffer {
  const bytes = toUint8Array(buffer)
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
}

export function spreadsheetPreviewFromBuffer(
  buffer: ArrayBuffer | Uint8Array | Buffer,
  fileName: string
): SpreadsheetPreviewTable | null {
  const name = (fileName || '').trim().toLowerCase()
  if (!isSpreadsheetFileName(name)) return null
  try {
    if (/\.csv$/i.test(name)) {
      const bytes = toUint8Array(buffer)
      const text = new TextDecoder('utf-8').decode(bytes)
      const lines = text
        .replace(/^\uFEFF/, '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
      if (lines.length < 1) return null
      const delimiter = lines[0].includes(';') ? ';' : lines[0].includes('|') ? '|' : ','
      const rows = lines.map((line) => line.split(delimiter).map((cell) => cell.trim()))
      const width = Math.max(...rows.map((row) => row.length))
      if (width < 1) return null
      const normalized = rows.map((row) => {
        const next = [...row]
        while (next.length < width) next.push('')
        return next.map(cellText)
      })
      const headers = normalized[0]
      return {
        headers,
        rows: normalized.slice(1),
        sheetName: 'CSV'
      }
    }

    const wb = XLSX.read(toUint8Array(buffer), { type: 'array' })
    const sheetName = wb.SheetNames[0]
    if (!sheetName) return null
    const sheet = wb.Sheets[sheetName]
    const matrix = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(sheet, {
      header: 1,
      defval: '',
      raw: false
    })
    if (!matrix.length) return null
    const width = Math.max(...matrix.map((row) => row.length))
    const normalized = matrix.map((row) => {
      const next = [...row]
      while (next.length < width) next.push('')
      return next.map(cellText)
    })
    const headers = normalized[0]
    const body = normalized.slice(1).filter((row) => row.some(Boolean))
    return { headers, rows: body, sheetName }
  } catch {
    return null
  }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function officeDocumentHtml(title: string, body: string): string {
  const safeTitle = escapeHtml(title || 'Документ')
  return `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${safeTitle}</title>
<style>
  html, body { margin: 0; min-height: 100%; background: #e6e6e6; color: #1f2937; }
  body { font-family: "Segoe UI", Arial, sans-serif; }
  .office-doc-shell { min-height: 100%; padding: 32px 24px; box-sizing: border-box; }
  .office-doc-page {
    max-width: 820px;
    min-height: 1050px;
    margin: 0 auto;
    padding: 72px 82px;
    background: #fff;
    box-shadow: 0 2px 16px rgba(0, 0, 0, 0.16);
    box-sizing: border-box;
  }
  .office-doc-title { margin: 0 0 28px; font-size: 18px; font-weight: 600; color: #323130; }
  .office-doc-page p { margin: 0 0 12px; line-height: 1.55; }
  .office-doc-page table { border-collapse: collapse; width: 100%; margin: 16px 0; }
  .office-doc-page th, .office-doc-page td { border: 1px solid #d4d4d4; padding: 6px 8px; }
  .office-doc-page img { max-width: 100%; height: auto; }
</style>
</head>
<body>
  <main class="office-doc-shell">
    <article class="office-doc-page">
      <h1 class="office-doc-title">${safeTitle}</h1>
      ${body}
    </article>
  </main>
</body>
</html>`
}

export async function docxPreviewDataUrl(
  buffer: ArrayBuffer | Uint8Array | Buffer,
  title: string
): Promise<string | null> {
  if (!isDocxFileName(title)) return null
  try {
    const result = await mammoth.convertToHtml({ arrayBuffer: toArrayBuffer(buffer) })
    const html = officeDocumentHtml(title, result.value || '<p>Документ пуст</p>')
    return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`
  } catch {
    return null
  }
}

export function spreadsheetPreviewHtml(table: SpreadsheetPreviewTable, title: string): string {
  const head = table.headers.map((cell) => `<th>${escapeHtml(cell || ' ')}</th>`).join('')
  const body = table.rows
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td>${escapeHtml(cell || '')}</td>`).join('')}</tr>`
    )
    .join('')
  const safeTitle = escapeHtml(title || table.sheetName || 'Таблица')
  return `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${safeTitle}</title>
<style>
  html, body { margin: 0; height: 100%; background: #ededed; color: #201f1e; }
  body { font-family: "Segoe UI", Calibri, Arial, sans-serif; }
  .office-shell { box-sizing: border-box; min-height: 100%; padding: 20px 24px 28px; }
  .office-title { margin: 0 0 12px; font-size: 14px; font-weight: 600; color: #323130; }
  .office-sheet-wrap {
    overflow: auto;
    background: #fff;
    border: 1px solid #c8c6c4;
    border-radius: 2px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
  }
  table { border-collapse: collapse; min-width: 100%; font-size: 13px; }
  th, td {
    border: 1px solid #d4d4d4;
    padding: 5px 10px;
    white-space: nowrap;
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  thead th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: #f3f2f1;
    font-weight: 600;
    color: #323130;
    box-shadow: 0 1px 0 #d4d4d4;
  }
  tbody tr:nth-child(even) td { background: #faf9f8; }
  tbody tr:hover td { background: #eef6fc; }
</style>
</head>
<body>
  <div class="office-shell">
    <p class="office-title">${safeTitle}</p>
    <div class="office-sheet-wrap">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  </div>
</body>
</html>`
}

export function spreadsheetPreviewDataUrl(table: SpreadsheetPreviewTable, title: string): string {
  const html = spreadsheetPreviewHtml(table, title)
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`
}
