import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, BoardAgent } from '../api/types'

const iconCalendar = new URL('../../../temp/KPI/calendar.png', import.meta.url).href
const iconActive = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_22_41.png', import.meta.url).href
const iconRuns = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_23_18.png', import.meta.url).href
const iconSuccess = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_23_35.png', import.meta.url).href
const iconAttention = new URL('../../../temp/KPI/3ee02669-15be-4acb-9537-89da251eaa83.png', import.meta.url).href
const robotGreen = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_28_22.png', import.meta.url).href
const robotBlue = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_28_29.png', import.meta.url).href
const robotYellow = new URL('../../../temp/KPI/9421cf0b-b18d-4568-9e74-cf99d542b73b.png', import.meta.url).href
const robotRed = new URL('../../../temp/KPI/59561baa-bbdc-4f74-8cf4-d78179bae59d.png', import.meta.url).href

type PeriodKey = '7' | '30' | '90'
type DynamicsMode = 'runs' | 'success'

interface AgentKpiView {
  agent: BoardAgent
  runs: AgentRunHistoryItem[]
  total: number
  successful: number
  attention: boolean
  successRate: number
  timelinessRate: number
  averageMinutes: number | null
  dailySuccess: number[]
}

const PERIOD_LABELS: Record<PeriodKey, string> = {
  '7': 'Последние 7 дней',
  '30': 'Последние 30 дней',
  '90': 'Последние 90 дней'
}

function isSuccess(status: string): boolean {
  const value = status.toLowerCase()
  return ['ok', 'success', 'successful', 'completed', 'done', 'ready'].some((x) => value.includes(x))
}

