import {
  ASSIGNMENT_REGISTRY_COLUMNS,
  type AssignmentRegistryRow,
  type AssignmentRegistryRowTone
} from './assignmentRegistryTypes'

/** Фоны строк — как в UI (extensionsGrid.css, .registry-tr.tone-*). */
const TONE_BACKGROUND: Record<AssignmentRegistryRowTone, string> = {
  done: 'rgba(46, 154, 111, 0.14)',
  overdue: 'rgba(198, 40, 40, 0.12)',
  due_soon: 'rgba(230, 167, 0, 0.18)',
  neutral: '#ffffff'
}

const TONE_ACCENT: Record<AssignmentRegistryRowTone, string> = {
  done: '#2e9a6f',
  overdue: '#c62828',
  due_soon: '#e6a700',
  neutral: '#8a94a6'
}

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function formatRuDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || '').trim())
  if (!match) return String(iso || '')
  return `${match[3]}.${match[2]}.${match[1]}`
}

function printDocument(title: string, bodyHtml: string): string {
  return `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(title)}</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 11px;
    color: #10141a;
    padding: 16px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  h1 { font-size: 16px; margin: 0 0 4px; }
  .doc-meta { margin: 0 0 12px; font-size: 10px; color: #5a6472; }
  table.registry {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }
  table.registry th, table.registry td {
    border: 1px solid #c8d0dc;
    padding: 4px 6px;
    text-align: left;
    vertical-align: top;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  table.registry th {
    background: #e8edf4;
    font-size: 10px;
    text-transform: none;
  }
  table.registry thead { display: table-header-group; }
  table.registry tr { page-break-inside: avoid; }
  .legend { margin-top: 10px; font-size: 10px; color: #5a6472; }
  .legend span { display: inline-block; margin-right: 14px; }
  .legend i {
    display: inline-block;
    width: 10px;
    height: 10px;
    margin-right: 4px;
    border: 1px solid #c8d0dc;
    vertical-align: -1px;
  }
  .card { border: 1px solid #c8d0dc; border-radius: 6px; overflow: hidden; }
  .card-head { padding: 10px 12px; border-bottom: 1px solid #c8d0dc; }
  .card-head h1 { margin: 0; }
  .card-head p { margin: 4px 0 0; font-size: 12px; color: #333a45; }
  .card-fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px 18px;
    padding: 10px 12px;
  }
  .card-field b {
    display: block;
    font-size: 9px;
    font-weight: 600;
    color: #5a6472;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .card-field span { font-size: 11px; }
  .tasks-title { font-size: 13px; margin: 14px 0 6px; }
  .task {
    border: 1px solid #d7dde7;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 8px;
    page-break-inside: avoid;
  }
  .task-head { display: flex; justify-content: space-between; font-size: 10px; color: #5a6472; }
  .task-head .prio { font-weight: 600; color: #10141a; }
  .task-text { margin: 4px 0 6px; font-size: 11px; line-height: 1.4; }
  .task-meta { font-size: 10px; color: #333a45; }
  .task-meta b { color: #5a6472; font-weight: 600; }
  .empty { color: #5a6472; font-style: italic; }
</style>
</head>
<body>
${bodyHtml}
</body>
</html>`
}

export type RegistryPrintOptions = {
  periodFrom?: string
  periodTo?: string
  filterLabel?: string
}

