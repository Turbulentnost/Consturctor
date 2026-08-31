import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  AgentKpi,
  BoardAgent,
  CalendarEvent,
  PositionOrchestrator,
  WorkflowFileItem,
  WorkflowBoard
} from '../api/types'
import { humanWhen, parseIso, sameDay, windowFor } from '../utils/calendar'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { personalAgentWorkflowId } from './personalAgent'
import {
  STATUS_LABEL,
  TASK_SOURCE_LABEL,
  TASK_STATUS_LABEL,
  type DayTask,
  type DayTaskStatus,
  type PreparedSolution,
  type ProcessStatus,
  type RunStage
} from './labels'

const EMPTY_BOARD: WorkflowBoard = {
  stats: { activeAgents: 0, runsToday: 0, errorsToday: 0, needsAttention: 0, nextRunAt: '' },
  agents: [],
  events: []
}

export interface WorkplaceAgent {
  id: string
  code: string
  name: string
  status: ProcessStatus
  stage: string
  owner: string
  due: string
  sla: string
  paused: boolean
  workflowId: string
  boardAgent?: BoardAgent
  tasks: DayTask[]
  stages: RunStage[]
  stageIndex: number
  solutions: PreparedSolution[]
  live: boolean
  standalone?: boolean
}

interface PersonalAgentSeed {
  userId: string
  fio: string
}

function eventStatus(status: string): DayTaskStatus {
  const value = (status || '').toLowerCase()
  if (value === 'ok' || value === 'done' || value === 'completed') return 'done'
  if (value === 'running' || value === 'active') return 'running'
  if (value === 'error' || value === 'needs_attention' || value === 'waiting_human') {
    return 'needs_decision'
  }
  return 'todo'
}

function formatDue(value: string): string {
  const stamp = parseIso(value)
  if (!stamp) return 'по календарю'
  const now = new Date()
  const hh = String(stamp.getHours()).padStart(2, '0')
  const mm = String(stamp.getMinutes()).padStart(2, '0')
  if (sameDay(stamp, now)) return `сегодня ${hh}:${mm}`
  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  if (sameDay(stamp, tomorrow)) return `завтра ${hh}:${mm}`
  return `${String(stamp.getDate()).padStart(2, '0')}.${String(stamp.getMonth() + 1).padStart(2, '0')} ${hh}:${mm}`
}

function eventToTask(event: CalendarEvent, processId: string): DayTask {
  const stamp = parseIso(event.startAt)
  const time = stamp
    ? `${String(stamp.getHours()).padStart(2, '0')}:${String(stamp.getMinutes()).padStart(2, '0')}`
    : '—'
  return {
    id: event.id || event.runId || `${event.workflowId}-${event.startAt}`,
    processId,
    time,
    title: event.title || event.subtitle || 'Прогон агента',
    source: 'agent',
    due: formatDue(event.startAt),
    status: eventStatus(event.status)
  }
}

function agentCode(title: string): string {
  const words = (title || '').split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return (title || 'AG').slice(0, 2).toUpperCase()
}

function agentProcessStatus(agent: BoardAgent): ProcessStatus {
  const last = (agent.lastRunStatus || '').toLowerCase()
  if (agent.paused) return 'PAUSED'
  if (agent.status === 'needs_attention' || last === 'error') return 'ERROR'
  if (last === 'running' || last === 'active') return 'ACTIVE'
  if (last === 'waiting_human' || last === 'hitl' || last === 'waiting') return 'WAITING_HUMAN'
  if (last === 'ok' || last === 'done' || last === 'completed') return 'COMPLETED'
  return 'READY'
}

function runStagePack(agent: BoardAgent, lastEvent?: CalendarEvent): { current: number; stages: RunStage[] } {
  const started = parseIso(lastEvent?.startAt || agent.lastRunAt)
  const last = (lastEvent?.status || agent.lastRunStatus || '').toLowerCase()
  const startHint = started ? humanWhen(started) : 'Ещё не запускался'
  let current = 0
  if (last === 'running' || last === 'active') current = 1
  else if (last === 'waiting_human' || last === 'hitl' || last === 'waiting') current = 2
  else if (last === 'ok' || last === 'done' || last === 'completed') current = 3
  else if (last === 'error') current = 1
  else if (started) current = 1
  return {
    current,
    stages: [
      { id: 'start', label: 'Запуск', hint: startHint, at: started ? startHint : undefined },
      {
        id: 'agent',
        label: 'Ход прогона',
        hint: last ? `статус: ${last}` : agent.triggerSummary || 'Нет активного этапа'
      },
      {
        id: 'human',
        label: 'Решение человека',
        hint: current >= 2 ? 'Агент передал результат' : 'После подготовки агента'
      },
      {
        id: 'next',
        label: 'Следующий этап',
        hint: current >= 3 ? 'Можно запускать следующий прогон' : 'Доступен после подтверждения'
      }
    ]
  }
}

