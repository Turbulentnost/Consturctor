import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { OneCReconnectDialog, OneCReconnectInline } from '../../workplace/OneCReconnectDialog'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT } from './useTabChromeLayout'
import { SpecPill, SpecProgress } from '../../workplace/specV04Components'
import { WorkplaceProgressSection } from '../../workplace/WorkplaceProgressSection'
import { displayTaskProgress } from '../../workplace/TaskProgressEditor'
import { taskActionContextFromTaskRow } from '../../workplace/taskSourceKind'
import { runDocflowAction } from '../../workplace/taskSourceActions'
import { formatSurnameInitials, isDocflowToMe } from '../../workplace/tileFilters'
import { useGridDataRefreshContext } from '../../workplace/GridDataRefreshContext'
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
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { deadlineInWorkplacePeriod } from '../../workplace/workplacePeriodFilter'
import { isNewOneCTask } from '../../workplace/onecTaskSnapshot'
import { NewOneCTaskMark } from '../../workplace/specV04Components'
import {
  DOCFLOW_KIND_LABEL,
  DOCFLOW_KIND_TONE,
  docflowPrimaryAction,
  docflowTaskKind,
  type DocflowTaskKind
} from '../../workplace/docflowTaskKind'
import { isPlatformTaskMine } from '../../workplace/platformTasks'
import { completePlatformTask, PlatformTaskDetail } from './PlatformTaskDetail'

