import { Component, useMemo, useState, type ReactNode } from 'react'
import { TodayResultReport } from './TodayResultReport'
import type { WorkbookKpi, WorkbookSheet } from './todayWorkbookPreview'

const TOKEN_RE =
  /(\bACT-?\d{2,4}-\d{3,}\b|\bIN PROGRESS\b|[A-Za-z0-9._-]+\.(?:xlsx|xls|csv|docx|pdf)\b|просроченн?\w*|в работе|не проведено|выполнен\w*|закрыт\w*|открыт\w*)/gi

function kpiTone(kpi: WorkbookKpi): 'alert' | 'warn' | 'ok' | 'neutral' {
  const blob = `${kpi.label} ${kpi.value}`.toLowerCase()
  if (/просроч|критич|провал/.test(blob)) return 'alert'
  if (/сегодня|ближай|риск/.test(blob)) return 'warn'
  if (/закрыт|выполн/.test(blob)) return 'ok'
  return 'neutral'
}

function headerKey(header: string): string {
  const value = header.toLowerCase()
  if (/статус|status|состояние/.test(value)) return 'status'
  if (/риск|эскалац/.test(value)) return 'risk'
  if (/поручен|тема|описание|результат|комментар|ссылк/.test(value)) return 'wide'
  if (/id|код|номер/.test(value)) return 'id'
  if (/дата|срок/.test(value)) return 'date'
  return 'text'
}

function flattenCellText(text: string): string {
  const value = String(text ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/\u00a0/g, ' ')
    .trim()
  if (!value.includes('\n')) return value.replace(/\s+/g, ' ').trim()
  const parts = value.split('\n').map((part) => part.trim())
  if (parts.length >= 2 && parts.every((part) => part.length <= 1)) return parts.join('')
  return parts.filter(Boolean).join(' ')
}

function tokenClass(token: string): string {
  if (/^ACT/i.test(token)) return 'today-result-code'
  if (/\.(xlsx|xls|csv|docx|pdf)$/i.test(token)) return 'today-result-file'
  const low = token.toLowerCase()
  if (/просроч/.test(low)) return 'today-result-pill is-alert'
  if (/выполн|закрыт/.test(low)) return 'today-result-pill is-ok'
  if (/in progress|в работе|открыт/.test(low)) return 'today-result-pill is-run'
  if (/не проведено/.test(low)) return 'today-result-pill is-warn'
  return ''
}

function tokenLabel(token: string): string {
  return /^IN PROGRESS$/i.test(token) ? 'в работе' : token
}

function CellText({ text }: { text: string }): React.JSX.Element {
  const value = flattenCellText(text)
  if (!value) return <span className="today-result-empty">—</span>
  const parts = value.split(TOKEN_RE)
  return (
    <>
      {parts.map((part, index) => {
        if (!part) return null
        const cls = tokenClass(part)
        if (cls) {
          return (
            <span key={`${part}:${index}`} className={cls}>
              {tokenLabel(part)}
            </span>
          )
        }
        return <span key={`${part}:${index}`}>{part}</span>
      })}
    </>
  )
}

function ruCount(count: number, one: string, few: string, many: string): string {
  const abs = Math.abs(count) % 100
  const last = abs % 10
  if (abs > 10 && abs < 20) return `${count} ${many}`
  if (last === 1) return `${count} ${one}`
  if (last >= 2 && last <= 4) return `${count} ${few}`
  return `${count} ${many}`
}

function normalizeSheet(sheet: WorkbookSheet): WorkbookSheet {
  return {
    name: String(sheet?.name || 'Лист'),
    title: flattenCellText(String(sheet?.title || '')),
    subtitle: flattenCellText(String(sheet?.subtitle || '')),
    kpis: Array.isArray(sheet?.kpis)
      ? sheet.kpis.map((kpi) => ({
          label: flattenCellText(String(kpi?.label || '')),
          value: flattenCellText(String(kpi?.value || ''))
        }))
      : [],
    notes: Array.isArray(sheet?.notes) ? sheet.notes.map((item) => flattenCellText(String(item || ''))) : [],
    headers: Array.isArray(sheet?.headers) ? sheet.headers.map((item) => flattenCellText(String(item || ''))) : [],
    rows: Array.isArray(sheet?.rows)
      ? sheet.rows.map((row) => (Array.isArray(row) ? row.map((cell) => flattenCellText(String(cell ?? ''))) : []))
      : []
  }
}

function SheetView({ sheet }: { sheet: WorkbookSheet }): React.JSX.Element {
  const title = sheet.title || sheet.name
  const keys = sheet.headers.map(headerKey)
  return (
    <div className="today-result-sheet">
      <div className="today-result-workbook-banner">
        <p className="today-result-workbook-kicker">Отчёт</p>
        <h3>{title}</h3>
        {sheet.subtitle ? <p>{sheet.subtitle}</p> : null}
      </div>
      {sheet.kpis.length ? (
        <div className="today-result-kpis">
          {sheet.kpis.map((kpi) => (
            <div key={`${kpi.label}:${kpi.value}`} className={`today-result-kpi tone-${kpiTone(kpi)}`}>
              <span className="today-result-kpi-label">{kpi.label}</span>
              <strong className="today-result-kpi-value">{kpi.value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {sheet.notes.map((note, index) => (
        <p key={`${index}:${note.slice(0, 40)}`} className="today-result-workbook-note">
          {note}
        </p>
      ))}
      {sheet.headers.length ? (
        <div className="today-result-preview-table-wrap today-result-workbook-table-wrap">
          <table className="today-result-preview-table today-result-workbook-table">
            <thead>
              <tr>
                {sheet.headers.map((header, index) => (
                  <th key={`${index}:${header}`} data-col={keys[index] || 'text'}>
                    {header || `Колонка ${index + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheet.rows.map((row, rowIndex) => (
                <tr key={`${row[0] || 'row'}:${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${cellIndex}:${cell}`} data-col={keys[cellIndex] || 'text'}>
                      <CellText text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {sheet.rows.length ? (
        <p className="today-result-workbook-count spec-v04-muted">
          {ruCount(sheet.rows.length, 'строка', 'строки', 'строк')}
        </p>
      ) : null}
    </div>
  )
}

export function TodayResultWorkbook({ sheets }: { sheets: WorkbookSheet[] }): React.JSX.Element {
  const safeSheets = useMemo(
    () => (Array.isArray(sheets) ? sheets.map(normalizeSheet) : []),
    [sheets]
  )
  const [active, setActive] = useState(0)
  const current = safeSheets[Math.min(active, Math.max(safeSheets.length - 1, 0))]
  if (!current) {
    return <p className="today-result-preview-status">В отчёте нет данных для просмотра</p>
  }
  return (
    <article className="today-result-preview-doc today-result-workbook">
      {safeSheets.length > 1 ? (
        <div className="today-result-sheet-tabs" role="tablist" aria-label="Листы отчёта">
          {safeSheets.map((sheet, index) => (
            <button
              key={`${sheet.name}:${index}`}
              type="button"
              role="tab"
              aria-selected={index === active}
              className={index === active ? 'is-active' : ''}
              onClick={() => setActive(index)}
            >
              {sheet.name}
            </button>
          ))}
        </div>
      ) : null}
      <SheetView sheet={current} />
    </article>
  )
}

export class WorkbookPreviewGuard extends Component<
  { fallbackText?: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  render(): ReactNode {
    if (this.state.failed) {
      const text = (this.props.fallbackText || '').trim()
      if (text) return <TodayResultReport text={text} />
      return <p className="today-result-preview-status">Не удалось показать таблицу отчёта</p>
    }
    return this.props.children
  }
}
