import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AgentKpi, AgentRunHistoryItem, BoardAgent, KpiTile } from '../api/types'

const iconCalendar = new URL('../../../temp/KPI/calendar.png', import.meta.url).href
const iconActive = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_22_41.png', import.meta.url).href
const iconRuns = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_23_18.png', import.meta.url).href
const iconSuccess = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_23_35.png', import.meta.url).href
const iconAttention = new URL('../../../temp/KPI/3ee02669-15be-4acb-9537-89da251eaa83.png', import.meta.url).href
const robotGreen = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_28_22.png', import.meta.url).href
const robotBlue = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_28_29.png', import.meta.url).href
const robotYellow = new URL('../../../temp/KPI/9421cf0b-b18d-4568-9e74-cf99d542b73b.png', import.meta.url).href
const robotRed = new URL('../../../temp/KPI/59561baa-bbdc-4f74-8cf4-d78179bae59d.png', import.meta.url).href

const HISTORY_KEY = 'constructor.kpi.snapshots'

type TabKey = 'overview' | 'agents'
type RangeKey = '7' | '30' | '90'
type PeriodKind = 'range' | 'date' | 'month'
type AgentFilter = 'all' | 'deviations' | 'critical'
type DynamicsMode = 'runs' | 'success'

interface PeriodState {
  kind: PeriodKind
  range: RangeKey
  date: string
  month: string
}

interface AgentKpiView {
  agent: BoardAgent
  runs: AgentRunHistoryItem[]
  total: number
  successful: number
  errors: number
  attention: boolean
  critical: boolean
  successRate: number
  timelinessRate: number
  completeness: number
  averageMinutes: number | null
  score: number
  uncalculated: boolean
  lastCalculatedAt: string
  dailySuccess: number[]
  dailyScore: number[]
}

interface KpiSnapshot {
  date: string
  agentId: string
  score: number
  successRate: number
  timelinessRate: number
  total: number
  errors: number
  averageMinutes: number | null
}

const RANGE_LABELS: Record<RangeKey, string> = {
  '7': 'Последние 7 дней',
  '30': 'Последние 30 дней',
  '90': 'Последние 90 дней'
}

function todayKey(): string {
  return dayKey(Date.now())
}

function monthKey(timestamp = Date.now()): string {
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

function defaultPeriod(): PeriodState {
  return { kind: 'range', range: '30', date: todayKey(), month: monthKey() }
}

function isSuccess(status: string): boolean {
  const value = status.toLowerCase()
  return ['ok', 'success', 'successful', 'completed', 'done', 'ready'].some((item) => value.includes(item))
}

function isErrorStatus(status: string): boolean {
  const value = status.toLowerCase()
  return ['error', 'fail', 'failed'].some((item) => value.includes(item))
}

function isAttentionStatus(status: string): boolean {
  const value = status.toLowerCase()
  return ['attention', 'approval', 'confirm', 'pending', 'wait', 'error', 'fail', 'stuck'].some((item) =>
    value.includes(item)
  )
}

function runTime(run: AgentRunHistoryItem): number {
  const raw = run.startedAt || run.finishedAt
  const time = Date.parse(raw || '')
  return Number.isFinite(time) ? time : 0
}

function runDurationMinutes(run: AgentRunHistoryItem): number | null {
  const started = Date.parse(run.startedAt || '')
  const finished = Date.parse(run.finishedAt || '')
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished <= started) return null
  return Math.max(1, Math.round((finished - started) / 60000))
}

