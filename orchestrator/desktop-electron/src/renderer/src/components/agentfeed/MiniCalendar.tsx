import { useMemo, useState } from 'react'
import type { AgentRunnerEvent } from '../../api/types'
import { DAYS_SHORT, MONTHS_GEN, isoWeekday, parseIso, STATUS_STYLE } from '../../utils/calendar'
import type { FeedItem } from './types'

export interface MiniMeeting {
  title: string
  start: string
  end: string
  mark: string
  reason: string
  organizer?: string
  location?: string
  attendees?: string[]
  substitutes?: string[]
}

const MARK_ALIAS: Record<string, string> = {
  add: 'recommend_add',
  green: 'recommend_add',
  recommend_add: 'recommend_add',
  cancel: 'recommend_cancel',
  red: 'recommend_cancel',
  recommend_cancel: 'recommend_cancel',
  keep: 'meeting',
  stay: 'meeting',
  meeting: 'meeting'
}

function markKey(raw: string): string {
  const key = (raw || '').trim().toLowerCase().replace(/-/g, '_')
  return MARK_ALIAS[key] || 'meeting'
}

function chipLabel(mark: string, variant: CalendarVariant): string {
  if (variant === 'outlook') return 'Встреча'
  if (mark === 'recommend_add') return 'Поставить'
  if (mark === 'recommend_cancel') return 'Отменить'
  return 'Уже стоит'
}

export type CalendarVariant = 'plan' | 'outlook'

function substitutesFromText(text: string): string[] {
  if (!text) return []
  const out: string[] = []
  const rules = [
    /([А-ЯЁA-Z][^.;\n]{0,70}?)\s+замещает\s+([А-ЯЁA-Z][^.;\n]{0,70})/gi,
    /([А-ЯЁA-Z][^.;\n]{0,70}?)\s+вместо\s+([А-ЯЁA-Z][^.;\n]{0,70})/gi
  ]
  for (const re of rules) {
    for (const match of text.matchAll(re)) {
      const who = (match[1] || '').trim().replace(/^[\s(]+/, '')
      const instead = (match[2] || '').trim().replace(/[)\s]+$/, '')
      if (who && instead && who.length < 80 && instead.length < 80) {
        out.push(`${who} замещает ${instead}`)
      }
    }
  }
  return out
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asNameList(value: unknown): string[] {
  if (value == null) return []
  if (typeof value === 'string') {
    return value
      .split(/[;\n,]/)
      .map((item) => item.trim())
      .filter(Boolean)
  }
  if (Array.isArray(value)) {
    const out: string[] = []
    for (const item of value) out.push(...asNameList(item))
    return out
  }
  const row = asRecord(value)
  if (!row) {
    const text = String(value).trim()
    return text ? [text] : []
  }
  const name = row.name || row.fio || row.full_name || row.email || row.title
  return name ? [String(name).trim()] : []
}

function formatSubstitute(row: Record<string, unknown>): string {
  const who = String(row.who || row.deputy || row.substitute || row.name || row.fio || '').trim()
  const instead = String(
    row.instead_of || row.replaces || row.for || row.absent || row.original || ''
  ).trim()
  if (who && instead) return `${who} замещает ${instead}`
  return who || instead
}

function asSubstitutes(value: unknown): string[] {
  if (value == null) return []
  if (typeof value === 'string') {
    return value
      .split(/[;\n]/)
      .map((item) => item.trim())
      .filter(Boolean)
  }
  if (Array.isArray(value)) {
    const out: string[] = []
    for (const item of value) out.push(...asSubstitutes(item))
    return out
  }
  const row = asRecord(value)
  if (!row) {
    const text = String(value).trim()
    return text ? [text] : []
  }
  const formatted = formatSubstitute(row)
  return formatted ? [formatted] : []
}

function unique(items: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const item of items) {
    const key = item.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
  }
  return out
}

