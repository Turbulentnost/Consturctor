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
import { CardMenu } from '../components/agents/CardMenu'
import { humanResponseDelayColor } from './humanResponseColor'
import { personalAgentWorkflowId } from './personalAgent'
import { useRuns } from '../store/runs'
import {
  findPendingToolRequest,
  isUserFacingResultFile,
  readVerdict,
  runDecisionId,
  writeVerdict
} from './preparedDecisions'
import { buildProcessKpiMetrics, latestAgentRun } from './kpiMetrics'
import type { AgentRunHistoryItem } from '../api/types'
import { isLiveRunState } from '../store/liveRun'
import {
  STATUS_LABEL,
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
  if (value === 'skipped') return 'done'
  if (value === 'error' || value === 'needs_attention' || value === 'waiting_human') {
    return 'needs_decision'
  }
  return 'todo'
}

function isNoiseBoardEvent(event: CalendarEvent): boolean {
  const status = (event.status || '').toLowerCase()
  if (status === 'canceled' || status === 'cancelled') return true
  const text = `${event.subtitle || ''} ${event.title || ''}`.trim().toLowerCase()
  return text.startsWith('агент уже выполняется')
}

function formatDue(value: string): string {
  const stamp = parseIso(value)
  if (!stamp) return 'по календарю'
  const now = new Date()
  const hh = String(stamp.getHours()).padStart(2, '0')
  const mm = String(stamp.getMinutes()).padStart(2, '0')
  if (sameDay(stamp, now)) return `Сегодня, ${hh}:${mm}`
  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  if (sameDay(stamp, tomorrow)) return `Завтра, ${hh}:${mm}`
  return `${String(stamp.getDate()).padStart(2, '0')}.${String(stamp.getMonth() + 1).padStart(2, '0')}, ${hh}:${mm}`
}

function isTechnicalTaskText(text: string): boolean {
  const value = (text || '').trim()
  if (!value) return true
  if (value.startsWith('{') || value.startsWith('[')) return true
  if (/errno\s*\d+|traceback|invalid argument|filenotfounderror/i.test(value)) return true
  if (/"verdict"\s*:/i.test(value) || /ответь только json/i.test(value)) return true
  if (/^агент уже выполняется/i.test(value)) return true
  return false
}

function taskTitleFromEvent(event: CalendarEvent, agentName: string): string {
  const agent = (agentName || '').trim()
  for (const raw of [event.subtitle, event.title]) {
    const text = (raw || '').trim()
    if (!text || text === agent || isTechnicalTaskText(text)) continue
    return text
  }
  return 'Запуск агента'
}

function eventToTask(event: CalendarEvent, processId: string, agentName: string): DayTask {
  const stamp = parseIso(event.startAt)
  const time = stamp
    ? `${String(stamp.getHours()).padStart(2, '0')}:${String(stamp.getMinutes()).padStart(2, '0')}`
    : '—'
  const status = eventStatus(event.status)
  return {
    id: event.id || event.runId || `${event.workflowId}-${event.startAt}`,
    processId,
    time,
    title: taskTitleFromEvent(event, agentName),
    source: status === 'needs_decision' ? 'human' : 'agent',
    due: formatDue(event.startAt),
    status,
    runId: (event.runId || '').trim() || undefined
  }
}

function pickRunId(agent: WorkplaceAgent): string {
  for (const task of agent.tasks) {
    if (task.runId && (task.status === 'running' || task.status === 'needs_decision')) {
      return task.runId
    }
  }
  const hasOpenSlot = agent.tasks.some((task) => task.status === 'todo' || task.status === 'running')
  if (hasOpenSlot) return ''
  for (const task of agent.tasks) {
    if (task.runId) return task.runId
  }
  return ''
}

