import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { createPortal } from 'react-dom'
import { Bot, Mic, PenLine, Search } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { toolLabel } from '../../components/agentfeed/labels'
import { useRuns } from '../../store/runs'
import { StandardTabChrome, type ChromeTileSpec } from './TabChromeGrid'
import { DEFAULT_MEETINGS_LAYOUT, STANDARD_TAB_LABELS } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { erpActorFio } from '../../workplace/userContext'
import {
  buildProtocolMessage,
  buildSupplementMessage,
  PROTOCOL_AGENT_TITLE,
  resolveProtocolAgentWorkflowId
} from '../../workplace/meetingProtocolAgent'
import { useMeetingProtocol } from '../../workplace/meetingProtocolStore'
import {
  ensureOutlookMeetings,
  formatMeetingStamp,
  isOutlookFolderOwner,
  meetingFormatHint,
  meetingInstanceKey,
  type MeetingEvent
} from '../../utils/outlookMeetings'
import { addDays, mondayOf, type CalendarView } from '../../utils/calendar'
import {
  countMeetingTiles,
  formatSurnameInitials,
  meetingMatchesTile,
  toggleSimpleTile
} from '../../workplace/tileFilters'
import { MeetingsCalendar, type DayRowSpec } from '../../components/agents/MeetingsCalendar'
import { GridFilterBar } from './gridFilters'
import { MeetingPopover } from './MeetingPopover'
import { MeetingsSidePanel, type MeetingCalendarRow } from './MeetingsSidePanel'
import { MeetingTileBreakdown } from './MeetingTileBreakdown'
import {
  applyMeetingQuickFilters,
  calendarColor,
  calendarPalette,
  EMPTY_MEETING_QUICK_FILTERS,
  meetingCalendarOwners,
  meetingOwnerCounts,
  meetingOwnerName,
  meetingSelfLabel,
  samePersonName,
  type MeetingQuickFilters
} from '../../workplace/meetingCalendars'
import {
  calendarStatusFor,
  useTrackedCalendars,
  useTrackedCalendarsVersion
} from '../../utils/trackedCalendars'
import { usePageSearch } from '../../layout/pageSearchContext'
import { useSpecV04Sources } from '../../workplace/useSpecV04Data'
import { MeetingReportModal } from './MeetingReportModal'
import { MeetingProtocolForm } from './MeetingProtocolForm'
import { MeetingPlannerPanel } from './MeetingPlannerPanel'
import { isMeetingPlannerUser, PLANNER_AGENT_TITLE } from '../../workplace/meetingPlannerAgent'
import { searchOnecProtocols, type OnecProtocolHit } from '../../workplace/meetingProtocolCreate'
import {
  detachProtocolDocument,
  PROTOCOL_CREATED_EVENT,
  rememberProtocolDocument,
  useProtocolMarks,
  type ProtocolMark
} from '../../workplace/meetingProtocolMarks'
import './meetingActions.css'

const AUDIO_EXTENSIONS = ['wav', 'mp3', 'm4a', 'aac', 'ogg', 'opus', 'flac', 'wma', 'amr', 'webm', 'mp4', 'mkv']

