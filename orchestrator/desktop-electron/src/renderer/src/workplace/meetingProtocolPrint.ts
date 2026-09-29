import type { OnecProtocolForm } from './meetingProtocolCreate'
import { stripOutlookMarker } from './meetingProtocolCreate'

function esc(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function ruDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso.trim())
  if (!match) return iso.trim()
  return `${match[3]}.${match[2]}.${match[1]}`
}

function multiline(text: string): string {
  return esc(text).replace(/\r?\n/g, '<br />')
}

function headerRow(label: string, value: string): string {
  if (!value.trim()) return ''
  return `<tr><th scope="row">${esc(label)}</th><td>${multiline(value)}</td></tr>`
}

export function protocolPrintTitle(card: OnecProtocolForm): string {
  const number = card.number.trim()
  return number ? `Протокол ${number}` : 'Протокол совещания'
}

/** Printable body (used inside wrapProtocolPrintHtml) rendered from 1C protocol data. */
export function renderProtocolHtml(card: OnecProtocolForm): string {
  const form = card.form
  const when = [ruDate(form.date), [form.time_start, form.time_end].filter(Boolean).join('–')]
    .filter(Boolean)
    .join(' ')
  const status = card.posted ? 'Проведён' : card.status || 'Подготовлен'

  const header = [
    headerRow('Тема совещания', form.topic),
    headerRow('Дата и время', when),
    headerRow('Вид совещания', form.meeting_type),
    headerRow('Кабинет', form.room),
    headerRow('Руководитель', form.leader),
    headerRow('Проверяющий', form.responsible),
    headerRow('Подготовил', form.prepared_by),
    headerRow('Подразделение', form.department),
    headerRow('Проект', form.project),
    headerRow('Гриф доступа', form.access),
    headerRow(
      'Отчётный период',
      form.report_period_from || form.report_period_to
        ? `${ruDate(form.report_period_from)} – ${ruDate(form.report_period_to)}`
        : ''
    ),
    headerRow('Дата следующего совещания', ruDate(form.next_meeting_date)),
    headerRow('Статус', status)
  ].join('')

  const participants = form.participants.length
    ? `<h2>Присутствующие</h2><ol>${form.participants.map((name) => `<li>${esc(name)}</li>`).join('')}</ol>`
    : ''

  const agenda = form.agenda.length
    ? `<h2>Повестка совещания</h2>
<table>
<thead><tr><th style="width:36px">№</th><th>Вопрос</th><th style="width:28%">Ответственный</th></tr></thead>
<tbody>${form.agenda
        .map(
          (row, index) =>
            `<tr><td>${index + 1}</td><td>${multiline(row.question)}</td><td>${esc(row.responsible)}</td></tr>`
        )
        .join('')}</tbody>
</table>`
    : ''

  const decisions = form.decisions.length
    ? `<h2>Решения</h2>
<table>
<thead><tr><th style="width:36px">№</th><th>Решение</th><th style="width:18%">Срок</th></tr></thead>
<tbody>${form.decisions
        .map(
          (row, index) =>
            `<tr><td>${index + 1}</td><td>${multiline(row.text)}</td><td>${esc(ruDate(row.due))}</td></tr>`
        )
        .join('')}</tbody>
</table>`
    : ''

  const tasks = form.tasks.length
    ? `<h2>Поставленные задачи</h2>
<table>
<thead><tr><th style="width:36px">№</th><th>Задача</th><th style="width:22%">Ответственный</th><th style="width:14%">Срок</th><th style="width:12%">Приоритет</th></tr></thead>
<tbody>${form.tasks
        .map(
          (row, index) =>
            `<tr><td>${esc(row.item || String(index + 1))}</td><td>${multiline(row.text)}${
              row.note ? `<div style="color:#5b6470;font-size:11px;margin-top:3px">${multiline(row.note)}</div>` : ''
            }</td><td>${esc(row.executor)}</td><td>${esc(ruDate(row.due))}</td><td>${esc(row.priority)}</td></tr>`
        )
        .join('')}</tbody>
</table>`
    : ''

  const comment = stripOutlookMarker(form.comment)
  const commentHtml = comment ? `<h2>Комментарий</h2><p>${multiline(comment)}</p>` : ''

  return `<h1>${esc(protocolPrintTitle(card))}</h1>
<table class="protocol-head"><tbody>${header}</tbody></table>
${participants}
${agenda}
${decisions}
${tasks}
${commentHtml}`
}
