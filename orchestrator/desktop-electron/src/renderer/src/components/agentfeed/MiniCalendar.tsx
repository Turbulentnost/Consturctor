import { useMemo, useState } from 'react'
import { DAYS_SHORT, MONTHS_GEN, isoWeekday, parseIso, STATUS_STYLE } from '../../utils/calendar'

export interface MiniMeeting {
  title: string
  start: string
  end: string
  mark: string
  reason: string
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

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function timeRange(start: string, end: string): string {
  const a = parseIso(start)
  if (!a) return ''
  const head = `${pad2(a.getHours())}:${pad2(a.getMinutes())}`
  const b = parseIso(end)
  if (!b) return head
  return `${head}–${pad2(b.getHours())}:${pad2(b.getMinutes())}`
}

function dayLabel(stamp: Date): string {
  return `${DAYS_SHORT[isoWeekday(stamp)]}, ${stamp.getDate()} ${MONTHS_GEN[stamp.getMonth() + 1]}`
}

interface NormMeeting extends MiniMeeting {
  key: string
  stamp: Date | null
}

interface DayGroup {
  label: string
  order: number
  items: NormMeeting[]
}

function groupByDay(meetings: MiniMeeting[]): DayGroup[] {
  const groups = new Map<string, DayGroup>()
  const loose: NormMeeting[] = []
  for (const raw of meetings) {
    const stamp = parseIso(raw.start)
    const item: NormMeeting = { ...raw, key: markKey(raw.mark), stamp }
    if (!stamp) {
      loose.push(item)
      continue
    }
    const id = `${stamp.getFullYear()}-${pad2(stamp.getMonth() + 1)}-${pad2(stamp.getDate())}`
    let group = groups.get(id)
    if (!group) {
      group = { label: dayLabel(stamp), order: stamp.getTime(), items: [] }
      groups.set(id, group)
    }
    group.items.push(item)
  }
  const ordered = Array.from(groups.values()).sort((l, r) => l.order - r.order)
  for (const group of ordered) {
    group.items.sort((l, r) => (l.stamp?.getTime() ?? 0) - (r.stamp?.getTime() ?? 0))
  }
  if (loose.length > 0) {
    ordered.push({ label: 'Без даты', order: Number.MAX_SAFE_INTEGER, items: loose })
  }
  return ordered
}

function Chip({ mark }: { mark: string }): React.JSX.Element {
  const style = STATUS_STYLE[mark] ?? STATUS_STYLE.meeting
  return (
    <span
      className="mini-cal-chip"
      style={{ background: style.bg, borderColor: style.border, color: style.border }}
    >
      {style.label}
    </span>
  )
}

function MeetingRows({ groups, full }: { groups: DayGroup[]; full: boolean }): React.JSX.Element {
  return (
    <>
      {groups.map((group) => (
        <div key={group.label} className="mini-cal-day">
          <div className="mini-cal-day-label">{group.label}</div>
          {group.items.map((item, index) => (
            <div key={`${item.title}-${index}`} className="mini-cal-row">
              <span className="mini-cal-time">{timeRange(item.start, item.end) || '—'}</span>
              <span className="mini-cal-body">
                <span className="mini-cal-row-head">
                  <span className="mini-cal-title" title={item.title}>
                    {item.title}
                  </span>
                  <Chip mark={item.key} />
                </span>
                {item.reason && (
                  <span className={full ? 'mini-cal-reason full' : 'mini-cal-reason'}>{item.reason}</span>
                )}
              </span>
            </div>
          ))}
        </div>
      ))}
    </>
  )
}

export function MiniCalendar({ meetings }: { meetings: MiniMeeting[] }): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  const groups = useMemo(() => groupByDay(meetings), [meetings])

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
    return { add, cancel, keep }
  }, [meetings])

  if (groups.length === 0) return null

  const summary = [
    counts.add > 0 ? `поставить ${counts.add}` : '',
    counts.cancel > 0 ? `отменить ${counts.cancel}` : '',
    counts.keep > 0 ? `оставить ${counts.keep}` : ''
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="mini-cal">
      <div className="mini-cal-head">
        <div className="mini-cal-headings">
          <span className="mini-cal-name">План совещаний</span>
          {summary && <span className="mini-cal-summary">{summary}</span>}
        </div>
        <button type="button" className="mini-cal-expand" onClick={() => setOpen(true)}>
          Развернуть
        </button>
      </div>
      <div className="mini-cal-list">
        <MeetingRows groups={groups} full={false} />
      </div>

      {open && (
        <div className="modal-overlay" onClick={() => setOpen(false)}>
          <div className="modal-card mini-cal-modal" onClick={(e) => e.stopPropagation()}>
            <div className="mini-cal-modal-head">
              <div className="modal-title">План совещаний</div>
              <button type="button" className="mini-cal-close" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>
            {summary && <div className="mini-cal-modal-summary">{summary}</div>}
            <div className="mini-cal-modal-body">
              <MeetingRows groups={groups} full />
            </div>
            <div className="mini-cal-legend">
              <span style={{ color: STATUS_STYLE.recommend_add.border }}>● Поставить</span>
              <span style={{ color: STATUS_STYLE.recommend_cancel.border }}>● Отменить</span>
              <span style={{ color: STATUS_STYLE.meeting.border }}>● Уже стоит</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
