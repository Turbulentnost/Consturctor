import { useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { OrchSlotFilters, OrchSlotMetrics, OrchSlotTodayCanvas } from '../../layout/GridSlots'
import { TodayWidgetGrid, useTodayWidgetLayout } from './TodayWidgetGrid'
import type { TodayWidgetId } from './useTodayWidgetLayout'
import { SpecAskOrchestratorBlock, SpecPanel, SpecPill, SpecSummaryTiles } from '../../workplace/specV04Components'
import { ASK_CHIPS } from '../../workplace/specV04DemoData'
import { buildTodayKpiTiles, useTodayKpiData } from '../../workplace/useTodayKpiData'
import { useTodayTileAlerts } from '../../workplace/useTodayTileAlerts'
import { alertTileForWidget, widgetIdForTodayTile } from '../../workplace/todayTileAlerts'
import { useTodayOutlookMail } from '../../workplace/useTodayOutlookMail'
import { comPasswordSessionHint, isOneCAuthFailure } from '../../workplace/onecSessionHints'
import { OneCReconnectDialog, OneCReconnectInline } from '../../workplace/OneCReconnectDialog'
import { erpActorFio } from '../../workplace/userContext'
import { formatDocflowCreated, isOutlookMailFromMe, mailPartyLabel } from '../../workplace/specV04Mappers'
import { useTodayProjectTasks } from '../../workplace/useTodayProjectTasks'
import { parseMeetingTime, selectUpcomingEventMeetings } from '../../utils/outlookMeetings'
import { MONTHS_GEN, sameDay } from '../../utils/calendar'
import { useTodayOutlookMeetings } from '../../workplace/useTodayOutlookMeetings'
import { useTodayPreparedDecisions } from '../../workplace/useTodayPreparedDecisions'
import { formatSurnameInitials, isTurboTaskAsManager, isTurboTaskToMe } from '../../workplace/tileFilters'
import { onecTodayRowsForTable } from '../../workplace/useTodayKpiData'
import { TodayFiltersBar, TodayPlanPanel } from './todayTzComponents'
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

function MiniTableCard({
  title,
  columns,
  rows,
  loading,
  error,
  emptyText,
  hint,
  emptyExtra,
  headerAction,
  tableClassName
}: {
  title: string
  columns: string[]
  rows: React.ReactNode[][]
  loading?: boolean
  /** Shown above the table (KPI/banner), never as a fake data row. */
  error?: string
  emptyText?: string
  hint?: string
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
    return rows.map((cells, index) => (
      <tr key={index}>
        {cells.map((cell, cellIndex) => (
          <td key={cellIndex}>{cell}</td>
        ))}
      </tr>
    ))
  })()

  const titleExtra = (
    <span className="today-mini-table-head">
      {headerAction}
      {hint ? <span className="spec-v04-muted today-table-hint">{hint}</span> : null}
    </span>
  )

  return (
    <SpecPanel title={title} extra={headerAction || hint ? titleExtra : undefined}>
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
  const { data, onecTodayRows } = useTodayKpiData(user, periodDay)
  const [onecDialogOpen, setOnecDialogOpen] = useState(false)
  const [onecFromMe, setOnecFromMe] = useState(false)
  const [outlookFromMe, setOutlookFromMe] = useState(false)
  const [projectAsManager, setProjectAsManager] = useState(false)
  const [openWidgetId, setOpenWidgetId] = useState<TodayWidgetId | null>(null)
  const outlookMail = useTodayOutlookMail(periodDay)
  const preparedDecisions = useTodayPreparedDecisions(periodDay, user.id)
  const projectTasks = useTodayProjectTasks(periodDay, data)
  const { alerts, dismissTile } = useTodayTileAlerts(data.boardAgents || [])
  const tiles = useMemo(
    () => buildTodayKpiTiles(data, periodDay, onecTodayRows, alerts),
    [alerts, data, onecTodayRows, periodDay]
  )
  const erpFio = erpActorFio(user)
  const outlookMeetings = useTodayOutlookMeetings(periodDay, {
    userId: user.id || '',
    fio: erpFio
  })

  const mailRows = useMemo(() => {
    return outlookMail.rows
      .filter((row) => (outlookFromMe ? isOutlookMailFromMe(row) : !isOutlookMailFromMe(row)))
      .slice(0, 4)
  }, [outlookFromMe, outlookMail.rows])
  const projectRowsAll = useMemo(() => {
    return projectTasks.rows.filter((row) =>
      projectAsManager ? isTurboTaskAsManager(row) : isTurboTaskToMe(row)
    )
  }, [projectAsManager, projectTasks.rows])
  const projectRows = useMemo(() => projectRowsAll.slice(0, 4), [projectRowsAll])
  const taskRows = useMemo(
    () => onecTodayRowsForTable(onecTodayRows, onecFromMe, erpFio),
    [erpFio, onecFromMe, onecTodayRows]
  )
  const upcomingMeetings = useMemo(
    () => selectUpcomingEventMeetings(outlookMeetings.meetings, periodDay),
    [outlookMeetings.meetings, periodDay]
  )
  const meetingRows = useMemo(() => {
    return upcomingMeetings.slice(0, 6).map((meeting) => {
        const start = parseMeetingTime(meeting.start)
        const clock = start
          ? `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`
          : meeting.start
        const time =
          start && !sameDay(start, periodDay)
            ? `${start.getDate()} ${MONTHS_GEN[start.getMonth() + 1]} ${clock}`
            : clock
        const attendees = (meeting.attendees || '')
          .split(/[,;]/)
          .map((part) => part.trim())
          .filter(Boolean)
        return {
          id: `${meeting.id}:${meeting.start}`,
          time,
          title: meeting.subject,
          format: meeting.location?.trim() || '—',
          participants: attendees.length ? `${attendees.length} чел.` : '—'
        }
      })
  }, [periodDay, upcomingMeetings])

  const ask = (message: string): void => {
    onAskOrchestrator(message, 'Вкладка «Сегодня»')
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
          <TodayPlanPanel periodDay={periodDay} userId={user.id || ''} fio={erpFio} />
        </TodayWindow>
      ),
      results: (
        <TodayWindow>
          <TodayResultsPanel periodDay={periodDay} userId={user.id} />
        </TodayWindow>
      ),
      outlook: (
        <TodayWindow>
        <MiniTableCard
          title="Письма из Outlook"
          tableClassName="today-mini-table-mail"
          headerAction={
            <label className="today-from-me-toggle">
              <input
                type="checkbox"
                checked={outlookFromMe}
                onChange={(event) => setOutlookFromMe(event.target.checked)}
              />
              <span>От меня</span>
            </label>
          }
          hint={
            [
              outlookFromMe ? 'кэш Outlook · отправленные' : 'кэш Outlook · входящие',
              outlookMail.source
                ? `Outlook COM · ${outlookMail.source}`
                : data.outlookMailbox || ''
            ]
              .filter(Boolean)
              .join(' · ') || undefined
          }
          loading={outlookMail.loading}
          error={outlookMail.error}
          emptyText={
            outlookFromMe ? 'Нет писем от меня за выбранный день' : 'Нет писем мне за выбранный день'
          }
          columns={['От / Кому', 'Тема', 'Время', 'Статус']}
          rows={mailRows.map((row) => [
            <TodayCellText key={`${row.id}-c`} text={mailPartyLabel(row)} />,
            <TodayCellText key={`${row.id}-sub`} text={row.subject} />,
            <TodayCellText key={`${row.id}-t`} text={row.time} />,
            <SpecPill key={`${row.id}-st`} tone={row.stTone}>
              {row.status}
            </SpecPill>
          ])}
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
            <span className="today-onec-head">
              <label className="today-from-me-toggle">
                <input
                  type="checkbox"
                  checked={onecFromMe}
                  onChange={(event) => setOnecFromMe(event.target.checked)}
                />
                <span>Задачи от меня</span>
              </label>
              <button
                type="button"
                className="today-refresh-btn"
                title="Обновить задачи 1С. На Сегодня — только срок сегодня и просроченные"
                disabled={data.sourcesLoading}
                onClick={() => forceRefresh()}
              >
                <RefreshCw size={14} aria-hidden />
              </button>
            </span>
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
                ? 'Нет задач от вас со сроком сегодня или просроченных'
                : 'Нет задач вам со сроком сегодня или просроченных'
          }
          hint={
            [
              onecFromMe ? 'от меня · срок сегодня и просроченные' : 'срок сегодня и просроченные',
              data.erpSecondaryHint,
              data.sources.erp !== '—' ? data.sources.erp : ''
            ]
              .filter(Boolean)
              .join(' · ') || undefined
          }
          emptyExtra={onecReconnectBlock}
          columns={
            onecFromMe
              ? ['Задача', 'Срок', 'Исполнитель', 'Создана']
              : ['Задача', 'Срок', 'Автор', 'Создана']
          }
          rows={taskRows.map((row) =>
            onecFromMe
              ? [
                  <TodayCellText key={`${row.id}-t`} text={row.title} />,
                  <TodayCellText key={`${row.id}-d`} text={row.deadline || '—'} />,
                  <TodayCellText
                    key={`${row.id}-p`}
                    text={formatSurnameInitials(row.performer || row.executor)}
                  />,
                  <TodayCellText key={`${row.id}-c`} text={formatDocflowCreated(row.createdAt || '')} />
                ]
              : [
                  <TodayCellText key={`${row.id}-t`} text={row.title} />,
                  <TodayCellText key={`${row.id}-d`} text={row.deadline || '—'} />,
                  <TodayCellText key={`${row.id}-a`} text={formatSurnameInitials(row.author || '')} />,
                  <TodayCellText key={`${row.id}-c`} text={formatDocflowCreated(row.createdAt || '')} />
                ]
          )}
        />
        </TodayWindow>
      ),
      projects: (
        <TodayWindow>
        <MiniTableCard
          title={
            projectRowsAll.length
              ? `Проектные задачи · ${projectRowsAll.length}`
              : 'Проектные задачи'
          }
          tableClassName="today-mini-table-tasks"
          headerAction={
            <label className="today-from-me-toggle">
              <input
                type="checkbox"
                checked={projectAsManager}
                onChange={(event) => setProjectAsManager(event.target.checked)}
              />
              <span>Как руководитель</span>
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
          hint={
            [
              projectAsManager ? 'кэш Turbo · руководитель' : 'кэш Turbo · исполнитель',
              data.sources.turbo !== '—' ? data.sources.turbo : ''
            ]
              .filter(Boolean)
              .join(' · ') || undefined
          }
          columns={['Задача', 'Срок', 'Статус']}
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
          title={
            upcomingMeetings.length
              ? `Предстоящие события · ${upcomingMeetings.length}`
              : 'Предстоящие события'
          }
          loading={outlookMeetings.loading}
          error={outlookMeetings.error || undefined}
          emptyText="Нет совещаний Outlook на выбранный день"
          hint={outlookMeetings.meetings.length ? 'календарь Outlook' : undefined}
          columns={['Время', 'Событие', 'Формат', 'Участники']}
          rows={meetingRows.map((row) => [
            <TodayCellText key={`${row.id}-t`} text={row.time} />,
            <TodayCellText key={`${row.id}-ti`} text={row.title} />,
            <TodayCellText key={`${row.id}-f`} text={row.format} />,
            <TodayCellText key={`${row.id}-p`} text={row.participants} />
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
            <p className="today-table-status">Нет запросов на разрешение за выбранный день</p>
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
                      <div className="today-decision-pills">
                        <SpecPill tone={item.statusTone}>{item.status}</SpecPill>
                        <SpecPill tone={item.tagTone}>{item.tag}</SpecPill>
                      </div>
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
      projectRowsAll,
      meetingRows,
      upcomingMeetings,
      onOpenDecisions,
      onOpenRun,
      outlookMail.error,
      outlookMail.loading,
      outlookMail.source,
      outlookMeetings.error,
      outlookMeetings.loading,
      outlookMeetings.meetings,
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
            onSelect={(id) => {
              const widgetId = widgetIdForTodayTile(id)
              if (widgetId) setOpenWidgetId(widgetId)
              if (id === 'ev' || id === 'meet') dismissTile('meet')
            }}
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
        <TodayWidgetGrid
          userId={user.id || ''}
          editMode={editMode}
          layoutWithStatic={layoutWithStatic}
          visibleWidgetIds={visibleWidgetIds}
          locked={locked}
          onLayoutChange={onLayoutChange}
          onToggleLock={toggleWidgetLock}
          widgets={todayWidgets}
          openWidgetId={openWidgetId}
          onOpenWidgetConsumed={() => setOpenWidgetId(null)}
          widgetAlerts={{
            events: alerts.meet,
            decisions: alerts.decisions,
            results: alerts.results
          }}
          onWidgetOpened={(id) => {
            const tile = alertTileForWidget(id)
            if (tile) dismissTile(tile)
          }}
        />
      </OrchSlotTodayCanvas>
      <OneCReconnectDialog
        open={onecDialogOpen}
        onClose={() => setOnecDialogOpen(false)}
        user={user}
        errorHint={data.erpError || data.error}
      />
    </>
  )
}