function scoreFromOrchestrator(snap: PositionOrchestrator | null): number | null {
  const tiles = snap?.tiles || []
  let acc = 0
  let total = 0
  for (const tile of tiles) {
    if (tile.scorePercent == null) continue
    const raw = Number(tile.measure?.params?.weight ?? 0)
    const weight = Number.isFinite(raw) && raw > 0 ? raw : 100 / Math.max(tiles.length, 1)
    acc += tile.scorePercent * weight
    total += weight
  }
  return total > 0 ? acc / total : null
}

function buildPersonalAgent(seed: PersonalAgentSeed): WorkplaceAgent {
  return {
    id: personalAgentWorkflowId(seed.userId),
    code: 'БА',
    name: 'Базовый агент',
    status: 'READY',
    stage: 'Организационные вопросы',
    owner: '',
    due: 'ручной запуск',
    sla: 'без SLA',
    paused: false,
    workflowId: personalAgentWorkflowId(seed.userId),
    tasks: [],
    stages: [
      { id: 'request', label: 'Запрос', hint: 'Опишите организационную задачу' },
      { id: 'work', label: 'Выполнение', hint: 'Агент использует доступные инструменты' },
      { id: 'result', label: 'Результат', hint: 'Возвращает итог и следующий шаг' }
    ],
    stageIndex: 0,
    solutions: [],
    live: false,
    standalone: true
  }
}

export function buildWorkplaceAgents(board: WorkflowBoard, personal?: PersonalAgentSeed | null): WorkplaceAgent[] {
  const today = new Date()
  const todayEvents = board.events.filter((event) => {
    const stamp = parseIso(event.startAt)
    return stamp ? sameDay(stamp, today) : false
  })
  const workflows = board.agents.filter((item) => item.kind === 'workflow')
  const used = new Set<string>()
  const rows: WorkplaceAgent[] = []

  const pushAgent = (agent: BoardAgent, code?: string): void => {
    if (!agent.id || used.has(agent.id)) return
    used.add(agent.id)
    const events = todayEvents.filter((event) => event.workflowId === agent.id)
    const lastEvent = [...events].sort((a, b) => (a.startAt > b.startAt ? -1 : 1))[0]
    const pack = runStagePack(agent, lastEvent)
    const status = agentProcessStatus(agent)
    rows.push({
      id: agent.id,
      code: code || agentCode(agent.title),
      name: agent.title || 'ИИ-агент',
      status,
      stage: agent.triggerSummary || lastEvent?.subtitle || agent.nextRunLabel || 'Нет активного этапа',
      owner: '',
      due: agent.nextRunLabel || (agent.nextRunAt ? formatDue(agent.nextRunAt) : 'нет слота'),
      sla: agent.lastRunStatus || 'нет прогона',
      paused: agent.paused,
      workflowId: agent.id,
      boardAgent: agent,
      tasks: events.map((event) => eventToTask(event, agent.id)).sort((a, b) => a.time.localeCompare(b.time)),
      stages: pack.stages,
      stageIndex: pack.current,
      solutions: [],
      live: true
    })
  }

  for (const agent of workflows) pushAgent(agent)
  if (personal?.userId) rows.unshift(buildPersonalAgent(personal))

  return rows.sort((left, right) => {
    if (left.standalone && !right.standalone) return -1
    if (!left.standalone && right.standalone) return 1
    const leftPlan = left.tasks.length ? 0 : 1
    const rightPlan = right.tasks.length ? 0 : 1
    if (leftPlan !== rightPlan) return leftPlan - rightPlan
    return left.name.localeCompare(right.name, 'ru')
  })
}

