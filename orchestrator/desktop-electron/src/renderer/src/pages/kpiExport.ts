export type KpiExportRow = {
  title: string
  plan: number | null
  fact: number | null
  agentDelayMinutes: number
  humanDelayMinutes: number
  automation: number
  sla: string
}

const HEADERS = [
  'Процесс',
  'План %',
  'Факт %',
  'Задержка агента (мин)',
  'Задержка человека (мин)',
  'Автоматизация %',
  'SLA статус'
] as const

function cell(value: string | number | null | undefined): string {
  if (value == null) return ''
  return String(value)
}

function escapeCsv(value: string): string {
  if (/[;"\n\r]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

export function buildKpiCsv(rows: KpiExportRow[], periodLabel: string): string {
  const lines = [
    `Показатели;период;${escapeCsv(periodLabel)}`,
    HEADERS.join(';'),
    ...rows.map((row) =>
      [
        escapeCsv(row.title),
        cell(row.plan),
        cell(row.fact),
        cell(row.agentDelayMinutes),
        cell(row.humanDelayMinutes),
        cell(row.automation),
        escapeCsv(row.sla)
      ].join(';')
    )
  ]
  return `\uFEFF${lines.join('\r\n')}`
}

function crc32(buf: Uint8Array): number {
  let crc = 0xffffffff
  for (let i = 0; i < buf.length; i += 1) {
    crc ^= buf[i]
    for (let j = 0; j < 8; j += 1) {
      const mask = -(crc & 1)
      crc = (crc >>> 1) ^ (0xedb88320 & mask)
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

function u16(value: number): Uint8Array {
  const out = new Uint8Array(2)
  out[0] = value & 0xff
  out[1] = (value >>> 8) & 0xff
  return out
}

function u32(value: number): Uint8Array {
  const out = new Uint8Array(4)
  out[0] = value & 0xff
  out[1] = (value >>> 8) & 0xff
  out[2] = (value >>> 16) & 0xff
  out[3] = (value >>> 24) & 0xff
  return out
}

function concat(parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0)
  const out = new Uint8Array(total)
  let offset = 0
  for (const part of parts) {
    out.set(part, offset)
    offset += part.length
  }
  return out
}

function zipStore(files: Array<{ name: string; data: Uint8Array }>): Uint8Array {
  const localParts: Uint8Array[] = []
  const centralParts: Uint8Array[] = []
  let offset = 0
  for (const file of files) {
    const nameBytes = new TextEncoder().encode(file.name)
    const crc = crc32(file.data)
    const local = concat([
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(file.data.length),
      u32(file.data.length),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      file.data
    ])
    localParts.push(local)
    centralParts.push(
      concat([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(crc),
        u32(file.data.length),
        u32(file.data.length),
        u16(nameBytes.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        nameBytes
      ])
    )
    offset += local.length
  }
  const central = concat(centralParts)
  const end = concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(central.length),
    u32(offset),
    u16(0)
  ])
  return concat([...localParts, central, end])
}

function xmlEscape(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function buildKpiXlsx(rows: KpiExportRow[], periodLabel: string): Uint8Array {
  const sheetRows = [
    ['Показатели', `Период: ${periodLabel}`],
    [...HEADERS],
    ...rows.map((row) => [
      row.title,
      row.plan ?? '',
      row.fact ?? '',
      row.agentDelayMinutes,
      row.humanDelayMinutes,
      row.automation,
      row.sla
    ])
  ]
  const sheetXml = [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
    ...sheetRows.map((cells, rowIndex) => {
      const cols = cells
        .map((value, colIndex) => {
          const ref = `${String.fromCharCode(65 + colIndex)}${rowIndex + 1}`
          if (typeof value === 'number') {
            return `<c r="${ref}"><v>${value}</v></c>`
          }
          return `<c r="${ref}" t="inlineStr"><is><t>${xmlEscape(String(value))}</t></is></c>`
        })
        .join('')
      return `<row r="${rowIndex + 1}">${cols}</row>`
    }),
    '</sheetData></worksheet>'
  ].join('')

  const encoder = new TextEncoder()
  return zipStore([
    {
      name: '[Content_Types].xml',
      data: encoder.encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`
      )
    },
    {
      name: '_rels/.rels',
      data: encoder.encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`
      )
    },
    {
      name: 'xl/workbook.xml',
      data: encoder.encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Показатели" sheetId="1" r:id="rId1"/></sheets>
</workbook>`
      )
    },
    {
      name: 'xl/_rels/workbook.xml.rels',
      data: encoder.encode(
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>`
      )
    },
    {
      name: 'xl/worksheets/sheet1.xml',
      data: encoder.encode(sheetXml)
    }
  ])
}

export function buildKpiPdfHtml(
  rows: KpiExportRow[],
  periodLabel: string,
  summary: { fact: number | null; agentDelay: number; humanDelay: number; automation: number }
): string {
  const bodyRows = rows
    .map(
      (row) => `<tr>
      <td>${xmlEscape(row.title)}</td>
      <td>${row.plan ?? '—'}% / ${row.fact ?? '—'}%</td>
      <td>${row.agentDelayMinutes} мин</td>
      <td>${row.humanDelayMinutes} мин</td>
      <td>${row.automation}%</td>
      <td>${xmlEscape(row.sla)}</td>
    </tr>`
    )
    .join('')
  return `<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<title>Показатели</title>
<style>
  body { font-family: "Segoe UI", Arial, sans-serif; color: #102033; padding: 28px; }
  h1 { font-size: 22px; margin: 0 0 6px; }
  .sub { color: #5b6b7c; margin-bottom: 18px; }
  .cards { display: flex; gap: 12px; margin-bottom: 20px; }
  .card { border: 1px solid #d7e0ea; border-radius: 10px; padding: 10px 12px; min-width: 120px; }
  .card span { display: block; font-size: 12px; color: #5b6b7c; }
  .card strong { font-size: 18px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { border: 1px solid #d7e0ea; padding: 8px; text-align: left; }
  th { background: #eef4fb; }
</style></head><body>
  <h1>Показатели</h1>
  <div class="sub">Период: ${xmlEscape(periodLabel)}</div>
  <div class="cards">
    <div class="card"><span>План / факт</span><strong>${summary.fact != null ? `${summary.fact}%` : '—'}</strong></div>
    <div class="card"><span>Задержка агента</span><strong>${summary.agentDelay} мин</strong></div>
    <div class="card"><span>Задержка человека</span><strong>${summary.humanDelay} мин</strong></div>
    <div class="card"><span>Автоматизация</span><strong>${summary.automation}%</strong></div>
  </div>
  <table>
    <thead><tr>
      <th>Процесс</th><th>План / факт</th><th>Задержка агента</th>
      <th>Задержка человека</th><th>Автоматизация</th><th>SLA</th>
    </tr></thead>
    <tbody>${bodyRows || '<tr><td colspan="6">Нет данных за период</td></tr>'}</tbody>
  </table>
</body></html>`
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary)
}