function normalizeMeetingList(raw: unknown): MiniMeeting[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => {
      const attendees = unique(
        asNameList(item.attendees).concat(
          asNameList(item.required_attendees),
          asNameList(item.participants),
          asNameList(item.people),
          asNameList(item.optional_attendees)
        )
      )
      const reason = String(
        item.reason ?? item.note ?? item.subtitle ?? item.body_preview ?? item.body ?? ''
      )
      const title = String(item.title ?? item.subject ?? item.name ?? '').trim() || '(без темы)'
      const substitutes = unique(
        asSubstitutes(item.substitutes).concat(
          asSubstitutes(item.replacements),
          asSubstitutes(item.deputies),
          asSubstitutes(item.who_replaces),
          substitutesFromText(title),
          substitutesFromText(reason)
        )
      )
      return {
        title,
        start: String(item.start ?? item.start_at ?? item.at ?? ''),
        end: String(item.end ?? item.end_at ?? ''),
        mark: String(item.mark ?? item.color ?? item.kind ?? 'keep'),
        reason,
        organizer: String(item.organizer ?? item.owner ?? item.chair ?? '').trim(),
        location: String(item.location ?? item.place ?? item.room ?? '').trim(),
        attendees,
        substitutes
      }
    })
    .filter((item) => item.title || item.start)
}

/** Extract meetings from a calendar.show_meetings payload (result or arguments). */
export function meetingsFromResult(result: unknown): MiniMeeting[] {
  const seen = new WeakSet<object>()
  const walk = (value: unknown, depth: number): MiniMeeting[] => {
    if (value == null || depth > 4) return []
    if (Array.isArray(value)) return normalizeMeetingList(value)
    const row = asRecord(value)
    if (!row || seen.has(row)) return []
    seen.add(row)
    for (const key of ['meetings', 'items', 'events']) {
      const found = normalizeMeetingList(row[key])
      if (found.length) return found
    }
    if (row.title && (row.start || row.start_at || row.at)) return normalizeMeetingList([row])
    for (const key of ['result', 'arguments', 'output', 'output_data', 'data']) {
      const found = walk(row[key], depth + 1)
      if (found.length) return found
    }
    return []
  }
  return walk(result, 0)
}

export function meetingsFromToolItem(item: { result?: unknown; arguments?: unknown }): MiniMeeting[] {
  const fromResult = meetingsFromResult(item.result)
  if (fromResult.length) return fromResult
  return meetingsFromResult(item.arguments)
}

export function meetingsFromFeed(items: FeedItem[]): MiniMeeting[] {
  let found: MiniMeeting[] = []
  for (const item of items) {
    if (item.kind !== 'tool' || item.tool !== 'calendar.show_meetings') continue
    const parsed = meetingsFromToolItem(item)
    if (parsed.length) found = parsed
  }
  return found
}

export function meetingsFromEvents(events: AgentRunnerEvent[]): MiniMeeting[] {
  let found: MiniMeeting[] = []
  for (const event of events) {
    if (String(event.tool || '') === 'calendar.show_meetings') {
      const parsed = meetingsFromToolItem({ result: event.result, arguments: event.arguments })
      if (parsed.length) found = parsed
      continue
    }
    const nested = meetingsFromResult(event.result).concat(meetingsFromResult(event.arguments))
    if (nested.length > 1) found = nested
  }
  return found
}

