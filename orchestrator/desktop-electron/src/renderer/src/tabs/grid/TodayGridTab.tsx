import { useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { OrchSlotFilters, OrchSlotMetrics, OrchSlotTodayCanvas } from '../../layout/GridSlots'
import { TodayWidgetGrid, useTodayWidgetLayout } from './TodayWidgetGrid'
import { SpecAskOrchestratorBlock, SpecPanel, SpecPill, SpecSummaryTiles } from '../../workplace/specV04Components'
import { ASK_CHIPS } from '../../workplace/specV04DemoData'
import { useTodayKpiData } from '../../workplace/useTodayKpiData'
import { useTodayOutlookMail } from '../../workplace/useTodayOutlookMail'
import { comPasswordSessionHint, isOneCAuthFailure } from '../../workplace/onecSessionHints'
import { OneCReconnectDialog, OneCReconnectInline } from '../../workplace/OneCReconnectDialog'
import { erpActorFio } from '../../workplace/userContext'
import { useTodayProjectTasks } from '../../workplace/useTodayProjectTasks'
import { parseMeetingTime } from '../../utils/outlookMeetings'
import { sameDay } from '../../utils/calendar'
import { useTodayPreparedDecisions } from '../../workplace/useTodayPreparedDecisions'
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
  headerAction
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
        <table className="today-mini-table">
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
  const { data, tiles } = useTodayKpiData(user)
  const [periodDay, setPeriodDay] = useState(startOfToday)
  const [onecDialogOpen, setOnecDialogOpen] = useState(false)
  const outlookMail = useTodayOutlookMail(periodDay)
  const preparedDecisions = useTodayPreparedDecisions(periodDay, user.id)
  const projectTasks = useTodayProjectTasks(periodDay, data)
  const erpFio = erpActorFio(user)

  const mailRows = useMemo(() => outlookMail.rows.slice(0, 4), [outlookMail.rows])
  const taskRows = useMemo(() => data.erpTasks.slice(0, 4), [data.erpTasks])
  const meetingRows = useMemo(() => {
    return data.meetings
      .filter((meeting) => {
        const start = parseMeetingTime(meeting.start)
        return start ? sameDay(start, periodDay) : false
      })
      .sort((left, right) => left.start.localeCompare(right.start))
      .slice(0, 4)
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

  const resultsRail = (
    <TodayResultsPanel periodDay={periodDay} userId={user.id} onOpenRun={onOpenRun} />
  )

  const showOneCReconnect =
    !data.sourcesLoading && !taskRows.length && data.oneCAuthFailure
  const onecReconnectBlock = showOneCReconnect ? (
    <OneCReconnectInline
      errorHint={data.erpError || data.error}
      onOpen={() => setOnecDialogOpen(true)}
    />
  ) : undefined

  useEffect(() => {
    if (data.sourcesLoading || !showOneCReconnect || data.comPasswordInSession) return
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

  const todayWidgets = useMemo(
    () => ({
      plan: (
        <TodayWindow>
          <TodayPlanPanel periodDay={periodDay} userId={user.id || ''} fio={erpFio} />
        </TodayWindow>
      ),
      results: null,
      outlook: (
        <TodayWindow>
        <MiniTableCard
          title="Письма из Outlook"
          hint={
            outlookMail.source
              ? `Outlook COM · ${outlookMail.source}`
              : data.outlookMailbox
                ? data.outlookMailbox
                : undefined
          }
          loading={outlookMail.loading}
          error={outlookMail.error}
          emptyText="Нет писем во входящих за выбранный день"
          columns={['Отправитель', 'Тема', 'Время', 'Приоритет', 'Статус']}
          rows={mailRows.map((row) => [
            <TodayCellText key={`${row.id}-s`} text={row.sender} />,
            <TodayCellText key={`${row.id}-sub`} text={row.subject} />,
            <TodayCellText key={`${row.id}-t`} text={row.time} />,
            <SpecPill key={`${row.id}-p`} tone={row.priTone}>
              {row.priority}
            </SpecPill>,
            <SpecPill key={`${row.id}-s`} tone={row.stTone}>
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
          headerAction={
            <button
              type="button"
              className="today-refresh-btn"
              title="Обновить задачи 1С:Документооборот: сегодня и просроченные"
              disabled={data.sourcesLoading}
              onClick={() => forceRefresh()}
            >
              <RefreshCw size={14} aria-hidden />
            </button>
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
              : 'Нет задач на сегодня и просроченных'
          }
          hint={
            [data.erpSecondaryHint, data.sources.erp !== '—' ? data.sources.erp : '']
              .filter(Boolean)
              .join(' · ') || undefined
          }
          emptyExtra={onecReconnectBlock}
          columns={['Задача', 'Срок', 'Статус', 'Исполнитель']}
          rows={taskRows.map((row) => [
            <TodayCellText key={`${row.id}-t`} text={row.title} />,
            <TodayCellText key={`${row.id}-d`} text={row.deadline} />,
            <SpecPill key={`${row.id}-st`} tone={row.statusTone}>
              {row.status}
            </SpecPill>,
            <SpecPill key={`${row.id}-who`} tone={row.who === 'Я' ? 'blue' : 'purple'}>
              {row.who === 'Я' ? 'Сотрудник' : row.who}
            </SpecPill>
          ])}
        />
        </TodayWindow>
      ),
      projects: (
        <TodayWindow>
        <MiniTableCard
          title="Проектные задачи"
          loading={projectTasks.loading}
          error={projectTasks.error || undefined}
          emptyText={projectTasks.noSession ? 'Нет активного сеанса' : 'Нет открытых проектных задач'}
          hint={data.sources.turbo !== '—' ? data.sources.turbo : undefined}
          columns={['Задача', 'Срок', 'Статус', 'Исполнитель']}
          rows={projectTasks.rows.map((row) => [
            <TodayCellText key={`${row.id}-t`} text={row.title} />,
            <TodayCellText key={`${row.id}-d`} text={row.deadline} />,
            <SpecPill key={`${row.id}-st`} tone={row.statusTone}>
              {row.status}
            </SpecPill>,
            <SpecPill key={`${row.id}-a`} tone={row.assigneeTone}>
              {row.assignee}
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
      user.id,
      onAskOrchestrator
    ]
  )

  return (
    <>
      <OrchSlotMetrics>
        <div className="orch-today-tiles">
          <SpecSummaryTiles tiles={tiles} />
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
          locked={locked}
          onLayoutChange={onLayoutChange}
          onToggleLock={toggleWidgetLock}
          widgets={todayWidgets}
          rightRail={resultsRail}
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
