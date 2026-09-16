import { useCallback, useEffect, useMemo, useState } from 'react'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT, STANDARD_TAB_LABELS } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { erpActorFio } from '../../workplace/userContext'
import {
  ensureOutlookMeetings,
  formatMeetingStamp,
  isOutlookFolderOwner,
  meetingFormatHint,
  type MeetingEvent
} from '../../utils/outlookMeetings'
import { addDays, mondayOf, type CalendarView } from '../../utils/calendar'
import { countMeetingTiles, meetingMatchesTile, toggleSimpleTile } from '../../workplace/tileFilters'
import { MeetingsCalendar } from '../../components/agents/MeetingsCalendar'
import { GridFilterBar } from './gridFilters'

function meetingField(value: string | undefined): string {
  const text = (value || '').trim()
  return text || '—'
}

function MeetingDetailCard({ meeting }: { meeting: MeetingEvent }): React.JSX.Element {
  const attendees = (meeting.attendees || '')
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)
  return (
    <div className="spec-detail-card wp-card">
      <h2>{meetingField(meeting.subject)}</h2>
      <dl className="spec-detail-meta">
        <div>
          <dt>Дата / время</dt>
          <dd>
            {formatMeetingStamp(meeting.start)}
            {meeting.end ? ` – ${formatMeetingStamp(meeting.end)}` : ''}
          </dd>
        </div>
        <div>
          <dt>Место</dt>
          <dd>{meetingField(meeting.location)}</dd>
        </div>
        <div>
          <dt>Формат</dt>
          <dd>{meetingFormatHint(meeting.location)}</dd>
        </div>
        <div>
          <dt>Организатор</dt>
          <dd>{meetingField(meeting.organizer)}</dd>
        </div>
        <div>
          <dt>Участники</dt>
          <dd>
            {attendees.length ? (
              <ul className="spec-detail-list">
                {attendees.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            ) : (
              '—'
            )}
          </dd>
        </div>
        {meeting.owner && !isOutlookFolderOwner(meeting.owner) ? (
          <div>
            <dt>Владелец</dt>
            <dd>{meeting.owner}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  )
}

export function MeetingsGridTab({ user }: { user: UserProfile }): React.JSX.Element {
  const fio = erpActorFio(user)
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [view, setView] = useState<CalendarView>('week')
  const [anchor, setAnchor] = useState(() => new Date())
  const [tileFilter, setTileFilter] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const [query, setQuery] = useState('')
  const [barStatus, setBarStatus] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    void ensureOutlookMeetings(view, anchor, { owner: fio, force: true })
      .then((cal) => {
        setMeetings(cal.meetings || [])
        setError(cal.ok ? '' : cal.error || 'Outlook недоступен')
      })
      .catch((err) => {
        setMeetings([])
        setError(err instanceof Error ? err.message : 'Ошибка календаря')
      })
      .finally(() => setLoading(false))
  }, [anchor, fio, view])

  useEffect(() => {
    load()
  }, [load])

  const visibleMeetings = useMemo(() => {
    const q = query.trim().toLowerCase()
    const now = new Date()
    return meetings.filter((item) => {
      if (!meetingMatchesTile(item, tileFilter, now)) return false
      if (barStatus === 'past' && !meetingMatchesTile(item, 'done', now)) return false
      if (barStatus === 'today' && !meetingMatchesTile(item, 'today', now)) return false
      if (barStatus === 'upcoming' && !meetingMatchesTile(item, 'upcoming', now)) return false
      if (q && !`${item.subject} ${item.location} ${item.organizer} ${item.attendees}`.toLowerCase().includes(q)) {
        return false
      }
      return true
    })
  }, [meetings, tileFilter, query, barStatus])

  const selected = visibleMeetings.find((item) => item.id === (selectedId || visibleMeetings[0]?.id))

  const tiles: SpecSummaryTile[] = useMemo(() => {
    const counts = countMeetingTiles(meetings)
    const dash = (n: number): string => (n ? String(n) : '—')
    return [
      { id: 'period', label: 'Совещания за период', value: dash(counts.period), tone: 'orange' },
      { id: 'today', label: 'Сегодня', value: dash(counts.today), tone: 'yellow' },
      { id: 'done', label: 'Прошло', value: dash(counts.done), tone: 'green' },
      { id: 'upcoming', label: 'Дальше', value: dash(counts.upcoming), tone: 'blue' }
    ]
  }, [meetings])

  const chromeTiles = useMemo(
    () =>
      summaryTilesAsChrome(tiles, tileFilter === 'all' ? 'period' : tileFilter, (id) => {
        setTileFilter((current) => (id === 'period' ? 'all' : toggleSimpleTile(current, id)))
      }),
    [tiles, tileFilter]
  )

  return (
    <StandardTabChrome
      tabId="meetings"
      userId={user.id || ''}
      defaults={DEFAULT_STANDARD_LAYOUT}
      labels={{ ...STANDARD_TAB_LABELS, main: 'Календарь' }}
      chromeTiles={chromeTiles}
      widgets={{
        filters: (
        <GridFilterBar
          search={{ value: query, onChange: setQuery, placeholder: 'Поиск совещаний…' }}
          selects={[
            {
              id: 'view',
              value: view,
              emptyLabel: '',
              onChange: (value) => setView((value as CalendarView) || 'week'),
              options: [
                { value: 'day', label: 'День' },
                { value: 'week', label: 'Неделя' },
                { value: 'month', label: 'Месяц' }
              ]
            },
            {
              id: 'status',
              value: barStatus,
              emptyLabel: 'Статус: все',
              onChange: setBarStatus,
              options: [
                { value: 'past', label: 'Прошло' },
                { value: 'today', label: 'Сегодня' },
                { value: 'upcoming', label: 'Дальше' }
              ]
            }
          ]}
          onReset={() => {
            setQuery('')
            setBarStatus('')
            setTileFilter('all')
            setView('week')
            setAnchor(new Date())
          }}
        />
        ),
        main: (
        <div className="wp-card meetings-grid-calendar">
          <MeetingsCalendar
            view={view}
            anchor={anchor}
            meetings={visibleMeetings}
            loading={loading}
            error={error}
            ownerName={fio}
            onView={setView}
            onShift={(step) => {
              setAnchor((current) => {
                if (view === 'month') return new Date(current.getFullYear(), current.getMonth() + step, 1)
                if (view === 'day') return addDays(current, step)
                return addDays(mondayOf(current), step * 7)
              })
            }}
            onToday={() => setAnchor(new Date())}
            onRefresh={load}
            selectedId={selected?.id}
            onSelectMeeting={(meeting) => setSelectedId(meeting.id)}
            showDetailsModal={false}
          />
        </div>
        ),
        side: selected ? (
          <MeetingDetailCard meeting={selected} />
        ) : (
          <div className="wp-card spec-v04-muted">Выберите совещание</div>
        )
      }}
    />
  )
}