function KpiIcon({ kind }: { kind: 'tasks' | 'alert' | 'kpi' }): React.JSX.Element {
  if (kind === 'alert') {
    return (
      <span className="wp-kpi-ico warn" aria-hidden>
        !
      </span>
    )
  }
  if (kind === 'kpi') {
    return (
      <span className="wp-kpi-ico chart" aria-hidden>
        ↗
      </span>
    )
  }
  return (
    <span className="wp-kpi-ico clip" aria-hidden>
      ≡
    </span>
  )
}

export function SummaryRow({
  total,
  done,
  attention,
  planFact,
  onOpenAttention,
  onOpenMetrics
}: {
  total: number
  done: number
  attention: number
  planFact: number
  onOpenAttention: () => void
  onOpenMetrics: () => void
}): React.JSX.Element {
  return (
    <div className="wp-summary">
      <article className="wp-summary-card">
        <KpiIcon kind="tasks" />
        <div>
          <h2>Задачи сегодня</h2>
          <p className="wp-summary-note">Прогоны агентов по календарю запусков</p>
          <div className="wp-summary-metrics">
            <div>
              <strong>{total}</strong>
              <span>На этот день</span>
            </div>
            <div>
              <strong>{done}</strong>
              <span>Выполненные</span>
            </div>
          </div>
        </div>
      </article>
      <button className="wp-summary-card wp-summary-btn" type="button" onClick={onOpenAttention}>
        <KpiIcon kind="alert" />
        <div>
          <h2>Задачи, требующие внимания</h2>
          <p className="wp-summary-note">Решения человека и отклонения SLA</p>
          <div className="wp-summary-metrics">
            <div>
              <strong>{attention}</strong>
              <span>На рассмотрении</span>
            </div>
          </div>
        </div>
      </button>
      <button className="wp-summary-card wp-summary-btn" type="button" onClick={onOpenMetrics}>
        <KpiIcon kind="kpi" />
        <div>
          <h2>План / факт KPI</h2>
          <p className="wp-summary-note">Исполнение показателей должности</p>
          <div className="wp-summary-metrics">
            <div>
              <strong>{planFact}%</strong>
              <span>Выполнено к плану</span>
            </div>
          </div>
        </div>
      </button>
    </div>
  )
}

