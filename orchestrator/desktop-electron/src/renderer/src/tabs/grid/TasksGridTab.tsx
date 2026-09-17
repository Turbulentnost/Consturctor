import { useEffect, useMemo, useState } from 'react'
import { OneCReconnectDialog, OneCReconnectInline } from '../../workplace/OneCReconnectDialog'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT } from './useTabChromeLayout'
import { SpecPill, SpecProgress } from '../../workplace/specV04Components'
import {
  comPasswordSessionHint,
  sessionOneCEmptyText,
  userFacingOneCError
} from '../../workplace/onecSessionHints'
import { isTechnicalTurboMessage } from '../../workplace/turboSession'
import { buildTaskTiles, useSpecV04Sources } from '../../workplace/useSpecV04Data'
import {
  applyTaskTileClick,
  buildTaskCatalog,
  compareTasksByUrgency,
  EMPTY_TASK_TILE_FILTER,
  filterTaskRows,
  formatSurnameInitials,
  isDeadTaskSource,
  isOverdueTask,
  parseTaskDueDate,
  taskTileActiveIds,
  type TaskSourceFilter,
  type TaskTileFilter
} from '../../workplace/tileFilters'
import { formatDocflowCreated } from '../../workplace/specV04Mappers'
import {
  CREATE_TASK_CHANNEL_LABEL,
  ORCH_CREATE_TASK,
  type CreateTaskChannel
} from '../../workplace/workplaceNav'
import { startOfDay, type AdminDateRange } from '../../admin/utils/dateRange'
import type { SpecTaskRow } from '../../workplace/specV04DemoData'
import { GridFilterBar, toFilterOptions, uniqueFilterValues } from './gridFilters'
import { OrchDateRangePicker } from './OrchDateRangePicker'

function taskRowDate(row: SpecTaskRow): Date | null {
  return parseTaskDueDate(row.deadline)
}

function inDateRange(stamp: Date | null, range: AdminDateRange): boolean {
  if (!stamp) return true
  const day = startOfDay(stamp).getTime()
  return day >= startOfDay(range.start).getTime() && day <= startOfDay(range.end).getTime()
}

function rangeFromTaskRows(rows: SpecTaskRow[]): AdminDateRange {
  const today = startOfDay(new Date())
  let min = today.getTime()
  let max = today.getTime()
  let found = false
  for (const row of rows) {
    const due = taskRowDate(row)
    if (!due) continue
    const t = startOfDay(due).getTime()
    if (!found) {
      min = t
      max = t
      found = true
      continue
    }
    if (t < min) min = t
    if (t > max) max = t
  }
  return { start: new Date(min), end: new Date(max) }
}

