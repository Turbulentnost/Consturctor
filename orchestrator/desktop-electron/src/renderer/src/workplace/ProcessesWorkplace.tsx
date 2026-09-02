import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AgentKpi, AgentRunHistoryItem, CalendarEvent } from '../api/types'
import { CardMenu } from '../components/agents/CardMenu'
import { humanWhen, parseIso } from '../utils/calendar'
import { FilterBar } from './FilterBar'
import { type ProcessStatus } from './labels'
import { useWorkplaceData, type WorkplaceAgent } from './WorkplaceBoard'

const STATUS_BADGE: Record<ProcessStatus, string> = {
  READY: 'Готов',
  ACTIVE: 'В работе',
  WAITING_HUMAN: 'Ждёт человека',
  PAUSED: 'Приостановлен',
  COMPLETED: 'Выполнен',
  ERROR: 'Ошибка'
}
const STATUS_FILTER_ORDER: ProcessStatus[] = ['READY', 'ACTIVE', 'WAITING_HUMAN', 'PAUSED', 'ERROR']
const DEFAULT_PLAN_PERCENT = 95

const MONTHS_SHORT = ['янв.', 'февр.', 'мар.', 'апр.', 'мая', 'июн.', 'июл.', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.']

type SortKey = 'action' | 'name' | 'deadline'

function latestRun(items: AgentRunHistoryItem[]): AgentRunHistoryItem | null {
  if (!items.length) return null
  return [...items].sort((left, right) => {
    const leftAt = left.startedAt || left.finishedAt || ''
    const rightAt = right.startedAt || right.finishedAt || ''
    return rightAt.localeCompare(leftAt)
  })[0]
}

function runStatusLabel(status: string): string {
  const value = (status || '').toLowerCase()
  if (value === 'ok' || value === 'done' || value === 'completed') return 'Выполнен'
  if (value === 'running' || value === 'active') return 'В работе'
  if (value === 'started') return 'Запущен'
  if (value === 'waiting_human' || value === 'hitl' || value === 'waiting') return 'Ждёт решения'
  if (value === 'canceled' || value === 'cancelled') return 'Отменён'
  if (value === 'error' || value === 'failed') return 'Ошибка'
  if (!value) return 'Без статуса'
  return status
}

function minutesLabel(ms: number): string {
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return '< 1 мин'
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`
}

function formatDeadline(iso: string): { when: string; left: string } | null {
  const stamp = parseIso(iso)
  if (!stamp) return null
  const hh = String(stamp.getHours()).padStart(2, '0')
  const mm = String(stamp.getMinutes()).padStart(2, '0')
  const when = `${stamp.getDate()} ${MONTHS_SHORT[stamp.getMonth()]}, ${hh}:${mm}`
  const diff = stamp.getTime() - Date.now()
  if (diff < 0) {
    const late = minutesLabel(-diff)
    return { when, left: `просрочен на ${late}` }
  }
  const hours = Math.floor(diff / 3_600_000)
  const days = Math.floor(hours / 24)
  const restHours = hours % 24
  const mins = Math.floor((diff % 3_600_000) / 60_000)
  if (days > 0) return { when, left: `через ${days} дн. ${restHours} ч.` }
  if (hours > 0) return { when, left: `через ${hours} ч. ${mins} мин.` }
  return { when, left: `через ${mins} мин.` }
}

function metricNumber(raw: unknown): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null
  if (typeof raw !== 'string') return null
  const cleaned = raw.replace(',', '.').replace(/[^\d.-]/g, '')
  if (!cleaned) return null
  const value = Number(cleaned)
  return Number.isFinite(value) ? value : null
}

function kpiScore(kpi: AgentKpi | null): number | null {
  const scores = (kpi?.tiles || [])
    .map((tile) => tile.scorePercent)
    .filter((value): value is number => value != null)
  if (scores.length) return Math.round(scores.reduce((acc, value) => acc + value, 0) / scores.length)

  // fallback: если scorePercent отсутствует, считаем план/факт по KPI-плиткам регламента
  const ratios = (kpi?.tiles || [])
    .map((tile) => {
      const plan = metricNumber(tile.plan?.value)
      const fact = metricNumber(tile.fact?.value)
      if (plan == null || fact == null || plan <= 0) return null
      return Math.round((fact / plan) * 100)
    })
    .filter((value): value is number => value != null)
  if (!ratios.length) return null
  return Math.round(ratios.reduce((acc, value) => acc + value, 0) / ratios.length)
}

function automationRate(events: CalendarEvent[]): number | null {
  if (!events.length) return null
  const done = events.filter((event) => {
    const status = (event.status || '').toLowerCase()
    return status === 'ok' || status === 'done' || status === 'completed'
  }).length
  return Math.round((done / events.length) * 100)
}

function actionRank(status: ProcessStatus): number {
  if (status === 'ERROR' || status === 'WAITING_HUMAN') return 0
  if (status === 'PAUSED') return 1
  if (status === 'ACTIVE') return 2
  return 3
}

function ProcessIcon({ status }: { status: ProcessStatus }): React.JSX.Element {
  const tone =
    status === 'PAUSED' || status === 'WAITING_HUMAN'
      ? 'warn'
      : status === 'ERROR'
        ? 'err'
        : status === 'ACTIVE' || status === 'COMPLETED'
          ? 'ok'
          : 'idle'
  return (
    <span className={`proc-ico ${tone}`} aria-hidden>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.8" />
        <circle cx="16" cy="8" r="3" stroke="currentColor" strokeWidth="1.8" />
        <path
          d="M4.5 18c.6-2.4 2.4-3.6 3.5-3.6s2.9 1.2 3.5 3.6"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
        <path
          d="M12.5 18c.6-2.4 2.4-3.6 3.5-3.6s2.9 1.2 3.5 3.6"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    </span>
  )
}

function ProcessCard({
  agent,
  kpi,
  events,
  onOpen,
  onFiles,
  onHistory,
  onSchedule,
  onPause,
  onResume,
  latestRunInfo
}: {
  agent: WorkplaceAgent
  kpi: AgentKpi | null
  events: CalendarEvent[]
  onOpen: (workflowId: string, title: string, autoStart?: boolean) => void
  onFiles: (workflowId: string, title: string) => void
  onHistory: (workflowId: string, title: string) => void
  onSchedule: (workflowId: string, title: string) => void
  onPause: (workflowId: string) => void
  onResume: (workflowId: string) => void
  latestRunInfo: AgentRunHistoryItem | null
}): React.JSX.Element {
  const board = agent.boardAgent
  const deadline = formatDeadline(board?.nextRunAt || '')
  const factPercent = kpiScore(kpi)
  const planFactLabel = `${DEFAULT_PLAN_PERCENT}% / ${factPercent != null ? `${factPercent}%` : '—'}`
  const auto = automationRate(events)
  const lastStart = parseIso(board?.lastRunAt || '')
  const nextStart = parseIso(board?.nextRunAt || '')
  const lastEvent = [...events].sort((a, b) => (a.startAt > b.startAt ? -1 : 1))[0]
  const scheduled = parseIso(lastEvent?.startAt || '')
  const agentDelayMs = lastStart && scheduled ? lastStart.getTime() - scheduled.getTime() : null
  const agentDelay =
    agentDelayMs != null
      ? agentDelayMs > 0
        ? minutesLabel(agentDelayMs)
        : '0 мин'
      : latestRunInfo
        ? '0 мин'
        : null
  const humanDelayMs =
    agent.status === 'WAITING_HUMAN' && lastStart
      ? Date.now() - lastStart.getTime()
      : nextStart && nextStart.getTime() < Date.now() && agent.status === 'READY'
        ? Date.now() - nextStart.getTime()
        : null
  const humanDelay = humanDelayMs != null ? minutesLabel(Math.max(humanDelayMs, 0)) : latestRunInfo ? '0 мин' : null
  const mixed = agent.status === 'WAITING_HUMAN' || agent.status === 'ERROR'
  const accent =
    agent.status === 'ERROR'
      ? 'err'
      : agent.status === 'PAUSED' || agent.status === 'WAITING_HUMAN'
        ? 'warn'
        : agent.status === 'ACTIVE' || agent.status === 'COMPLETED'
          ? 'ok'
          : 'idle'
  const stageCurrent = Math.min(agent.stageIndex + 1, agent.stages.length)
  const stageTotal = agent.stages.length
  const progress = stageTotal ? Math.round((stageCurrent / stageTotal) * 100) : 0
  const version = (board?.phase || '').trim()
  const agentLive = board?.paused ? 'Пауза' : 'Активен'
  const runStartedAt = parseIso(latestRunInfo?.startedAt || latestRunInfo?.finishedAt || '')
  const runWhen = runStartedAt ? humanWhen(runStartedAt) : 'ещё не запускался'
  const runStatus = runStatusLabel(latestRunInfo?.status || board?.lastRunStatus || '')
  const runId = String(latestRunInfo?.runId || '').trim()
  const openChatLabel = `Перейти в чат ${agent.name}`
  const openChat = (): void => onOpen(agent.workflowId, agent.name)
  const stopCardClick: React.MouseEventHandler<HTMLElement> = (event): void => {
    event.stopPropagation()
  }
  const onCardKeyDown: React.KeyboardEventHandler<HTMLElement> = (event): void => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    openChat()
  }

  return (
    <article
      className={`proc-card ${accent}`}
      role="button"
      tabIndex={0}
      onClick={openChat}
      onKeyDown={onCardKeyDown}
      aria-label={openChatLabel}
    >
      <header className="proc-card-head">
        <ProcessIcon status={agent.status} />
        <div className="proc-card-title">
          <h2>{agent.name}</h2>
          <div className="proc-badges">
            <span className={`proc-badge proc-badge-${agent.status.toLowerCase()}`}>
              {STATUS_BADGE[agent.status]}
            </span>
            <span className={`proc-badge ${mixed ? 'proc-badge-mixed' : 'proc-badge-ai'}`}>
              {mixed ? 'ИИ + человек' : 'ИИ'}
            </span>
          </div>
        </div>
        <div className="proc-card-tools" onClick={stopCardClick}>
          {!agent.standalone && agent.paused ? (
            <button
              className="btn-primary"
              type="button"
              onClick={() => onResume(agent.workflowId)}
            >
              Возобновить
            </button>
          ) : null}
          {!agent.standalone ? (
            <CardMenu
              items={[
                agent.paused
                  ? { label: 'Возобновить', onClick: () => onResume(agent.workflowId) }
                  : { label: 'Приостановить', onClick: () => onPause(agent.workflowId) },
                { label: 'Файлы агента', onClick: () => onFiles(agent.workflowId, agent.name) },
                { label: 'История', onClick: () => onHistory(agent.workflowId, agent.name) },
                { label: 'Расписание', onClick: () => onSchedule(agent.workflowId, agent.name) }
              ]}
            />
          ) : null}
        </div>
      </header>
      <div className="proc-chat-hint" aria-hidden>
        {openChatLabel}
      </div>

      <div className="proc-card-grid">
        <div>
          <span className="proc-label">Этапы</span>
          <strong>
            {stageCurrent} / {stageTotal || '—'}
          </strong>
          <div className="proc-bar" aria-hidden>
            <i style={{ width: `${progress}%` }} />
          </div>
          <small>{agent.stages[agent.stageIndex]?.label || agent.stage}</small>
        </div>
        <div>
          <span className="proc-label">Ближайший дедлайн</span>
          <strong>{agent.standalone ? 'По запросу пользователя' : deadline?.when || agent.due}</strong>
          {!agent.standalone && deadline ? (
            <small className={deadline.left.startsWith('просрочен') ? 'late' : ''}>{deadline.left}</small>
          ) : null}
        </div>
        <div>
          <span className="proc-label">Ответственный агент</span>
          <strong>
            {agent.code}
            {version ? ` · ${version}` : ''}
          </strong>
          <small className={agent.paused ? '' : 'live'}>{agentLive}</small>
          {!agent.standalone ? <small>Последний прогон: {runWhen}</small> : null}
          {!agent.standalone ? <small>ID: {runId || 'нет'}</small> : null}
        </div>
      </div>

      {!agent.standalone ? (
        <footer className="proc-kpis">
          <div>
            <span>План / факт</span>
            <strong>{planFactLabel}</strong>
          </div>
          <div>
            <span>Статус прогона</span>
            <strong>{runStatus}</strong>
          </div>
          <div>
            <span>Задержка агента</span>
            <strong>{agentDelay || '—'}</strong>
          </div>
          <div>
            <span>Задержка человека</span>
            <strong>{humanDelay || '—'}</strong>
          </div>
          <div>
            <span>Автоматизация</span>
            <strong>{auto != null ? `${auto}%` : '—'}</strong>
          </div>
        </footer>
      ) : null}
    </article>
  )
}

export function ProcessesWorkplace({
  userId,
  userFio,
  onOpen,
  onFiles,
  onHistory,
  onSchedule
}: {
  userId: string
  userFio: string
  onOpen: (workflowId: string, title: string, autoStart?: boolean) => void
  onFiles: (workflowId: string, title: string) => void
  onHistory: (workflowId: string, title: string) => void
  onSchedule: (workflowId: string, title: string) => void
}): React.JSX.Element {
  const { board, agents, loading, error, flash, pause, resume } = useWorkplaceData({
    userId,
    fio: userFio
  })
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ProcessStatus | ''>('')
  const [stage, setStage] = useState('')
  const [devOnly, setDevOnly] = useState(false)
  const [sort, setSort] = useState<SortKey>('action')
  const [kpiById, setKpiById] = useState<Record<string, AgentKpi | null>>({})
  const [latestRunById, setLatestRunById] = useState<Record<string, AgentRunHistoryItem | null>>({})
  const trackedAgentsCount = useMemo(() => agents.filter((item) => !item.standalone).length, [agents])

  useEffect(() => {
    let alive = true
    const workflowAgents = agents.filter((item) => !item.standalone)
    void Promise.all(
      workflowAgents.map(async (item) => {
        const kpi = await api.getWorkflowKpi(item.workflowId).catch(() => null)
        return [item.workflowId, kpi] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const next: Record<string, AgentKpi | null> = {}
      for (const [id, kpi] of pairs) next[id] = kpi
      setKpiById(next)
    })
    return () => {
      alive = false
    }
  }, [agents])

  useEffect(() => {
    let alive = true
    const workflowAgents = agents.filter((item) => !item.standalone)
    void Promise.all(
      workflowAgents.map(async (item) => {
        const runs = await api.listAgentRuns(item.workflowId).catch(() => [] as AgentRunHistoryItem[])
        return [item.workflowId, latestRun(runs)] as const
      })
    ).then((pairs) => {
      if (!alive) return
      const next: Record<string, AgentRunHistoryItem | null> = {}
      for (const [id, run] of pairs) {
        next[id] = run
      }
      setLatestRunById(next)
    })
    return () => {
      alive = false
    }
  }, [agents])

  const stages = useMemo(() => {
    const values = new Set(agents.map((item) => item.stage).filter(Boolean))
    return [...values]
  }, [agents])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = agents.filter((item) => {
      if (status && item.status !== status) return false
      if (stage && item.stage !== stage) return false
      if (devOnly && item.status !== 'ERROR' && item.status !== 'WAITING_HUMAN' && item.status !== 'PAUSED') {
        return false
      }
      if (q && !`${item.name} ${item.code} ${item.workflowId} ${item.stage}`.toLowerCase().includes(q)) {
        return false
      }
      return true
    })
    rows.sort((left, right) => {
      if (sort === 'name') return left.name.localeCompare(right.name, 'ru')
      if (sort === 'deadline') {
        return (left.boardAgent?.nextRunAt || '').localeCompare(right.boardAgent?.nextRunAt || '')
      }
      const rank = actionRank(left.status) - actionRank(right.status)
      return rank !== 0 ? rank : left.name.localeCompare(right.name, 'ru')
    })
    return rows
  }, [agents, query, status, stage, devOnly, sort])

  return (
    <div className="wp-page proc-page">
      <div className="wp-head">
        <div>
          <h1 className="page-title">Процессы должности</h1>
          <div className="wp-sub">Полный перечень процессов и их текущее состояние</div>
        </div>
        <span className="orch-badge">{loading ? 'загрузка' : `${trackedAgentsCount} процессов`}</span>
      </div>
      {flash ? <div className="wp-toast">{flash}</div> : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}

      <FilterBar
        query={query}
        onQuery={setQuery}
        queryPlaceholder="Найти процесс"
        chips={[
          { id: 'q', label: query ? `поиск: ${query}` : '', onClear: () => setQuery('') },
          {
            id: 's',
            label: status ? `Статус: ${STATUS_BADGE[status]}` : '',
            onClear: () => setStatus('')
          },
          { id: 'st', label: stage ? `Этап: ${stage}` : '', onClear: () => setStage('') },
          { id: 'd', label: devOnly ? 'только с отклонениями' : '', onClear: () => setDevOnly(false) }
        ]}
        onReset={() => {
          setQuery('')
          setStatus('')
          setStage('')
          setDevOnly(false)
          setSort('action')
        }}
      >
        <select className="wp-select" value={status} onChange={(e) => setStatus(e.target.value as ProcessStatus | '')}>
          <option value="">Статус: все</option>
          {STATUS_FILTER_ORDER.map((key) => (
            <option key={key} value={key}>
              {STATUS_BADGE[key]}
            </option>
          ))}
        </select>
        <select className="wp-select" value={stage} onChange={(e) => setStage(e.target.value)}>
          <option value="">Текущий этап: все</option>
          {stages.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <label className="wp-toggle">
          <input type="checkbox" checked={devOnly} onChange={(e) => setDevOnly(e.target.checked)} />
          Только с отклонениями
        </label>
        <select className="wp-select" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="action">Сначала требующие действия</option>
          <option value="name">По названию</option>
          <option value="deadline">По дедлайну</option>
        </select>
      </FilterBar>

      <div className="proc-list">
        {loading ? <div className="wp-card">Загружаем процессы с сервера…</div> : null}
        {!loading && !visible.length ? (
          <div className="wp-card">
            {agents.length
              ? 'Нет процессов по текущему фильтру.'
              : 'На сервере нет опубликованных агентов. Создайте и опубликуйте их в Constructor — они появятся здесь.'}
          </div>
        ) : null}
        {visible.map((agent) => (
          <ProcessCard
            key={agent.id}
            agent={agent}
            kpi={kpiById[agent.workflowId] || null}
            latestRunInfo={latestRunById[agent.workflowId] || null}
            events={board.events.filter((event) => event.workflowId === agent.workflowId)}
            onOpen={onOpen}
            onFiles={onFiles}
            onHistory={onHistory}
            onSchedule={onSchedule}
            onPause={(id) => void pause(id)}
            onResume={(id) => void resume(id)}
          />
        ))}
      </div>
    </div>
  )
}