function TaskTable({ tasks }: { tasks: DayTask[] }): React.JSX.Element {
  if (!tasks.length) {
    return <p className="wp-empty-plan">Плана на сегодня нет — карточку можно запустить вручную.</p>
  }
  const sourceLabel = (source: DayTask['source']): string => {
    if (source === 'agent') return 'Агент'
    if (source === 'onec') return '1С'
    return 'Человек'
  }
  return (
    <table className="wp-task-table">
      <thead>
        <tr>
          <th className="col-time">Время</th>
          <th className="col-task">Задача</th>
          <th className="col-source">Источник</th>
          <th className="col-due">Срок</th>
          <th className="col-status">Статус</th>
        </tr>
      </thead>
      <tbody>
        {tasks.map((task) => (
          <tr key={task.id}>
            <td className="col-time">{task.time}</td>
            <td className="col-task" title={task.title}>
              {task.title}
            </td>
            <td className="col-source" title={TASK_SOURCE_LABEL[task.source]}>
              {sourceLabel(task.source)}
            </td>
            <td className="col-due" title={task.due}>
              {task.due}
            </td>
            <td className="col-status">
              <span className={`wp-pill wp-pill-${task.status}`}>{TASK_STATUS_LABEL[task.status]}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function AgentPlanCard({
  agent,
  selected,
  onSelect,
  onOpen,
  onRun,
  onOpenFiles,
  recentFiles,
  onPause,
  onResume
}: {
  agent: WorkplaceAgent
  selected: boolean
  onSelect: (id: string) => void
  onOpen: (workflowId: string, title: string) => void
  onRun: (workflowId: string, title: string) => void
  onOpenFiles: (workflowId: string, title: string) => void
  recentFiles: WorkflowFileItem[]
  onPause: (workflowId: string) => void
  onResume: (workflowId: string) => void
}): React.JSX.Element {
  const hasPlan = agent.tasks.length > 0
  const lastTwoFiles = [...recentFiles]
    .sort((left, right) => (right.createdAt || '').localeCompare(left.createdAt || ''))
    .slice(0, 2)
  return (
    <article
      className={`wp-agent-card${selected ? ' selected' : ''}${hasPlan ? '' : ' idle'}`}
      onClick={() => {
        onSelect(agent.id)
        onOpen(agent.workflowId, agent.name)
      }}
    >
      <header className="wp-agent-head">
        <div>
          <div className="wp-code">{agent.code}</div>
          <h2>{agent.name}</h2>
          {!agent.standalone ? (
            <p>
              {STATUS_LABEL[agent.status]} · этап: {agent.stage}
              {agent.owner ? ` · владелец: ${agent.owner}` : ''}
            </p>
          ) : null}
        </div>
        <div className="wp-agent-meta">
          <span>{hasPlan ? `${agent.tasks.length} в плане` : 'Без плана на сегодня'}</span>
          <div className="wp-actions">
            <button
              className="btn-primary"
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onRun(agent.workflowId, agent.name)
              }}
            >
              Запустить
            </button>
            {!agent.standalone &&
              (agent.paused ? (
                <button
                  className="btn-ghost"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onResume(agent.workflowId)
                  }}
                >
                  Возобновить
                </button>
              ) : (
                <button
                  className="btn-ghost"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onPause(agent.workflowId)
                  }}
                >
                  Пауза
                </button>
              ))}
          </div>
        </div>
      </header>
      <div className={`wp-agent-content${agent.standalone ? ' single' : ''}`}>
        <div className="wp-agent-content-main">{hasPlan ? <TaskTable tasks={agent.tasks} /> : <p className="wp-empty-plan">Плана на сегодня нет — карточку можно запустить вручную.</p>}</div>
        {!agent.standalone ? (
          <aside
            className={`wp-agent-files-side${hasPlan ? ' with-plan' : ''}`}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="wp-agent-files-last">
              {lastTwoFiles.length ? (
                lastTwoFiles.map((file) => (
                  <button
                    key={file.id || file.name}
                    className="wp-agent-file-chip"
                    title={file.name}
                    type="button"
                    onClick={() => {
                      if (file.downloadUrl) {
                        void api.download(file.downloadUrl, file.name || 'file').catch(() => {
                          onOpenFiles(agent.workflowId, agent.name)
                        })
                        return
                      }
                      onOpenFiles(agent.workflowId, agent.name)
                    }}
                  >
                    <img src={fileTypeIconSrc(file.name || '')} alt="" />
                    <span>{file.name}</span>
                  </button>
                ))
              ) : (
                <span className="wp-agent-file-empty">Файлов пока нет</span>
              )}
            </div>
            <button
              className="wp-agent-files-link"
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onOpenFiles(agent.workflowId, agent.name)
              }}
            >
              Все файлы агента →
            </button>
          </aside>
        ) : null}
      </div>
    </article>
  )
}

export function ProcessStepper({
  agent
}: {
  agent: WorkplaceAgent
}): React.JSX.Element {
  const waiting = agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR'
  return (
    <section className="wp-card wp-stepper">
      <div className="wp-stepper-head">
        <div>
          <h2>Ход работы агента</h2>
          <p>
            {agent.name} · {agent.standalone ? 'персональный агент' : agent.workflowId ? `id ${agent.workflowId.slice(0, 8)}` : 'нет на сервере'} ·
            этап: {agent.stages[agent.stageIndex]?.label || 'не начат'}
          </p>
        </div>
      </div>
      <ol className="wp-steps">
        {agent.stages.map((stage, index) => {
          const state = index < agent.stageIndex ? 'done' : index === agent.stageIndex ? 'active' : 'pending'
          return (
            <li key={stage.id} className={`wp-step ${state}`}>
              <span className="wp-step-dot">{state === 'done' ? '✓' : index + 1}</span>
              <div>
                <strong>{stage.label}</strong>
                <small>
                  {stage.at ? `${stage.at} · ` : ''}
                  {stage.hint}
                </small>
              </div>
            </li>
          )
        })}
      </ol>
      {waiting && <p className="wp-step-note">Сначала подтвердите решение или разберите ошибку в прогоне.</p>}
    </section>
  )
}

function kpiScore(kpi: AgentKpi | null): number | null {
  const tiles = kpi?.tiles || []
  const scores = tiles.map((tile) => tile.scorePercent).filter((value): value is number => value != null)
  if (!scores.length) return null
  return Math.round(scores.reduce((acc, value) => acc + value, 0) / scores.length)
}

