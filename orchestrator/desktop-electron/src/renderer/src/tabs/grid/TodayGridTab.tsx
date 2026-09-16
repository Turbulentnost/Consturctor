import { useEffect, useMemo, useRef, useState } from 'react'
import type { Layout } from 'react-grid-layout/legacy'
import type { UserProfile } from '../../api/types'
import { OrchSlotFilters, OrchSlotMetrics, OrchSlotTodayCanvas } from '../../layout/GridSlots'
import { TodayWidgetGrid, useTodayWidgetLayout } from './TodayWidgetGrid'
import { SpecAskOrchestratorBlock, SpecPanel, SpecPill, SpecSummaryTiles } from '../../workplace/specV04Components'
import { ASK_CHIPS, DEMO_MEETING_ROWS, DEMO_TASK_ROWS } from '../../workplace/specV04DemoData'
import { useTodayKpiData } from '../../workplace/useTodayKpiData'
import { useTodayOutlookMail } from '../../workplace/useTodayOutlookMail'
import { erpActorFio } from '../../workplace/userContext'
import { useTodayProjectTasks } from '../../workplace/useTodayProjectTasks'
import { parseMeetingTime } from '../../utils/outlookMeetings'
import { sameDay } from '../../utils/calendar'
import { useTodayPreparedDecisions } from '../../workplace/useTodayPreparedDecisions'
import { TodayFiltersBar, TodayPlanPanel } from './todayTzComponents'
import { TodayResultsPanel } from './TodayResultsPanel'
import { TodayOutlookMailPanel } from './TodayOutlookMailPanel'
import {
  readTodayWidgetVisibility,
  TODAY_WIDGET_VISIBILITY_EVENT,
  visibleTodayWidgetIds,
  type TodayWidgetId
} from './todayWidgetSettings'
import { mergeTodayLayout, reflowTodayLayout } from './todayLayoutCompact'
import { TODAY_GRID_COLS, TODAY_WIDGET_IDS } from './useTodayWidgetLayout'

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
  hint
}: {
  title: string
  columns: string[]
  rows: React.ReactNode[][]
  loading?: boolean
  error?: string
  emptyText?: string
  hint?: string
}): React.JSX.Element {
  const body = ((): React.ReactNode => {
    if (loading) {
      return (
        <tr>
          <td colSpan={columns.length} className="today-table-status">
            Загружаем…
          </td>
        </tr>
      )
    }
    if (error) {
      return (
        <tr>
          <td colSpan={columns.length} className="today-table-status today-table-error">
            {error}
          </td>
        </tr>
      )
    }
    if (!rows.length) {
      return (
        <tr>
          <td colSpan={columns.length} className="today-table-status">
            {emptyText || 'Нет данных'}
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

  return (
    <SpecPanel
      title={title}
      extra={hint ? <span className="spec-v04-muted today-table-hint">{hint}</span> : undefined}
    >
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
  const { data, tiles } = useTodayKpiData(user)
  const [periodDay, setPeriodDay] = useState(startOfToday)
  const outlookMail = useTodayOutlookMail(periodDay)
  const preparedDecisions = useTodayPreparedDecisions(periodDay, user.id)
  const projectTasks = useTodayProjectTasks(periodDay, data)
  const erpFio = erpActorFio(user)

  const mailRows = useMemo(() => outlookMail.rows.slice(0, 4), [outlookMail.rows])
  const taskRows = useMemo(() => {
    const live = data.erpTasks.slice(0, 4)
    if (live.length) return live
    return DEMO_TASK_ROWS.slice(0, 4)
  }, [data.erpTasks])
  const meetingRows = useMemo(() => {
    const live = data.meetings
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
    if (live.length) return live
    return DEMO_MEETING_ROWS.slice(0, 4).map((row) => ({
      time: row.time,
      title: row.title,
      format: row.format,
      participants: row.participants
    }))
  }, [data.meetings, data.sourcesLoading, periodDay])

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
    layout,
    layoutWithStatic,
    locked,
    editMode,
    setEditMode,
    onLayoutChange,
    toggleWidgetLock,
    resetLayout
  } = useTodayWidgetLayout(user.id || '')
  const [widgetVisibility, setWidgetVisibility] = useState(() =>
    readTodayWidgetVisibility(user.id || '')
  )

  useEffect(() => {
    setWidgetVisibility(readTodayWidgetVisibility(user.id || ''))
  }, [user.id])

  useEffect(() => {
    function syncVisibility(): void {
      setWidgetVisibility(readTodayWidgetVisibility(user.id || ''))
    }
    window.addEventListener(TODAY_WIDGET_VISIBILITY_EVENT, syncVisibility)
    return () => window.removeEventListener(TODAY_WIDGET_VISIBILITY_EVENT, syncVisibility)
  }, [user.id])

  const visibleWidgetIds = useMemo(
    () => visibleTodayWidgetIds(widgetVisibility),
    [widgetVisibility]
  )

  const prevVisibleKeyRef = useRef(visibleWidgetIds.join(','))
  const prevEditModeRef = useRef(editMode)

  const lockedAnchorIds = useMemo(
    () => TODAY_WIDGET_IDS.filter((id) => locked[id]),
    [locked]
  )

  const reflowVisibleLayout = useMemo(
    () =>
      (source: Layout): Layout => {
        const visible = source.filter((item) => visibleWidgetIds.includes(item.i as TodayWidgetId))
        const reflowed = reflowTodayLayout(visible, lockedAnchorIds, TODAY_GRID_COLS, locked)
        return mergeTodayLayout(source, visibleWidgetIds, reflowed)
      },
    [locked, lockedAnchorIds, visibleWidgetIds]
  )

  useEffect(() => {
    const nextKey = visibleWidgetIds.join(',')
    if (prevVisibleKeyRef.current === nextKey) return
    prevVisibleKeyRef.current = nextKey
    onLayoutChange(reflowVisibleLayout(layout))
  }, [layout, onLayoutChange, reflowVisibleLayout, visibleWidgetIds])

  useEffect(() => {
    if (prevEditModeRef.current && !editMode) {
      onLayoutChange(reflowVisibleLayout(layout))
    }
    prevEditModeRef.current = editMode
  }, [editMode, layout, onLayoutChange, reflowVisibleLayout])

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
          <TodayOutlookMailPanel
            rows={outlookMail.rows}
            compactRows={mailRows}
            loading={outlookMail.loading && !mailRows.length}
            error={outlookMail.error}
            hint={
              outlookMail.source
                ? `Outlook COM · ${outlookMail.source}`
                : data.outlookMailbox
                  ? data.outlookMailbox
                  : undefined
            }
          />
        </TodayWindow>
      ),
      onec: (
        <TodayWindow>
        <MiniTableCard
          title="Задачи из 1С"
          loading={data.sourcesLoading && !taskRows.length}
          error={
            taskRows.length ? undefined : data.erpError || data.error || undefined
          }
          emptyText="Нет задач 1С для отображения"
          hint={
            taskRows.length && data.erpError
              ? data.erpError
              : data.sources.erp !== '—'
                ? data.sources.erp
                : undefined
          }
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
          loading={projectTasks.loading && !projectTasks.rows.length}
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
          loading={data.sourcesLoading && !meetingRows.length}
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
          {preparedDecisions.loading && !preparedDecisions.items.length ? (
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
      outlookMail.rows,
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
          fullLayout={layout}
          locked={locked}
          onLayoutChange={onLayoutChange}
          onToggleLock={toggleWidgetLock}
          onRequestEditMode={() => setEditMode(true)}
          visibleWidgetIds={visibleWidgetIds}
          widgets={todayWidgets}
          rightRail={resultsRail}
        />
      </OrchSlotTodayCanvas>
    </>
  )
}
