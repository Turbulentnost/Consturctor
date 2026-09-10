import { useState } from 'react'
import { MiniCalendar, meetingsFromToolItem } from './MiniCalendar'
import { OdataBriefing, odataEntityHint, odataRecordsFromResult } from './OdataBriefing'
import { toolArgHint } from './labels'
import { countCalendarEvents, countOdataRows, summarizeToolResult } from './resultSummary'
import type { ToolItem } from './types'

interface ToolCardProps {
  item: ToolItem
  liftMeetings?: boolean
}

const CALENDAR_PLAN = 'calendar.show_meetings'
const CALENDAR_TOOLS = new Set(['calendar.show_meetings', 'outlook.read_calendar'])
const ODATA_TOOLS = new Set([
  'onec.odata_get',
  'onec.odata_post',
  'onec.odata_patch',
  'onec.odata_catalog',
  'onec.search_documents',
  'onec.get_document_card',
  'onec.meeting_service_notes',
  'onec.meeting_protocols'
])

function pretty(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function requestLines(item: ToolItem): string[] {
  const args = item.arguments || {}
  const lines: string[] = []
  const people = asText(args.people) || asText(args.attendees) || asText(args.mailbox)
  const from = asText(args.date_from) || asText(args.start) || asText(args.from)
  const to = asText(args.date_to) || asText(args.end) || asText(args.to)
  const entity = asText(args.entity)
  const path = asText(args.path)
  const filter = asText(args.filter) || asText(args.query)
  const number = asText(args.number)
  if (people) lines.push(`Кто: ${people}`)
  if (from || to) lines.push(`Период: ${[from, to].filter(Boolean).join(' — ')}`)
  if (entity) lines.push(`Сущность: ${entity}`)
  if (path && path !== entity) lines.push(`Путь: ${path}`)
  if (number) lines.push(`Номер: ${number}`)
  if (filter) lines.push(`Фильтр: ${filter}`)
  if (!lines.length) {
    const hint = item.hint || toolArgHint(args)
    if (hint) lines.push(hint)
  }
  return lines
}

function displayStatus(item: ToolItem, meetings: number, rows: number): string {
  if (item.error) return item.summary || item.statusText || 'Ошибка'
  if (!item.done) {
    const hint = requestLines(item)[0] || item.hint
    return hint ? `Выполняется: ${hint}` : item.statusText || 'Выполняется…'
  }
  if (meetings === 1) return '1 встреча — раскройте состав'
  if (meetings > 1) return `${meetings} встреч — раскройте состав`
  if (rows === 1) return '1 запись 1С'
  if (rows > 1) return `${rows} записей 1С`
  if (item.result) return summarizeToolResult(item.result)
  return item.statusText || item.summary || 'Готово'
}

export function ToolCard({ item, liftMeetings = false }: ToolCardProps): React.JSX.Element {
  const meetings = CALENDAR_TOOLS.has(item.tool) ? meetingsFromToolItem(item) : []
  const odataRows = ODATA_TOOLS.has(item.tool) ? odataRecordsFromResult(item.result) : []
  const request = requestLines(item)
  const hasResult = Boolean(item.result && Object.keys(item.result).length > 0)
  const structured = meetings.length > 0 || odataRows.length > 0
  const expandable = structured || hasResult || request.length > 0
  const [open, setOpen] = useState(false)
  const [touched, setTouched] = useState(false)
  const shown = touched ? open : structured || (!item.done && request.length > 0)

  if (meetings.length > 0 && liftMeetings && item.tool === CALENDAR_PLAN) {
    const status = item.error ? item.summary || 'Ошибка' : 'В результате'
    return (
      <div className={['feed-tool', 'done', item.error ? 'error' : ''].filter(Boolean).join(' ')}>
        <div className="feed-tool-head static">
          <span className={`feed-tool-dot${item.error ? ' error' : ' done'}`} />
          <span className="feed-tool-copy">
            <span className="feed-tool-title">{item.title}</span>
            <span className={`feed-tool-status${item.error ? ' error' : ''}`}>{status}</span>
          </span>
        </div>
      </div>
    )
  }

  const classes = ['feed-tool']
  if (item.done) classes.push('done')
  if (item.error) classes.push('error')
  if (!item.done) classes.push('live')
  const eventCount = meetings.length || countCalendarEvents(item.result)
  const rowCount = odataRows.length || countOdataRows(item.result)
  const status = displayStatus(item, eventCount, rowCount)
  const Head = expandable ? 'button' : 'div'

  return (
    <div className={classes.join(' ')}>
      <Head
        className="feed-tool-head"
        {...(expandable
          ? {
              onClick: () => {
                setTouched(true)
                setOpen(!shown)
              }
            }
          : {})}
      >
        <span className={`feed-tool-dot${item.error ? ' error' : item.done ? ' done' : ' run'}`} />
        <span className="feed-tool-copy">
          <span className="feed-tool-title">{item.title}</span>
          <span className={`feed-tool-status${item.done ? '' : ' live'}${item.error ? ' error' : ''}`}>
            {status}
          </span>
        </span>
        {expandable && <span className="feed-tool-chevron">{shown ? '\u25B2' : '\u25BC'}</span>}
      </Head>
      {shown && expandable && (
        <div className="feed-tool-body">
          {request.length > 0 && (
            <div className="feed-tool-request">
              {request.map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
          )}
          {meetings.length > 0 && (
            <MiniCalendar
              meetings={meetings}
              variant={item.tool === 'outlook.read_calendar' ? 'outlook' : 'plan'}
            />
          )}
          {odataRows.length > 0 && (
            <OdataBriefing
              records={odataRows}
              entityHint={odataEntityHint(item.arguments, item.result)}
            />
          )}
          {hasResult && !structured && item.result && (
            <div className="feed-tool-block">
              <div className="feed-tool-label">Результат</div>
              <pre>{pretty(item.result)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