export function DetailRail({
  agent
}: {
  agent: WorkplaceAgent
}): React.JSX.Element {
  const [kpi, setKpi] = useState<AgentKpi | null>(null)

  useEffect(() => {
    if (!agent.workflowId || agent.standalone) {
      setKpi(null)
      return
    }
    let alive = true
    void api.getWorkflowKpi(agent.workflowId).catch(() => null).then((nextKpi) => {
      if (!alive) return
      setKpi(nextKpi)
    })
    return () => {
      alive = false
    }
  }, [agent.workflowId])

  const score = kpiScore(kpi)

  return (
    <aside className="wp-rail">
      <section className="wp-card">
        <h2>Показатели процесса</h2>
        {agent.standalone ? <p>Для базового агента KPI процесса не рассчитываются.</p> : null}
        {!agent.standalone && kpi?.tiles.length ? (
          <div className="wp-kpi-mini">
            {kpi.tiles.slice(0, 6).map((tile) => (
              <div key={tile.id || tile.name}>
                <span>{tile.name}</span>
                <strong>
                  {tile.scorePercent != null ? `${Math.round(tile.scorePercent)}%` : tile.fact?.value ?? '—'}
                </strong>
              </div>
            ))}
            {score != null && (
              <div>
                <span>Итого план/факт</span>
                <strong>{score}%</strong>
              </div>
            )}
          </div>
        ) : !agent.standalone ? (
          <p>KPI этого агента ещё не посчитаны на сервере.</p>
        ) : null}
      </section>
    </aside>
  )
}

export function useWorkplaceData(): {
  board: WorkflowBoard
  orch: PositionOrchestrator | null
  agents: WorkplaceAgent[]
  loading: boolean
  error: string
  flash: string
  reload: () => Promise<void>
  pause: (workflowId: string) => Promise<void>
  resume: (workflowId: string) => Promise<void>
}

export function useWorkplaceData(personal?: PersonalAgentSeed | null): {
  board: WorkflowBoard
  orch: PositionOrchestrator | null
  agents: WorkplaceAgent[]
  loading: boolean
  error: string
  flash: string
  reload: () => Promise<void>
  pause: (workflowId: string) => Promise<void>
  resume: (workflowId: string) => Promise<void>
} {
  const [board, setBoard] = useState<WorkflowBoard>(EMPTY_BOARD)
  const [orch, setOrch] = useState<PositionOrchestrator | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [flash, setFlash] = useState('')
  const reloadRef = useRef<() => Promise<void>>(async () => undefined)

  const reload = async (): Promise<void> => {
    const win = windowFor('week', new Date())
    try {
      const [nextBoard, nextOrch] = await Promise.all([
        api.getWorkflowBoard({ window_from: win.from, window_to: win.to }),
        api.getOrchestrator().catch(() => null)
      ])
      setBoard(nextBoard)
      setOrch(nextOrch)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Нет связи с сервером Constructor')
    } finally {
      setLoading(false)
    }
  }
  reloadRef.current = reload

  useEffect(() => {
    void reload()
    const unsubscribe = window.api.onBoardUpdated?.(() => {
      void reloadRef.current()
    })
    return () => unsubscribe?.()
  }, [])

  const notice = (text: string): void => {
    setFlash(text)
    window.setTimeout(() => setFlash(''), 4000)
  }

  const pause = async (workflowId: string): Promise<void> => {
    if (!workflowId) return
    try {
      await api.stopWorkflowAutoRun(workflowId)
      await reload()
      notice('Автозапуск агента приостановлен')
    } catch (err) {
      notice(err instanceof Error ? err.message : 'Не удалось поставить на паузу')
    }
  }

  const resume = async (workflowId: string): Promise<void> => {
    if (!workflowId) return
    try {
      await api.resumeWorkflowAutoRun(workflowId)
      await reload()
      notice('Автозапуск агента возобновлён')
    } catch (err) {
      notice(err instanceof Error ? err.message : 'Не удалось возобновить агента')
    }
  }

  const agents = useMemo(() => buildWorkplaceAgents(board, personal), [board, personal?.userId, personal?.fio])
  return { board, orch, agents, loading, error, flash, reload, pause, resume }
}