export function TasksGridTab({
  user,
  navTaskFilter
}: {
  user: UserProfile
  navTaskFilter?: TaskTileFilter | null
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const { softRefresh } = useGridDataRefreshContext()
  const [executedIds, setExecutedIds] = useState<Set<string>>(() => new Set())
  const { from: periodFrom, to: periodTo } = useWorkplacePeriod()
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
    () => buildTaskCatalog(data.erpTasks, data.turboTasks, data.processRows, data.platformTasks),
    [data.erpTasks, data.turboTasks, data.processRows, data.platformTasks]
  )
  const effectiveTile: TaskTileFilter = {
    source: (barSource as TaskSourceFilter) || tileFilter.source,
    overdueOnly: barOverdue || tileFilter.overdueOnly
  }
  const taskRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = filterTaskRows(catalog.rows, effectiveTile, catalog.erpIds, catalog.turboIds).filter(
      (row) => {
        if (executedIds.has(row.id)) return false
        if (!deadlineInWorkplacePeriod(row.deadline, periodFrom, periodTo)) return false
        if (barStatus && row.status !== barStatus) return false
        if (barProject && row.project !== barProject) return false
        if (
          q &&
          !`${row.title} ${row.source} ${row.process} ${row.project} ${row.author || ''} ${row.performer || ''}`
            .toLowerCase()
            .includes(q)
        ) {
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
  }, [catalog, effectiveTile, query, barStatus, barProject, barSort, barOverdue, periodFrom, periodTo, executedIds])
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
    if (data.comPasswordInSession) {
      setOnecDialogOpen(false)
      return
    }
    if (data.erpLoading || !showOneCReconnect) return
    setOnecDialogOpen(true)
  }, [data.erpLoading, showOneCReconnect, data.comPasswordInSession])
  const [selectedId, setSelectedId] = useState('')
  const [closingId, setClosingId] = useState('')
  const [closeNote, setCloseNote] = useState('')
  const partyColumn =
    effectiveTile.source === 'onec'
      ? 'От кого'
      : effectiveTile.source === 'onec-from-me'
        ? 'Кому'
        : effectiveTile.source === 'platform'
          ? 'От кого / кому'
          : 'Процесс'
  const platformAction = (row: (typeof taskRows)[number]): boolean =>
    Boolean(row.platform && isPlatformTaskMine(row.platform) && row.platform.status === 'open')
  const runPlatformDone = (row: (typeof taskRows)[number]): void => {
    if (!row.platform || closingId) return
    setClosingId(row.id)
    setCloseNote('')
    void completePlatformTask(row.platform)
      .then((message) => {
        setCloseNote(message)
        softRefresh()
      })
      .catch((err: unknown) => setCloseNote(err instanceof Error ? err.message : 'Не удалось отметить задачу'))
      .finally(() => setClosingId(''))
  }
  const partyOf = (row: (typeof taskRows)[number]): string => {
    if (effectiveTile.source === 'onec') return row.author || '—'
    if (effectiveTile.source === 'onec-from-me') return row.performer || row.executor || '—'
    return row.process
  }
  const kindOf = (row: (typeof taskRows)[number]): DocflowTaskKind | null =>
    row.sourceKind === 'docflow' ? row.docflowKind ?? docflowTaskKind(row.step, row.taskName) : null
  const rowAction = (row: (typeof taskRows)[number]) => {
    const kind = kindOf(row)
    if (!kind || !isDocflowToMe(row) || /выполн|закры|заверш/i.test(row.status)) return null
    return docflowPrimaryAction(kind)
  }
  const hideExecuted = (id: string): void => {
    setExecutedIds((current) => new Set(current).add(id))
    setSelectedId('')
    softRefresh()
  }
  const runRowAction = (row: (typeof taskRows)[number]): void => {
    const action = rowAction(row)
    if (!action || closingId) return
    setClosingId(row.id)
    setCloseNote('')
    void runDocflowAction(user, taskActionContextFromTaskRow(row), action.id)
      .then((result) => {
        setCloseNote(result.message)
        if (result.ok) hideExecuted(row.id)
      })
      .catch((err: unknown) => {
        setCloseNote(err instanceof Error ? err.message : 'Документооборот не принял действие')
      })
      .finally(() => setClosingId(''))
  }
  const isAcquaintRow = (row: (typeof taskRows)[number]): boolean => {
    const kind = kindOf(row)
    return kind === 'acquaint' || kind === 'acquaint_result'
  }
  const mainRows = taskRows.filter((row) => !isAcquaintRow(row))
  const acquaintRows = taskRows.filter(isAcquaintRow)
  const acquaintTargets = acquaintRows.filter((row) => rowAction(row)?.id === 'acquaint')
  const [acquaintOpen, setAcquaintOpen] = useState(false)
  const [bulkProgress, setBulkProgress] = useState('')
  const acquaintAll = async (): Promise<void> => {
    const targets = [...acquaintTargets]
    if (!targets.length || bulkProgress || closingId) return
    if (!window.confirm(`Отметить в 1С:Документооборот ознакомление по ${targets.length} задачам?`)) return
    setCloseNote('')
    let done = 0
    const failed: string[] = []
    for (const [index, row] of targets.entries()) {
      setBulkProgress(`${index + 1} из ${targets.length}`)
      try {
        const result = await runDocflowAction(user, taskActionContextFromTaskRow(row), 'acquaint')
        if (result.ok) {
          done += 1
          setExecutedIds((current) => new Set(current).add(row.id))
        } else {
          failed.push(`«${row.title}»: ${result.message}`)
        }
      } catch (err) {
        failed.push(`«${row.title}»: ${err instanceof Error ? err.message : 'ошибка'}`)
      }
    }
    setBulkProgress('')
    setCloseNote(
      failed.length
        ? `Ознакомление отмечено: ${done} из ${targets.length}. Не прошло — ${failed.join('; ')}`
        : `Ознакомление отмечено по всем задачам: ${done}.`
    )
    if (done) {
      setSelectedId('')
      softRefresh()
    }
  }
  const [createChannel, setCreateChannel] = useState<CreateTaskChannel | null>(null)
  const visibleRows = acquaintOpen ? [...mainRows, ...acquaintRows] : mainRows
  const effectiveId = selectedId || visibleRows[0]?.id || ''
  const selected = taskRows.find((item) => item.id === effectiveId)
  const renderRow = (row: (typeof taskRows)[number]): React.JSX.Element => {
    const isNew = catalog.erpIds.has(row.id) && isNewOneCTask(data.newOneCTaskKeys, row)
    const kind = kindOf(row)
    const action = rowAction(row)
    return (
      <tr
        key={row.id}
        className={[
          effectiveId === row.id ? 'selected' : '',
          isNew ? 'is-new-onec' : '',
          row.platform ? 'ptask-row' : '',
          row.platform?.status === 'open' ? `prio-${row.platform.priority}` : ''
        ]
          .filter(Boolean)
          .join(' ')}
        onClick={() => setSelectedId(row.id)}
      >
        <td>
          <input type="checkbox" onClick={(e) => e.stopPropagation()} />
        </td>
        <td>
          <strong>{row.title}</strong>
          {isNew ? <NewOneCTaskMark /> : null}
          {row.role === 'delegate' ? (
            <span className="spec-row-delegate">за {formatSurnameInitials(row.performer || row.executor)}</span>
          ) : null}
        </td>
        <td>
          {kind ? (
            <SpecPill tone={DOCFLOW_KIND_TONE[kind]}>{DOCFLOW_KIND_LABEL[kind]}</SpecPill>
          ) : row.platform ? (
            <SpecPill tone={row.priorityTone}>{row.priority}</SpecPill>
          ) : (
            '—'
          )}
        </td>
        <td>{row.source}</td>
        <td>{partyOf(row)}</td>
        <td className={row.urgent ? 'spec-deadline-urgent' : undefined}>{row.deadline}</td>
        <td>
          <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
        </td>
        <td>
          <SpecProgress value={displayTaskProgress(row.id, row.progress)} />
        </td>
        <td>
          {action ? (
            <button
              type="button"
              className="spec-row-action"
              title={`${action.label} в 1С:Документооборот`}
              disabled={Boolean(closingId) || Boolean(bulkProgress)}
              onClick={(event) => {
                event.stopPropagation()
                runRowAction(row)
              }}
            >
              {closingId === row.id ? 'Отправляем…' : action.shortLabel}
            </button>
          ) : platformAction(row) ? (
            <button
              type="button"
              className="spec-row-action"
              title="Отметить задачу исполненной"
              disabled={Boolean(closingId)}
              onClick={(event) => {
                event.stopPropagation()
                runPlatformDone(row)
              }}
            >
              {closingId === row.id ? 'Отправляем…' : 'Исполнено'}
            </button>
          ) : null}
        </td>
      </tr>
    )
  }

  useEffect(() => {
    const onCreate = (event: Event): void => {
      const channel = (event as CustomEvent<{ channel?: CreateTaskChannel }>).detail?.channel
      if (channel === 'platform') {
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
                { value: 'platform', label: 'Платформа' },
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
          {closeNote ? <p className="spec-v04-muted orch-process-close-note">{closeNote}</p> : null}
          <table className="spec-v04-table">
            <thead>
              <tr>
                <th />
                <th>Задача</th>
                <th>Тип</th>
                <th>Источник</th>
                <th>{partyColumn}</th>
                <th>Срок</th>
                <th>Статус</th>
                <th>Прогресс</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {!taskRows.length ? (
                <tr>
                  <td colSpan={9} className="spec-v04-empty">
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
              {mainRows.map(renderRow)}
              {acquaintRows.length ? (
                <tr className="spec-group-row" onClick={() => setAcquaintOpen((open) => !open)}>
                  <td colSpan={9}>
                    <div className="spec-group-head">
                      <button type="button" className="spec-group-toggle" aria-expanded={acquaintOpen}>
                        {acquaintOpen ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
                        Ознакомление
                        <em>{acquaintRows.length}</em>
                      </button>
                      {acquaintTargets.length ? (
                        <button
                          type="button"
                          className="spec-row-action"
                          disabled={Boolean(bulkProgress) || Boolean(closingId)}
                          onClick={(event) => {
                            event.stopPropagation()
                            void acquaintAll()
                          }}
                        >
                          {bulkProgress
                            ? `Ознакомление ${bulkProgress}…`
                            : `Ознакомиться со всеми (${acquaintTargets.length})`}
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ) : null}
              {acquaintOpen ? acquaintRows.map(renderRow) : null}
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
        ) : selected?.platform ? (
          <PlatformTaskDetail
            row={selected}
            onChanged={(message) => {
              setCloseNote(message)
              softRefresh()
            }}
          />
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
              {selected.sourceKind === 'docflow' ? (
                <div>
                  <dt>Шаг процесса</dt>
                  <dd>{selected.step || DOCFLOW_KIND_LABEL[kindOf(selected) ?? 'other']}</dd>
                </div>
              ) : null}
              <div>
                <dt>Кто</dt>
                <dd>{selected.who}</dd>
              </div>
            </dl>
            <WorkplaceProgressSection
              user={user}
              rowId={selected.id}
              baseProgress={selected.progress}
              actionContext={taskActionContextFromTaskRow(selected)}
              onActionCompleted={() => hideExecuted(selected.id)}
            />
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