/** Автономный HTML с таблицей реестра поручений (для printToPDF / печати). */
export function buildRegistryPrintHtml(
  rows: AssignmentRegistryRow[],
  opts: RegistryPrintOptions = {}
): string {
  const metaParts: string[] = []
  if (opts.periodFrom || opts.periodTo) {
    metaParts.push(
      `Период: ${escapeHtml(formatRuDate(opts.periodFrom || ''))} — ${escapeHtml(
        formatRuDate(opts.periodTo || '')
      )}`
    )
  }
  if (opts.filterLabel) metaParts.push(`Фильтр: ${escapeHtml(opts.filterLabel)}`)
  metaParts.push(`Поручений: ${rows.length}`)
  metaParts.push(`Сформировано: ${escapeHtml(new Date().toLocaleString('ru-RU'))}`)

  const headCells = ASSIGNMENT_REGISTRY_COLUMNS.map(
    (column) => `<th${column.compact ? ' style="width:7%"' : ''}>${escapeHtml(column.label)}</th>`
  ).join('')

  const bodyRows = rows.length
    ? rows
        .map((row) => {
          const background = TONE_BACKGROUND[row.tone] || TONE_BACKGROUND.neutral
          const cells = ASSIGNMENT_REGISTRY_COLUMNS.map(
            (column) => `<td>${escapeHtml(row[column.id])}</td>`
          ).join('')
          return `<tr style="background:${background}">${cells}</tr>`
        })
        .join('\n')
    : `<tr><td colspan="${ASSIGNMENT_REGISTRY_COLUMNS.length}" class="empty">Нет поручений</td></tr>`

  const legend = `<p class="legend">
<span><i style="background:${TONE_BACKGROUND.done}"></i>выполненные</span>
<span><i style="background:${TONE_BACKGROUND.overdue}"></i>просроченные</span>
<span><i style="background:${TONE_BACKGROUND.due_soon}"></i>подходит срок</span>
</p>`

  const body = `<h1>Реестр поручений</h1>
<p class="doc-meta">${metaParts.join(' · ')}</p>
<table class="registry">
<thead><tr>${headCells}</tr></thead>
<tbody>
${bodyRows}
</tbody>
</table>
${legend}`

  return printDocument('Реестр поручений', body)
}

/** Автономный HTML карточки одного поручения (поля + список задач). */
export function buildAssignmentCardPrintHtml(row: AssignmentRegistryRow): string {
  const accent = TONE_ACCENT[row.tone] || TONE_ACCENT.neutral
  const fields: { label: string; value: string }[] = [
    { label: 'Статус', value: row.status },
    { label: 'Дата', value: row.date },
    { label: 'Руководитель', value: row.manager },
    { label: 'Организация', value: row.organization },
    { label: 'Основание', value: row.basis },
    { label: 'Срок устранения', value: row.fullRemediationDue },
    { label: 'Еженедельный отчёт', value: row.weeklyReportDate },
    { label: 'Итоговый доклад', value: row.finalReportDate },
    { label: 'Кто доложит', value: row.reporter },
    { label: 'Секретарь', value: row.secretary }
  ]

  const fieldsHtml = fields
    .map(
      (field) => `<div class="card-field">
<b>${escapeHtml(field.label)}</b>
<span>${escapeHtml(field.value || '—')}</span>
</div>`
    )
    .join('\n')

  const tasksHtml = row.lines.length
    ? row.lines
        .map((line, index) => {
          const priority =
            line.priority && line.priority !== '—'
              ? `<span class="prio">${escapeHtml(line.priority)}</span>`
              : ''
          return `<div class="task">
<div class="task-head"><span>Задача ${escapeHtml(line.line || index + 1)}</span>${priority}</div>
<p class="task-text">${escapeHtml(line.text)}</p>
<p class="task-meta"><b>Исполнитель:</b> ${escapeHtml(line.executor || '—')} · <b>Срок:</b> ${escapeHtml(
            line.due || '—'
          )}</p>
</div>`
        })
        .join('\n')
    : '<p class="empty">Задачи отсутствуют.</p>'

  const body = `<div class="card" style="border-left:4px solid ${accent}">
<div class="card-head">
<h1>Поручение ${escapeHtml(row.number)}</h1>
<p>${escapeHtml(row.topic)}</p>
</div>
<div class="card-fields">
${fieldsHtml}
</div>
</div>
<h2 class="tasks-title">Задачи${row.lines.length ? ` (${row.lines.length})` : ''}</h2>
${tasksHtml}`

  return printDocument(`Поручение ${row.number}`, body)
}
