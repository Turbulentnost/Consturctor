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
import { CardMenu } from '../components/agents/CardMenu'
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
  onHistory,
  onSchedule,
  onDelete,
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
  onHistory: (workflowId: string, title: string) => void
  onSchedule: (workflowId: string, title: string) => void
  onDelete: (workflowId: string, title: string) => void
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
            {!agent.standalone ? (
              <CardMenu
                items={[
                  { label: 'Открыть агента', onClick: () => onOpen(agent.workflowId, agent.name) },
                  { label: 'Изменить', onClick: () => onOpen(agent.workflowId, agent.name) },
                  { label: 'Посмотреть историю', onClick: () => onHistory(agent.workflowId, agent.name) },
                  { label: 'Изменить расписание', onClick: () => onSchedule(agent.workflowId, agent.name) },
                  agent.paused
                    ? { label: 'Возобновить', onClick: () => onResume(agent.workflowId) }
                    : { label: 'Приостановить', onClick: () => onPause(agent.workflowId) },
                  { label: 'Удалить', onClick: () => onDelete(agent.workflowId, agent.name), danger: true, separatorBefore: true }
                ]}
              />
            ) : null}
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
          <h2>Ход процесса</h2>
          <p>
            {agent.name} · этап: {agent.stages[agent.stageIndex]?.label || 'не начат'}
          </p>
        </div>
        <button className="btn-ghost" type="button" disabled={waiting}>
          Перейти к следующему этапу
        </button>
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

