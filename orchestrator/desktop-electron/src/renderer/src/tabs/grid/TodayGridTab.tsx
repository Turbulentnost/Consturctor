import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useReportError } from '../../components/ErrorToast'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { OrchSlotTodayCanvas } from '../../layout/GridSlots'
import { HomeToday } from './HomeToday'
import { TodayWidgetGrid, useTodayWidgetLayout } from './TodayWidgetGrid'
import { TODAY_WIDGET_IDS, type TodayWidgetId } from './useTodayWidgetLayout'
import {
  readTodayTileOrder,
  readTodayTileVisibility,
  TODAY_TILE_VISIBILITY_EVENT,
  type TodayTileId
} from './todayWidgetSettings'
import { TodayOutlookMailPanel } from './TodayOutlookMailPanel'
import { TrackedCalendarsControl } from './TrackedCalendarsControl'
import {
  NewOneCTaskMark,
  SpecAskOrchestratorBlock,
  SpecPanel,
  SpecPill,
  SpecSummaryTileCard
} from '../../workplace/specV04Components'
import { isNewOneCTask } from '../../workplace/onecTaskSnapshot'
import { ASK_CHIPS } from '../../workplace/specV04DemoData'
import { tasksMatchingTasksPage, useTodayKpiData } from '../../workplace/useTodayKpiData'
import { formatProtocolDay, useBoardReportReadiness } from '../../workplace/boardReportReadiness'
import { requestProtocolFocus } from '../../workplace/protocolFocus'
import { useTodayOutlookMail } from '../../workplace/useTodayOutlookMail'
import { comPasswordSessionHint, isOneCAuthFailure } from '../../workplace/onecSessionHints'
import { OneCReconnectDialog, OneCReconnectInline } from '../../workplace/OneCReconnectDialog'
import { erpActorFio } from '../../workplace/userContext'
import { useTodayProjectTasks } from '../../workplace/useTodayProjectTasks'
import { isCanceledMeeting, parseMeetingTime } from '../../utils/outlookMeetings'
import { isIlchenkoAccount } from '../../workplace/boardReportReadiness'
import { isSelfCalendarMeeting, ownMeetingsHidden, useShowOwnMeetings } from '../../workplace/ownMeetings'
import { sameDay } from '../../utils/calendar'
import { useTodayPreparedDecisions } from '../../workplace/useTodayPreparedDecisions'
import {
  formatSurnameInitials,
  isDocflowToMe,
  isTurboTaskAsManager,
  isTurboTaskToMe,
  applyTodayKpiTileClick,
  EMPTY_TODAY_KPI_TILE,
  type TaskSourceFilter
} from '../../workplace/tileFilters'
import {
  DOCFLOW_GROUP_ORDER,
  docflowGroupKey,
  docflowGroupLabel,
  docflowKindActions,
  docflowTaskKind,
  type DocflowGroupKey
} from '../../workplace/docflowTaskKind'
import { runDocflowAction } from '../../workplace/taskSourceActions'
import { taskActionContextFromTaskRow } from '../../workplace/taskSourceKind'
import type { DocflowUiAction } from '../../workplace/taskSourceActions'
import type { SpecTaskRow } from '../../workplace/specV04DemoData'
import { acceptPlatformTask, completePlatformTask } from './PlatformTaskDetail'
import { TodayFiltersBar, TodayPlanPanel } from './todayTzComponents'
import { requestMeetingsDay } from '../../workplace/meetingsFocus'
import { TodayIlchenkoAlertTile } from './TodayIlchenkoAlertTile'
import { TodayTaskDetailModal, type TodayTaskDetailRow } from './TodayTaskDetailModal'
import { TodayResultsPanel } from './TodayResultsPanel'
import { useGridDataRefreshContext } from '../../workplace/GridDataRefreshContext'
import {
  isPlatformTaskMine,
  needsPlatformReview
} from '../../workplace/platformTasks'
import './platformTasks.css'

