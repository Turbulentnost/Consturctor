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
  isDeadTaskSource,
  isOverdueTask,
  parseTaskDueDate,
  taskTileActiveIds,
  type TaskSourceFilter,
  type TaskTileFilter
} from '../../workplace/tileFilters'
import {
  CREATE_TASK_CHANNEL_LABEL,
  ORCH_CREATE_TASK,
  type CreateTaskChannel
} from '../../workplace/workplaceNav'
import { GridFilterBar, toFilterOptions, uniqueFilterValues } from './gridFilters'

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
  const [barStatus, setBarStatus] = useState('')
  const [barProject, setBarProject] = useState('')
  const [barSort, setBarSort] = useState('urgent')
  const [barOverdue, setBarOverdue] = useState(false)
  useEffect(() => {
    if (navTaskFilter) setTileFilter(navTaskFilter)
  }, [navTaskFilter])
  const catalog = useMemo(
    () => buildTaskCatalog(data.erpTasks, data.turboTasks, data.processRows),
    [data.erpTasks, data.turboTasks, data.processRows]
  )
  const effectiveTile: TaskTileFilter = {
    source: (barSource as TaskSourceFilter) || tileFilter.source,
    overdueOnly: barOverdue || tileFilter.overdueOnly
  }
  const taskRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = filterTaskRows(catalog.rows, effectiveTile, catalog.erpIds, catalog.turboIds).filter(
      (row) => {
        if (barStatus && row.status !== barStatus) return false
        if (barProject && row.project !== barProject) return false
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
  }, [catalog, effectiveTile, query, barStatus, barProject, barSort, barOverdue])
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
          ? 'Нет задач по выбранной плитке.'
        : soapBanner || turboBanner
          ? 'Нет открытых задач в таблице.'
          : sessionOneCEmptyText(data.erpFio)
  const reconnectHint = showOneCReconnect
    ? soapBanner || 'Не удалось загрузить задачи 1С.'
    : ''
  const [onecDialogOpen, setOnecDialogOpen] = useState(false)
  useEffect(() => {
    if (data.erpLoading || !showOneCReconnect || data.comPasswordInSession) return
    setOnecDialogOpen(true)
  }, [data.erpLoading, showOneCReconnect, data.comPasswordInSession])
  const [selectedId, setSelectedId] = useState('')
  const [createChannel, setCreateChannel] = useState<CreateTaskChannel | null>(null)
  const effectiveId = selectedId || taskRows[0]?.id || ''
  const selected = taskRows.find((item) => item.id === effectiveId)

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
              id: 'status',
              value: barStatus,
              emptyLabel: 'Статус: все',
              onChange: setBarStatus,
              options: toFilterOptions(uniqueFilterValues(catalog.rows.map((row) => row.status)))
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
            setBarStatus('')
            setBarProject('')
            setBarSort('urgent')
            setBarOverdue(false)
            setTileFilter(EMPTY_TASK_TILE_FILTER)
          }}
        />
          ),
          main: (
        <div className="spec-v04-table-wrap wp-card">
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
          <table className="spec-v04-table">
            <thead>
              <tr>
                <th />
                <th>Задача</th>
                <th>Источник</th>
                <th>Процесс</th>
                <th>Срок</th>
                <th>Статус</th>
                <th>Прогресс</th>
              </tr>
            </thead>
            <tbody>
              {!taskRows.length ? (
                <tr>
                  <td colSpan={7} className="spec-v04-empty">
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
                  <td>
                    <input type="checkbox" onClick={(e) => e.stopPropagation()} />
                  </td>
                  <td>
                    <strong>{row.title}</strong>
                  </td>
                  <td>{row.source}</td>
                  <td>{row.process}</td>
                  <td className={row.urgent ? 'spec-deadline-urgent' : undefined}>{row.deadline}</td>
                  <td>
                    <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                  </td>
                  <td>
                    <SpecProgress value={row.progress} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
