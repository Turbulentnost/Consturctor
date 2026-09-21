import { Fragment, useEffect, useMemo, useState } from 'react'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { SpecPill, SpecProgress } from '../../workplace/specV04Components'
import { WorkplaceProgressSection } from '../../workplace/WorkplaceProgressSection'
import { displayTaskProgress } from '../../workplace/TaskProgressEditor'
import {
  taskActionContextFromProject,
  taskActionContextFromTurboOpenTask
} from '../../workplace/taskSourceKind'
import { useSpecV04Sources } from '../../workplace/useSpecV04Data'
import { projectMatchesTile, toggleSimpleTile } from '../../workplace/tileFilters'
import {
  useTurboProjectOpenTasks,
  type TurboProjectOpenTaskRow,
  type TurboProjectTasksFetchOptions
} from '../../workplace/useTurboProjectOpenTasks'
import { openHttpUrl } from '../../workplace/workplaceNav'
import { GridFilterBar, toFilterOptions, uniqueFilterValues } from './gridFilters'
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { deadlineInWorkplacePeriod } from '../../workplace/workplacePeriodFilter'
import { hasTurboSessionCredentials } from '../../workplace/userContext'

function ProjectTasksTable({
  rows,
  loading,
  error,
  emptyLabel,
  selectedTaskId,
  onSelectTask
}: {
  rows: TurboProjectOpenTaskRow[]
  loading: boolean
  error: string
  emptyLabel: string
  selectedTaskId?: string
  onSelectTask?: (taskId: string) => void
}): React.JSX.Element {
  if (loading) {
    return <p className="spec-v04-muted">Загружаем задачи…</p>
  }
  if (error) {
    return <p className="spec-v04-muted">{error}</p>
  }
  if (!rows.length) {
    return <p className="spec-v04-muted">{emptyLabel}</p>
  }
  return (
    <div className="spec-v04-nested-wrap">
      <table className="spec-v04-table spec-v04-table-compact">
        <thead>
          <tr>
            <th>Задача</th>
            <th>Срок</th>
            <th>Статус</th>
            <th>Прогресс</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((task) => (
            <tr
              key={task.id}
              className={selectedTaskId === task.id ? 'selected' : undefined}
              onClick={() => onSelectTask?.(task.id)}
            >
              <td>
                <strong>{task.title}</strong>
              </td>
              <td className={task.status === 'Просрочена' ? 'spec-deadline-urgent' : undefined}>
                {task.deadline}
              </td>
              <td>
                <SpecPill tone={task.statusTone}>{task.status}</SpecPill>
              </td>
              <td>
                <SpecProgress value={displayTaskProgress(`turbo:${task.projectId}:${task.taskUid || task.id}`, task.progress ?? 0)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ProjectExpandedTasks({
  projectId,
  user,
  erpFio,
  enabled,
  taskFetch,
  emptyLabel
}: {
  projectId: string
  user: UserProfile
  erpFio: string
  enabled: boolean
  taskFetch: TurboProjectTasksFetchOptions
  emptyLabel: string
}): React.JSX.Element {
  const tasks = useTurboProjectOpenTasks(projectId, user, erpFio, enabled, taskFetch)
  return (
    <ProjectTasksTable
      rows={tasks.rows}
      loading={tasks.loading}
      error={tasks.error}
      emptyLabel={emptyLabel}
    />
  )
}

export function ProjectsGridTab({
  user
}: {
  user: UserProfile
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const { from: periodFrom, to: periodTo } = useWorkplacePeriod()
  const [tileFilter, setTileFilter] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const [selectedProjectTaskId, setSelectedProjectTaskId] = useState('')
  const [query, setQuery] = useState('')
  const [barStatus, setBarStatus] = useState('')
  const [barRisk, setBarRisk] = useState('')
  const [barMine, setBarMine] = useState(false)
  const projects = useMemo(() => {
    const q = query.trim().toLowerCase()
    return data.projects.filter((row) => {
      if (!deadlineInWorkplacePeriod(row.deadline, periodFrom, periodTo)) return false
      if (!projectMatchesTile(row, tileFilter)) return false
      if (barStatus && row.status !== barStatus) return false
      if (barRisk && row.risk !== barRisk) return false
      if (barMine && !/руковод|исполн|я|мне|мо/i.test(row.role)) return false
      if (q && !`${row.name} ${row.code} ${row.role}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [data.projects, tileFilter, query, barStatus, barRisk, barMine, periodFrom, periodTo])
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set())
  const [myTasksOnly, setMyTasksOnly] = useState(true)
  const effectiveId = selectedId || projects[0]?.id || ''
  const selected = projects.find((p) => p.id === effectiveId)

  const taskFetch = useMemo(
    (): TurboProjectTasksFetchOptions => ({
      openOnly: true,
      assigneeOnly: myTasksOnly,
      limit: 200
    }),
    [myTasksOnly]
  )
  const tasksEmptyLabel = myTasksOnly
    ? 'Нет моих открытых задач в проекте'
    : 'Нет открытых задач в MPP'

  useEffect(() => {
    if (selectedId || !projects[0]?.id) return
    setSelectedId(projects[0].id)
  }, [projects, selectedId])

  useEffect(() => {
    setSelectedProjectTaskId('')
  }, [effectiveId])

  useEffect(() => {
    if (!effectiveId) return
    setExpandedIds((prev) => {
      if (prev.has(effectiveId)) return prev
      const next = new Set(prev)
      next.add(effectiveId)
      return next
    })
  }, [effectiveId])

  const turboLive = hasTurboSessionCredentials(data.user)
  const canFetchTasks = Boolean(effectiveId) && (turboLive || data.projects.length > 0)

  const projectTasks = useTurboProjectOpenTasks(
    effectiveId,
    data.user,
    data.erpFio,
    canFetchTasks,
    taskFetch
  )

  const projectTasksInPeriod = useMemo(
    () =>
      projectTasks.rows.filter((row) => deadlineInWorkplacePeriod(row.deadline, periodFrom, periodTo)),
    [projectTasks.rows, periodFrom, periodTo]
  )

  const selectedProjectTask = useMemo(
    () => projectTasksInPeriod.find((row) => row.id === selectedProjectTaskId) ?? null,
    [projectTasksInPeriod, selectedProjectTaskId]
  )

  const allProjects = data.projects
  const riskCount = useMemo(
    () => allProjects.filter((p) => p.riskTone === 'red' || p.riskTone === 'orange').length,
    [allProjects]
  )

  const doneTasksInView = useMemo(
    () => projectTasksInPeriod.filter((row) => row.status === 'Выполнена').length,
    [projectTasksInPeriod]
  )

  const tiles: SpecSummaryTile[] = useMemo(
    () => [
      { id: 'active', label: 'Активные проекты', value: String(allProjects.length || '—'), tone: 'green' },
      {
        id: 'tasks',
        label: myTasksOnly ? 'Мои открытые задачи' : 'Открытые задачи',
        value: myTasksOnly
          ? projectTasks.loading
            ? '…'
            : String(projectTasks.matchedCount || projectTasksInPeriod.length || '—')
          : String(allProjects.reduce((s, p) => s + p.tasks, 0) || '—'),
        tone: 'blue'
      },
      { id: 'risk', label: 'С риском', value: riskCount ? String(riskCount) : '—', tone: 'orange' },
      {
        id: 'done',
        label: 'Выполнено (выбранный)',
        value: selected && projectTasksInPeriod.length ? String(doneTasksInView) : '—',
        tone: 'purple'
      },
      { id: 'load', label: 'Загрузка', value: '—', tone: 'yellow' }
    ],
    [
      allProjects,
      riskCount,
      selected,
      myTasksOnly,
      projectTasks.loading,
      projectTasks.matchedCount,
      projectTasksInPeriod.length,
      doneTasksInView
    ]
  )

  const toggleExpanded = (projectId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
  }

  const fileLabel = selected?.fileId || selected?.id || '—'
  const [openHint, setOpenHint] = useState('')

  const openSelectedProject = (): void => {
    if (!selected) return
    setSelectedId(selected.id)
    if (selected.url && openHttpUrl(selected.url)) {
      setOpenHint('')
      return
    }
    setOpenHint('Нет внешней ссылки Turbo — карточка проекта открыта справа.')
  }

  return (
    <StandardTabChrome
      tabId="projects"
      userId={user.id || ''}
      defaults={DEFAULT_STANDARD_LAYOUT}
      chromeTiles={summaryTilesAsChrome(tiles, tileFilter === 'all' ? 'active' : tileFilter, (id) => {
        if (id === 'load') return
        setTileFilter((current) => (id === 'active' ? 'all' : toggleSimpleTile(current, id)))
      })}
      widgets={{
        filters: (
        <GridFilterBar
          search={{ value: query, onChange: setQuery, placeholder: 'Поиск по проектам…' }}
          selects={[
            {
              id: 'status',
              value: barStatus,
              emptyLabel: 'Статус: все',
              onChange: setBarStatus,
              options: toFilterOptions(uniqueFilterValues(data.projects.map((row) => row.status)))
            },
            {
              id: 'risk',
              value: barRisk,
              emptyLabel: 'Риск: все',
              onChange: setBarRisk,
              options: toFilterOptions(uniqueFilterValues(data.projects.map((row) => row.risk)))
            }
          ]}
          toggles={[{ id: 'mine', label: 'Только мои', checked: barMine, onChange: setBarMine }]}
          onReset={() => {
            setQuery('')
            setBarStatus('')
            setBarRisk('')
            setBarMine(false)
            setTileFilter('all')
          }}
        />
        ),
        main: (
        <div className="spec-v04-table-wrap wp-card">
          <table className="spec-v04-table">
            <thead>
              <tr>
                <th className="spec-v04-col-expand" aria-label="Развернуть" />
                <th>Проект</th>
                <th>Код</th>
                <th>Роль</th>
                <th>{myTasksOnly ? 'Мои задачи' : 'Задачи'}</th>
                <th>Статус</th>
                <th>Срок</th>
                <th>Прогресс</th>
                <th>Риск</th>
              </tr>
            </thead>
            <tbody>
              {!projects.length ? (
                <tr>
                  <td colSpan={9} className="spec-v04-empty">
                    {data.turboLoading
                      ? 'Загружаем портфель…'
                      : allProjects.length
                        ? 'Нет проектов по выбранной плитке'
                        : 'Портфель пуст'}
                  </td>
                </tr>
              ) : null}
              {projects.map((p) => {
                const expanded = expandedIds.has(p.id)
                return (
                  <Fragment key={p.id}>
                    <tr
                      className={selected?.id === p.id ? 'selected' : ''}
                      onClick={() => setSelectedId(p.id)}
                    >
                      <td className="spec-v04-col-expand">
                        <button
                          type="button"
                          className={`spec-v04-expand-btn${expanded ? ' open' : ''}`}
                          aria-expanded={expanded}
                          aria-label={expanded ? 'Свернуть задачи' : 'Развернуть задачи'}
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleExpanded(p.id)
                          }}
                        >
                          ▶
                        </button>
                      </td>
                      <td>
                        <strong>{p.name}</strong>
                      </td>
                      <td>{p.code}</td>
                      <td>{p.role}</td>
                      <td>
                        {myTasksOnly
                          ? p.id === effectiveId
                            ? projectTasks.loading
                              ? '…'
                              : projectTasks.matchedCount || projectTasksInPeriod.length
                            : '—'
                          : p.tasks}
                      </td>
                      <td>
                        <SpecPill tone={p.statusTone}>{p.status}</SpecPill>
                      </td>
                      <td>{p.deadline}</td>
                      <td>
                        <SpecProgress value={p.progress} />
                      </td>
                      <td>
                        <SpecPill tone={p.riskTone}>{p.risk}</SpecPill>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="spec-v04-row-expand">
                        <td colSpan={9}>
                          {p.id === effectiveId ? (
                            <ProjectTasksTable
                              rows={projectTasksInPeriod}
                              loading={projectTasks.loading}
                              error={projectTasks.error}
                              emptyLabel={tasksEmptyLabel}
                            />
                          ) : (
                            <ProjectExpandedTasks
                              projectId={p.id}
                              user={user}
                              erpFio={data.erpFio}
                              enabled={Boolean(p.id) && (turboLive || data.projects.length > 0)}
                              taskFetch={taskFetch}
                              emptyLabel={tasksEmptyLabel}
                            />
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        ),
        side: selected ? (
          <div className="spec-detail-card wp-card">
            <h2>{selected.name}</h2>
            <div className="spec-detail-tags">
              <SpecPill tone={selected.statusTone}>{selected.status}</SpecPill>
              <SpecPill tone={selected.riskTone}>{selected.risk}</SpecPill>
            </div>
            <dl className="spec-detail-meta">
              <div>
                <dt>Код / file_id</dt>
                <dd>
                  {selected.code}
                  {fileLabel !== selected.code ? ` · ${fileLabel}` : ''}
                </dd>
              </div>
              <div>
                <dt>Роль</dt>
                <dd>{selected.role}</dd>
              </div>
              <div>
                <dt>Срок</dt>
                <dd>{selected.deadline}</dd>
              </div>
              {selected.manager ? (
                <div>
                  <dt>Руководитель</dt>
                  <dd>{selected.manager}</dd>
                </div>
              ) : null}
            </dl>
            <p className="spec-v04-muted">
              {projectTasks.loading
                ? myTasksOnly
                  ? 'Загружаем мои открытые задачи…'
                  : 'Загружаем открытые задачи…'
                : myTasksOnly
                  ? projectTasks.matchedCount || projectTasksInPeriod.length
                    ? projectTasks.matchedCount > projectTasksInPeriod.length
                      ? `Моих открытых задач: ${projectTasks.matchedCount} · показано ${projectTasksInPeriod.length}`
                      : `Моих открытых задач: ${projectTasks.matchedCount || projectTasksInPeriod.length}`
                    : 'Нет моих открытых задач в проекте'
                  : projectTasks.matchedCount > projectTasksInPeriod.length
                    ? `Открытых задач (MPP): ${projectTasks.matchedCount} · показано ${projectTasksInPeriod.length}`
                    : `Открытых задач (MPP): ${projectTasks.matchedCount || selected.tasks}`}
            </p>
            <WorkplaceProgressSection
              user={user}
              rowId={`proj:${selected.id}`}
              baseProgress={selected.progress}
              actionContext={taskActionContextFromProject(selected)}
              projectUrl={selected.url}
            />
            <div className="spec-detail-pane spec-detail-pane-row">
              <h4>{myTasksOnly ? 'Мои задачи проекта' : 'Задачи проекта'}</h4>
              <label className="spec-v04-toggle-inline">
                <input
                  type="checkbox"
                  checked={myTasksOnly}
                  onChange={(e) => setMyTasksOnly(e.target.checked)}
                />
                Только мои
              </label>
            </div>
            <ProjectTasksTable
              rows={projectTasksInPeriod}
              loading={projectTasks.loading}
              error={projectTasks.error}
              emptyLabel={
                myTasksOnly ? 'Нет моих открытых задач в проекте' : 'Нет открытых задач в MPP'
              }
              selectedTaskId={selectedProjectTaskId}
              onSelectTask={setSelectedProjectTaskId}
            />
            {selectedProjectTask ? (
              <div className="project-task-detail">
                <h4>{selectedProjectTask.title}</h4>
                <WorkplaceProgressSection
                  user={user}
                  rowId={`turbo:${effectiveId}:${selectedProjectTask.taskUid || selectedProjectTask.id}`}
                  baseProgress={selectedProjectTask.progress ?? 0}
                  actionContext={taskActionContextFromTurboOpenTask(selectedProjectTask, effectiveId)}
                  projectUrl={selected.url}
                />
              </div>
            ) : null}
            {openHint ? <p className="spec-v04-muted">{openHint}</p> : null}
            <footer className="spec-detail-actions">
              <button type="button" className="btn-primary" onClick={openSelectedProject}>
                Открыть в проекте
              </button>
            </footer>
          </div>
        ) : (
          <div className="wp-card spec-v04-muted">Выберите проект</div>
        )
      }}
    />
  )
}