/** File browsing the agent does while drafting — not the protocol itself. */
const NOISY_TOOLS = new Set([
  'Read',
  'read',
  'Grep',
  'grep',
  'Glob',
  'glob',
  'LS',
  'ls',
  'Edit',
  'edit',
  'Write',
  'write',
  'Delete',
  'Shell',
  'shell',
  'SemanticSearch',
  'semSearch'
])

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
  const { record, runEntry, rememberStart, patchRecord, forgetRecord } = useMeetingProtocol(meeting, userId)
  const [resolvedProtocolRef, setResolvedProtocolRef] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [reportOpen, setReportOpen] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [formMode, setFormMode] = useState<'create' | 'edit'>('create')
  const [chooserOpen, setChooserOpen] = useState(false)
  const [attachOpen, setAttachOpen] = useState(false)

  const attendees = (meeting.attendees || '')
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)

  const state = runEntry?.state
  const agentLiveOnThisMeeting =
    Boolean(runEntry) &&
    (Boolean(state?.running) || Boolean(state?.pendingHitl) || Boolean(state?.pendingQuestion))
  const isRunning = agentLiveOnThisMeeting

  const toolSteps = useMemo(() => {
    const items = (state?.items || []).filter(
      (item): item is Extract<typeof item, { kind: 'tool' }> => item.kind === 'tool'
    )
    const kept = items.filter((item) => !NOISY_TOOLS.has(item.tool) || item.error)
    const folded: { id: string; label: string; done: boolean; error: boolean; count: number }[] = []
    for (const item of kept) {
      const label = toolLabel(item.tool) || item.title || item.tool
      const last = folded[folded.length - 1]
      if (last && last.label === label && last.error === item.error) {
        last.count += 1
        last.done = last.done && item.done
        last.id = item.id
        continue
      }
      folded.push({ id: item.id, label, done: item.done, error: item.error, count: 1 })
    }
    return folded.slice(-8)
  }, [state?.items])

  const createdProtocol = useMemo(() => {
    const items = state?.items || []
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index]
      if (item.kind !== 'tool' || item.tool !== 'onec.meeting_protocol_write' || !item.done || item.error) {
        continue
      }
      const result = item.result || {}
      const number = String(result.number || '').trim()
      const refKey = String(result.ref_key || result.erp_document_id || '').trim()
      if (number || refKey) return { number, refKey }
    }
    return null
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
        backendRunId: '',
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

  const hasDocx = Boolean(record?.reportFileId) && (record?.status === 'done' || Boolean(protocol?.number))
  const protocolRefKey = (resolvedProtocolRef || protocol?.refKey || '').trim()
  const hasProtocol = Boolean(protocolRefKey || protocol?.number)
  const canOpenReport = hasDocx || Boolean(protocolRefKey)

  const supplementWithAudio = useCallback(async () => {
    if (busy || isRunning || !protocolRefKey) return
    setActionError('')
    setBusy(true)
    try {
      const paths = await window.api.openFile({
        title: 'Выберите аудиозапись для дополнения протокола',
        filters: [{ name: 'Аудио', extensions: AUDIO_EXTENSIONS }],
        properties: ['openFile']
      })
      const audioPath = paths?.[0]
      if (!audioPath) return

      const res = await api.invokeServerTool('onec.meeting_protocols', { ref_key: protocolRefKey }, 60_000)
      const card = (res.ok && res.result && typeof res.result === 'object'
        ? (res.result as { protocol?: Record<string, unknown> }).protocol
        : undefined) as
        | { number?: string; editable?: boolean; status?: string; form?: Record<string, unknown> }
        | undefined
      if (!card?.form) {
        throw new Error(res.error || 'Не удалось прочитать протокол из 1С')
      }
      if (card.editable === false) {
        throw new Error(
          `Протокол ${card.number || ''} уже проведён (статус «${card.status || 'проведён'}») — дополнить можно только черновик`
        )
      }

      const workflowId = await resolveProtocolAgentWorkflowId()
      const message = buildSupplementMessage(meeting, audioPath, {
        number: String(card.number || protocol?.number || ''),
        refKey: protocolRefKey,
        form: card.form
      })
      const runId = runs.startRun({
        workflowId,
        title: PROTOCOL_AGENT_TITLE,
        message,
        filePaths: [audioPath]
      })
      rememberStart({
        workflowId,
        runId: runId || '',
        backendRunId: '',
        status: 'running',
        audioPath,
        audioName: basename(audioPath),
        startedAt: new Date().toISOString(),
        reportFileId: '',
        reportName: '',
        reportUrl: ''
      })
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Не удалось запустить дополнение протокола')
    } finally {
      setBusy(false)
    }
  }, [busy, isRunning, meeting, protocol?.number, protocolRefKey, rememberStart, runs])

  const detachProtocol = (): void => {
    if (isRunning) return
    const label = protocol?.number ? `Протокол ${protocol.number}` : 'Протокол'
    const ok = window.confirm(
      `${label} будет отвязан от этого совещания во вкладке «Совещания».\nДокумент в 1С не удаляется.`
    )
    if (!ok) return
    detachProtocolDocument(userId, meeting, protocolRefKey)
    forgetRecord()
    setResolvedProtocolRef('')
    setReportOpen(false)
    setFormOpen(false)
    setActionError('')
  }

  useEffect(() => {
    setResolvedProtocolRef('')
  }, [meeting.id, meeting.start, protocol?.refKey, protocol?.number])

  useEffect(() => {
    const number = (protocol?.number || '').trim()
    if ((protocol?.refKey || '').trim() || !number) return
    let cancelled = false
    void api
      .invokeServerTool(
        'onec.meeting_protocols',
        {
          meeting_kind: 'any',
          number,
          review_only: false,
          include_closed: true,
          max_results: 5
        },
        60_000
      )
      .then((res) => {
        if (cancelled || !res.ok || !res.result || typeof res.result !== 'object') return
        const rows = (res.result as { protocols?: { ref_key?: string }[] }).protocols
        const hit = Array.isArray(rows)
          ? rows.find((row) => String(row?.ref_key || '').trim())
          : undefined
        const ref = String(hit?.ref_key || '').trim()
        if (ref) setResolvedProtocolRef(ref)
      })
    return () => {
      cancelled = true
    }
  }, [protocol?.number, protocol?.refKey])

  useEffect(() => {
    if (!hasProtocol || agentLiveOnThisMeeting || record?.status !== 'running') return
    patchRecord({ status: 'done' })
  }, [hasProtocol, agentLiveOnThisMeeting, record?.status, patchRecord])

  // Agent finished or wrote the protocol: remember the document and refresh calendar marks.
  const recordStatus = record?.status
  useEffect(() => {
    if (createdProtocol) {
      rememberProtocolDocument(userId, meeting, createdProtocol)
    }
    if (recordStatus === 'done' || createdProtocol) {
      window.dispatchEvent(new CustomEvent(PROTOCOL_CREATED_EVENT))
    }
  }, [recordStatus, createdProtocol, userId, meeting.id])

  const openForm = (mode: 'create' | 'edit'): void => {
    setChooserOpen(false)
    setFormMode(mode)
    setFormOpen(true)
  }

  const attachFromOnec = (hit: OnecProtocolHit): void => {
    setAttachOpen(false)
    setResolvedProtocolRef(hit.refKey)
    rememberProtocolDocument(userId, meeting, { number: hit.number, refKey: hit.refKey, manual: true })
    openForm('edit')
  }

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
              {isRunning
                ? state?.status || 'В работе…'
                : protocol?.number
                  ? `Протокол в 1С: ${protocol.number}`
                  : createdProtocol?.number
                    ? `Протокол создан: ${createdProtocol.number}`
                    : record.status === 'done'
                      ? 'Готово'
                      : record.status === 'error'
                        ? 'Ошибка'
                        : hasProtocol
                          ? 'Готово'
                          : 'В работе…'}
            </span>
          </div>
          {toolSteps.length ? (
            <ul className="meeting-protocol-steps">
              {toolSteps.map((step) => (
                <li key={step.id} className={step.error ? 'is-error' : step.done ? 'is-done' : ''}>
                  {step.label}
                  {step.count > 1 ? ` ×${step.count}` : ''}
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

      {isRunning && !hasProtocol ? null : (
        <footer className="spec-detail-actions meeting-protocol-actions">
          {hasProtocol ? (
            <button
              type="button"
              className="cal-btn"
              onClick={() => openForm('edit')}
              disabled={!protocolRefKey}
              title={
                protocolRefKey
                  ? 'Показать и изменить то, что заполнено в 1С'
                  : 'Подтягиваем ссылку на документ 1С…'
              }
            >
              Изменить протокол
            </button>
          ) : (
            <button
              type="button"
              className="cal-btn primary"
              onClick={() => setChooserOpen(true)}
              disabled={busy}
            >
              {busy ? 'Запуск…' : 'Создать протокол'}
            </button>
          )}
          {hasProtocol ? null : (
            <button
              type="button"
              className="cal-btn"
              onClick={() => setAttachOpen(true)}
              disabled={busy}
              title="Найти готовый протокол в 1С по номеру и привязать к совещанию"
            >
              Подгрузить из 1С
            </button>
          )}
          {hasProtocol || hasDocx ? (
            <button
              type="button"
              className="cal-btn primary"
              onClick={() => setReportOpen(true)}
              disabled={!canOpenReport}
            >
              Получить протокол
            </button>
          ) : null}
          {hasProtocol ? (
            <button
              type="button"
              className="cal-btn"
              onClick={() => void supplementWithAudio()}
              disabled={busy || isRunning || !protocolRefKey}
              title="Агент дополнит и исправит задачи, решения и другие данные протокола по новой записи"
            >
              {busy ? 'Запуск…' : 'Дополнить аудиозаписью'}
            </button>
          ) : null}
          {hasProtocol || hasDocx ? (
            <button
              type="button"
              className="cal-btn"
              onClick={detachProtocol}
              disabled={busy || isRunning}
              title="Отвязать протокол от этого совещания; документ в 1С не удаляется"
            >
              Удалить протокол
            </button>
          ) : null}
        </footer>
      )}
      {protocol?.number ? (
        <p className="meeting-protocol-hint">Протокол в 1С: {protocol.number}</p>
      ) : null}

      <ProtocolCreateChooser
        open={chooserOpen}
        busy={busy}
        onClose={() => setChooserOpen(false)}
        onAudio={() => {
          setChooserOpen(false)
          void attachAudio()
        }}
        onManual={() => openForm('create')}
      />

      <ProtocolAttachDialog open={attachOpen} onClose={() => setAttachOpen(false)} onPick={attachFromOnec} />

      <MeetingProtocolForm
        open={formOpen}
        meeting={meeting}
        actorFio={actorFio}
        mode={formMode}
        refKey={protocolRefKey}
        onClose={() => setFormOpen(false)}
        onCreated={(result) => {
          rememberProtocolDocument(userId, meeting, {
            number: result.number || protocol?.number || '',
            refKey: result.refKey || protocolRefKey
          })
        }}
      />

      <MeetingReportModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        reportUrl={protocolRefKey ? '' : hasDocx ? record?.reportUrl || '' : ''}
        reportName={record?.reportName || 'protocol.docx'}
        protocolRefKey={protocolRefKey}
      />
    </div>
  )
}

function ProtocolAttachDialog({
  open,
  onClose,
  onPick
}: {
  open: boolean
  onClose: () => void
  onPick: (hit: OnecProtocolHit) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [hits, setHits] = useState<OnecProtocolHit[] | null>(null)

  useEffect(() => {
    if (!open) return
    setError('')
    setHits(null)
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const search = async (): Promise<void> => {
    if (searching) return
    setSearching(true)
    setError('')
    try {
      const res = await searchOnecProtocols(query)
      if (!res.ok) {
        setError(res.error)
        setHits(null)
        return
      }
      setHits(res.hits)
    } finally {
      setSearching(false)
    }
  }

  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card meeting-protocol-attach"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <h4 className="modal-title" id={titleId}>
          Подгрузить протокол из 1С
        </h4>
        <p className="spec-v04-muted">
          Найдите протокол по номеру — он привяжется к совещанию и откроется для изменения.
        </p>
        <form
          className="meeting-protocol-attach-search"
          onSubmit={(event) => {
            event.preventDefault()
            void search()
          }}
        >
          <input
            className="onec-reconnect-input"
            type="search"
            autoFocus
            value={query}
            placeholder="Номер, например ДР__143_О_004 или 143_О_004"
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={searching || query.trim().length < 3}>
            <Search size={14} aria-hidden /> {searching ? 'Ищем…' : 'Найти'}
          </button>
        </form>
        {error ? <p className="meeting-protocol-error">{error}</p> : null}
        {hits && !hits.length ? (
          <p className="spec-v04-muted">Протоколы с таким номером не найдены или у вас нет к ним доступа.</p>
        ) : null}
        {hits?.length ? (
          <ul className="meeting-protocol-attach-list">
            {hits.map((hit) => (
              <li key={hit.refKey}>
                <button type="button" className="meeting-protocol-attach-item" onClick={() => onPick(hit)}>
                  <span className="meeting-protocol-attach-number">{hit.number}</span>
                  <span className="meeting-protocol-attach-meta">
                    {[hit.date ? hit.date.split('-').reverse().join('.') : '', hit.status || (hit.posted ? 'Проведён' : '')]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {hit.topic ? <span className="meeting-protocol-attach-topic">{hit.topic}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="btn-light" onClick={onClose}>
            Отмена
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

function ProtocolCreateChooser({
  open,
  busy,
  onClose,
  onAudio,
  onManual
}: {
  open: boolean
  busy: boolean
  onClose: () => void
  onAudio: () => void
  onManual: () => void
}): React.JSX.Element | null {
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card meeting-protocol-chooser"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <h4 className="modal-title" id={titleId}>
          Создать протокол
        </h4>
        <p className="spec-v04-muted">Как заполнить протокол совещания?</p>
        <div className="meeting-protocol-chooser-options">
          <button type="button" className="meeting-protocol-chooser-option" onClick={onAudio} disabled={busy}>
            <Mic size={20} aria-hidden />
            <span className="meeting-protocol-chooser-option-title">Прикрепить аудио</span>
            <span className="meeting-protocol-chooser-option-sub">
              Агент расшифрует запись, составит протокол и создаст черновик в 1С
            </span>
          </button>
          <button type="button" className="meeting-protocol-chooser-option" onClick={onManual} disabled={busy}>
            <PenLine size={20} aria-hidden />
            <span className="meeting-protocol-chooser-option-title">Вручную</span>
            <span className="meeting-protocol-chooser-option-sub">Заполнить форму протокола 1С самостоятельно</span>
          </button>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-light" onClick={onClose}>
            Отмена
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

export function MeetingsGridTab({ user }: { user: UserProfile }): React.JSX.Element {
  const fio = erpActorFio(user)
  const userId = user.id || ''
  const sharedMeetings = useSpecV04Sources(user).meetings
  const [meetings, setMeetings] = useState<MeetingEvent[]>(sharedMeetings)
  const [loading, setLoading] = useState(sharedMeetings.length === 0)
  const [error, setError] = useState('')
  const [view, setView] = useState<CalendarView>('week')
  const [anchor, setAnchor] = useState(() => new Date())
  const [tileFilter, setTileFilter] = useState('all')
  /** Открытая карточка совещания: сам ключ и рамка блока, у которого её показать. */
  const [picked, setPicked] = useState<{ key: string; anchor: DOMRect } | null>(null)
  const { query, setQuery } = usePageSearch()
  const [barStatus, setBarStatus] = useState('')
  const trackedVersion = useTrackedCalendarsVersion()
  const tracked = useTrackedCalendars(fio)
  const [hiddenOwners, setHiddenOwners] = useState<string[]>([])
  const [quick, setQuick] = useState<MeetingQuickFilters>(EMPTY_MEETING_QUICK_FILTERS)
  const [syncedAt, setSyncedAt] = useState('')
  const [plannerOpen, setPlannerOpen] = useState(false)
  const canPlan = isMeetingPlannerUser(user)
  const runs = useRuns()
  const plannerState = useMemo(
    () => Object.values(runs.entries).find((item) => !item.background && item.title === PLANNER_AGENT_TITLE)?.state,
    [runs.entries]
  )
  const plannerWaiting = Boolean(plannerState?.pendingHitl || plannerState?.pendingQuestion)
  const plannerRunning = Boolean(plannerState?.running) || plannerWaiting

  const owners = useMemo(
    () => meetingCalendarOwners(fio, tracked.people, tracked.order),
    [fio, tracked.people, tracked.order]
  )
  // Не owners[0]: список переупорядочен приоритетом, а свой календарь от него не зависит.
  const selfLabel = useMemo(() => meetingSelfLabel(fio) || fio, [fio])
  const visibleOwners = useMemo(
    () => owners.filter((person) => !hiddenOwners.some((hidden) => samePersonName(hidden, person))),
    [owners, hiddenOwners]
  )
  const ownerIndex = useCallback(
    (person: string) => owners.findIndex((item) => samePersonName(item, person)),
    [owners]
  )

  /** Цвет закреплён за человеком: смена приоритета не должна перекрашивать календарь. */
  const colorIndex = useCallback(
    (person: string) => {
      const slot = tracked.colorSlots.find((item) => samePersonName(item.person, person))
      if (slot) return slot.slot
      if (samePersonName(person, selfLabel)) return 0
      // Календарь добавили до появления слотов — берём позицию в списке отслеживаемых.
      const at = tracked.people.findIndex((item) => samePersonName(item, person))
      return at < 0 ? 0 : at + 1
    },
    [selfLabel, tracked.colorSlots, tracked.people]
  )
  const ownerColor = useCallback(
    (person: string) => calendarColor(colorIndex(person)),
    [colorIndex]
  )

  const load = useCallback((force = false) => {
    setLoading(true)
    void ensureOutlookMeetings(view, anchor, { owner: fio, force })
      .then((cal) => {
        if (cal.ok || cal.meetings.length) {
          setMeetings(cal.meetings || [])
          setError('')
          setSyncedAt(
            new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
          )
          return
        }
        setError(cal.error || 'Outlook недоступен')
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Ошибка календаря')
      })
      .finally(() => setLoading(false))
  }, [anchor, fio, view, trackedVersion])

  useEffect(() => {
    if (!sharedMeetings.length) return
    setMeetings((current) => (current.length ? current : sharedMeetings))
    setLoading(false)
  }, [sharedMeetings])

  useEffect(() => {
    load(false)
  }, [load])

  // Приглашение из календаря «Совещания» доходит до участников через Exchange не мгновенно.
  const refreshAfterPlanning = useCallback(() => {
    window.setTimeout(() => load(true), 5000)
  }, [load])

  /** Что вообще показываем: только календари с включённой галочкой. Плитки считаем от этого же. */
  const ownerScoped = useMemo(
    () =>
      meetings.filter((item) =>
        visibleOwners.some((person) => samePersonName(meetingOwnerName(item, selfLabel), person))
      ),
    [meetings, visibleOwners, selfLabel]
  )

  const visibleMeetings = useMemo(() => {
    const q = query.trim().toLowerCase()
    const now = new Date()
    const scoped = applyMeetingQuickFilters(ownerScoped, quick, {
      selfLabel,
      others: visibleOwners
    })
    return scoped.filter((item) => {
      if (!meetingMatchesTile(item, tileFilter, now)) return false
      if (barStatus === 'past' && !meetingMatchesTile(item, 'done', now)) return false
      if (barStatus === 'today' && !meetingMatchesTile(item, 'today', now)) return false
      if (barStatus === 'upcoming' && !meetingMatchesTile(item, 'upcoming', now)) return false
      if (q && !`${item.subject} ${item.location} ${item.organizer} ${item.attendees}`.toLowerCase().includes(q)) {
        return false
      }
      return true
    })
  }, [ownerScoped, quick, selfLabel, visibleOwners, tileFilter, query, barStatus])

  // Совещание могло уйти из выборки после смены фильтров — тогда карточку закрываем.
  const selected = picked
    ? visibleMeetings.find((item) => meetingInstanceKey(item) === picked.key)
    : undefined
  useEffect(() => {
    if (picked && !selected) setPicked(null)
  }, [picked, selected])

  const protocolMarks = useProtocolMarks(userId, meetings, view, anchor)

  const tiles: SpecSummaryTile[] = useMemo(() => {
    const counts = countMeetingTiles(ownerScoped)
    const dash = (n: number): string => (n ? String(n) : '—')
    return [
      {
        id: 'period',
        icon: 'meet-period',
        label: 'Совещания за период',
        value: dash(counts.period),
        tone: 'orange'
      },
      { id: 'today', icon: 'meet-today', label: 'Сегодня', value: dash(counts.today), tone: 'yellow' },
      { id: 'done', icon: 'meet-done', label: 'Прошло', value: dash(counts.done), tone: 'green' },
      { id: 'upcoming', icon: 'meet-next', label: 'Дальше', value: dash(counts.upcoming), tone: 'blue' }
    ]
  }, [ownerScoped])

  const shiftAnchorBy = useCallback(
    (step: number) => {
      setAnchor((current) => {
        if (view === 'month') return new Date(current.getFullYear(), current.getMonth() + step, 1)
        if (view === 'day') return addDays(current, step)
        return addDays(mondayOf(current), step * 7)
      })
    },
    [view]
  )

  const chromeTiles: ChromeTileSpec[] = useMemo(() => {
    const activeId = tileFilter === 'all' ? 'period' : tileFilter
    const select = (id: string): void => {
      setTileFilter((current) => (id === 'period' ? 'all' : toggleSimpleTile(current, id)))
    }
    return tiles.map((tile) => ({
      id: tile.id,
      label: tile.label,
      node: (
        <MeetingTileBreakdown
          tile={tile}
          active={activeId === tile.id}
          rows={
            visibleOwners.length > 1
              ? meetingOwnerCounts(ownerScoped, tile.id, visibleOwners, selfLabel).map((row) => ({
                  ...row,
                  color: ownerColor(row.person)
                }))
              : []
          }
          onSelect={select}
        />
      )
    }))
  }, [tiles, tileFilter, ownerScoped, visibleOwners, selfLabel, ownerColor])

  // Сетка пересчитывает раскладку и пересечения, когда меняется любая из этих функций,
  // поэтому держим их стабильными.
  const eventPalette = useCallback(
    (meeting: MeetingEvent) => calendarPalette(colorIndex(meetingOwnerName(meeting, selfLabel))),
    [colorIndex, selfLabel]
  )
  const rowKeyOf = useCallback(
    (meeting: MeetingEvent) => {
      const owner = meetingOwnerName(meeting, selfLabel)
      return visibleOwners.find((person) => samePersonName(person, owner)) || ''
    },
    [visibleOwners, selfLabel]
  )
  const priorityOf = useCallback(
    (meeting: MeetingEvent) => {
      const at = ownerIndex(meetingOwnerName(meeting, selfLabel))
      return at < 0 ? owners.length : at
    },
    [ownerIndex, owners.length, selfLabel]
  )

  /** Режим дня: строка на каждый видимый календарь, порядок — как в левой панели. */
  const dayRows: DayRowSpec[] = useMemo(
    () =>
      visibleOwners.map((person) => ({
        key: person,
        label: formatSurnameInitials(person),
        palette: calendarPalette(colorIndex(person))
      })),
    [visibleOwners, colorIndex]
  )

  const calendarRows: MeetingCalendarRow[] = useMemo(
    () =>
      owners.map((person) => {
        const status = calendarStatusFor(person, tracked.statuses)
        return {
          person,
          color: ownerColor(person),
          palette: colorIndex(person),
          visible: !hiddenOwners.some((hidden) => samePersonName(hidden, person)),
          removable: !samePersonName(person, selfLabel),
          hint: status?.hint ? `${person}: ${status.hint}` : person
        }
      }),
    [owners, tracked.statuses, hiddenOwners, ownerColor, colorIndex, selfLabel]
  )

  return (
    <>
    <StandardTabChrome
      tabId="meetings"
      userId={userId}
      defaults={DEFAULT_MEETINGS_LAYOUT}
      labels={{ ...STANDARD_TAB_LABELS, main: 'Календарь' }}
      chromeTiles={chromeTiles}
      // Периодом здесь управляет левая панель, общий KPI-календарь только путал.
      hideGlobalPeriod
      filterToolbarExtra={
        canPlan ? (
          <button
            type="button"
            className="meetings-agent-btn"
            onClick={() => setPlannerOpen(true)}
            title={
              plannerWaiting
                ? 'Агент ждёт вашего решения'
                : 'Планировщик совещаний по служебным запискам'
            }
          >
            {plannerRunning ? (
              <span className={`meetings-agent-btn-dot${plannerWaiting ? ' is-waiting' : ''}`} aria-hidden />
            ) : (
              <Bot size={14} aria-hidden />
            )}
            Запустить ИИ-агента
          </button>
        ) : null
      }
      widgets={{
        filters: (
        <GridFilterBar
          search={{ value: query, onChange: setQuery, placeholder: 'Поиск совещаний…' }}
          selects={[
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
            setHiddenOwners([])
            setQuick(EMPTY_MEETING_QUICK_FILTERS)
          }}
        />
        ),
        rail: (
        <MeetingsSidePanel
          view={view}
          anchor={anchor}
          onView={setView}
          onShift={shiftAnchorBy}
          onToday={() => setAnchor(new Date())}
          onPickDay={(day) => setAnchor(day)}
          calendars={calendarRows}
          onToggleCalendar={(person) =>
            setHiddenOwners((current) =>
              current.some((hidden) => samePersonName(hidden, person))
                ? current.filter((hidden) => !samePersonName(hidden, person))
                : [...current, person]
            )
          }
          onMoveCalendar={(person, step) => {
            const at = ownerIndex(person)
            const to = at + step
            if (at < 0 || to < 0 || to >= owners.length) return
            const next = [...owners]
            next.splice(to, 0, ...next.splice(at, 1))
            tracked.setOrder(next)
          }}
          onPickColor={(person, slot) => tracked.setColor(person, slot)}
          onRemoveCalendar={(person) => {
            setHiddenOwners((current) => current.filter((hidden) => !samePersonName(hidden, person)))
            tracked.remove(person)
          }}
          onAddCalendar={(person) => {
            const opened = owners.find((item) => samePersonName(item, person))
            if (opened) return `Календарь ${formatSurnameInitials(opened)} уже открыт`
            tracked.add(person)
            return ''
          }}
          filters={quick}
          onFilters={setQuick}
          loading={loading}
          syncedAt={syncedAt}
          onRefresh={() => load(true)}
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
            onShift={shiftAnchorBy}
            onToday={() => setAnchor(new Date())}
            onRefresh={() => load(true)}
            selectedId={selected ? meetingInstanceKey(selected) : ''}
            onSelectMeeting={(meeting, rect) =>
              setPicked({ key: meetingInstanceKey(meeting), anchor: rect })
            }
            showDetailsModal={false}
            protocolMarks={protocolMarks}
            hideHeader
            eventPalette={eventPalette}
            dayRows={dayRows}
            rowKeyOf={rowKeyOf}
            priorityOf={priorityOf}
          />
          {selected && picked ? (
            <MeetingPopover key={picked.key} anchor={picked.anchor} onClose={() => setPicked(null)}>
              <MeetingDetailCard
                meeting={selected}
                userId={userId}
                actorFio={fio}
                protocol={protocolMarks.get(meetingInstanceKey(selected))}
              />
            </MeetingPopover>
          ) : null}
        </div>
        )
      }}
    />
    {canPlan ? (
      <MeetingPlannerPanel
        open={plannerOpen}
        onClose={() => setPlannerOpen(false)}
        onMeetingCreated={refreshAfterPlanning}
      />
    ) : null}
    </>
  )
}