export function TasksGridTab({
  user,
  navTaskFilter
}: {
  user: UserProfile
  navTaskFilter?: TaskTileFilter | null
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const [tileFilter, setTileFilter] = useState(navTaskFilter ?? EMPTY_TASK_TILE_FILTER)
  const [query, setQuery] = useState('')
  const [barSource, setBarSource] = useState('')
  const [barProject, setBarProject] = useState('')
  const [barSort, setBarSort] = useState('urgent')
  const [barOverdue, setBarOverdue] = useState(false)
  const [dateRange, setDateRange] = useState<AdminDateRange>(() => rangeFromTaskRows([]))
  const [dateRangeTouched, setDateRangeTouched] = useState(false)
  useEffect(() => {
    if (navTaskFilter) setTileFilter(navTaskFilter)
  }, [navTaskFilter])
  const catalog = useMemo(
    () => buildTaskCatalog(data.erpTasks, data.turboTasks, data.processRows),
    [data.erpTasks, data.turboTasks, data.processRows]
  )
  useEffect(() => {
    if (dateRangeTouched || !catalog.rows.length) return
    setDateRange(rangeFromTaskRows(catalog.rows))
  }, [catalog.rows, dateRangeTouched])
  const effectiveTile: TaskTileFilter = {
    source: (barSource as TaskSourceFilter) || tileFilter.source,
    overdueOnly: barOverdue || tileFilter.overdueOnly
  }
  const taskRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = filterTaskRows(
      catalog.rows,
      effectiveTile,
      catalog.erpIds,
      catalog.turboIds,
      data.erpFio
    ).filter(
      (row) => {
        if (barProject && row.project !== barProject) return false
        if (!inDateRange(taskRowDate(row), dateRange)) return false
        if (q && !`${row.title} ${row.source} ${row.process} ${row.project}`.toLowerCase().includes(q)) {
          return false
        }
        if (barOverdue && !isOverdueTask(row)) return false
        return true
      }
    )
    if (barSort === 'name') {
      return [...filtered].sort((left, right) => left.title.localeCompare(right.title, 'ru'))
    }
    if (barSort === 'due') {
      return [...filtered].sort((left, right) => {
        const leftDue = parseTaskDueDate(left.deadline)?.getTime() ?? Number.POSITIVE_INFINITY
        const rightDue = parseTaskDueDate(right.deadline)?.getTime() ?? Number.POSITIVE_INFINITY
        return leftDue - rightDue
      })
    }
    return [...filtered].sort(compareTasksByUrgency)
  }, [catalog, data.erpFio, effectiveTile, query, barProject, barSort, barOverdue, dateRange])
  const onTileSelect = (id: string): void => {
    setTileFilter((current) => applyTaskTileClick(current, id, isDeadTaskSource(data, id)))
  }
  const soapBanner = userFacingOneCError(data.erpError)
  const turboBanner = isTechnicalTurboMessage(data.turboError)
    ? ''
    : userFacingOneCError(data.turboError)
  const showOneCReconnect = !data.erpLoading && data.oneCAuthFailure
  const emptyTableText =
    (data.erpLoading || data.turboLoading) && !taskRows.length
      ? data.erpLoading && data.erpFio
        ? `Загружаем задачи 1С для ${data.erpFio}…`
        : data.turboLoading
          ? 'Загружаем проектные задачи…'
          : 'Загружаем задачи…'
      : showOneCReconnect && !taskRows.length
        ? 'Нужно подключить 1С.'
        : catalog.rows.length && !taskRows.length
          ? dateRangeTouched
            ? 'Нет задач за выбранный период.'
            : 'Нет задач по выбранной плитке.'
        : soapBanner || turboBanner
          ? 'Нет открытых задач в таблице.'
          : sessionOneCEmptyText(data.erpFio)
  const reconnectHint = showOneCReconnect
    ? soapBanner || 'Не удалось загрузить задачи 1С.'
    : ''
  const [onecDialogOpen, setOnecDialogOpen] = useState(false)
  useEffect(() => {
    if (data.comPasswordInSession) {
      setOnecDialogOpen(false)
      return
    }
    if (data.erpLoading || !showOneCReconnect) return
    setOnecDialogOpen(true)
  }, [data.erpLoading, showOneCReconnect, data.comPasswordInSession])
  const [selectedId, setSelectedId] = useState('')
  const [createChannel, setCreateChannel] = useState<CreateTaskChannel | null>(null)
  const effectiveId = selectedId || taskRows[0]?.id || ''
  const selected = taskRows.find((item) => item.id === effectiveId)
  const onecToMe = effectiveTile.source === 'onec'
  const onecFromMe = effectiveTile.source === 'onec-from-me'

  useEffect(() => {
    const onCreate = (event: Event): void => {
      const channel = (event as CustomEvent<{ channel?: CreateTaskChannel }>).detail?.channel
      if (channel === 'onec' || channel === 'turbo' || channel === 'draft') {
        setCreateChannel(channel)
      }
    }
    window.addEventListener(ORCH_CREATE_TASK, onCreate)
    return () => window.removeEventListener(ORCH_CREATE_TASK, onCreate)
  }, [])

  return (
    <>
      <StandardTabChrome
        tabId="tasks"
        userId={user.id || ''}
        defaults={DEFAULT_STANDARD_LAYOUT}
        chromeTiles={summaryTilesAsChrome(buildTaskTiles(data), taskTileActiveIds(tileFilter), onTileSelect)}
        widgets={{
          filters: (
        <GridFilterBar
          search={{ value: query, onChange: setQuery, placeholder: 'Поиск по задачам…' }}
          selects={[
            {
              id: 'source',
              value: barSource,
              emptyLabel: 'Источник: все',
              onChange: setBarSource,
              options: [
                { value: 'onec', label: '1С' },
                { value: 'proj', label: 'TurboProject' },
                { value: 'reg', label: 'Регламент' }
              ]
            },
            {
              id: 'project',
              value: barProject,
              emptyLabel: 'Проект: все',
              onChange: setBarProject,
              options: toFilterOptions(uniqueFilterValues(catalog.rows.map((row) => row.project)))
            }
          ]}
          sort={{
            id: 'sort',
            value: barSort,
            emptyLabel: '',
            onChange: setBarSort,
            options: [
              { value: 'urgent', label: 'Сортировка: срочные сначала' },
              { value: 'due', label: 'Сортировка: по сроку' },
              { value: 'name', label: 'Сортировка: по названию' }
            ]
          }}
          toggles={[
            { id: 'overdue', label: 'Только просроченные', checked: barOverdue, onChange: setBarOverdue }
          ]}
          onReset={() => {
            setQuery('')
            setBarSource('')
            setBarProject('')
            setBarSort('urgent')
            setBarOverdue(false)
            setDateRangeTouched(false)
            setDateRange(rangeFromTaskRows(catalog.rows))
            setTileFilter(EMPTY_TASK_TILE_FILTER)
          }}
        />
          ),
          main: (
        <div className="orch-tasks-main">
        <div className="spec-table-toolbar orch-tasks-toolbar">
          <div className="orch-process-tabs-tools">
            <OrchDateRangePicker
              value={dateRange}
              label="Период"
              onChange={(next) => {
                setDateRangeTouched(true)
                setDateRange(next)
              }}
            />
          </div>
        </div>
        <div className="spec-v04-table-wrap spec-v04-table-wrap-tasks wp-card">
          {soapBanner ? (
            <p className="today-table-status today-table-error today-table-banner">{soapBanner}</p>
          ) : null}
          {showOneCReconnect && taskRows.length ? (
            <OneCReconnectInline errorHint={reconnectHint} onOpen={() => setOnecDialogOpen(true)} />
          ) : null}
          {turboBanner ? (
            <p className="today-table-status today-table-error today-table-banner">{turboBanner}</p>
          ) : null}
          {!soapBanner && !turboBanner && data.erpSecondaryHint ? (
            <p className="today-table-status today-table-banner">{data.erpSecondaryHint}</p>
          ) : null}
          {!soapBanner && !turboBanner && !data.erpSecondaryHint && !data.erpLoading && !data.turboLoading && !taskRows.length ? (
            <p className="today-table-status today-table-banner spec-v04-muted">
              {comPasswordSessionHint()}
            </p>
          ) : null}
          <table className="spec-v04-table spec-v04-table-tasks">
            <colgroup>
              <col className="spec-v04-col-check" />
              <col className="spec-v04-col-task" />
              <col className="spec-v04-col-source" />
              <col className="spec-v04-col-process" />
              <col className="spec-v04-col-deadline" />
              <col className="spec-v04-col-progress" />
            </colgroup>
            <thead>
              <tr>
                <th className="spec-v04-cell-check" />
                <th className="spec-v04-cell-task">Задача</th>
                <th className="spec-v04-cell-deadline">Срок</th>
                {onecFromMe ? <th>Исполнитель</th> : null}
                {onecToMe ? <th>Автор</th> : null}
                {onecToMe || onecFromMe ? <th>Создана</th> : null}
                {onecToMe || onecFromMe ? null : (
                  <>
                    <th className="spec-v04-cell-source">Источник</th>
                    <th className="spec-v04-cell-process">Процесс</th>
                    <th>Статус</th>
                    <th className="spec-v04-cell-progress">Прогресс</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {!taskRows.length ? (
                <tr>
                  <td colSpan={onecToMe || onecFromMe ? 5 : 7} className="spec-v04-empty">
                    {showOneCReconnect ? (
                      <OneCReconnectInline
                        errorHint={reconnectHint}
                        onOpen={() => setOnecDialogOpen(true)}
                      />
                    ) : (
                      emptyTableText
                    )}
                  </td>
                </tr>
              ) : null}
              {taskRows.map((row) => (
                <tr
                  key={row.id}
                  className={effectiveId === row.id ? 'selected' : ''}
                  onClick={() => setSelectedId(row.id)}
                >
                  <td className="spec-v04-cell-check">
                    <input type="checkbox" onClick={(e) => e.stopPropagation()} />
                  </td>
                  <td className="spec-v04-cell-task">
                    <strong>{row.title}</strong>
                  </td>
                  <td
                    className={`spec-v04-cell-deadline${row.urgent ? ' spec-deadline-urgent' : ''}`}
                    title={row.deadline}
                  >
                    {row.deadline || '—'}
                  </td>
                  {onecFromMe ? (
                    <>
                      <td>{formatSurnameInitials(row.performer || row.executor)}</td>
                      <td>{formatDocflowCreated(row.createdAt || '')}</td>
                    </>
                  ) : onecToMe ? (
                    <>
                      <td>{formatSurnameInitials(row.author || '')}</td>
                      <td>{formatDocflowCreated(row.createdAt || '')}</td>
                    </>
                  ) : (
                    <>
                      <td className="spec-v04-cell-source">{row.source}</td>
                      <td className="spec-v04-cell-process">{row.process}</td>
                      <td>
                        <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                      </td>
                      <td className="spec-v04-cell-progress">
                        <SpecProgress value={row.progress} />
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
          ),
          side: (
        <>
        {createChannel ? (
          <div className="spec-detail-card wp-card">
            <h2>Создать задачу</h2>
            <SpecPill tone="blue">{CREATE_TASK_CHANNEL_LABEL[createChannel]}</SpecPill>
            <p className="spec-v04-muted">
              Write-API для канала «{CREATE_TASK_CHANNEL_LABEL[createChannel]}» ещё не готов. Задача не
              создана.
            </p>
            <button type="button" className="spec-btn-outline spec-btn-outline-block" onClick={() => setCreateChannel(null)}>
              Закрыть
            </button>
          </div>
        ) : selected ? (
          <div className="spec-detail-card wp-card">
            <h2>{selected.title}</h2>
            <SpecPill tone={selected.statusTone}>{selected.status}</SpecPill>
            <p className="spec-v04-muted">{selected.process}</p>
            <dl className="spec-detail-meta">
              <div>
                <dt>Автор</dt>
                <dd>{selected.author || '—'}</dd>
              </div>
              <div>
                <dt>Исполнитель</dt>
                <dd>{selected.performer || selected.executor || '—'}</dd>
              </div>
              <div>
                <dt>Создана</dt>
                <dd>{formatDocflowCreated(selected.createdAt || '')}</dd>
              </div>
              <div>
                <dt>Канал</dt>
                <dd>{selected.channel === 'soap' ? 'SOAP' : selected.channel || '—'}</dd>
              </div>
              <div>
                <dt>Источник</dt>
                <dd>{selected.source}</dd>
              </div>
              <div>
                <dt>Кто</dt>
                <dd>{selected.who}</dd>
              </div>
            </dl>
            <SpecProgress value={selected.progress} />
            <button type="button" className="spec-btn-launch spec-btn-launch-block">
              Отметить выполненной
            </button>
          </div>
        ) : (
          <div className="wp-card spec-v04-muted">Выберите задачу</div>
        )}
        </>
          )
        }}
      />
      <OneCReconnectDialog
        open={onecDialogOpen}
        onClose={() => setOnecDialogOpen(false)}
        user={user}
        errorHint={soapBanner}
      />
    </>
  )
}