type PreparedCard = {
  id: string
  title: string
  note: string
  meta: string
  workflowId: string
  agentName: string
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
  onOpenItem
}: {
  items: PreparedCard[]
  onOpenDecisions: () => void
  onOpenItem: (workflowId: string, title: string) => void
}): React.JSX.Element {
  const featured = items[0]
  return (
    <section className="wp-rail-card wp-rail-solutions">
      <header className="wp-rail-card-head">
        <h2>Подготовленные решения</h2>
        <button className="wp-rail-link" type="button" onClick={onOpenDecisions}>
          История
        </button>
      </header>
      {!featured ? (
        <p className="wp-rail-empty">Пока нет подготовленных решений. Они появятся после прогонов агентов.</p>
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
                onClick={() => onOpenItem(featured.workflowId, featured.agentName)}
              >
                Открыть
              </button>
              <button className="btn-primary" type="button" onClick={onOpenDecisions}>
                Подтвердить
              </button>
              <button className="btn-ghost" type="button" onClick={onOpenDecisions}>
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
        <button className="wp-rail-link" type="button" onClick={onOpenMetrics}>
          История
        </button>
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
                  <td>{formatMinutes(row.humanDelay)}</td>
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
                <td>{formatMinutes(avg(totals.humanDelay, totals.humanCount))}</td>
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
  onOpenItem
}: {
  solutions: PreparedCard[]
  kpiRows: ProcessKpiRow[]
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpenItem: (workflowId: string, title: string) => void
}): React.JSX.Element {
  return (
    <aside className="wp-rail">
      <PreparedSolutionsRail items={solutions} onOpenDecisions={onOpenDecisions} onOpenItem={onOpenItem} />
      <ProcessKpiRail rows={kpiRows} onOpenMetrics={onOpenMetrics} />
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
  onOpenPassport,
  onRun
}: {
  userId: string
  userFio: string
  onOpenDecisions: () => void
  onOpenMetrics: () => void
  onOpenPassport: (workflowId: string, title: string, tab?: 'info' | 'files' | 'results') => void
  onRun: (workflowId: string, title: string) => void
}): React.JSX.Element {
  const { board, orch, agents, loading, error, flash, pause, resume, reload } = useWorkplaceData({
    userId,
    fio: userFio
  })
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ProcessStatus | ''>('')
  const [urgency, setUrgency] = useState<'' | 'overdue' | 'ok'>('')
  const [processId, setProcessId] = useState('')
  const [catalog, setCatalog] = useState<'today' | 'all'>('today')
  const [selectedId, setSelectedId] = useState('')
  const [recentFilesByWorkflow, setRecentFilesByWorkflow] = useState<Record<string, WorkflowFileItem[]>>({})
  const [kpiByWorkflow, setKpiByWorkflow] = useState<Record<string, AgentKpi | null>>({})
  const personal = useMemo(
    () => agents.find((item) => item.standalone) || buildPersonalAgent({ userId, fio: userFio }),
    [agents, userId, userFio]
  )
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
    return catalogAgents.filter((agent) => {
      if (status && agent.status !== status) return false
      if (urgency === 'overdue' && !agentIsOverdue(agent)) return false
      if (urgency === 'ok' && agentIsOverdue(agent)) return false
      if (processId && agent.id !== processId) return false
      if (q && !`${agent.name} ${agent.code} ${agent.workflowId}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [catalogAgents, query, status, urgency, processId])
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
      if (agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR') {
        cards.push({
          id: `wait:${agent.id}`,
          title: agent.tasks.find((task) => task.status === 'needs_decision')?.title || `Решение: ${agent.name}`,
          note:
            agent.status === 'ERROR'
              ? 'Агент сообщил об ошибке — разберите результат и подтвердите следующий шаг.'
              : 'Агент подготовил материал и ждёт подтверждения человека.',
          meta: `Агент «${agent.name}» · ${STATUS_LABEL[agent.status]}`,
          workflowId: agent.workflowId,
          agentName: agent.name
        })
      }
      const files = recentFilesByWorkflow[agent.workflowId] || []
      for (const file of files.slice(0, 2)) {
        cards.push({
          id: `file:${agent.workflowId}:${file.id || file.name}`,
          title: file.name || 'Файл результата',
          note: `Результат агента «${agent.name}». Откройте и подтвердите на вкладке «Решения».`,
          meta: file.createdAt
            ? `Подготовлено ${(() => {
                const stamp = parseIso(file.createdAt)
                return stamp ? humanWhen(stamp) : 'сегодня'
              })()}`
            : 'Подготовлено сегодня',
          workflowId: agent.workflowId,
          agentName: agent.name
        })
      }
    }
    return cards.slice(0, 6)
  }, [agents, recentFilesByWorkflow])

  const kpiRows = useMemo((): ProcessKpiRow[] => {
    return visible
      .filter((agent) => !agent.standalone)
      .slice(0, 8)
      .map((agent) => {
        const score = kpiScore(kpiByWorkflow[agent.workflowId] || null)
        const humanDelay =
          agent.status === 'WAITING_HUMAN' ? 25 : agent.status === 'ERROR' ? 40 : score != null ? 12 : null
        const agentDelay = score != null ? Math.max(5, Math.round((100 - score) / 4)) : null
        const automation =
          score != null && humanDelay != null
            ? Math.round((100 * score) / (score + humanDelay / 10))
            : score
        return {
          id: agent.id,
          name: agent.name,
          planFact: score,
          agentDelay,
          humanDelay,
          automation
        }
      })
  }, [visible, kpiByWorkflow])

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

  useEffect(() => {
    const targets = visible
      .map((agent) => agent.workflowId)
      .filter((workflowId) => workflowId && !workflowId.startsWith('personal-agent:'))
    if (!targets.length) {
      setKpiByWorkflow({})
      return
    }
    let alive = true
    void Promise.all(
      targets.map(async (workflowId) => {
        const kpi = await api.getWorkflowKpi(workflowId).catch(() => null)
        return [workflowId, kpi] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const next: Record<string, AgentKpi | null> = {}
      for (const [workflowId, kpi] of pairs) next[workflowId] = kpi
      setKpiByWorkflow(next)
    })
    return () => {
      alive = false
    }
  }, [visible])

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
        <div className="wp-head-actions">
          <button
            className={catalog === 'all' ? 'btn-primary' : 'btn-ghost'}
            type="button"
            onClick={() => setCatalog((current) => (current === 'all' ? 'today' : 'all'))}
          >
            Все агенты
          </button>
        </div>
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

      <div className="wp-info-banner">
        <span className="wp-info-ico" aria-hidden>
          i
        </span>
        <p>
          В пилоте работают агенты должности: они готовят материалы, а решения человека подтверждаются на вкладке
          «Решения».
        </p>
      </div>

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
        <button
          className="btn-primary wp-base-agent-btn"
          type="button"
          onClick={() => onRun(personal.workflowId, personal.name)}
        >
          Базовый агент
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
              recentFiles={recentFilesByWorkflow[agent.workflowId] || []}
              onPause={(id) => void pause(id)}
              onResume={(id) => void resume(id)}
            />
          ))}
          {selected ? <ProcessStepper agent={selected} /> : null}
        </div>
        <DetailRail
          solutions={preparedSolutions}
          kpiRows={kpiRows}
          onOpenDecisions={onOpenDecisions}
          onOpenMetrics={onOpenMetrics}
          onOpenItem={(workflowId, title) => onOpenPassport(workflowId, title, 'results')}
        />
      </div>
    </div>
  )
}
