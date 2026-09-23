import { useCallback, useEffect, useMemo, useState } from 'react'
import type { UserProfile } from '../../api/types'
import { toolLabel } from '../../components/agentfeed/labels'
import { useRuns } from '../../store/runs'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT, STANDARD_TAB_LABELS } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { erpActorFio } from '../../workplace/userContext'
import {
  buildProtocolMessage,
  PROTOCOL_AGENT_TITLE,
  resolveProtocolAgentWorkflowId
} from '../../workplace/meetingProtocolAgent'
import { useMeetingProtocol } from '../../workplace/meetingProtocolStore'
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
import { usePageSearch } from '../../layout/pageSearchContext'
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { isoTimestampInWorkplacePeriod } from '../../workplace/workplacePeriodFilter'
import { MeetingReportModal } from './MeetingReportModal'
import { MeetingProtocolForm } from './MeetingProtocolForm'
import { rememberProtocolDocument, useProtocolMarks, type ProtocolMark } from '../../workplace/meetingProtocolMarks'

const AUDIO_EXTENSIONS = ['wav', 'mp3', 'm4a', 'aac', 'ogg', 'opus', 'flac', 'wma', 'amr', 'webm', 'mp4', 'mkv']

function meetingField(value: string | undefined): string {
  const text = (value || '').trim()
  return text || '—'
}

function basename(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || filePath
}

function MeetingDetailCard({
  meeting,
  userId,
  actorFio,
  protocol
}: {
  meeting: MeetingEvent
  userId: string
  actorFio: string
  protocol?: ProtocolMark
}): React.JSX.Element {
  const runs = useRuns()
  const { record, runEntry, rememberStart } = useMeetingProtocol(meeting, userId)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [reportOpen, setReportOpen] = useState(false)
  const [formOpen, setFormOpen] = useState(false)

  const attendees = (meeting.attendees || '')
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)

  const state = runEntry?.state
  const isRunning =
    record?.status === 'running' ||
    Boolean(state?.running) ||
    Boolean(state?.pendingHitl) ||
    Boolean(state?.pendingQuestion)

  const toolSteps = useMemo(() => {
    const items = state?.items || []
    return items
      .filter((item): item is Extract<typeof item, { kind: 'tool' }> => item.kind === 'tool')
      .map((item) => ({
        id: item.id,
        label: toolLabel(item.tool) || item.title || item.tool,
        done: item.done,
        error: item.error
      }))
  }, [state?.items])

  const attachAudio = useCallback(async () => {
    if (busy || isRunning) return
    setActionError('')
    setBusy(true)
    try {
      const paths = await window.api.openFile({
        title: 'Выберите аудиозапись совещания',
        filters: [{ name: 'Аудио', extensions: AUDIO_EXTENSIONS }],
        properties: ['openFile']
      })
      const audioPath = paths?.[0]
      if (!audioPath) return

      const workflowId = await resolveProtocolAgentWorkflowId()
      const message = buildProtocolMessage(meeting, audioPath)
      const runId = runs.startRun({
        workflowId,
        title: PROTOCOL_AGENT_TITLE,
        message,
        filePaths: [audioPath]
      })
      rememberStart({
        workflowId,
        runId: runId || '',
        backendRunId: runs.entries[workflowId]?.backendRunId || '',
        status: 'running',
        audioPath,
        audioName: basename(audioPath),
        startedAt: new Date().toISOString(),
        reportFileId: '',
        reportName: '',
        reportUrl: ''
      })
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Не удалось запустить формирование протокола')
    } finally {
      setBusy(false)
    }
  }, [busy, isRunning, meeting, rememberStart, runs])

  const canOpenReport = record?.status === 'done' && Boolean(record.reportFileId)

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

      {record ? (
        <div className="meeting-protocol-progress">
          <div className="meeting-protocol-progress-row">
            <span className="meeting-protocol-label">Аудио</span>
            <span>{record.audioName || basename(record.audioPath)}</span>
          </div>
          <div className="meeting-protocol-progress-row">
            <span className="meeting-protocol-label">Статус</span>
            <span>
              {state?.status ||
                (record.status === 'done'
                  ? 'Готово'
                  : record.status === 'error'
                    ? 'Ошибка'
                    : 'В работе…')}
            </span>
          </div>
          {toolSteps.length ? (
            <ul className="meeting-protocol-steps">
              {toolSteps.map((step) => (
                <li key={step.id} className={step.error ? 'is-error' : step.done ? 'is-done' : ''}>
                  {step.label}
                </li>
              ))}
            </ul>
          ) : null}
          {state?.error || (record.status === 'error' && !state?.error) ? (
            <p className="meeting-protocol-error">{state?.error || 'Запуск завершился с ошибкой'}</p>
          ) : null}
          {state?.pendingHitl ? (
            <div className="meeting-protocol-hitl">
              <p>{state.pendingHitl.title || 'Нужно ваше решение'}</p>
              {state.pendingHitl.intent ? (
                <p className="meeting-protocol-hitl-intent">{state.pendingHitl.intent}</p>
              ) : null}
              <div className="meeting-protocol-hitl-actions">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() =>
                    runs.respondHitl(record.workflowId, state.pendingHitl!.requestId, true)
                  }
                >
                  Подтвердить
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() =>
                    runs.respondHitl(record.workflowId, state.pendingHitl!.requestId, false)
                  }
                >
                  Отклонить
                </button>
              </div>
            </div>
          ) : null}
          {state?.pendingQuestion ? (
            <p className="meeting-protocol-hint">
              Агент задал вопрос — ответьте во вкладке «Решения».
            </p>
          ) : null}
        </div>
      ) : null}

      {actionError ? <p className="meeting-protocol-error">{actionError}</p> : null}

      <footer className="spec-detail-actions">
        <button
          type="button"
          className="btn-primary"
          onClick={() => void attachAudio()}
          disabled={busy || isRunning}
        >
          {busy ? 'Запуск…' : 'Прикрепить аудио'}
        </button>
        <button type="button" className="btn-light" onClick={() => setFormOpen(true)}>
          Создать протокол
        </button>
        <button
          type="button"
          className="btn-primary"
          onClick={() => setReportOpen(true)}
          disabled={!canOpenReport}
        >
          Получить отчёт
        </button>
      </footer>
      {protocol?.number ? (
        <p className="meeting-protocol-hint">Протокол в 1С: {protocol.number}</p>
      ) : null}

      <MeetingProtocolForm
        open={formOpen}
        meeting={meeting}
        actorFio={actorFio}
        onClose={() => setFormOpen(false)}
        onCreated={(result) => {
          rememberProtocolDocument(userId, meeting.id, {
            number: result.number || '',
            refKey: result.refKey || ''
          })
        }}
      />

      <MeetingReportModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        reportUrl={record?.reportUrl || ''}
        reportName={record?.reportName || 'protocol.docx'}
      />
    </div>
  )
}