export function meetingsForHistoryRun(
  events: AgentRunnerEvent[],
  stored?: Array<Partial<MiniMeeting> & { title: string; start: string }> | null
): MiniMeeting[] {
  const fromEvents = meetingsFromEvents(events)
  if (fromEvents.length) return fromEvents
  return normalizeMeetingList(stored || [])
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function hhmm(stamp: Date): string {
  return `${pad2(stamp.getHours())}:${pad2(stamp.getMinutes())}`
}

function timeRange(start: string, end: string): string {
  const a = parseIso(start)
  if (!a) return ''
  const b = parseIso(end)
  return b ? `${hhmm(a)}–${hhmm(b)}` : hhmm(a)
}

function dayLabel(stamp: Date): string {
  return `${DAYS_SHORT[isoWeekday(stamp)]}, ${stamp.getDate()} ${MONTHS_GEN[stamp.getMonth() + 1]}`
}

interface NormMeeting extends MiniMeeting {
  key: string
  stamp: Date | null
}

interface DayColumn {
  id: string
  label: string
  order: number
  items: NormMeeting[]
}

function normalize(meetings: MiniMeeting[]): { columns: DayColumn[]; loose: NormMeeting[] } {
  const map = new Map<string, DayColumn>()
  const loose: NormMeeting[] = []
  for (const raw of meetings) {
    const stamp = parseIso(raw.start)
    const item: NormMeeting = { ...raw, key: markKey(raw.mark), stamp }
    if (!stamp) {
      loose.push(item)
      continue
    }
    const id = `${stamp.getFullYear()}-${pad2(stamp.getMonth() + 1)}-${pad2(stamp.getDate())}`
    let column = map.get(id)
    if (!column) {
      column = { id, label: dayLabel(stamp), order: stamp.getTime(), items: [] }
      map.set(id, column)
    }
    column.items.push(item)
  }
  const columns = Array.from(map.values()).sort((l, r) => l.order - r.order)
  for (const column of columns) {
    column.items.sort((l, r) => (l.stamp?.getTime() ?? 0) - (r.stamp?.getTime() ?? 0))
  }
  return { columns, loose }
}

function Chip({ mark, variant }: { mark: string; variant: CalendarVariant }): React.JSX.Element {
  const style = STATUS_STYLE[mark] ?? STATUS_STYLE.meeting
  return (
    <span
      className="mini-cal-chip"
      style={{ background: style.bg, borderColor: style.border, color: style.border }}
    >
      {chipLabel(mark, variant)}
    </span>
  )
}

function PeopleBlock({
  label,
  items,
  empty
}: {
  label: string
  items: string[]
  empty?: string
}): React.JSX.Element {
  return (
    <div className="mini-cal-people">
      <div className="mini-cal-people-label">{label}</div>
      {items.length > 0 ? (
        <ul>
          {items.map((name, index) => (
            <li key={`${name}-${index}`}>{name}</li>
          ))}
        </ul>
      ) : (
        <div className="mini-cal-empty-people">{empty || 'не указаны'}</div>
      )}
    </div>
  )
}

function BriefingCard({
  item,
  defaultOpen,
  variant
}: {
  item: NormMeeting
  defaultOpen: boolean
  variant: CalendarVariant
}): React.JSX.Element {
  const [open, setOpen] = useState(defaultOpen)
  const style = STATUS_STYLE[item.key] ?? STATUS_STYLE.meeting
  const attendees = item.attendees || []
  const substitutes = item.substitutes || []
  const summary = [
    attendees.length > 0 ? `${attendees.length} участн.` : '',
    substitutes.length > 0 ? `${substitutes.length} замен.` : ''
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <button
      type="button"
      className={`mini-cal-card${open ? ' open' : ''}`}
      style={{ background: style.bg, borderColor: style.border }}
      onClick={() => setOpen((prev) => !prev)}
    >
      <div className="mini-cal-card-head">
        <div className="mini-cal-card-meta">
          <span className="mini-cal-card-time">{timeRange(item.start, item.end) || '—'}</span>
          <Chip mark={item.key} variant={variant} />
        </div>
        <span className="mini-cal-card-toggle">{open ? 'Свернуть' : 'Состав'}</span>
      </div>
      <div className="mini-cal-card-title">{item.title}</div>
      {!open && (
        <div className="mini-cal-card-preview">
          {attendees.length > 0 ? (
            <div className="mini-cal-people-text">Участники: {attendees.join(', ')}</div>
          ) : (
            <div className="mini-cal-empty-people">участники не переданы</div>
          )}
          {substitutes.length > 0 && (
            <div className="mini-cal-people-text">Замещения: {substitutes.join('; ')}</div>
          )}
          {summary && <div className="mini-cal-card-summary">{summary}</div>}
        </div>
      )}
      {open && (
        <div className="mini-cal-card-body">
          {item.organizer && (
            <div className="mini-cal-people">
              <div className="mini-cal-people-label">Организатор</div>
              <div className="mini-cal-people-text">{item.organizer}</div>
            </div>
          )}
          {item.location && (
            <div className="mini-cal-people">
              <div className="mini-cal-people-label">Место</div>
              <div className="mini-cal-people-text">{item.location}</div>
            </div>
          )}
          <PeopleBlock label="Участники" items={attendees} empty="участники не переданы" />
          <PeopleBlock
            label="Кто замещает кого"
            items={substitutes}
            empty="замещений нет"
          />
          {item.reason && <div className="mini-cal-reason full">{item.reason}</div>}
        </div>
      )}
    </button>
  )
}

function BriefingList({
  columns,
  loose,
  defaultOpen,
  variant
}: {
  columns: DayColumn[]
  loose: NormMeeting[]
  defaultOpen: boolean
  variant: CalendarVariant
}): React.JSX.Element {
  return (
    <div className="mini-cal-brief">
      {columns.map((column) => (
        <div key={column.id} className="mini-cal-day">
          <div className="mini-cal-day-label">{column.label}</div>
          {column.items.map((item, index) => (
            <BriefingCard
              key={`${column.id}-${item.title}-${index}`}
              item={item}
              defaultOpen={defaultOpen}
              variant={variant}
            />
          ))}
        </div>
      ))}
      {loose.length > 0 && (
        <div className="mini-cal-day">
          <div className="mini-cal-day-label">Без даты</div>
          {loose.map((item, index) => (
            <BriefingCard
              key={`loose-${item.title}-${index}`}
              item={item}
              defaultOpen={defaultOpen}
              variant={variant}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function MiniCalendar({
  meetings,
  variant = 'plan'
}: {
  meetings: MiniMeeting[]
  variant?: CalendarVariant
}): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  const { columns, loose } = useMemo(() => normalize(meetings), [meetings])
  const heading = variant === 'outlook' ? 'Календарь Outlook' : 'План совещаний'

  const counts = useMemo(() => {
    let add = 0
    let cancel = 0
    let keep = 0
    for (const item of meetings) {
      const key = markKey(item.mark)
      if (key === 'recommend_add') add += 1
      else if (key === 'recommend_cancel') cancel += 1
      else keep += 1
    }
    return { add, cancel, keep, total: meetings.length }
  }, [meetings])

  if (columns.length === 0 && loose.length === 0) return null

  const summary =
    variant === 'outlook'
      ? counts.total === 1
        ? '1 встреча'
        : `${counts.total} встреч`
      : [
          counts.add > 0 ? `поставить ${counts.add}` : '',
          counts.cancel > 0 ? `отменить ${counts.cancel}` : '',
          counts.keep > 0 ? `оставить ${counts.keep}` : ''
        ]
          .filter(Boolean)
          .join(' · ')

  const legend =
    variant === 'outlook' ? null : (
      <div className="mini-cal-legend">
        <span style={{ color: STATUS_STYLE.recommend_add.border }}>● Поставить</span>
        <span style={{ color: STATUS_STYLE.recommend_cancel.border }}>● Отменить</span>
        <span style={{ color: STATUS_STYLE.meeting.border }}>● Уже стоит</span>
      </div>
    )

  return (
    <div className="mini-cal">
      <div className="mini-cal-head">
        <div className="mini-cal-headings">
          <span className="mini-cal-name">{heading}</span>
          {summary && <span className="mini-cal-summary">{summary}</span>}
        </div>
        <button type="button" className="mini-cal-expand" onClick={() => setOpen(true)}>
          Развернуть
        </button>
      </div>
      <div className="mini-cal-scroll">
        <BriefingList columns={columns} loose={loose} defaultOpen={false} variant={variant} />
      </div>
      {legend}

      {open && (
        <div className="modal-overlay" onClick={() => setOpen(false)}>
          <div className="modal-card mini-cal-modal" onClick={(e) => e.stopPropagation()}>
            <div className="mini-cal-modal-head">
              <div className="modal-title">{heading}</div>
              <button type="button" className="mini-cal-close" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>
            {summary && <div className="mini-cal-modal-summary">{summary}</div>}
            <div className="mini-cal-modal-body">
              <BriefingList columns={columns} loose={loose} defaultOpen variant={variant} />
            </div>
            {legend}
          </div>
        </div>
      )}
    </div>
  )
}
