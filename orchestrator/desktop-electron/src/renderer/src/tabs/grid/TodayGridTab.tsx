import { useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { OrchSlotFilters, OrchSlotMetrics, OrchSlotTodayCanvas } from '../../layout/GridSlots'
import { TodayWidgetGrid, useTodayWidgetLayout } from './TodayWidgetGrid'
import { TODAY_WIDGET_IDS, type TodayWidgetId } from './useTodayWidgetLayout'
import { TodayOutlookMailPanel } from './TodayOutlookMailPanel'
import { SpecAskOrchestratorBlock, SpecPanel, SpecPill, SpecSummaryTiles } from '../../workplace/specV04Components'
import { ASK_CHIPS } from '../../workplace/specV04DemoData'
import { useTodayKpiData } from '../../workplace/useTodayKpiData'
import { useTodayOutlookMail } from '../../workplace/useTodayOutlookMail'
import { comPasswordSessionHint, isOneCAuthFailure } from '../../workplace/onecSessionHints'
import { OneCReconnectDialog, OneCReconnectInline } from '../../workplace/OneCReconnectDialog'
import { erpActorFio } from '../../workplace/userContext'
import { isOutlookMailFromMe } from '../../workplace/specV04Mappers'
import { useTodayProjectTasks } from '../../workplace/useTodayProjectTasks'
import { parseMeetingTime } from '../../utils/outlookMeetings'
import { sameDay } from '../../utils/calendar'
import { useTodayPreparedDecisions } from '../../workplace/useTodayPreparedDecisions'
import {
  formatSurnameInitials,
  isDocflowFromMe,
  isDocflowToMe,
  isTaskDueOnDay,
  isTurboTaskAsManager,
  isTurboTaskToMe,
  applyTodayKpiTileClick,
  EMPTY_TODAY_KPI_TILE
} from '../../workplace/tileFilters'
import { TodayFiltersBar, TodayPlanPanel } from './todayTzComponents'
import { TodayFullPlanModal } from './TodayFullPlanModal'
import { TodayResultsPanel } from './TodayResultsPanel'
import { useGridDataRefreshContext } from '../../workplace/GridDataRefreshContext'

function TodayCellText({ text }: { text: string }): React.JSX.Element {
  return (
    <span className="today-cell-text" title={text}>
      {text}
    </span>
  )
}

function TodayWindow({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div className="today-grid-window">{children}</div>
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

function MiniTableCard({
  title,
  columns,
  rows,
  rowTones,
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
  loading?: boolean
  /** Shown above the table (KPI/banner), never as a fake data row. */
  error?: string
  emptyText?: string
  emptyExtra?: React.ReactNode
  headerAction?: React.ReactNode
  tableClassName?: string
}): React.JSX.Element {
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
    return rows.map((cells, index) => {
      const tone = rowTones?.[index]
      return (
        <tr key={index} className={tone && tone !== 'neutral' ? `today-tr-tone-${tone}` : undefined}>
          {cells.map((cell, cellIndex) => (
            <td key={cellIndex}>{cell}</td>
          ))}
        </tr>
      )
    })
  })()

  return (
    <SpecPanel
      title={title}
      extra={headerAction ? <div className="today-mini-card-actions">{headerAction}</div> : undefined}
    >
      {error && !loading ? (
        <p className="today-table-status today-table-error today-table-banner">{error}</p>
      ) : null}
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

function startOfToday(): Date {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

export function TodayGridTab({
  user,
  onOpenDecisions,
  onOpenRun,
  onAskOrchestrator
}: {
  user: UserProfile
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpenPassport: (workflowId: string, title: string, tab?: 'info' | 'files' | 'results') => void
  onRun: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  onAskOrchestrator: (message: string, appContext: string) => void
}): React.JSX.Element {
  const { forceRefresh } = useGridDataRefreshContext()
  const [periodDay, setPeriodDay] = useState(startOfToday)
  const { data, tiles } = useTodayKpiData(user, periodDay)
  const [onecDialogOpen, setOnecDialogOpen] = useState(false)
  const [fullPlanOpen, setFullPlanOpen] = useState(false)
  const [kpiTiles, setKpiTiles] = useState(EMPTY_TODAY_KPI_TILE)
  const onecFromMe = kpiTiles.onecFromMe
  const outlookFromMe = kpiTiles.outlookFromMe
  const projectAsManager = kpiTiles.projectAsManager
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const outlookMail = useTodayOutlookMail(periodDay)
  const preparedDecisions = useTodayPreparedDecisions(periodDay, user.id)
  const projectTasks = useTodayProjectTasks(periodDay, data)
  const erpFio = erpActorFio(user)

  const mailRows = useMemo(() => {
    return outlookMail.rows.filter((row) =>
      outlookFromMe ? isOutlookMailFromMe(row) : !isOutlookMailFromMe(row)
    )
  }, [outlookFromMe, outlookMail.rows])
  const projectRows = useMemo(() => {
    return projectTasks.rows.filter((row) =>
      projectAsManager ? isTurboTaskAsManager(row) : isTurboTaskToMe(row)
    )
  }, [projectAsManager, projectTasks.rows])
  const taskRows = useMemo(() => {
    return data.erpTasks.filter((row) => {
      if (onecFromMe) {
        return isDocflowFromMe(row, erpFio) && isTaskDueOnDay(row, periodDay)
      }
      return isDocflowToMe(row)
    })
  }, [data.erpTasks, onecFromMe, erpFio, periodDay])
  const meetingRows = useMemo(() => {
    return data.meetings
      .filter((meeting) => {
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
  }, [data.meetings, periodDay])

  const ask = (message: string): void => {
    onAskOrchestrator(message, 'Вкладка «Сегодня»')
  }

  const kpiFocusWidgetIds = useMemo(() => {
    const allowed = new Set<string>(TODAY_WIDGET_IDS)
    return kpiTiles.activeIds.filter((id): id is TodayWidgetId => allowed.has(id))
  }, [kpiTiles.activeIds])

  useEffect(() => {
    const targetId = kpiFocusWidgetIds[0]
    if (!targetId || !canvasRef.current) return
    const node = canvasRef.current.querySelector(`[data-widget-id="${targetId}"]`)
    node?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [kpiFocusWidgetIds])

  const onKpiTileSelect = (id: string): void => {
    setKpiTiles((current) => applyTodayKpiTileClick(current, id))
  }

  const showOneCReconnect =
    !data.sourcesLoading && !taskRows.length && data.oneCAuthFailure
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
    if (data.sourcesLoading || !showOneCReconnect) return
    setOnecDialogOpen(true)
  }, [data.sourcesLoading, showOneCReconnect, data.comPasswordInSession])

  const {
    layout,
    layoutWithStatic,
    locked,
    editMode,
    setEditMode,
    onLayoutChange,
    toggleWidgetLock,
    resetLayout
  } = useTodayWidgetLayout(user.id || '')

  const visibleWidgetIds = useMemo(
    () => layoutWithStatic.map((item) => item.i as TodayWidgetId),
    [layoutWithStatic]
  )

  const todayWidgets = useMemo(
    () => ({
      plan: (
        <TodayWindow>
          <TodayPlanPanel
            periodDay={periodDay}
            userId={user.id || ''}
            fio={erpFio}
            onOpenFullPlan={() => setFullPlanOpen(true)}
          />
        </TodayWindow>
      ),
      results: (
        <TodayWindow>
          <TodayResultsPanel periodDay={periodDay} userId={user.id} />
        </TodayWindow>
      ),
      outlook: (
        <TodayWindow>
          <TodayOutlookMailPanel
            rows={outlookMail.rows}
            compactRows={mailRows}
            loading={outlookMail.loading}
            error={outlookMail.error}
          />
        </TodayWindow>
      ),
      onec: (
        <TodayWindow>
        <MiniTableCard
          title="Задачи из 1С"
          tableClassName={
            onecFromMe ? 'today-mini-table-tasks today-mini-table-from-me' : 'today-mini-table-to-me'
          }
          headerAction={
            <>
              <label className="today-from-me-toggle">
                <input
                  type="checkbox"
                  checked={onecFromMe}
                  onChange={(event) =>
                    setKpiTiles((current) => ({
                      ...current,
                      onecFromMe: event.target.checked,
                      activeIds: ['onec']
                    }))
                  }
                />
                <span className="today-from-me-toggle-label">Задачи от меня</span>
              </label>
              <button
                type="button"
                className="today-refresh-btn"
                title="Обновить задачи 1С:Документооборот: сегодня и просроченные"
                disabled={data.sourcesLoading}
                onClick={() => forceRefresh()}
              >
                <RefreshCw size={14} aria-hidden />
              </button>
            </>
          }
          loading={data.sourcesLoading}
          error={
            taskRows.length
              ? data.erpError || data.error || undefined
              : data.erpError || data.error
                ? isOneCAuthFailure(data.erpError || data.error)
                  ? [data.erpError || data.error, comPasswordSessionHint()].filter(Boolean).join(' · ')
                  : data.erpError || data.error
                : undefined
          }
          emptyText={
            data.erpError || data.error
              ? 'Не удалось загрузить задачи документооборота'
              : onecFromMe
                ? 'Нет задач от вас на выбранный день'
                : 'Нет задач на сегодня и просроченных'
          }
          emptyExtra={onecReconnectBlock}
          columns={onecFromMe ? ['Задача', 'Исполнитель', 'Статус'] : ['Задача', 'Статус']}
          rowTones={taskRows.map((row) => todayRowTone(row.status, row.deadline, row.urgent))}
          rows={taskRows.map((row) =>
            onecFromMe
              ? [
                  <TodayCellText key={`${row.id}-t`} text={row.title} />,
                  <TodayCellText
                    key={`${row.id}-p`}
                    text={formatSurnameInitials(row.performer || row.executor)}
                  />,
                  <SpecPill key={`${row.id}-st`} tone={row.statusTone}>
                    {row.status}
                  </SpecPill>
                ]
              : [
                  <TodayCellText key={`${row.id}-t`} text={row.title} />,
                  <SpecPill key={`${row.id}-st`} tone={row.statusTone}>
                    {row.status}
                  </SpecPill>
                ]
          )}
        />
        </TodayWindow>
      ),
      projects: (
        <TodayWindow>
        <MiniTableCard
          title="Проектные задачи"
          tableClassName="today-mini-table-tasks"
          headerAction={
            <label className="today-from-me-toggle">
              <input
                type="checkbox"
                checked={projectAsManager}
                onChange={(event) =>
                  setKpiTiles((current) => ({
                    ...current,
                    projectAsManager: event.target.checked,
                    activeIds: ['projects']
                  }))
                }
              />
              <span className="today-from-me-toggle-label">Как руководитель</span>
            </label>
          }
          loading={projectTasks.loading}
          error={projectTasks.error || undefined}
          emptyText={
            projectTasks.noSession
              ? 'Нет активного сеанса'
              : projectAsManager
                ? 'Нет задач на сегодня и просроченных в ваших проектах'
                : 'Нет задач на сегодня и просроченных'
          }
          columns={['Задача', 'Срок', 'Статус']}
          rowTones={projectRows.map((row) => todayRowTone(row.status, row.deadline))}
          rows={projectRows.map((row) => [
            <TodayCellText key={`${row.id}-t`} text={row.title} />,
            <TodayCellText key={`${row.id}-d`} text={row.deadline} />,
            <SpecPill key={`${row.id}-st`} tone={row.statusTone}>
              {row.status}
            </SpecPill>
          ])}
        />
        </TodayWindow>
      ),
      events: (
        <TodayWindow>
        <MiniTableCard
          title="Предстоящие события"
          loading={data.sourcesLoading}
          emptyText="Нет событий Outlook на выбранный день"
          columns={['Время', 'Событие', 'Формат', 'Участники']}
          rows={meetingRows.map((row) => [
            <TodayCellText key={`${row.time}-t`} text={row.time} />,
            <TodayCellText key={`${row.time}-ti`} text={row.title} />,
            <TodayCellText key={`${row.time}-f`} text={row.format} />,
            <TodayCellText key={`${row.time}-p`} text={row.participants} />
          ])}
        />
        </TodayWindow>
      ),
      decisions: (
        <TodayWindow>
        <SpecPanel
          title="Подготовленные решения"
          extra={
            <button type="button" className="today-link-btn" onClick={onOpenDecisions}>
              Все
            </button>
          }
        >
          {preparedDecisions.loading ? (
            <p className="today-table-status">Загружаем…</p>
          ) : preparedDecisions.error ? (
            <p className="today-table-status today-table-error">{preparedDecisions.error}</p>
          ) : !preparedDecisions.items.length ? (
            <p className="today-table-status">Нет подготовленных решений за выбранный день</p>
          ) : (
            <ul className="today-decision-list">
              {preparedDecisions.items.map((item) => {
                const openRow = (): void => {
                  if (item.workflowId && item.runId) {
                    onOpenRun(item.workflowId, item.agentName, item.runId)
                    return
                  }
                  if (item.workflowId) {
                    onOpenRun(item.workflowId, item.agentName)
                  }
                }
                const clickable = Boolean(item.workflowId)
                return (
                  <li
                    key={item.id}
                    className={`today-decision-item${clickable ? ' today-decision-item-clickable' : ''}`}
                    role={clickable ? 'button' : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    onClick={clickable ? openRow : undefined}
                    onKeyDown={
                      clickable
                        ? (event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              openRow()
                            }
                          }
                        : undefined
                    }
                  >
                    <span className={`today-decision-status tone-${item.statusTone}`}>
                      {item.statusIcon}
                    </span>
                    <div className="today-decision-body">
                      <strong>{item.title}</strong>
                      {item.subtitle ? (
                        <p className="today-decision-agent-action spec-v04-muted">{item.subtitle}</p>
                      ) : null}
                      <SpecPill tone={item.tagTone}>{item.tag}</SpecPill>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </SpecPanel>
        </TodayWindow>
      ),
      ask: (
        <TodayWindow>
          <SpecAskOrchestratorBlock
            placeholder="Например: какие регламентные процессы просрочены?"
            chips={ASK_CHIPS.today}
            onSubmit={ask}
          />
        </TodayWindow>
      )
    }),
    [
      data.erpError,
      data.erpTasks,
      data.error,
      data.oneCAuthFailure,
      onecReconnectBlock,
      data.meetings,
      data.outlookMailbox,
      data.sources.erp,
      data.sources.turbo,
      data.sourcesLoading,
      erpFio,
      preparedDecisions.error,
      preparedDecisions.items,
      preparedDecisions.loading,
      mailRows,
      projectRows,
      meetingRows,
      onOpenDecisions,
      onOpenRun,
      outlookMail.error,
      outlookMail.loading,
      outlookMail.source,
      periodDay,
      projectTasks.error,
      projectTasks.loading,
      projectTasks.noSession,
      projectTasks.rows,
      taskRows,
      onecFromMe,
      outlookFromMe,
      projectAsManager,
      user.id,
      onAskOrchestrator
    ]
  )

  return (
    <>
      <OrchSlotMetrics>
        <div className="orch-today-tiles">
          <SpecSummaryTiles
            tiles={tiles}
            activeId={kpiTiles.activeIds}
            onSelect={onKpiTileSelect}
          />
        </div>
      </OrchSlotMetrics>

      <OrchSlotFilters>
        <TodayFiltersBar
          periodDay={periodDay}
          onPeriodDayChange={setPeriodDay}
          widgetEditMode={editMode}
          onWidgetEditModeChange={setEditMode}
          onResetWidgetLayout={resetLayout}
        />
      </OrchSlotFilters>

      <OrchSlotTodayCanvas>
        <div ref={canvasRef} className="today-widget-grid-host-wrap">
          <TodayWidgetGrid
            userId={user.id || ''}
            editMode={editMode}
            layoutWithStatic={layoutWithStatic}
            fullLayout={layout}
            visibleWidgetIds={visibleWidgetIds}
            locked={locked}
            onLayoutChange={onLayoutChange}
            onToggleLock={toggleWidgetLock}
            onRequestEditMode={() => setEditMode(true)}
            widgets={todayWidgets}
            kpiFocusWidgetIds={kpiFocusWidgetIds}
          />
        </div>
      </OrchSlotTodayCanvas>
      <OneCReconnectDialog
        open={onecDialogOpen}
        onClose={() => setOnecDialogOpen(false)}
        user={user}
        errorHint={data.erpError || data.error}
      />
      <TodayFullPlanModal
        open={fullPlanOpen}
        periodDay={periodDay}
        fio={erpFio}
        onClose={() => setFullPlanOpen(false)}
        onOpenRun={onOpenRun}
      />
    </>
  )
}