export function MeetingsGridTab({ user }: { user: UserProfile }): React.JSX.Element {
  const fio = erpActorFio(user)
  const userId = user.id || ''
  const { from: periodFrom, to: periodTo } = useWorkplacePeriod()
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [view, setView] = useState<CalendarView>('week')
  const [anchor, setAnchor] = useState(() => new Date())
  const [tileFilter, setTileFilter] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const { query, setQuery } = usePageSearch()
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
      if (!isoTimestampInWorkplacePeriod(item.start, periodFrom, periodTo)) return false
      if (!meetingMatchesTile(item, tileFilter, now)) return false
      if (barStatus === 'past' && !meetingMatchesTile(item, 'done', now)) return false
      if (barStatus === 'today' && !meetingMatchesTile(item, 'today', now)) return false
      if (barStatus === 'upcoming' && !meetingMatchesTile(item, 'upcoming', now)) return false
      if (q && !`${item.subject} ${item.location} ${item.organizer} ${item.attendees}`.toLowerCase().includes(q)) {
        return false
      }
      return true
    })
  }, [meetings, tileFilter, query, barStatus, periodFrom, periodTo])

  const selected = visibleMeetings.find((item) => item.id === (selectedId || visibleMeetings[0]?.id))
  const protocolMarks = useProtocolMarks(userId, meetings, view, anchor)

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
      userId={userId}
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
            onSelectMeeting={(m) => setSelectedId(m.id)}
            showDetailsModal={false}
            protocolMarks={protocolMarks}
          />
        </div>
        ),
        side: selected ? (
          <MeetingDetailCard
            meeting={selected}
            userId={userId}
            actorFio={fio}
            protocol={protocolMarks.get(selected.id)}
          />
        ) : (
          <div className="wp-card spec-v04-muted">Выберите совещание</div>
        )
      }}
    />
  )
}