function isAttentionStatus(status: string): boolean {
  const value = status.toLowerCase()
  return ['attention', 'approval', 'confirm', 'pending', 'wait', 'error', 'fail', 'stuck'].some((x) =>
    value.includes(x)
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

function inPeriod(run: AgentRunHistoryItem, from: number): boolean {
  const time = runTime(run)
  return time > 0 && time >= from
}

function dayKey(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate()
  ).padStart(2, '0')}`
}

function periodDays(period: PeriodKey): string[] {
  const days = Number(period)
  const out: string[] = []
  const base = new Date()
  base.setHours(0, 0, 0, 0)
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = new Date(base)
    date.setDate(base.getDate() - i)
    out.push(dayKey(date.getTime()))
  }
  return out
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

function Sparkline({ values, tone = 'green' }: { values: number[]; tone?: 'green' | 'orange' | 'red' }): React.JSX.Element {
  const stroke = tone === 'green' ? '#08745f' : tone === 'orange' ? '#e67e22' : '#c0392b'
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

function robotFor(index: number, attention: boolean): string {
  if (attention) return robotRed
  return [robotGreen, robotBlue, robotYellow, robotGreen][index % 4]
}

function statusLabel(row: AgentKpiView): string {
  if (row.attention) return row.successRate < 80 ? 'Ошибка' : 'Внимание'
  return 'Работает'
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

export function KpiPage(): React.JSX.Element {
  const [period, setPeriod] = useState<PeriodKey>('30')
  const [dynamicsMode, setDynamicsMode] = useState<DynamicsMode>('runs')
  const [agents, setAgents] = useState<BoardAgent[]>([])
  const [runsByAgent, setRunsByAgent] = useState<Record<string, AgentRunHistoryItem[]>>({})
  const [loading, setLoading] = useState(true)

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
              return [agent.id, await api.listAgentRuns(agent.id)] as const
            } catch {
              return [agent.id, []] as const
            }
          })
        )
        if (!alive) return
        setRunsByAgent(Object.fromEntries(pairs))
      } finally {
        if (alive) setLoading(false)
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [])

  const model = useMemo(() => {
    const from = Date.now() - Number(period) * 24 * 60 * 60 * 1000
    const days = periodDays(period)
    const rows: AgentKpiView[] = agents.map((agent) => {
      const runs = (runsByAgent[agent.id] ?? []).filter((run) => inPeriod(run, from))
      const successful = runs.filter((run) => isSuccess(run.status)).length
      const durations = runs
        .map(runDurationMinutes)
        .filter((value): value is number => value !== null)
      const timely = durations.length
        ? runs.filter((run) => {
            const duration = runDurationMinutes(run)
            return duration !== null && duration <= 10
          }).length
        : successful
      const daily = Object.fromEntries(days.map((day) => [day, 0]))
      runs.forEach((run) => {
        const time = runTime(run)
        if (!time || !isSuccess(run.status)) return
        const key = dayKey(time)
        if (key in daily) daily[key] += 1
      })
      const attention = isAttentionStatus(agent.status) || isAttentionStatus(agent.lastRunStatus)
      return {
        agent,
        runs,
        total: runs.length,
        successful,
        attention,
        successRate: runs.length ? Math.round((successful / runs.length) * 100) : 0,
        timelinessRate: runs.length ? Math.round((timely / runs.length) * 100) : 0,
        averageMinutes: durations.length
          ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length)
          : null,
        dailySuccess: days.map((day) => daily[day])
      }
    })
    const allRuns = rows.flatMap((row) => row.runs)
    const totalByDay = Object.fromEntries(days.map((day) => [day, 0]))
    const successByDay = Object.fromEntries(days.map((day) => [day, 0]))
    allRuns.forEach((run) => {
      const time = runTime(run)
      if (!time) return
      const key = dayKey(time)
      if (key in totalByDay) totalByDay[key] += 1
      if (key in successByDay && isSuccess(run.status)) successByDay[key] += 1
    })
    const activeAgents = agents.filter((agent) => agent.status === 'active').length
    const successfulRuns = allRuns.filter((run) => isSuccess(run.status)).length
    const attentionRows = rows.filter((row) => row.attention)
    const successScore = allRuns.length ? Math.round((successfulRuns / allRuns.length) * 100) : 0
    const stabilityScore = rows.length
      ? Math.round((rows.filter((row) => !row.attention).length / rows.length) * 100)
      : 0
    const qualityScore = Math.round((successScore + stabilityScore) / 2)
    return {
      rows,
      top: [...rows]
        .sort((a, b) => b.successRate + b.timelinessRate - (a.successRate + a.timelinessRate) || b.total - a.total)
        .slice(0, 4),
      attentionRows,
      stats: {
        activeAgents,
        totalRuns: allRuns.length,
        successfulRuns,
        attention: attentionRows.length
      },
      totalSeries: days.map((day) => totalByDay[day]),
      successSeries: days.map((day) => successByDay[day]),
      score: Math.round((successScore + stabilityScore + qualityScore) / 3),
      scores: {
        quality: qualityScore,
        success: successScore,
        stability: stabilityScore
      }
    }
  }, [agents, period, runsByAgent])

  return (
    <div className="kpi-page">
      <div className="kpi-head">
        <div>
          <h1 className="page-title">KPI агентов</h1>
          <p className="page-subtitle">Контроль эффективности и качества работы всех ИИ-агентов</p>
        </div>
        <label className="kpi-period">
          <img src={iconCalendar} alt="" />
          <select value={period} onChange={(event) => setPeriod(event.target.value as PeriodKey)}>
            {Object.entries(PERIOD_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpi-stat-grid">
        <div className="kpi-stat-card">
          <span className="kpi-icon mint"><img src={iconActive} alt="" /></span>
          <div><strong>{model.stats.activeAgents}</strong><span>Активных агентов</span></div>
          <Sparkline values={[1, 2, 2, 3, 4, model.stats.activeAgents]} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon mint"><img src={iconRuns} alt="" /></span>
          <div><strong>{model.stats.totalRuns}</strong><span>Запусков за период</span></div>
          <Sparkline values={model.totalSeries.slice(-8)} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon mint"><img src={iconSuccess} alt="" /></span>
          <div><strong>{model.stats.successfulRuns}</strong><span>Успешных запусков</span></div>
          <Sparkline values={model.successSeries.slice(-8)} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon warm"><img src={iconAttention} alt="" /></span>
          <div><strong>{model.stats.attention}</strong><span>Требуют внимания</span></div>
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
                  <img src={robotFor(index, row.attention)} alt="" />
                  <span>{row.agent.title}</span>
                </span>
                <span className={row.attention ? 'kpi-badge danger' : 'kpi-badge ok'}>
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
                <Sparkline values={row.dailySuccess.slice(-8)} tone={row.attention ? 'orange' : 'green'} />
              </div>
            ))}
            {!model.top.length && <div className="kpi-empty">Агенты появятся после публикации.</div>}
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
            <button
              className={dynamicsMode === 'runs' ? 'active' : ''}
              onClick={() => setDynamicsMode('runs')}
            >
              Запуски
            </button>
            <button
              className={dynamicsMode === 'success' ? 'active' : ''}
              onClick={() => setDynamicsMode('success')}
            >
              Успешные
            </button>
          </div>
          <svg viewBox="0 0 640 190" className="kpi-chart" preserveAspectRatio="none">
            {[40, 80, 120, 160].map((y) => <line key={y} x1="0" x2="640" y1={y} y2={y} />)}
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
            <span>Качество <b>{model.scores.quality}</b></span>
            <span>Успех <b>{model.scores.success}</b></span>
            <span>Стабильность <b>{model.scores.stability}</b></span>
          </div>
        </aside>
      </div>
    </div>
  )
}

export function DashboardPage(): React.JSX.Element {
  return (
    <div>
      <h1 className="page-title">Мой дашборд</h1>
      <p className="page-subtitle">Сводка по вашим агентам и задачам</p>
      <div className="placeholder-card">
        Раздел дашборда будет перенесён на следующем шаге миграции.
      </div>
    </div>
  )
}

export function RegulationResultView({
  fileName,
  pageCount,
  sectionCount,
  onBack
}: {
  fileName: string
  pageCount: number
  sectionCount: number
  onBack: () => void
}): React.JSX.Element {
  return (
    <div>
      <h1 className="page-title">Регламент распознан</h1>
      <p className="page-subtitle">{fileName}</p>
      <div className="placeholder-card" style={{ textAlign: 'left' }}>
        <div>
          Страниц: <b>{pageCount}</b>
        </div>
        <div>
          Разделов: <b>{sectionCount}</b>
        </div>
        <p style={{ marginTop: 16, color: 'var(--content-muted)' }}>
          Следующие шаги конструктора (проверка регламента, подбор функций по должности,
          готовность, паспорт агента, формирование и пробный прогон) переносятся поэтапно.
        </p>
      </div>
      <button className="btn-primary" style={{ maxWidth: 200, marginTop: 20 }} onClick={onBack}>
        Назад
      </button>
    </div>
  )
}