export function TodayWorkplace({
  userId,
  userFio,
  onOpenDecisions,
  onOpenMetrics,
  onOpen,
  onRun,
  onOpenFiles
}: {
  userId: string
  userFio: string
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpen: (workflowId: string, title: string) => void
  onRun: (workflowId: string, title: string) => void
  onOpenFiles: (workflowId: string, title: string) => void
}): React.JSX.Element {
  const { board, orch, agents, loading, error, flash, pause, resume } = useWorkplaceData({
    userId,
    fio: userFio
  })
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ProcessStatus | ''>('')
  const [selectedId, setSelectedId] = useState('')
  const [recentFilesByWorkflow, setRecentFilesByWorkflow] = useState<Record<string, WorkflowFileItem[]>>({})
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return agents.filter((agent) => {
      if (status && agent.status !== status) return false
      if (q && !`${agent.name} ${agent.code} ${agent.workflowId}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [agents, query, status])
  const selected = visible.find((item) => item.id === selectedId) || visible[0]

  const todayEvents = board.events.filter((event) => {
    const stamp = parseIso(event.startAt)
    return stamp ? sameDay(stamp, new Date()) : false
  })
  const total = todayEvents.length || board.stats.runsToday
  const done = todayEvents.filter((event) => eventStatus(event.status) === 'done').length
  const attention = Math.max(
    board.stats.needsAttention,
    agents.filter((item) => item.status === 'WAITING_HUMAN' || item.status === 'ERROR').length
  )
  const planFact = Math.round(scoreFromOrchestrator(orch) ?? 0)
  const linked = agents.filter((item) => item.live).length

  useEffect(() => {
    const targets = agents
      .map((agent) => agent.workflowId)
      .filter((workflowId) => workflowId && !workflowId.startsWith('personal-agent:'))
    if (!targets.length) {
      setRecentFilesByWorkflow({})
      return
    }
    let alive = true
    void Promise.all(
      targets.map(async (workflowId) => {
        const files = await api.listWorkflowFiles(workflowId).catch(() => [] as WorkflowFileItem[])
        const produced = files.filter((file) => {
          const source = String(file.source || '').toLowerCase()
          const origin = String(file.origin || '').toLowerCase()
          return source === 'agent' || source === 'result' || origin.includes('agent')
        })
        return [workflowId, produced] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const next: Record<string, WorkflowFileItem[]> = {}
      for (const [workflowId, files] of pairs) next[workflowId] = files
      setRecentFilesByWorkflow(next)
    })
    return () => {
      alive = false
    }
  }, [agents])

  return (
    <div className="wp-page wp-today">
      <div className="wp-head">
        <div>
          <h1 className="page-title">Рабочее место сотрудника</h1>
        </div>
        <span className="orch-badge">{loading ? 'загрузка' : `${linked} агентов`}</span>
      </div>

      {flash ? <div className="wp-toast">{flash}</div> : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}

      <SummaryRow
        total={total}
        done={done}
        attention={attention}
        planFact={planFact}
        onOpenAttention={onOpenDecisions}
        onOpenMetrics={onOpenMetrics}
      />

      <div className="wp-filters-row">
        <select className="wp-select" value={status} onChange={(e) => setStatus(e.target.value as ProcessStatus | '')}>
          <option value="">Все статусы</option>
          {Object.entries(STATUS_LABEL).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <input
          className="wp-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск агента или id"
        />
        <button
          className="btn-ghost"
          type="button"
          onClick={() => {
            setQuery('')
            setStatus('')
          }}
        >
          Сбросить
        </button>
      </div>

      <div className="wp-today-layout">
        <div className="wp-today-main">
          <h2 className="wp-section-title">Агенты и план на сегодня</h2>
          {loading ? <div className="wp-card">Загружаем агентов с сервера…</div> : null}
          {!loading && !visible.length ? (
            <div className="wp-card">
              На сервере нет опубликованных агентов. Создайте и опубликуйте их в Constructor — они появятся здесь.
            </div>
          ) : null}
          {visible.map((agent) => (
            <AgentPlanCard
              key={agent.id}
              agent={agent}
              selected={selected?.id === agent.id}
              onSelect={setSelectedId}
              onOpen={onOpen}
              onRun={onRun}
              onOpenFiles={onOpenFiles}
              recentFiles={recentFilesByWorkflow[agent.workflowId] || []}
              onPause={(id) => void pause(id)}
              onResume={(id) => void resume(id)}
            />
          ))}
          {selected ? <ProcessStepper agent={selected} /> : null}
        </div>
        {selected ? (
          <DetailRail agent={selected} />
        ) : null}
      </div>
    </div>
  )
}