function dayKey(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function enumerateDays(from: number, to: number): string[] {
  const out: string[] = []
  const cursor = new Date(from)
  cursor.setHours(0, 0, 0, 0)
  const end = new Date(to)
  end.setHours(0, 0, 0, 0)
  while (cursor.getTime() <= end.getTime()) {
    out.push(dayKey(cursor.getTime()))
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
}

function periodWindow(period: PeriodState): { from: number; to: number; days: string[] } {
  if (period.kind === 'date') {
    const start = new Date(`${period.date}T00:00:00`)
    const from = Number.isNaN(start.getTime()) ? Date.now() : start.getTime()
    return { from, to: from + 86400000 - 1, days: [dayKey(from)] }
  }
  if (period.kind === 'month') {
    const [year, month] = period.month.split('-').map(Number)
    const start = new Date(year, (month || 1) - 1, 1)
    const end = new Date(year, month || 1, 0, 23, 59, 59, 999)
    return { from: start.getTime(), to: end.getTime(), days: enumerateDays(start.getTime(), end.getTime()) }
  }
  const days = Number(period.range)
  const end = new Date()
  end.setHours(23, 59, 59, 999)
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - (days - 1))
  return { from: start.getTime(), to: end.getTime(), days: enumerateDays(start.getTime(), end.getTime()) }
}

function inWindow(run: AgentRunHistoryItem, from: number, to: number): boolean {
  const time = runTime(run)
  return time > 0 && time >= from && time <= to
}

function chartPoints(values: number[], width: number, height: number): string {
  const max = Math.max(1, ...values)
  const step = values.length > 1 ? width / (values.length - 1) : width
  return values
    .map((value, index) => {
      const x = index * step
      const y = height - (value / max) * (height - 10) - 5
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function Sparkline({
  values,
  tone = 'green'
}: {
  values: number[]
  tone?: 'green' | 'orange' | 'red' | 'grey'
}): React.JSX.Element {
  const stroke = tone === 'green' ? '#08745f' : tone === 'orange' ? '#e67e22' : tone === 'red' ? '#c0392b' : '#9aa7a2'
  return (
    <svg className="kpi-spark" viewBox="0 0 100 32" preserveAspectRatio="none">
      <polyline points={chartPoints(values, 100, 32)} fill="none" stroke={stroke} strokeWidth="2.4" />
    </svg>
  )
}

function RateBar({ value, tone = 'green' }: { value: number; tone?: 'green' | 'orange' | 'red' }): React.JSX.Element {
  const normalized = Math.max(0, Math.min(100, value))
  return (
    <span className={`kpi-rate ${tone}`}>
      <span style={{ width: `${normalized}%` }} />
    </span>
  )
}

function Donut({ score }: { score: number }): React.JSX.Element {
  const normalized = Math.max(0, Math.min(100, score))
  return (
    <div
      className="kpi-donut"
      style={{ background: `conic-gradient(#08745f ${normalized * 3.6}deg, #edf3f0 0deg)` }}
    >
      <div>
        <strong>{normalized}</strong>
        <span>из 100</span>
      </div>
    </div>
  )
}

function robotFor(index: number, attention: boolean, critical = false, uncalculated = false): string {
  if (uncalculated) return robotBlue
  if (critical) return robotRed
  if (attention) return robotYellow
  return [robotGreen, robotBlue, robotYellow, robotGreen][index % 4]
}

function statusLabel(row: AgentKpiView): string {
  if (row.uncalculated) return 'Нет расчёта'
  if (row.critical) return 'Ошибка'
  if (row.attention) return 'Внимание'
  return 'Работает'
}

function statusTone(row: AgentKpiView): 'green' | 'orange' | 'red' | 'grey' {
  if (row.uncalculated) return 'grey'
  if (row.critical) return 'red'
  if (row.attention) return 'orange'
  return 'green'
}

function rowTone(value: number): 'green' | 'orange' | 'red' {
  if (value >= 90) return 'green'
  if (value >= 75) return 'orange'
  return 'red'
}

function formatAverage(minutes: number | null): string {
  if (minutes == null) return '—'
  if (minutes < 60) return `${minutes} мин`
  const hours = minutes / 60
  return `${hours % 1 === 0 ? hours.toFixed(0) : hours.toFixed(1)} ч`
}

function formatWhen(raw?: string): string {
  const time = Date.parse(raw || '')
  if (!Number.isFinite(time)) return 'нет расчёта'
  return new Date(time).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function formatDayLabel(key: string): string {
  const date = new Date(`${key}T00:00:00`)
  if (Number.isNaN(date.getTime())) return key
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function tileNumber(tile?: KpiTile | null): number | null {
  if (!tile) return null
  const raw = tile.fact?.value
  if (raw === null || raw === undefined || raw === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

function latestTileUpdate(kpi: AgentKpi | null | undefined): string {
  if (!kpi?.tiles.length) return kpi?.generatedAt || ''
  return kpi.tiles.reduce((latest, tile) => {
    if (!tile.updatedAt) return latest
    return !latest || tile.updatedAt > latest ? tile.updatedAt : latest
  }, '')
}

function tilesHaveFacts(kpi: AgentKpi | null | undefined): boolean {
  return Boolean(
    kpi?.tiles.some((tile) => tile.scorePercent != null || tileNumber(tile) != null || Boolean(tile.updatedAt))
  )
}

function applyKpiTiles(
  metrics: ReturnType<typeof metricsFromRuns>,
  kpi: AgentKpi | null | undefined
): ReturnType<typeof metricsFromRuns> {
  if (!kpi) return metrics
  const byId = new Map(kpi.tiles.map((tile) => [tile.id, tile]))
  const success = tileNumber(byId.get('success_rate'))
  const timely = tileNumber(byId.get('on_schedule_rate'))
  const fails = tileNumber(byId.get('fail_count'))
  const runs = tileNumber(byId.get('runs_count'))
  const interval = tileNumber(byId.get('expected_interval'))
  const scores = kpi.tiles.map((tile) => tile.scorePercent).filter((value): value is number => value != null)
  return {
    ...metrics,
    successRate: success != null ? Math.round(success) : metrics.successRate,
    timelinessRate: timely != null ? Math.round(timely) : metrics.timelinessRate,
    errors: fails != null ? Math.round(fails) : metrics.errors,
    total: runs != null ? Math.round(runs) : metrics.total,
    averageMinutes: interval != null ? Math.round(interval) : metrics.averageMinutes,
    score: scores.length
      ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length)
      : metrics.score
  }
}

function metricsFromRuns(runs: AgentRunHistoryItem[], dayCount: number): Omit<
  AgentKpiView,
  'agent' | 'runs' | 'attention' | 'critical' | 'uncalculated' | 'lastCalculatedAt' | 'dailySuccess' | 'dailyScore'
> {
  const successful = runs.filter((run) => isSuccess(run.status)).length
  const errors = runs.filter((run) => isErrorStatus(run.status)).length
  const durations = runs.map(runDurationMinutes).filter((value): value is number => value !== null)
  const timely = durations.length
    ? runs.filter((run) => {
        const duration = runDurationMinutes(run)
        return duration !== null && duration <= 10
      }).length
    : successful
  const daysWithRun = new Set(
    runs.map((run) => dayKey(runTime(run))).filter((key) => key && key !== 'NaN-NaN-NaN')
  )
  const successRate = runs.length ? Math.round((successful / runs.length) * 100) : 0
  const timelinessRate = runs.length ? Math.round((timely / runs.length) * 100) : 0
  const completeness = dayCount ? Math.round((daysWithRun.size / dayCount) * 100) : 0
  const score = Math.round((successRate + timelinessRate + completeness) / 3)
  return {
    total: runs.length,
    successful,
    errors,
    successRate,
    timelinessRate,
    completeness,
    averageMinutes: durations.length
      ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length)
      : null,
    score
  }
}

function loadSnapshots(): KpiSnapshot[] {
  try {
    const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
    return Array.isArray(raw) ? (raw as KpiSnapshot[]) : []
  } catch {
    return []
  }
}

function saveSnapshots(items: KpiSnapshot[]): void {
  const latest = items.slice(-800)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(latest))
}

function upsertSnapshots(items: KpiSnapshot[]): KpiSnapshot[] {
  const next = loadSnapshots()
  const index = new Map(next.map((item, i) => [`${item.agentId}:${item.date}`, i]))
  for (const item of items) {
    const key = `${item.agentId}:${item.date}`
    const at = index.get(key)
    if (at == null) {
      index.set(key, next.length)
      next.push(item)
    } else {
      next[at] = item
    }
  }
  saveSnapshots(next)
  return next
}

function scoreForRuns(runs: AgentRunHistoryItem[]): number {
  return metricsFromRuns(runs, 1).score
}

export function KpiPage(): React.JSX.Element {
  const [tab, setTab] = useState<TabKey>('overview')
  const [period, setPeriod] = useState<PeriodState>(defaultPeriod)
  const [dynamicsMode, setDynamicsMode] = useState<DynamicsMode>('runs')
  const [agents, setAgents] = useState<BoardAgent[]>([])
  const [runsByAgent, setRunsByAgent] = useState<Record<string, AgentRunHistoryItem[]>>({})
  const [kpiByAgent, setKpiByAgent] = useState<Record<string, AgentKpi | null>>({})
  const [loading, setLoading] = useState(true)
  const [agentFilter, setAgentFilter] = useState<AgentFilter>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [snapshots, setSnapshots] = useState<KpiSnapshot[]>(() => loadSnapshots())
  const [recalcId, setRecalcId] = useState('')
  const [recalcAll, setRecalcAll] = useState(false)
  const [recalcError, setRecalcError] = useState('')
  const [recalcNote, setRecalcNote] = useState('')

  useEffect(() => {
    let alive = true
    async function load(): Promise<void> {
      setLoading(true)
      try {
        const board = await api.getWorkflowBoard()
        if (!alive) return
        const formedAgents = board.agents.filter(
          (agent) => agent.kind === 'workflow' && agent.phase === 'done' && !agent.paused
        )
        setAgents(formedAgents)
        const pairs = await Promise.all(
          formedAgents.map(async (agent) => {
            try {
              const [runs, kpi] = await Promise.all([
                api.listAgentRuns(agent.id),
                api.getWorkflowKpi(agent.id).catch(() => null)
              ])
              return [agent.id, runs, kpi] as const
            } catch {
              return [agent.id, [] as AgentRunHistoryItem[], null] as const
            }
          })
        )
        if (!alive) return
        setRunsByAgent(Object.fromEntries(pairs.map(([id, runs]) => [id, runs])))
        setKpiByAgent(Object.fromEntries(pairs.map(([id, , kpi]) => [id, kpi])))
      } finally {
        if (alive) setLoading(false)
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [])

  const bounds = useMemo(() => periodWindow(period), [period])

  const rows = useMemo(() => {
    return agents.map((agent) => {
      const allRuns = runsByAgent[agent.id] ?? []
      const runs = allRuns.filter((run) => inWindow(run, bounds.from, bounds.to))
      const runMetrics = metricsFromRuns(runs, bounds.days.length)
      const kpi = kpiByAgent[agent.id]
      const metrics = applyKpiTiles(runMetrics, kpi)
      const dailySuccess: number[] = []
      const dailyScore: number[] = []
      for (const day of bounds.days) {
        const dayRuns = allRuns.filter((run) => dayKey(runTime(run)) === day)
        dailySuccess.push(dayRuns.filter((run) => isSuccess(run.status)).length)
        dailyScore.push(scoreForRuns(dayRuns))
      }
      const uncalculated = runMetrics.total === 0 && !tilesHaveFacts(kpi)
      const attention =
        !uncalculated &&
        (metrics.successRate < 90 ||
          isAttentionStatus(agent.status) ||
          isAttentionStatus(agent.lastRunStatus))
      const critical = !uncalculated && (metrics.successRate < 75 || isErrorStatus(agent.lastRunStatus))
      return {
        agent,
        runs,
        ...metrics,
        attention,
        critical,
        uncalculated,
        lastCalculatedAt: latestTileUpdate(kpi),
        dailySuccess,
        dailyScore
      } satisfies AgentKpiView
    })
  }, [agents, runsByAgent, kpiByAgent, bounds])

  useEffect(() => {
    if (!rows.length) return
    const fresh: KpiSnapshot[] = []
    for (const row of rows) {
      bounds.days.forEach((date, index) => {
        if (!row.dailyScore[index] && !row.dailySuccess[index]) return
        fresh.push({
          date,
          agentId: row.agent.id,
          score: row.dailyScore[index] || 0,
          successRate: row.successRate,
          timelinessRate: row.timelinessRate,
          total: row.dailySuccess[index] || 0,
          errors: row.errors,
          averageMinutes: row.averageMinutes
        })
      })
    }
    if (fresh.length) setSnapshots(upsertSnapshots(fresh))
  }, [rows, bounds.days])

  useEffect(() => {
    if (selectedId && rows.some((row) => row.agent.id === selectedId)) return
    setSelectedId(rows[0]?.agent.id || '')
  }, [rows, selectedId])

  const overview = useMemo(() => {
    const allRuns = rows.flatMap((row) => row.runs)
    const totalByDay = bounds.days.map((day) =>
      allRuns.filter((run) => dayKey(runTime(run)) === day).length
    )
    const successByDay = bounds.days.map(
      (day) => allRuns.filter((run) => dayKey(runTime(run)) === day && isSuccess(run.status)).length
    )
    const attentionRows = rows.filter((row) => row.attention)
    const successfulRuns = allRuns.filter((run) => isSuccess(run.status)).length
    const successScore = allRuns.length ? Math.round((successfulRuns / allRuns.length) * 100) : 0
    const stabilityScore = rows.length
      ? Math.round((rows.filter((row) => !row.attention).length / rows.length) * 100)
      : 0
    const qualityScore = Math.round((successScore + stabilityScore) / 2)
    return {
      top: [...rows]
        .sort((a, b) => b.score - a.score || b.total - a.total)
        .slice(0, 4),
      attentionRows,
      stats: {
        activeAgents: agents.filter((agent) => agent.status === 'active').length,
        totalRuns: allRuns.length,
        successfulRuns,
        attention: attentionRows.length
      },
      totalSeries: totalByDay,
      successSeries: successByDay,
      score: Math.round((successScore + stabilityScore + qualityScore) / 3),
      scores: { quality: qualityScore, success: successScore, stability: stabilityScore }
    }
  }, [rows, agents, bounds.days])

  const filteredAgents = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (agentFilter === 'deviations' && !row.attention) return false
      if (agentFilter === 'critical' && !row.critical) return false
      if (q && !row.agent.title.toLowerCase().includes(q)) return false
      return true
    })
  }, [rows, agentFilter, query])

  const selected = rows.find((row) => row.agent.id === selectedId) || filteredAgents[0] || null
  const selectedHistory = snapshots
    .filter((item) => item.agentId === selected?.agent.id)
    .sort((a, b) => a.date.localeCompare(b.date))
  const previous = selected
    ? [...selectedHistory].reverse().find((item) => item.date !== bounds.days[bounds.days.length - 1])
    : null
  const change = selected && previous
    ? {
        up: Number(selected.score > previous.score),
        down: Number(selected.score < previous.score),
        same: Number(selected.score === previous.score)
      }
    : { up: 0, down: 0, same: selected ? 1 : 0 }

  const setKind = (kind: PeriodKind | RangeKey): void => {
    if (kind === '7' || kind === '30' || kind === '90') {
      setPeriod((prev) => ({ ...prev, kind: 'range', range: kind }))
      return
    }
    setPeriod((prev) => ({ ...prev, kind }))
  }

  const jumpToDate = (date: string): void => {
    setPeriod((prev) => ({ ...prev, kind: 'date', date }))
    setHistoryOpen(false)
  }

  const recalculate = async (workflowId: string): Promise<boolean> => {
    setRecalcError('')
    setRecalcNote('')
    setRecalcId(workflowId)
    try {
      const kpi = await api.calculateWorkflowKpi(workflowId)
      const runs = await api.listAgentRuns(workflowId)
      setKpiByAgent((prev) => ({ ...prev, [workflowId]: kpi }))
      setRunsByAgent((prev) => ({ ...prev, [workflowId]: runs }))
      const periodRuns = runs.filter((run) => inWindow(run, bounds.from, bounds.to))
      const metrics = applyKpiTiles(metricsFromRuns(periodRuns, bounds.days.length), kpi)
      setSnapshots(
        upsertSnapshots([
          {
            date: todayKey(),
            agentId: workflowId,
            score: metrics.score,
            successRate: metrics.successRate,
            timelinessRate: metrics.timelinessRate,
            total: metrics.total,
            errors: metrics.errors,
            averageMinutes: metrics.averageMinutes
          }
        ])
      )
      if (!tilesHaveFacts(kpi) && periodRuns.length === 0) {
        setRecalcNote('Пересчёт выполнен. Фактов пока нет: у агента нет запусков за период.')
      }
      return true
    } catch (error) {
      setRecalcError(error instanceof Error ? error.message : 'Не удалось пересчитать KPI')
      return false
    } finally {
      setRecalcId('')
    }
  }

  const recalculateAll = async (): Promise<void> => {
    setRecalcAll(true)
    try {
      for (const row of rows) {
        const ok = await recalculate(row.agent.id)
        if (!ok) break
      }
    } finally {
      setRecalcAll(false)
    }
  }

  const recalcBusy = Boolean(recalcId) || recalcAll

  return (
    <div className="kpi-page">
      <div className="kpi-head">
        <div>
          <h1 className="page-title">KPI агентов</h1>
          <p className="page-subtitle">Контроль эффективности и качества работы всех ИИ-агентов</p>
        </div>
      </div>

      <div className="kpi-toolbar">
        <div className="kpi-tabs">
          <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>
            Обзор
          </button>
          <button className={tab === 'agents' ? 'active' : ''} onClick={() => setTab('agents')}>
            Агенты
          </button>
        </div>
        <div className="kpi-period-bar">
          {tab === 'agents' && (
            <button
              className="btn-primary kpi-recalc-all"
              onClick={() => void recalculateAll()}
              disabled={recalcBusy || !rows.length}
            >
              {recalcBusy ? 'Пересчитываем...' : 'Пересчитать все KPI'}
            </button>
          )}
          <label className="kpi-period">
            <img src={iconCalendar} alt="" />
            <select
              value={period.kind === 'range' ? period.range : period.kind}
              onChange={(event) => setKind(event.target.value as PeriodKind | RangeKey)}
            >
              {Object.entries(RANGE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
              <option value="date">Конкретная дата</option>
              <option value="month">Конкретный месяц</option>
            </select>
          </label>
          {period.kind === 'date' && (
            <input
              className="kpi-date-input"
              type="date"
              value={period.date}
              onChange={(event) => setPeriod((prev) => ({ ...prev, date: event.target.value }))}
            />
          )}
          {period.kind === 'month' && (
            <input
              className="kpi-date-input"
              type="month"
              value={period.month}
              onChange={(event) => setPeriod((prev) => ({ ...prev, month: event.target.value }))}
            />
          )}
        </div>
      </div>

      {tab === 'overview' ? (
        <Overview
          loading={loading}
          model={overview}
          dynamicsMode={dynamicsMode}
          onDynamics={setDynamicsMode}
        />
      ) : (
        <AgentsPane
          rows={filteredAgents}
          allCount={rows.length}
          deviations={rows.filter((row) => row.attention).length}
          critical={rows.filter((row) => row.critical).length}
          filter={agentFilter}
          query={query}
          selected={selected}
          history={selectedHistory}
          historyOpen={historyOpen}
          days={bounds.days}
          change={change}
          onFilter={setAgentFilter}
          onQuery={setQuery}
          onSelect={setSelectedId}
          onToggleHistory={() => setHistoryOpen((value) => !value)}
          onJump={jumpToDate}
          recalcBusy={recalcBusy}
          recalcError={recalcError}
          recalcNote={recalcNote}
          onRecalc={() => selected && void recalculate(selected.agent.id)}
        />
      )}
    </div>
  )
}

function Overview({
  loading,
  model,
  dynamicsMode,
  onDynamics
}: {
  loading: boolean
  model: {
    top: AgentKpiView[]
    attentionRows: AgentKpiView[]
    stats: { activeAgents: number; totalRuns: number; successfulRuns: number; attention: number }
    totalSeries: number[]
    successSeries: number[]
    score: number
    scores: { quality: number; success: number; stability: number }
  }
  dynamicsMode: DynamicsMode
  onDynamics: (mode: DynamicsMode) => void
}): React.JSX.Element {
  return (
    <>
      <div className="kpi-stat-grid">
        <div className="kpi-stat-card">
          <span className="kpi-icon mint">
            <img src={iconActive} alt="" />
          </span>
          <div>
            <strong>{model.stats.activeAgents}</strong>
            <span>Активных агентов</span>
          </div>
          <Sparkline values={[1, 2, 2, 3, 4, model.stats.activeAgents]} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon mint">
            <img src={iconRuns} alt="" />
          </span>
          <div>
            <strong>{model.stats.totalRuns}</strong>
            <span>Запусков за период</span>
          </div>
          <Sparkline values={model.totalSeries.slice(-8)} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon mint">
            <img src={iconSuccess} alt="" />
          </span>
          <div>
            <strong>{model.stats.successfulRuns}</strong>
            <span>Успешных запусков</span>
          </div>
          <Sparkline values={model.successSeries.slice(-8)} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon warm">
            <img src={iconAttention} alt="" />
          </span>
          <div>
            <strong>{model.stats.attention}</strong>
            <span>Требуют внимания</span>
          </div>
          <Sparkline values={[0, 1, 0, 2, 1, model.stats.attention]} tone="orange" />
        </div>
      </div>

      <div className="kpi-grid-main">
        <section className="kpi-card kpi-efficiency">
          <div className="kpi-card-head">
            <div>
              <h3>Эффективность топ-4 агентов</h3>
              <p>Сравнение успешности запусков за выбранный период</p>
            </div>
            {loading && <span className="kpi-loading">Обновляем...</span>}
          </div>
          <div className="kpi-table-scroll">
            <div className="kpi-table">
              <div className="kpi-table-row head">
                <span>ИИ-агент</span>
                <span>Статус</span>
                <span>Запуски</span>
                <span>Успешность</span>
                <span>Своевременность</span>
                <span>Среднее время</span>
                <span>Динамика</span>
              </div>
              {model.top.map((row, index) => (
                <div className="kpi-table-row" key={row.agent.id}>
                  <span className="kpi-agent-cell">
                    <img src={robotFor(index, row.attention, row.critical, row.uncalculated)} alt="" />
                    <span>{row.agent.title}</span>
                  </span>
                  <span
                    className={`kpi-badge ${
                      row.uncalculated ? 'grey' : row.critical ? 'danger' : row.attention ? 'warn' : 'ok'
                    }`}
                  >
                    {statusLabel(row)}
                  </span>
                  <span>{row.total}</span>
                  <span className="kpi-rate-cell">
                    {row.total ? `${row.successRate}%` : 'нет запусков'}
                    {row.total > 0 && <RateBar value={row.successRate} tone={rowTone(row.successRate)} />}
                  </span>
                  <span className="kpi-rate-cell">
                    {row.total ? `${row.timelinessRate}%` : 'нет запусков'}
                    {row.total > 0 && <RateBar value={row.timelinessRate} tone={rowTone(row.timelinessRate)} />}
                  </span>
                  <span className={row.averageMinutes !== null && row.averageMinutes > 10 ? 'kpi-time warn' : 'kpi-time'}>
                    {formatAverage(row.averageMinutes)}
                  </span>
                  <Sparkline values={row.dailySuccess.slice(-8)} tone={statusTone(row)} />
                </div>
              ))}
              {!model.top.length && <div className="kpi-empty">Агенты появятся после публикации.</div>}
            </div>
          </div>
        </section>

        <aside className="kpi-card kpi-attention">
          <div className="kpi-card-head">
            <div>
              <h3>Требуют внимания</h3>
              <p>Зависли на подтверждении или завершились ошибкой</p>
            </div>
            <span className="kpi-count">{model.attentionRows.length}</span>
          </div>
          {model.attentionRows.slice(0, 4).map((row) => (
            <div className="kpi-attention-row" key={row.agent.id}>
              <img src={iconAttention} alt="" />
              <div>
                <strong>{row.agent.title}</strong>
                <span>{row.agent.lastRunStatus || row.agent.status || 'Требуется проверка'}</span>
              </div>
            </div>
          ))}
          {!model.attentionRows.length && <div className="kpi-empty">Критичных зависаний нет.</div>}
        </aside>
      </div>

      <div className="kpi-bottom-grid">
        <section className="kpi-card kpi-dynamics">
          <h3>Динамика запусков</h3>
          <div className="kpi-toggle">
            <button className={dynamicsMode === 'runs' ? 'active' : ''} onClick={() => onDynamics('runs')}>
              Запуски
            </button>
            <button className={dynamicsMode === 'success' ? 'active' : ''} onClick={() => onDynamics('success')}>
              Успешные
            </button>
          </div>
          <svg viewBox="0 0 640 190" className="kpi-chart" preserveAspectRatio="none">
            {[40, 80, 120, 160].map((y) => (
              <line key={y} x1="0" x2="640" y1={y} y2={y} />
            ))}
            <polyline
              points={chartPoints(dynamicsMode === 'runs' ? model.totalSeries : model.successSeries, 640, 180)}
              fill="none"
              stroke={dynamicsMode === 'runs' ? '#08745f' : '#33d3a1'}
              strokeWidth="3"
            />
          </svg>
        </section>

        <aside className="kpi-card kpi-score">
          <h3>Общая оценка</h3>
          <Donut score={model.score} />
          <div className="kpi-score-list">
            <span>
              Качество <b>{model.scores.quality}</b>
            </span>
            <span>
              Успех <b>{model.scores.success}</b>
            </span>
            <span>
              Стабильность <b>{model.scores.stability}</b>
            </span>
          </div>
        </aside>
      </div>
    </>
  )
}

function AgentsPane({
  rows,
  allCount,
  deviations,
  critical,
  filter,
  query,
  selected,
  history,
  historyOpen,
  days,
  change,
  onFilter,
  onQuery,
  onSelect,
  onToggleHistory,
  onJump,
  recalcBusy,
  recalcError,
  recalcNote,
  onRecalc
}: {
  rows: AgentKpiView[]
  allCount: number
  deviations: number
  critical: number
  filter: AgentFilter
  query: string
  selected: AgentKpiView | null
  history: KpiSnapshot[]
  historyOpen: boolean
  days: string[]
  change: { up: number; down: number; same: number }
  onFilter: (value: AgentFilter) => void
  onQuery: (value: string) => void
  onSelect: (id: string) => void
  onToggleHistory: () => void
  onJump: (date: string) => void
  recalcBusy: boolean
  recalcError: string
  recalcNote: string
  onRecalc: () => void
}): React.JSX.Element {
  return (
    <div className="kpi-agents">
      <aside className="kpi-card kpi-agent-list">
        <div className="kpi-card-head">
          <h3>Агенты</h3>
          <span className="kpi-count">{allCount}</span>
        </div>
        <input
          className="kpi-agent-search"
          value={query}
          placeholder="Найти агента"
          onChange={(event) => onQuery(event.target.value)}
        />
        <div className="kpi-chips">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => onFilter('all')}>
            Все
          </button>
          <button className={filter === 'deviations' ? 'active' : ''} onClick={() => onFilter('deviations')}>
            С отклонениями {deviations}
          </button>
          <button className={filter === 'critical' ? 'active' : ''} onClick={() => onFilter('critical')}>
            Критичные {critical}
          </button>
        </div>
        <div className="kpi-agent-scroll">
          {rows.map((row, index) => (
            <button
              key={row.agent.id}
              className={`kpi-agent-item${selected?.agent.id === row.agent.id ? ' selected' : ''}`}
              onClick={() => onSelect(row.agent.id)}
            >
              <img src={robotFor(index, row.attention, row.critical, row.uncalculated)} alt="" />
              <span>
                <b>{row.agent.title}</b>
                <i>
                  {row.uncalculated
                    ? 'KPI ещё не рассчитаны'
                    : `Расчёт: ${formatWhen(row.lastCalculatedAt || row.agent.lastRunAt)}`}
                </i>
              </span>
              <em className={`kpi-dot ${statusTone(row)}`} />
            </button>
          ))}
          {!rows.length && <div className="kpi-empty">Нет агентов по фильтру.</div>}
        </div>
      </aside>

      <div className="kpi-agent-detail">
        {selected ? (
          <>
            <section className="kpi-card kpi-agent-hero">
              <div className="kpi-agent-hero-main">
                <img src={robotFor(0, selected.attention, selected.critical, selected.uncalculated)} alt="" />
                <div>
                  <h3>{selected.agent.title}</h3>
                  <p>{selected.agent.triggerSummary || selected.agent.description || 'Опубликованный агент'}</p>
                  <small className="kpi-hero-meta">
                    {selected.uncalculated
                      ? 'KPI ещё не рассчитаны'
                      : `Последний пересчёт: ${formatWhen(selected.lastCalculatedAt || selected.agent.lastRunAt)}`}
                  </small>
                  <span
                    className={`kpi-badge ${
                      selected.uncalculated ? 'grey' : selected.critical ? 'danger' : selected.attention ? 'warn' : 'ok'
                    }`}
                  >
                    {statusLabel(selected)}
                  </span>
                </div>
              </div>
              <div className="kpi-agent-hero-side">
                <div className="kpi-agent-scorebox">
                  <strong>{selected.uncalculated ? '—' : selected.score}</strong>
                  <span>из 100</span>
                  <em className={selected.uncalculated ? 'grey' : selected.attention ? 'warn' : 'ok'}>
                    {selected.uncalculated
                      ? 'Нет расчёта'
                      : selected.attention
                        ? 'Есть отклонения'
                        : 'В норме'}
                  </em>
                </div>
                <button className="btn-primary kpi-recalc-btn" onClick={onRecalc} disabled={recalcBusy}>
                  {recalcBusy ? 'Пересчитываем...' : 'Пересчитать KPI'}
                </button>
              </div>
            </section>
            {recalcError && <div className="kpi-empty kpi-recalc-error">{recalcError}</div>}
            {recalcNote && !recalcError && <div className="kpi-empty">{recalcNote}</div>}

            <div className="kpi-metric-legend">
              <span className="ok">Норма</span>
              <span className="warn">Отклонение</span>
              <span className="danger">Критично</span>
              <span className="grey">Нет расчёта</span>
            </div>

            <div className="kpi-metric-grid">
              <MetricCard title="Успешность" value={selected.total ? `${selected.successRate}%` : '—'} hint="Доля успешных запусков" spark={selected.dailySuccess} tone={selected.total ? rowTone(selected.successRate) : 'grey'} />
              <MetricCard title="Своевременность" value={selected.total ? `${selected.timelinessRate}%` : '—'} hint="Запуски до 10 минут" spark={selected.dailyScore} tone={selected.total ? rowTone(selected.timelinessRate) : 'grey'} />
              <MetricCard title="Ошибки" value={String(selected.errors)} hint="Запуски со статусом ошибки" spark={selected.dailyScore} tone={selected.errors ? 'red' : selected.total ? 'green' : 'grey'} />
              <MetricCard title="Число запусков" value={String(selected.total)} hint="Все запуски за период" spark={selected.dailySuccess} tone={selected.total ? 'green' : 'grey'} />
              <MetricCard title="Среднее время" value={formatAverage(selected.averageMinutes)} hint="Средняя длительность запуска" spark={selected.dailyScore} tone={selected.averageMinutes == null ? 'grey' : selected.averageMinutes > 10 ? 'orange' : 'green'} />
              <MetricCard title="Полнота" value={`${selected.completeness}%`} hint="Дни периода с запусками" spark={selected.dailySuccess} tone={selected.total ? rowTone(selected.completeness) : 'grey'} />
            </div>

            <div className="kpi-agent-bottom">
              <section className="kpi-card">
                <div className="kpi-card-head">
                  <div>
                    <h3>История пересчётов</h3>
                    <p>Динамика общей оценки за выбранный период</p>
                  </div>
                  <button className="kpi-history-btn" onClick={onToggleHistory}>
                    {historyOpen ? 'Скрыть историю' : 'Открыть историю'}
                  </button>
                </div>
                <svg viewBox="0 0 640 190" className="kpi-chart" preserveAspectRatio="none">
                  {[40, 80, 120, 160].map((y) => (
                    <line key={y} x1="0" x2="640" y1={y} y2={y} />
                  ))}
                  <polyline
                    points={chartPoints(selected.dailyScore.length ? selected.dailyScore : [0], 640, 180)}
                    fill="none"
                    stroke="#08745f"
                    strokeWidth="3"
                  />
                </svg>
                <div className="kpi-chart-axis">
                  {days.filter((_, index) => index === 0 || index === days.length - 1 || index === Math.floor(days.length / 2)).map((day) => (
                    <span key={day}>{formatDayLabel(day)}</span>
                  ))}
                </div>
                {historyOpen && (
                  <div className="kpi-history-list">
                    {history.length ? (
                      history
                        .slice()
                        .reverse()
                        .slice(0, 14)
                        .map((item) => (
                          <button key={`${item.agentId}:${item.date}`} onClick={() => onJump(item.date)}>
                            <b>{formatDayLabel(item.date)}</b>
                            <span>{item.score} из 100</span>
                          </button>
                        ))
                    ) : (
                      <div className="kpi-empty">История появится после первых расчётов за период.</div>
                    )}
                  </div>
                )}
              </section>
              <aside className="kpi-card">
                <h3>Изменилось после пересчёта</h3>
                <div className="kpi-change-list">
                  <span className="ok">Улучшилось <b>{change.up}</b></span>
                  <span className="danger">Ухудшилось <b>{change.down}</b></span>
                  <span>Без изменений <b>{change.same}</b></span>
                </div>
              </aside>
            </div>
          </>
        ) : (
          <div className="kpi-card kpi-empty">Выберите агента слева, чтобы увидеть его KPI.</div>
        )}
      </div>
    </div>
  )
}

function MetricCard({
  title,
  value,
  hint,
  spark,
  tone
}: {
  title: string
  value: string
  hint: string
  spark: number[]
  tone: 'green' | 'orange' | 'red' | 'grey'
}): React.JSX.Element {
  const label = tone === 'green' ? 'В норме' : tone === 'orange' ? 'Отклонение' : tone === 'red' ? 'Критично' : 'Нет расчёта'
  return (
    <article className={`kpi-metric-card ${tone}`}>
      <div>
        <span>{title}</span>
        <strong>{value}</strong>
        <em>{label}</em>
        <p>{hint}</p>
      </div>
      <Sparkline values={spark.slice(-8)} tone={tone} />
    </article>
  )
}