function latestTaskStatus(agent: WorkplaceAgent): string {
  const last = agent.tasks[agent.tasks.length - 1]
  if (!last) return (agent.boardAgent?.lastRunStatus || '').toLowerCase()
  if (last.status === 'needs_decision') return 'waiting_human'
  if (last.status === 'running') return 'running'
  if (last.status === 'done') return 'ok'
  if (last.status === 'todo') return 'scheduled'
  return (agent.boardAgent?.lastRunStatus || '').toLowerCase()
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
  else if (last === 'scheduled' || last === 'missed') current = 0
  else if (started) current = 1
  return {
    current,
    stages: [
      { id: 'start', label: 'Запуск', hint: startHint, at: started ? startHint : undefined },
      {
        id: 'agent',
        label: 'Ход запуска',
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
        hint: current >= 3 ? 'Можно запустить снова' : 'Доступен после подтверждения'
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

export function agentHasWorkToday(agent: WorkplaceAgent, today = new Date()): boolean {
  if (agent.standalone) return false
  if (agent.tasks.length > 0) return true
  const last = parseIso(agent.boardAgent?.lastRunAt || '')
  if (last && sameDay(last, today)) return true
  const next = parseIso(agent.boardAgent?.nextRunAt || '')
  if (next && sameDay(next, today)) return true
  const lastStatus = (agent.boardAgent?.lastRunStatus || '').toLowerCase()
  if (
    lastStatus === 'running' ||
    lastStatus === 'active' ||
    lastStatus === 'waiting_human' ||
    lastStatus === 'hitl' ||
    lastStatus === 'waiting'
  ) {
    return true
  }
  return agent.status === 'ACTIVE' || agent.status === 'WAITING_HUMAN'
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
    const stage =
      [agent.triggerSummary, lastEvent?.subtitle, agent.nextRunLabel].find(
        (text) => Boolean(text) && !isTechnicalTaskText(text || '')
      ) || 'Нет активного этапа'
    rows.push({
      id: agent.id,
      code: code || agentCode(agent.title),
      name: agent.title || 'ИИ-агент',
      status,
      stage,
      owner: '',
      due: agent.nextRunLabel || (agent.nextRunAt ? formatDue(agent.nextRunAt) : 'нет слота'),
      sla: agent.lastRunStatus || 'нет запуска',
      paused: agent.paused,
      workflowId: agent.id,
      boardAgent: agent,
      tasks: events
        .filter((event) => !isNoiseBoardEvent(event))
        .map((event) => {
          const task = eventToTask(event, agent.id, agent.title || 'ИИ-агент')
          const runId = (event.runId || task.runId || '').trim()
          if (runId && readVerdict(agent.id, runDecisionId(runId)) === 'confirmed') {
            return { ...task, status: 'done' as DayTaskStatus, source: 'agent' as const }
          }
          if (/work_result/i.test(task.title) && task.status === 'needs_decision') {
            return { ...task, status: 'done' as DayTaskStatus, source: 'agent' as const }
          }
          return task
        })
        .sort((a, b) => a.time.localeCompare(b.time)),
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
          <div className="wp-summary-metrics">
            <div>
              <strong>{total}</strong>
              <span>Всего задач</span>
            </div>
            <div>
              <strong>{done}</strong>
              <span>Готово</span>
            </div>
          </div>
        </div>
      </article>
      <button className="wp-summary-card wp-summary-btn" type="button" onClick={onOpenAttention}>
        <KpiIcon kind="alert" />
        <div>
          <h2>Требуют решения</h2>
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
          <h2>План / факт</h2>
          <div className="wp-summary-metrics">
            <div>
              <strong>{planFact}%</strong>
              <span>Выполнено задач</span>
            </div>
          </div>
        </div>
      </button>
    </div>
  )
}

function tasksWord(count: number): string {
  const n10 = count % 10
  const n100 = count % 100
  if (n10 === 1 && n100 !== 11) return 'задача'
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return 'задачи'
  return 'задач'
}

function groupWorkBadge(agent: WorkplaceAgent): { label: string; tone: 'work' | 'done' | 'pause' } {
  if (agent.paused) return { label: 'Пауза', tone: 'pause' }
  if (agent.tasks.length > 0 && agent.tasks.every((task) => task.status === 'done')) {
    return { label: 'Готово', tone: 'done' }
  }
  if (agent.status === 'READY' && !agent.tasks.length) return { label: 'Готов', tone: 'work' }
  return { label: 'В работе', tone: 'work' }
}

function IconRobot(): React.JSX.Element {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="5" y="8" width="14" height="11" rx="3" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="9.2" cy="13" r="1.15" fill="currentColor" />
      <circle cx="14.8" cy="13" r="1.15" fill="currentColor" />
      <path d="M12 8V5.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <circle cx="12" cy="4.1" r="1.05" fill="currentColor" />
    </svg>
  )
}

function IconPerson(): React.JSX.Element {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="8" r="3.1" stroke="currentColor" strokeWidth="1.7" />
      <path
        d="M5.6 19c1.15-3.15 3.35-4.7 6.4-4.7s5.25 1.55 6.4 4.7"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  )
}

function IconCalendar(): React.JSX.Element {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="4" y="6" width="16" height="14" rx="2.2" stroke="currentColor" strokeWidth="1.7" />
      <path d="M8 4.5v4M16 4.5v4M4 11h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  )
}

function TaskRows({
  tasks,
  onOpenTask
}: {
  tasks: DayTask[]
  onOpenTask: (task: DayTask) => void
}): React.JSX.Element {
  if (!tasks.length) {
    return <p className="wp-empty-plan">Плана на сегодня нет — запустите агента из меню карточки.</p>
  }
  return (
    <ul className="wp-task-list">
      {tasks.map((task) => {
        const human = task.source === 'human'
        return (
          <li key={task.id}>
            <button className="wp-task-row" type="button" onClick={() => onOpenTask(task)}>
              <span className="wp-task-time">{task.time}</span>
              <span className="wp-task-title" title={task.title}>
                {task.title}
              </span>
              <span className={`wp-task-mode ${human ? 'human' : 'auto'}`}>
                {human ? <IconPerson /> : <IconRobot />}
                {human ? 'Решение человека' : 'Автоматически'}
              </span>
              <span className="wp-task-due">
                <IconCalendar />
                {task.due}
              </span>
              <span className={`wp-task-status wp-pill wp-pill-${task.status}`}>{TASK_STATUS_LABEL[task.status]}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

export function AgentPlanCard({
  agent,
  selected,
  onSelect,
  onOpen,
  onRun,
  onOpenFiles,
  onHistory,
  onSchedule,
  onDelete,
  onPause,
  onResume
}: {
  agent: WorkplaceAgent
  selected: boolean
  onSelect: (id: string) => void
  onOpen: (workflowId: string, title: string) => void
  onRun: (workflowId: string, title: string) => void
  onOpenFiles: (workflowId: string, title: string) => void
  onHistory: (workflowId: string, title: string) => void
  onSchedule: (workflowId: string, title: string) => void
  onDelete: (workflowId: string, title: string) => void
  onPause: (workflowId: string) => void
  onResume: (workflowId: string) => void
}): React.JSX.Element {
  const hasPlan = agent.tasks.length > 0
  const [expanded, setExpanded] = useState(hasPlan)
  const badge = groupWorkBadge(agent)
  return (
    <article className={`wp-agent-card${selected ? ' selected' : ''}${hasPlan ? '' : ' idle'}`}>
      <header className="wp-agent-head">
        <button
          className={`wp-agent-toggle${expanded ? ' open' : ''}`}
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? 'Свернуть' : 'Развернуть'}
          onClick={() => {
            onSelect(agent.id)
            setExpanded((current) => !current)
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
            <path d="M2.2 4.2L6 8l3.8-3.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <button
          className="wp-agent-title-btn"
          type="button"
          onClick={() => {
            onSelect(agent.id)
            setExpanded(true)
          }}
        >
          <h2>{agent.name}</h2>
        </button>
        <span className={`wp-group-badge ${badge.tone}`}>{badge.label}</span>
        <span className="wp-group-count">
          {agent.tasks.length} {tasksWord(agent.tasks.length)}
        </span>
        <div className="wp-agent-head-actions">
          {!agent.standalone ? (
            <button
              className="wp-history-link"
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onHistory(agent.workflowId, agent.name)
              }}
            >
              История
            </button>
          ) : null}
          {!agent.standalone ? (
            <CardMenu
              items={[
                { label: 'Запустить', onClick: () => onRun(agent.workflowId, agent.name) },
                { label: 'Открыть агента', onClick: () => onOpen(agent.workflowId, agent.name) },
                { label: 'Посмотреть историю', onClick: () => onHistory(agent.workflowId, agent.name) },
                { label: 'Файлы агента', onClick: () => onOpenFiles(agent.workflowId, agent.name) },
                { label: 'Изменить расписание', onClick: () => onSchedule(agent.workflowId, agent.name) },
                agent.paused
                  ? { label: 'Возобновить', onClick: () => onResume(agent.workflowId) }
                  : { label: 'Приостановить', onClick: () => onPause(agent.workflowId) },
                { label: 'Удалить', onClick: () => onDelete(agent.workflowId, agent.name), danger: true, separatorBefore: true }
              ]}
            />
          ) : (
            <CardMenu items={[{ label: 'Запустить', onClick: () => onRun(agent.workflowId, agent.name) }]} />
          )}
        </div>
      </header>
      {expanded ? (
        <div className="wp-agent-content single">
          <TaskRows
            tasks={agent.tasks}
            onOpenTask={() => onHistory(agent.workflowId, agent.name)}
          />
        </div>
      ) : null}
    </article>
  )
}

export function ProcessStepper({
  agent,
  onRun,
  onOpenRun,
  onOpenDecisions
}: {
  agent: WorkplaceAgent
  onRun: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  onOpenDecisions: () => void
}): React.JSX.Element {
  const waiting = agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR'
  const paused = agent.paused || agent.status === 'PAUSED'
  const stageId = agent.stages[agent.stageIndex]?.id || 'start'

  const advance = (): void => {
    if (waiting || paused) return
    const slotStatus = latestTaskStatus(agent)
    if (stageId === 'start' || stageId === 'next' || slotStatus === 'scheduled' || slotStatus === 'missed') {
      onRun(agent.workflowId, agent.name)
      return
    }
    if (stageId === 'human' || agent.status === 'WAITING_HUMAN') {
      onOpenDecisions()
      return
    }
    const runId = pickRunId(agent)
    if (runId) {
      onOpenRun(agent.workflowId, agent.name, runId)
      return
    }
    onRun(agent.workflowId, agent.name)
  }

  return (
    <section className="wp-card wp-stepper">
      <div className="wp-stepper-head">
        <div>
          <h2>Ход процесса</h2>
          <p>
            {agent.name} · этап: {agent.stages[agent.stageIndex]?.label || 'не начат'}
          </p>
        </div>
      </div>
      <ol className="wp-steps">
        {agent.stages.map((stage, index) => {
          const state = index < agent.stageIndex ? 'done' : index === agent.stageIndex ? 'active' : 'pending'
          const isLast = index === agent.stages.length - 1
          return (
            <li key={stage.id} className={`wp-step ${state}`}>
              <div className="wp-step-rail">
                <span className="wp-step-dot">{state === 'done' ? '✓' : index + 1}</span>
                {!isLast ? (
                  <span className="wp-step-connector" aria-hidden>
                    <span className="wp-step-connector-line" />
                    <span className="wp-step-connector-arrow" />
                  </span>
                ) : null}
              </div>
              <div className="wp-step-body">
                <strong>{stage.label}</strong>
                <small>
                  {stage.at ? `${stage.at} · ` : ''}
                  {stage.hint}
                </small>
              </div>
            </li>
          )
        })}
        <li className="wp-step-next-cell">
          <button
            className="btn-ghost wp-step-next"
            type="button"
            disabled={waiting || paused}
            onClick={advance}
          >
            Перейти к следующему этапу
          </button>
        </li>
      </ol>
      {waiting ? (
        <p className="wp-step-note">Сначала подтвердите решение или разберите ошибку в запуске.</p>
      ) : paused ? (
        <p className="wp-step-note">Агент на паузе — возобновите автозапуск в карточке процесса.</p>
      ) : null}
    </section>
  )
}

function formatMinutes(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const minutes = Math.max(0, Math.round(value))
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`
}

function agentIsOverdue(agent: WorkplaceAgent, now = new Date()): boolean {
  if (agent.standalone) return false
  if (agent.status === 'ERROR' || agent.status === 'WAITING_HUMAN') return true
  const next = parseIso(agent.boardAgent?.nextRunAt || '')
  if (next && next.getTime() < now.getTime()) return true
  const last = (agent.boardAgent?.lastRunStatus || '').toLowerCase()
  return last === 'error' || last === 'failed' || last === 'waiting_human' || last === 'hitl'
}

type TodaySort = '' | 'time' | 'status' | 'name'

function taskClockMs(time: string, now = new Date()): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec((time || '').trim())
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null
  const stamp = new Date(now)
  stamp.setHours(hours, minutes, 0, 0)
  return stamp.getTime()
}

function agentSortTime(agent: WorkplaceAgent, now = new Date()): number {
  const stamps: number[] = []
  const next = parseIso(agent.boardAgent?.nextRunAt || '')
  if (next) stamps.push(next.getTime())
  const last = parseIso(agent.boardAgent?.lastRunAt || '')
  if (last) stamps.push(last.getTime())
  for (const task of agent.tasks) {
    const clock = taskClockMs(task.time, now)
    if (clock != null) stamps.push(clock)
  }
  return stamps.length ? Math.min(...stamps) : Number.POSITIVE_INFINITY
}

function agentStatusRank(agent: WorkplaceAgent): number {
  if (agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR') return 0
  if (agent.tasks.some((task) => task.status === 'needs_decision')) return 0
  if (agent.status === 'ACTIVE') return 1
  if (agent.tasks.some((task) => task.status === 'running')) return 1
  if (agent.status === 'READY') return 2
  if (agent.status === 'PAUSED') return 3
  if (agent.status === 'COMPLETED') return 4
  return 5
}

function taskStatusRank(status: DayTaskStatus): number {
  if (status === 'needs_decision') return 0
  if (status === 'running') return 1
  if (status === 'todo') return 2
  return 3
}

function sortTodayAgents(agents: WorkplaceAgent[], sort: TodaySort): WorkplaceAgent[] {
  if (!sort) return agents
  const rows = [...agents]
  rows.sort((left, right) => {
    if (sort === 'time') {
      const cmp = agentSortTime(left) - agentSortTime(right)
      return cmp !== 0 ? cmp : left.name.localeCompare(right.name, 'ru')
    }
    if (sort === 'status') {
      const cmp = agentStatusRank(left) - agentStatusRank(right)
      return cmp !== 0 ? cmp : left.name.localeCompare(right.name, 'ru')
    }
    return left.name.localeCompare(right.name, 'ru')
  })
  return rows.map((agent) => {
    const tasks = [...agent.tasks]
    if (sort === 'time') tasks.sort((left, right) => left.time.localeCompare(right.time))
    else if (sort === 'status') {
      tasks.sort((left, right) => {
        const cmp = taskStatusRank(left.status) - taskStatusRank(right.status)
        return cmp !== 0 ? cmp : left.time.localeCompare(right.time)
      })
    } else {
      tasks.sort((left, right) => left.title.localeCompare(right.title, 'ru'))
    }
    return { ...agent, tasks }
  })
}

type PreparedCard = {
  id: string
  title: string
  note: string
  meta: string
  workflowId: string
  agentName: string
  kind: 'file' | 'waiting'
  fileId?: string
  fileUrl?: string
  runId?: string
  requestId?: string
  live?: boolean
}

type ProcessKpiRow = {
  id: string
  name: string
  planFact: number | null
  agentDelay: number | null
  humanDelay: number | null
  automation: number | null
}

function PreparedSolutionsRail({
  items,
  onOpenDecisions,
  onOpenItem,
  onConfirmItem,
  onReturnItem,
  busyId
}: {
  items: PreparedCard[]
  onOpenDecisions: () => void
  onOpenItem: (item: PreparedCard) => void
  onConfirmItem: (item: PreparedCard) => void
  onReturnItem: (item: PreparedCard) => void
  busyId: string
}): React.JSX.Element {
  const featured = items[0]
  const busy = featured ? busyId === featured.id : false
  return (
    <section className="wp-rail-card wp-rail-solutions">
      <header className="wp-rail-card-head">
        <h2>Подготовленные решения</h2>
        <div className="wp-rail-card-actions">
          <button className="wp-rail-link" type="button" onClick={onOpenDecisions}>
            История
          </button>
          <CardMenu
            items={[
              { label: 'Открыть решения', onClick: onOpenDecisions },
              ...(featured ? [{ label: 'Открыть решение', onClick: () => onOpenItem(featured) }] : []),
              { label: 'Посмотреть историю', onClick: onOpenDecisions }
            ]}
          />
        </div>
      </header>
      {!featured ? (
        <p className="wp-rail-empty">Пока нет подготовленных решений. Они появятся после запусков агентов.</p>
      ) : (
        <article className="wp-solution-card">
          <div className="wp-solution-ico" aria-hidden>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M7 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9.5A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5Z" />
              <path d="M14 3.5V8h4M8 12h8M8 15.5h6" strokeLinecap="round" />
            </svg>
          </div>
          <div className="wp-solution-body">
            <h3>{featured.title}</h3>
            <p className="wp-solution-meta">{featured.meta}</p>
            <p className="wp-solution-note">{featured.note}</p>
            <div className="wp-solution-actions">
              <button
                className="btn-primary"
                type="button"
                disabled={busy}
                onClick={() => onOpenItem(featured)}
              >
                Открыть
              </button>
              <button
                className="btn-primary"
                type="button"
                disabled={busy}
                onClick={() => onConfirmItem(featured)}
              >
                {busy ? 'Подтверждаем…' : 'Подтвердить'}
              </button>
              <button
                className="btn-ghost"
                type="button"
                disabled={busy}
                onClick={() => onReturnItem(featured)}
              >
                Вернуть
              </button>
            </div>
          </div>
        </article>
      )}
      {items.length > 1 ? (
        <button className="wp-rail-more" type="button" onClick={onOpenDecisions}>
          Ещё {items.length - 1} → вкладка «Решения»
        </button>
      ) : null}
    </section>
  )
}

function ProcessKpiRail({
  rows,
  onOpenMetrics
}: {
  rows: ProcessKpiRow[]
  onOpenMetrics: () => void
}): React.JSX.Element {
  const totals = rows.reduce(
    (acc, row) => {
      if (row.planFact != null) {
        acc.planFact += row.planFact
        acc.planCount += 1
      }
      if (row.agentDelay != null) {
        acc.agentDelay += row.agentDelay
        acc.agentCount += 1
      }
      if (row.humanDelay != null) {
        acc.humanDelay += row.humanDelay
        acc.humanCount += 1
      }
      if (row.automation != null) {
        acc.automation += row.automation
        acc.autoCount += 1
      }
      return acc
    },
    {
      planFact: 0,
      planCount: 0,
      agentDelay: 0,
      agentCount: 0,
      humanDelay: 0,
      humanCount: 0,
      automation: 0,
      autoCount: 0
    }
  )
  const avg = (sum: number, count: number): number | null => (count ? Math.round(sum / count) : null)

  return (
    <section className="wp-rail-card wp-rail-kpi">
      <header className="wp-rail-card-head">
        <h2>KPI по процессам</h2>
        <div className="wp-rail-card-actions">
          <button className="wp-rail-link" type="button" onClick={onOpenMetrics}>
            История
          </button>
          <CardMenu
            items={[
              { label: 'Открыть показатели', onClick: onOpenMetrics },
              { label: 'Посмотреть историю', onClick: onOpenMetrics }
            ]}
          />
        </div>
      </header>
      {!rows.length ? (
        <p className="wp-rail-empty">Нет процессов с KPI на сегодня.</p>
      ) : (
        <div className="wp-kpi-table-wrap">
          <table className="wp-kpi-table wp-kpi-table-rail">
            <thead>
              <tr>
                <th>Процесс</th>
                <th title="План / факт">
                  План/
                  <br />
                  факт
                </th>
                <th title="Задержка агента">
                  Задержка
                  <br />
                  агента
                </th>
                <th title="Задержка человека">
                  Задержка
                  <br />
                  человека
                </th>
                <th title="Автоматизация">
                  Авто-
                  <br />
                  матизация
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td title={row.name}>{row.name}</td>
                  <td>{row.planFact != null ? `${row.planFact}%` : '—'}</td>
                  <td>{formatMinutes(row.agentDelay)}</td>
                  <td
                    style={
                      row.humanDelay != null
                        ? { color: humanResponseDelayColor(row.humanDelay), fontWeight: 700 }
                        : undefined
                    }
                  >
                    {formatMinutes(row.humanDelay)}
                  </td>
                  <td>{row.automation != null ? `${row.automation}%` : '—'}</td>
                </tr>
              ))}
              <tr className="wp-kpi-total">
                <td>Итого</td>
                <td>
                  {avg(totals.planFact, totals.planCount) != null
                    ? `${avg(totals.planFact, totals.planCount)}%`
                    : '—'}
                </td>
                <td>{formatMinutes(avg(totals.agentDelay, totals.agentCount))}</td>
                <td
                  style={
                    avg(totals.humanDelay, totals.humanCount) != null
                      ? {
                          color: humanResponseDelayColor(avg(totals.humanDelay, totals.humanCount)!),
                          fontWeight: 700
                        }
                      : undefined
                  }
                >
                  {formatMinutes(avg(totals.humanDelay, totals.humanCount))}
                </td>
                <td>
                  {avg(totals.automation, totals.autoCount) != null
                    ? `${avg(totals.automation, totals.autoCount)}%`
                    : '—'}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function DetailRail({
  solutions,
  kpiRows,
  onOpenDecisions,
  onOpenMetrics,
  onOpenItem,
  onConfirmItem,
  onReturnItem,
  busySolutionId
}: {
  solutions: PreparedCard[]
  kpiRows: ProcessKpiRow[]
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpenItem: (item: PreparedCard) => void
  onConfirmItem: (item: PreparedCard) => void
  onReturnItem: (item: PreparedCard) => void
  busySolutionId: string
}): React.JSX.Element {
  return (
    <aside className="wp-rail">
      <PreparedSolutionsRail
        items={solutions}
        onOpenDecisions={onOpenDecisions}
        onOpenItem={onOpenItem}
        onConfirmItem={onConfirmItem}
        onReturnItem={onReturnItem}
        busyId={busySolutionId}
      />
      <ProcessKpiRail rows={kpiRows} onOpenMetrics={onOpenMetrics} />
    </aside>
  )
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
  onOpenPassport,
  onRun,
  onOpenRun,
  onAskOrchestrator
}: {
  userId: string
  userFio: string
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpenPassport: (workflowId: string, title: string, tab?: 'info' | 'files' | 'results') => void
  onRun: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
  onAskOrchestrator: (message: string, appContext: string) => void
}): React.JSX.Element {
  const { board, orch, agents, loading, error, flash, pause, resume, reload } = useWorkplaceData({
    userId,
    fio: userFio
  })
  const runs = useRuns()
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ProcessStatus | ''>('')
  const [urgency, setUrgency] = useState<'' | 'overdue' | 'ok'>('')
  const [processId, setProcessId] = useState('')
  const [sort, setSort] = useState<TodaySort>('')
  const [catalog, setCatalog] = useState<'today' | 'all'>('today')
  const [selectedId, setSelectedId] = useState('')
  const [askText, setAskText] = useState('')
  const [recentFilesByWorkflow, setRecentFilesByWorkflow] = useState<Record<string, WorkflowFileItem[]>>({})
  const [kpiByWorkflow, setKpiByWorkflow] = useState<Record<string, AgentKpi | null>>({})
  const [latestRunByWorkflow, setLatestRunByWorkflow] = useState<Record<string, AgentRunHistoryItem | null>>({})
  const [boardTick, setBoardTick] = useState(0)
  const [decisionTick, setDecisionTick] = useState(0)
  const [busySolutionId, setBusySolutionId] = useState('')
  const [actionNote, setActionNote] = useState('')

  useEffect(() => {
    if (!actionNote) return
    const timer = window.setTimeout(() => setActionNote(''), 4000)
    return () => window.clearTimeout(timer)
  }, [actionNote])
  const catalogAgents = useMemo(() => {
    const today = new Date()
    return agents.filter((agent) => {
      if (agent.standalone) return false
      if (catalog === 'all') return true
      return agentHasWorkToday(agent, today)
    })
  }, [agents, catalog])
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = catalogAgents.filter((agent) => {
      if (status && agent.status !== status) return false
      if (urgency === 'overdue' && !agentIsOverdue(agent)) return false
      if (urgency === 'ok' && agentIsOverdue(agent)) return false
      if (processId && agent.id !== processId) return false
      if (q && !`${agent.name} ${agent.code} ${agent.workflowId}`.toLowerCase().includes(q)) return false
      return true
    })
    return sortTodayAgents(rows, sort)
  }, [catalogAgents, query, status, urgency, processId, sort])
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
  const emptyToday = catalog === 'today' && !loading && !visible.length && !query && !status && !urgency && !processId
  const emptyAll = catalog === 'all' && !loading && !catalogAgents.length

  const preparedSolutions = useMemo((): PreparedCard[] => {
    const cards: PreparedCard[] = []
    for (const agent of agents) {
      if (agent.standalone) continue
      const liveHitl = runs.entries[agent.workflowId]?.state.pendingHitl
      if (agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR' || liveHitl) {
        cards.push({
          id: `wait:${agent.id}`,
          kind: 'waiting',
          title: agent.tasks.find((task) => task.status === 'needs_decision')?.title || `Решение: ${agent.name}`,
          note:
            agent.status === 'ERROR'
              ? 'Агент сообщил об ошибке — разберите результат и подтвердите следующий шаг.'
              : 'Агент подготовил материал и ждёт подтверждения человека.',
          meta: `Агент «${agent.name}» · ${STATUS_LABEL[agent.status]}`,
          workflowId: agent.workflowId,
          agentName: agent.name,
          requestId: liveHitl?.requestId,
          runId: runs.entries[agent.workflowId]?.backendRunId || agent.tasks.find((task) => task.runId)?.runId,
          live: Boolean(liveHitl?.requestId)
        })
      }
      const files = (recentFilesByWorkflow[agent.workflowId] || []).filter(isUserFacingResultFile)
      for (const file of files.slice(0, 2)) {
        const fileId = file.id || file.name
        if (readVerdict(agent.workflowId, fileId)) continue
        cards.push({
          id: `file:${agent.workflowId}:${fileId}`,
          kind: 'file',
          title: file.name || 'Файл результата',
          note: `Результат агента «${agent.name}». Откройте файл и подтвердите или верните на доработку.`,
          meta: file.createdAt
            ? `Подготовлено ${(() => {
                const stamp = parseIso(file.createdAt)
                return stamp ? humanWhen(stamp) : 'сегодня'
              })()}`
            : 'Подготовлено сегодня',
          workflowId: agent.workflowId,
          agentName: agent.name,
          fileId,
          fileUrl: file.downloadUrl,
          runId: file.runId
        })
      }
    }
    return cards.slice(0, 6)
  }, [agents, recentFilesByWorkflow, runs.entries, decisionTick])

  const openPreparedItem = (item: PreparedCard): void => {
    if (item.fileUrl) {
      void api.download(item.fileUrl, item.title || 'file')
      return
    }
    if (item.runId) {
      onOpenRun(item.workflowId, item.agentName, item.runId)
      return
    }
    onOpenPassport(item.workflowId, item.agentName, 'results')
  }

  const refreshWorkflowKpi = async (workflowId: string): Promise<void> => {
    const kpi = await api.calculateWorkflowKpi(workflowId).catch(() => null)
    if (kpi) {
      setKpiByWorkflow((prev) => ({ ...prev, [workflowId]: kpi }))
    }
  }

  const confirmPreparedItem = async (item: PreparedCard): Promise<void> => {
    setBusySolutionId(item.id)
    setActionNote('')
    try {
      if (item.kind === 'file' && item.fileId) {
        writeVerdict(item.workflowId, item.fileId, 'confirmed')
        if (item.runId) {
          writeVerdict(item.workflowId, runDecisionId(item.runId), 'confirmed')
        }
        setDecisionTick((value) => value + 1)
        await refreshWorkflowKpi(item.workflowId)
        return
      }
      const pending =
        item.kind === 'waiting' || item.requestId
          ? await findPendingToolRequest(item.workflowId, item.requestId)
          : null
      if (pending?.requestId) {
        runs.respondHitl(item.workflowId, pending.requestId, true)
        setActionNote('Действие подтверждено — агент продолжит работу.')
        await refreshWorkflowKpi(item.workflowId)
        await reload()
        return
      }
      if (item.runId) {
        writeVerdict(item.workflowId, runDecisionId(item.runId), 'confirmed')
        setDecisionTick((value) => value + 1)
        await refreshWorkflowKpi(item.workflowId)
        await reload()
        return
      }
      onOpenDecisions()
    } catch (err) {
      setActionNote(err instanceof Error ? err.message : 'Не удалось подтвердить результат')
    } finally {
      setBusySolutionId('')
    }
  }

  const returnPreparedItem = async (item: PreparedCard): Promise<void> => {
    setBusySolutionId(item.id)
    setActionNote('')
    try {
      if (item.kind === 'file' && item.fileId) {
        writeVerdict(item.workflowId, item.fileId, 'returned')
        if (item.runId) {
          writeVerdict(item.workflowId, runDecisionId(item.runId), 'returned')
        }
        setDecisionTick((value) => value + 1)
        setActionNote(`Результат «${item.title}» возвращён на доработку.`)
        return
      }
      const pending =
        item.kind === 'waiting' || item.requestId
          ? await findPendingToolRequest(item.workflowId, item.requestId)
          : null
      if (pending?.requestId) {
        runs.respondHitl(item.workflowId, pending.requestId, false)
        setActionNote('Действие возвращено — агент получит отказ.')
        await reload()
        return
      }
      onOpenDecisions()
    } catch (err) {
      setActionNote(err instanceof Error ? err.message : 'Не удалось вернуть результат')
    } finally {
      setBusySolutionId('')
    }
  }

  const kpiRows = useMemo((): ProcessKpiRow[] => {
    const now = Date.now()
    return visible
      .filter((agent) => !agent.standalone)
      .slice(0, 8)
      .map((agent) => {
        const live = runs.entries[agent.workflowId]
        const liveActive = Boolean(live && isLiveRunState(live.state))
        const metrics = buildProcessKpiMetrics(
          agent,
          kpiByWorkflow[agent.workflowId] || null,
          latestRunByWorkflow[agent.workflowId] || null,
          live?.state.timing,
          liveActive,
          now
        )
        return {
          id: agent.id,
          name: agent.name,
          ...metrics
        }
      })
  }, [visible, kpiByWorkflow, latestRunByWorkflow, runs.entries, boardTick])

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
        const produced = files
          .filter((file) => {
            const source = String(file.source || '').toLowerCase()
            const origin = String(file.origin || '').toLowerCase()
            return source === 'agent' || source === 'result' || origin.includes('agent')
          })
          .filter(isUserFacingResultFile)
          .sort((left, right) => String(right.createdAt || '').localeCompare(String(left.createdAt || '')))
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

  useEffect(() => {
    const unsubscribe = window.api.onBoardUpdated?.(() => setBoardTick((value) => value + 1))
    return () => unsubscribe?.()
  }, [])

  useEffect(() => {
    const targets = agents
      .map((agent) => agent.workflowId)
      .filter((workflowId) => workflowId && !workflowId.startsWith('personal-agent:'))
    if (!targets.length) {
      setKpiByWorkflow({})
      setLatestRunByWorkflow({})
      return
    }
    let alive = true
    void Promise.all(
      targets.map(async (workflowId) => {
        const kpi =
          (await api.calculateWorkflowKpi(workflowId).catch(() => null)) ||
          (await api.getWorkflowKpi(workflowId).catch(() => null))
        const history = await api.listAgentRuns(workflowId).catch(() => [] as AgentRunHistoryItem[])
        return [workflowId, kpi, latestAgentRun(history)] as const
      })
    ).then((rows) => {
      if (!alive) return
      const nextKpi: Record<string, AgentKpi | null> = {}
      const nextRuns: Record<string, AgentRunHistoryItem | null> = {}
      for (const [workflowId, kpi, latestRun] of rows) {
        nextKpi[workflowId] = kpi
        nextRuns[workflowId] = latestRun
      }
      setKpiByWorkflow(nextKpi)
      setLatestRunByWorkflow(nextRuns)
    })
    return () => {
      alive = false
    }
  }, [agents, boardTick, decisionTick])

  const removeAgent = async (workflowId: string, title: string): Promise<void> => {
    if (!workflowId || workflowId.startsWith('personal-agent:')) return
    const agreed = window.confirm(`Удалить агента «${title}»?`)
    if (!agreed) return
    try {
      await api.deleteWorkflow(workflowId)
      await reload()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Не удалось удалить агента')
    }
  }

  return (
    <div className="wp-page wp-today">
      <div className="wp-head wp-today-head">
        <div className="wp-today-head-title">
          <h1 className="page-title">Рабочее место сотрудника</h1>
          <p className="wp-today-subtitle">Оркестратор должности</p>
        </div>
      </div>

      {flash ? <div className="wp-toast">{flash}</div> : null}
      {actionNote ? <div className="wp-toast">{actionNote}</div> : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}

      <SummaryRow
        total={total}
        done={done}
        attention={attention}
        planFact={planFact}
        onOpenAttention={onOpenDecisions}
        onOpenMetrics={onOpenMetrics}
      />

      <div className="wp-filters-row wp-filters-row-today">
        <select className="wp-select" value={status} onChange={(e) => setStatus(e.target.value as ProcessStatus | '')}>
          <option value="">Статус</option>
          {Object.entries(STATUS_LABEL).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          className="wp-select"
          value={urgency}
          onChange={(e) => setUrgency(e.target.value as '' | 'overdue' | 'ok')}
          aria-label="Срочность"
        >
          <option value="">Срочность</option>
          <option value="overdue">Просрочено</option>
          <option value="ok">Не просрочено</option>
        </select>
        <select
          className="wp-select"
          value={processId}
          onChange={(e) => setProcessId(e.target.value)}
          aria-label="Процесс"
        >
          <option value="">Процесс</option>
          {catalogAgents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
        <input
          className="wp-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск задач и процессов"
        />
        <select
          className="wp-select"
          value={sort}
          onChange={(e) => setSort(e.target.value as TodaySort)}
          aria-label="Вид сортировки"
        >
          <option value="">Вид сортировки</option>
          <option value="time">По времени</option>
          <option value="status">По статусу</option>
          <option value="name">По названию</option>
        </select>
        <button
          className={catalog === 'all' ? 'btn-primary wp-all-agents-btn' : 'btn-ghost wp-all-agents-btn'}
          type="button"
          onClick={() => setCatalog((current) => (current === 'all' ? 'today' : 'all'))}
        >
          Все агенты
        </button>
      </div>

      <div className="wp-today-layout">
        <div className="wp-today-main">
          <h2 className="wp-section-title">
            {catalog === 'all' ? 'Все агенты' : 'Работа агентов сегодня'}
          </h2>
          {loading ? <div className="wp-card">Загружаем агентов с сервера…</div> : null}
          {emptyAll ? (
            <div className="wp-card">
              На сервере нет опубликованных агентов. Создайте и опубликуйте их в Constructor — они появятся здесь.
            </div>
          ) : null}
          {emptyToday ? (
            <div className="wp-card">
              Сегодня нет запусков и запланированной работы агентов. Откройте «Все агенты», чтобы посмотреть полный список.
            </div>
          ) : null}
          {!loading && !visible.length && !emptyToday && !emptyAll ? (
            <div className="wp-card">Нет агентов по заданному фильтру.</div>
          ) : null}
          {visible.map((agent) => (
            <AgentPlanCard
              key={agent.id}
              agent={agent}
              selected={selected?.id === agent.id}
              onSelect={setSelectedId}
              onOpen={(workflowId, title) => onOpenPassport(workflowId, title, 'info')}
              onRun={onRun}
              onOpenFiles={(workflowId, title) => onOpenPassport(workflowId, title, 'files')}
              onHistory={(workflowId, title) => onOpenPassport(workflowId, title, 'results')}
              onSchedule={(workflowId, title) => onOpenPassport(workflowId, title, 'info')}
              onDelete={(workflowId, title) => void removeAgent(workflowId, title)}
              onPause={(id) => void pause(id)}
              onResume={(id) => void resume(id)}
            />
          ))}
          {selected ? (
            <ProcessStepper
              agent={selected}
              onRun={onRun}
              onOpenRun={onOpenRun}
              onOpenDecisions={onOpenDecisions}
            />
          ) : null}
        </div>
        <DetailRail
          solutions={preparedSolutions}
          kpiRows={kpiRows}
          onOpenDecisions={onOpenDecisions}
          onOpenMetrics={onOpenMetrics}
          onOpenItem={openPreparedItem}
          onConfirmItem={(item) => void confirmPreparedItem(item)}
          onReturnItem={(item) => void returnPreparedItem(item)}
          busySolutionId={busySolutionId}
        />
      </div>

      <form
        className="wp-ask-bar"
        onSubmit={(event) => {
          event.preventDefault()
          const message = askText.trim()
          if (!message) return
          const context = buildOrchestratorContext({
            userFio,
            agents: catalogAgents,
            solutions: preparedSolutions,
            kpiRows,
            selectedName: selected?.name || '',
            stats: board.stats
          })
          setAskText('')
          onAskOrchestrator(message, context)
        }}
      >
        <span className="wp-ask-spark" aria-hidden>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 3l1.2 5.2L18 9.5l-4.8 1.3L12 16l-1.2-5.2L6 9.5l4.8-1.3L12 3z"
              fill="currentColor"
            />
            <path d="M18 14l.7 2.3L21 17l-2.3.7L18 20l-.7-2.3L15 17l2.3-.7L18 14z" fill="currentColor" />
          </svg>
        </span>
        <input
          className="wp-ask-input"
          value={askText}
          onChange={(e) => setAskText(e.target.value)}
          placeholder="Задать вопрос оркестратору..."
          aria-label="Задать вопрос оркестратору"
        />
        <button className="wp-ask-send" type="submit" disabled={!askText.trim()} title="Отправить">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path
              d="M4 11.5L20 4l-5.5 16-2.7-6.3L4 11.5z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </div>
  )
}

function buildOrchestratorContext(opts: {
  userFio: string
  agents: WorkplaceAgent[]
  solutions: PreparedCard[]
  kpiRows: ProcessKpiRow[]
  selectedName: string
  stats: WorkflowBoard['stats']
}): string {
  const lines: string[] = [
    `Сотрудник: ${opts.userFio || '—'}`,
    `Сводка сегодня: активных агентов ${opts.stats.activeAgents}, запусков ${opts.stats.runsToday}, ошибок ${opts.stats.errorsToday}, требуют внимания ${opts.stats.needsAttention}.`,
    `Выбранный процесс на экране: ${opts.selectedName || 'не выбран'}.`,
    '',
    'Процессы / агенты:'
  ]
  for (const agent of opts.agents.slice(0, 20)) {
    const tasks = agent.tasks
      .slice(0, 5)
      .map((task) => `${task.time} ${task.title} [${task.status}]`)
      .join('; ')
    lines.push(
      `- ${agent.name} (${agent.status}${agent.paused ? ', пауза' : ''})` +
        (tasks ? `: ${tasks}` : '')
    )
  }
  lines.push('', 'Подготовленные решения:')
  if (!opts.solutions.length) lines.push('- нет')
  for (const item of opts.solutions.slice(0, 10)) {
    lines.push(`- ${item.title} · ${item.agentName} · ${item.meta}`)
  }
  lines.push('', 'KPI по процессам:')
  if (!opts.kpiRows.length) lines.push('- нет данных')
  for (const row of opts.kpiRows.slice(0, 12)) {
    lines.push(
      `- ${row.name}: план/факт ${row.planFact ?? '—'}%, задержка агента ${formatMinutes(row.agentDelay)}, человека ${formatMinutes(row.humanDelay)}, авто ${row.automation ?? '—'}%`
    )
  }
  lines.push(
    '',
    'Доступные вкладки UI: Сегодня, Процессы, Календарь, Решения, Показатели, История, Настройки.',
    'Можно открывать запуски, подтверждать решения, смотреть KPI и историю через инструменты API.'
  )
  return lines.join('\n')
}