function TodayWidgetChoice({
  options
}: {
  options: { id: string; label: string; active: boolean; onClick: () => void }[]
}): React.JSX.Element {
  return (
    <div className="today-widget-choice" role="group">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          className={option.active ? 'is-active' : ''}
          aria-pressed={option.active}
          onClick={option.onClick}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function TodayCellText({ text }: { text: string }): React.JSX.Element {
  return (
    <span className="today-cell-text" title={text}>
      {text}
    </span>
  )
}

function TodayTaskTitle({
  text,
  isNew,
  platform = false
}: {
  text: string
  isNew: boolean
  platform?: boolean
}): React.JSX.Element {
  if (!isNew && !platform) return <TodayCellText text={text} />
  return (
    <span className="today-cell-with-mark">
      {platform ? <span className="today-ptask-badge">Платформа</span> : null}
      <TodayCellText text={text} />
      {isNew ? <NewOneCTaskMark /> : null}
    </span>
  )
}

function TodayWindow({
  children,
  searchId
}: {
  children: React.ReactNode
  searchId?: string
}): React.JSX.Element {
  return (
    <div className="today-grid-window" data-search-id={searchId}>
      {children}
    </div>
  )
}

/** Цветовая маркировка строк — как в «Реестре поручений». */
type TodayRowTone = 'done' | 'overdue' | 'due_soon' | 'neutral'

/** Дедлайн из мини-таблиц: `16.09` или `16.09.2026`. */
function parseMiniDeadline(raw: string): Date | null {
  const text = (raw || '').trim()
  const match = /^(\d{2})\.(\d{2})(?:\.(\d{4}))?$/.exec(text)
  if (!match) return null
  const year = match[3] ? Number(match[3]) : new Date().getFullYear()
  return new Date(year, Number(match[2]) - 1, Number(match[1]))
}

function todayRowTone(status: string, deadline: string, urgent?: boolean): TodayRowTone {
  if (/выполнен/i.test(status)) return 'done'
  if (urgent || /просрочен/i.test(status)) return 'overdue'
  const due = parseMiniDeadline(deadline)
  if (due) {
    const now = new Date()
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    if (due < start) return 'overdue'
    const end = new Date(start)
    end.setDate(end.getDate() + 3)
    if (due <= end) return 'due_soon'
  }
  return 'neutral'
}

/** Раздел задачи в виджете: вид из Документооборота, остальное — «Прочие». */
function todayGroupKey(row: SpecTaskRow): DocflowGroupKey {
  const kind =
    row.sourceKind === 'docflow' ? row.docflowKind ?? docflowTaskKind(row.step, row.taskName) : null
  return docflowGroupKey(kind)
}

function MiniTableCard({
  title,
  columns,
  rows,
  rowTones,
  rowClassNames,
  rowGroups,
  closedGroups,
  onRowClick,
  loading,
  error,
  emptyText,
  emptyExtra,
  headerAction,
  tableClassName
}: {
  title: string
  columns: string[]
  rows: React.ReactNode[][]
  /** Тона строк (по индексам rows): done | overdue | due_soon | neutral. */
  rowTones?: TodayRowTone[]
  /** Дополнительные классы строк (по индексам rows). */
  rowClassNames?: (string | undefined)[]
  /** Название раздела для каждой строки; строки должны идти разделами подряд. */
  rowGroups?: string[]
  /** Разделы, свёрнутые при открытии. */
  closedGroups?: string[]
  /** Клик по строке: открыть карточку записи. */
  onRowClick?: (index: number) => void
  loading?: boolean
  /** Shown above the table (KPI/banner), never as a fake data row. */
  error?: string
  emptyText?: string
  emptyExtra?: React.ReactNode
  headerAction?: React.ReactNode
  tableClassName?: string
}): React.JSX.Element {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set(closedGroups || []))
  useReportError(error)
  const groups = useMemo(() => {
    if (!rowGroups) return []
    const out: { label: string; indexes: number[] }[] = []
    rows.forEach((_, index) => {
      const label = rowGroups[index] || ''
      const last = out[out.length - 1]
      if (last && last.label === label) last.indexes.push(index)
      else out.push({ label, indexes: [index] })
    })
    return out
  }, [rows, rowGroups])

  const renderRow = (cells: React.ReactNode[], index: number): React.JSX.Element => {
    const tone = rowTones?.[index]
    const className = [
      tone && tone !== 'neutral' ? `today-tr-tone-${tone}` : '',
      rowClassNames?.[index] || '',
      onRowClick ? 'today-tr-clickable' : ''
    ]
      .filter(Boolean)
      .join(' ')
    return (
      <tr
        key={index}
        className={className || undefined}
        tabIndex={onRowClick ? 0 : undefined}
        onClick={onRowClick ? () => onRowClick(index) : undefined}
        onKeyDown={
          onRowClick
            ? (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onRowClick(index)
                }
              }
            : undefined
        }
      >
        {cells.map((cell, cellIndex) => (
          <td key={cellIndex}>{cell}</td>
        ))}
      </tr>
    )
  }

  const toggleGroup = (label: string): void => {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  const body = ((): React.ReactNode => {
    if (loading && !rows.length) {
      return (
        <tr>
          <td colSpan={columns.length} className="today-table-status">
            Загружаем…
          </td>
        </tr>
      )
    }
    if (!rows.length) {
      return (
        <tr>
          <td colSpan={columns.length} className="today-table-status">
            {emptyExtra || emptyText || 'Нет данных'}
          </td>
        </tr>
      )
    }
    if (!groups.length) return rows.map(renderRow)
    return groups.map((group) => {
      const open = !collapsed.has(group.label)
      return (
        <Fragment key={group.label}>
          <tr className="today-group-row" onClick={() => toggleGroup(group.label)}>
            <td colSpan={columns.length}>
              <button type="button" className="today-group-toggle" aria-expanded={open}>
                {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
                {group.label}
                <em>{group.indexes.length}</em>
              </button>
            </td>
          </tr>
          {open ? group.indexes.map((index) => renderRow(rows[index], index)) : null}
        </Fragment>
      )
    })
  })()

  return (
    <SpecPanel
      title={title}
      extra={headerAction ? <div className="today-mini-card-actions">{headerAction}</div> : undefined}
    >
      <div className="spec-v04-table-wrap today-table-scroll">
        <table className={['today-mini-table', tableClassName].filter(Boolean).join(' ')}>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </SpecPanel>
  )
}

function todayTaskActions(row: TodayTaskDetailRow | null): { id: string; label: string }[] {
  if (!row || /выполн|закры|заверш/i.test(row.status)) return []
  if (row.platform) {
    if (needsPlatformReview(row.platform)) return [{ id: 'accept', label: 'Принять' }]
    if (isPlatformTaskMine(row.platform) && row.platform.status === 'open') {
      return [{ id: 'done', label: 'Исполнено' }]
    }
    return []
  }
  const docflow = row.sourceKind === 'docflow' || /документооборот|1с\s*до/i.test(row.source || '')
  if (!docflow || !isDocflowToMe(row)) return []
  const kind = row.docflowKind ?? docflowTaskKind(row.step, row.taskName)
  return docflowKindActions(kind).map((action) => ({ id: action.id, label: action.shortLabel }))
}

async function runTodayTaskAction(
  user: UserProfile,
  row: TodayTaskDetailRow,
  actionId: string,
  hooks: {
    setBusy: (value: boolean) => void
    setNote: (value: string) => void
    onDone: (mode?: 'local') => void
  }
): Promise<void> {
  const spec = docflowKindActions(row.docflowKind ?? docflowTaskKind(row.step, row.taskName)).find(
    (item) => item.id === actionId
  )
  let comment = ''
  let due = ''
  if (spec?.needsComment) {
    comment = window.prompt('Комментарий для 1С:Документооборот', '')?.trim() || ''
    if (!comment) return
  }
  if (spec?.needsDue) {
    due = window.prompt('Новый срок (ДД.ММ.ГГГГ)', '')?.trim() || ''
    if (!due) return
  }
  hooks.setBusy(true)
  hooks.setNote('')
  try {
    if (row.platform && (actionId === 'accept' || actionId === 'done')) {
      const message =
        actionId === 'accept'
          ? await acceptPlatformTask(row.platform)
          : await completePlatformTask(row.platform)
      hooks.setNote(message)
      hooks.onDone()
      return
    }
    const result = await runDocflowAction(
      user,
      taskActionContextFromTaskRow(row as SpecTaskRow),
      actionId as DocflowUiAction,
      comment,
      due
    )
    hooks.setNote(result.message)
    if (result.closed) hooks.onDone('local')
  } catch (err) {
    hooks.setNote(err instanceof Error ? err.message : 'Документооборот не принял действие')
  } finally {
    hooks.setBusy(false)
  }
}

function startOfToday(): Date {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

export function TodayGridTab({
  user,
  onOpenDecisions,
  onOpenMeetings,
  onOpenDocflow,
  onOpenRun,
  onAskOrchestrator
}: {
  user: UserProfile
  onOpenDecisions: () => void
  /** Кнопка «Открыть план»: переход во вкладку совещаний на выбранный день. */
  onOpenMeetings?: (day: Date) => void
  /** Плитка «Совет директоров»: журнал протоколов и карточка, по которой считалась готовность. */
  onOpenDocflow?: () => void
  onOpenMetrics: () => void
  onOpenPassport: (workflowId: string, title: string, tab?: 'info' | 'files' | 'results') => void
  onRun: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  onAskOrchestrator: (message: string, appContext: string) => void
}): React.JSX.Element {
  const { forceRefresh } = useGridDataRefreshContext()
  const [periodDay, setPeriodDay] = useState(startOfToday)
  const { data, tiles: allTiles } = useTodayKpiData(user, periodDay)
  const board = useBoardReportReadiness(user)
  const [tileVisibility, setTileVisibility] = useState(() => readTodayTileVisibility(user.id || ''))
  const [tileOrder, setTileOrder] = useState(() => readTodayTileOrder(user.id || ''))
  useEffect(() => {
    const sync = (): void => {
      setTileVisibility(readTodayTileVisibility(user.id || ''))
      setTileOrder(readTodayTileOrder(user.id || ''))
    }
    sync()
    window.addEventListener(TODAY_TILE_VISIBILITY_EVENT, sync)
    return () => window.removeEventListener(TODAY_TILE_VISIBILITY_EVENT, sync)
  }, [user.id])
  const tiles = useMemo(() => {
    const visible = allTiles.filter((tile) => tileVisibility[tile.id as TodayTileId] !== false)
    if (!board.enabled) return visible
    const hint = board.loading
      ? 'считаем…'
      : board.readiness.total
        ? `${board.readiness.done} из ${board.readiness.total}`
        : 'нет задач'
    const protocol = board.readiness.protocolNumber
      ? `${board.readiness.protocolNumber}${
          board.readiness.protocolDate ? ` от ${formatProtocolDay(board.readiness.protocolDate)}` : ''
        }`
      : 'протокол совета директоров по ГК'
    return [
      ...visible,
      {
        id: 'sd-board',
        label: 'Совет директоров',
        value: board.loading ? '' : board.readiness.total ? `${board.readiness.percent}%` : '—',
        loading: board.loading,
        hint,
        tooltip: `Задачи на контроле: отчётность за 2 рабочих дня до совета директоров по ГК. ${protocol}. Выполнено ${board.readiness.done} из ${board.readiness.total}.`,
        tone: 'blue' as const,
        progress: board.loading || !board.readiness.total ? undefined : board.readiness.percent,
        ring: false
      }
    ]
  }, [allTiles, tileVisibility, board])
  const tileStrip = useMemo(() => {
    const byId = new Map(tiles.filter((tile) => tile.id !== 'sd-board').map((tile) => [tile.id, tile]))
    const boardTile = tiles.find((tile) => tile.id === 'sd-board')
    const showAssignments = isIlchenkoAccount(user) && tileVisibility.assignments !== false
    const ordered: Array<'assignments' | (typeof tiles)[number]> = []
    for (const id of tileOrder) {
      if (id === 'assignments') {
        if (showAssignments) ordered.push('assignments')
        continue
      }
      if (tileVisibility[id] === false) continue
      const tile = byId.get(id)
      if (tile) ordered.push(tile)
    }
    if (boardTile) ordered.push(boardTile)
    return ordered
  }, [tileOrder, tileVisibility, tiles, user])
  const [onecDialogOpen, setOnecDialogOpen] = useState(false)
  const [taskDetail, setTaskDetail] = useState<TodayTaskDetailRow | null>(null)
  const [closedTaskIds, setClosedTaskIds] = useState<Set<string>>(() => new Set())
  const [taskActionBusy, setTaskActionBusy] = useState(false)
  const [taskActionNote, setTaskActionNote] = useState('')
  const [kpiTiles, setKpiTiles] = useState(EMPTY_TODAY_KPI_TILE)
  useEffect(() => {
    if (kpiTiles.activeIds.some((id) => tileVisibility[id as TodayTileId] === false)) {
      setKpiTiles(EMPTY_TODAY_KPI_TILE)
    }
  }, [kpiTiles.activeIds, tileVisibility])
  const onecFromMe = kpiTiles.onecFromMe
  const outlookFromMe = kpiTiles.outlookFromMe
  const projectAsManager = kpiTiles.projectAsManager
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const erpFio = erpActorFio(user)
  const [showOwnToday, setShowOwnToday] = useShowOwnMeetings(erpFio)
  const hideOwnToday = ownMeetingsHidden(user, showOwnToday)
  const outlookMail = useTodayOutlookMail(periodDay)
  const preparedDecisions = useTodayPreparedDecisions(periodDay, user.id)
  const projectTasks = useTodayProjectTasks(periodDay, data)

  const projectRows = useMemo(() => {
    return projectTasks.rows.filter((row) =>
      projectAsManager ? isTurboTaskAsManager(row) : isTurboTaskToMe(row)
    )
  }, [projectAsManager, projectTasks.rows])
  const taskRows = useMemo(() => {
    const source: TaskSourceFilter = onecFromMe
      ? 'onec-from-me'
      : kpiTiles.activeIds.includes('onec')
        ? 'onec'
        : 'all'
    const rows = tasksMatchingTasksPage(data, periodDay, source).filter(
      (row) => !closedTaskIds.has(row.id)
    )
    return DOCFLOW_GROUP_ORDER.flatMap((key) => rows.filter((row) => todayGroupKey(row) === key))
  }, [data, periodDay, onecFromMe, kpiTiles.activeIds, closedTaskIds])
  const taskGroupLabels = useMemo(
    () => taskRows.map((row) => docflowGroupLabel(todayGroupKey(row))),
    [taskRows]
  )
  const meetingRows = useMemo(() => {
    return data.meetings
      .filter((meeting) => {
        if (isCanceledMeeting(meeting)) return false
        if (hideOwnToday && isSelfCalendarMeeting(meeting, erpFio)) return false
        const start = parseMeetingTime(meeting.start)
        return start ? sameDay(start, periodDay) : false
      })
      .sort((left, right) => left.start.localeCompare(right.start))
      .map((meeting) => {
        const start = parseMeetingTime(meeting.start)
        const time =
          start != null
            ? `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`
            : meeting.start
        const attendees = (meeting.attendees || '').split(/[,;]/).map((part) => part.trim()).filter(Boolean)
        return {
          time,
          title: meeting.subject,
          format: meeting.location?.trim() || '—',
          participants: attendees.length ? `${attendees.length} чел.` : '—'
        }
      })
  }, [data.meetings, periodDay, hideOwnToday, erpFio])

  const ask = (message: string): void => {
    onAskOrchestrator(message, 'Вкладка «Сегодня»')
  }


  const onKpiTileSelect = (id: string): void => {
    if (id === 'sd-board') {
      const protocolId = board.readiness.protocolId.trim()
      if (!protocolId) return
      requestProtocolFocus({
        id: protocolId,
        date: board.readiness.protocolDate,
        number: board.readiness.protocolNumber
      })
      onOpenDocflow?.()
      return
    }
    setKpiTiles((current) => applyTodayKpiTileClick(current, id))
  }

  const showOneCReconnect =
    !data.erpLoading && !taskRows.length && data.oneCAuthFailure
  const onecReconnectBlock = showOneCReconnect ? (
    <OneCReconnectInline
      errorHint={data.erpError || data.error}
      onOpen={() => setOnecDialogOpen(true)}
    />
  ) : undefined

  useEffect(() => {
    if (data.comPasswordInSession) {
      setOnecDialogOpen(false)
      return
    }
    if (data.erpLoading || !showOneCReconnect) return
    setOnecDialogOpen(true)
  }, [data.erpLoading, showOneCReconnect, data.comPasswordInSession])


  const homeTiles = tileStrip.filter((item): item is Exclude<typeof item, 'assignments'> => item !== 'assignments')

  return (
    <>
      <OrchSlotTodayCanvas>
        <HomeToday
          user={user}
          periodDay={periodDay}
          onPeriodDayChange={setPeriodDay}
          tiles={homeTiles}
          activeTileIds={kpiTiles.activeIds}
          onTile={onKpiTileSelect}
          mailRows={outlookMail.rows}
          mailLoading={outlookMail.loading}
          mailError={outlookMail.error}
          tasks={taskRows}
          tasksLoading={data.erpLoading}
          tasksError={data.erpError || data.error || ''}
          projects={projectRows}
          decisions={preparedDecisions.items}
          decisionsLoading={preparedDecisions.loading}
          onOpenMeetings={() => {
            requestMeetingsDay(periodDay)
            onOpenMeetings?.(periodDay)
          }}
          onOpenDecisions={onOpenDecisions}
          onOpenMail={() => window.dispatchEvent(new CustomEvent('orchestrator:open-tab', { detail: { key: 'mail' } }))}
          onOpenTask={(row) => {
            const full = taskRows.find((item) => item.id === row.id) || projectRows.find((item) => item.id === row.id)
            if (full) setTaskDetail(full)
          }}
          onOpenDecision={(row) => {
            if (row.workflowId && row.runId) onOpenRun(row.workflowId, row.agentName, row.runId)
            else if (row.workflowId) onOpenRun(row.workflowId, row.agentName)
            else onOpenDecisions()
          }}
          assignments={tileStrip.includes('assignments') ? <TodayIlchenkoAlertTile user={user} /> : null}
        />
      </OrchSlotTodayCanvas>
      <OneCReconnectDialog
        open={onecDialogOpen}
        onClose={() => setOnecDialogOpen(false)}
        user={user}
        errorHint={data.erpError || data.error}
      />
      <TodayTaskDetailModal
        row={taskDetail}
        onClose={() => {
          setTaskDetail(null)
          setTaskActionNote('')
        }}
        onAskOrchestrator={onAskOrchestrator}
        actionBusy={taskActionBusy}
        actionNote={taskActionNote}
        actions={todayTaskActions(taskDetail)}
        onAction={(actionId) => {
          if (!taskDetail || taskActionBusy) return
          void runTodayTaskAction(user, taskDetail, actionId, {
            setBusy: setTaskActionBusy,
            setNote: setTaskActionNote,
            onDone: (mode) => {
              const id = taskDetail?.id || ''
              setTaskDetail(null)
              if (mode === 'local' && id) {
                setClosedTaskIds((current) => new Set(current).add(id))
                return
              }
              forceRefresh()
            }
          })
        }}
      />
    </>
  )
}
