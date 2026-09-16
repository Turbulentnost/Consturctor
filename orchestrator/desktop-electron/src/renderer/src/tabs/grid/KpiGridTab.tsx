import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_KPI_LAYOUT } from './useTabChromeLayout'
import type { UserProfile } from '../../api/types'
import { KpiRangePicker, type KpiRangeShortcut } from '../../pages/KpiRangePicker'
import { SpecFilters, SpecPanel, SpecPill, SpecProgress } from '../../workplace/specV04Components'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { SpecIconSearch } from '../../workplace/specV04Icons'
import { currentWeekRange, rollingKpiRange } from '../../workplace/kpiPeriod'
import { setKpiExportSnapshot } from '../../workplace/kpiExportSnapshot'
import {
  buildKpiDailySyncPayload,
  computeKpiEmployeeSnapshot,
  mergeEmployeeKpiAndZones
} from '../../workplace/mergeKpiEmployee'
import { useKpiPeriodSources } from '../../workplace/useKpiPeriodSources'
import { useKpiWorkflowBoard } from '../../workplace/useKpiWorkflowBoard'
import { useWorkplaceKpiDashboard } from '../../workplace/useWorkplaceKpiDashboard'
import { agentMatchesKpiTile, toggleSimpleTile } from '../../workplace/tileFilters'
import type { WorkplaceKpiCard } from '../../workplace/workplaceKpiTypes'
import { KpiEmployeePanel } from './KpiEmployeePanel'
import { KpiPeriodDynamicsChart } from './KpiPeriodDynamicsChart'
import { KpiProblemZonesTable } from './KpiProblemZonesTable'
import './kpiGrid.css'

const WEEK = currentWeekRange()

const LOADING_TILES: SpecSummaryTile[] = [
  { id: 'tasks', label: 'Выполнение задач', value: '—', tone: 'orange' },
  { id: 'sla', label: 'SLA', value: '—', tone: 'blue' },
  { id: 'load', label: 'Загрузка', value: '—', tone: 'purple' },
  { id: 'ai', label: 'Эффективность ИИ', value: '—', tone: 'green' },
  { id: 'auto', label: 'Доля автоматизации', value: '—', tone: 'yellow' },
  { id: 'quality', label: 'Качество', value: '—', tone: 'lilac' }
]

function cardsToTiles(cards: WorkplaceKpiCard[]): SpecSummaryTile[] {
  return cards.map((card) => ({
    id: card.id,
    label: card.label,
    value: card.displayValue,
    hint: card.trend ?? undefined,
    tone: (card.tone as SpecSummaryTile['tone']) || 'blue',
    progress: card.progress ?? undefined,
    ring: card.ring !== false && card.progress != null
  }))
}

export function KpiGridTab(_props: {
  user?: UserProfile
  onOpenProcesses?: () => void
  onOpenDecisions?: () => void
}): React.JSX.Element {
  const [from, setFrom] = useState(WEEK.from)
  const [to, setTo] = useState(WEEK.to)
  const [shortcut, setShortcut] = useState<KpiRangeShortcut | null>(null)
  const [agentQuery, setAgentQuery] = useState('')
  const [tileFilter, setTileFilter] = useState('all')
  const { data, loading, error, notice, reload } = useWorkplaceKpiDashboard(from, to)
  const periodSources = useKpiPeriodSources()
  const { board: workflowBoard } = useKpiWorkflowBoard(from, to)
  const dailySyncKeyRef = useRef('')

  const dashboard = useMemo(
    () => mergeEmployeeKpiAndZones(data, periodSources, from, to, workflowBoard),
    [data, periodSources, from, to, workflowBoard]
  )

  const tiles = useMemo(() => {
    if (dashboard?.cards.length) return cardsToTiles(dashboard.cards)
    if (loading) return LOADING_TILES
    return []
  }, [dashboard, loading])

  const agents = useMemo(() => {
    const rows = dashboard?.agents ?? []
    const byTile =
      tileFilter === 'all' ? rows : rows.filter((row) => agentMatchesKpiTile(row, tileFilter))
    const q = agentQuery.trim().toLowerCase()
    if (!q) return byTile
    return byTile.filter((row) =>
      [row.name, row.code, row.process, row.status].some((value) => value.toLowerCase().includes(q))
    )
  }, [dashboard, agentQuery, tileFilter])

  useEffect(() => {
    setKpiExportSnapshot({ from, to, data: dashboard })
    return () => setKpiExportSnapshot({ from: '', to: '', data: null })
  }, [from, to, dashboard])

  useEffect(() => {
    if (loading || !periodSources) return
    const snap = computeKpiEmployeeSnapshot(periodSources, from, to)
    if (!snap) return
    const metrics = buildKpiDailySyncPayload(from, to, snap)
    const key = metrics.map((m) => `${m.day}:${m.tasksPct}:${m.slaPct}`).join('|')
    if (dailySyncKeyRef.current === key) return
    dailySyncKeyRef.current = key
    void api
      .syncWorkplaceKpiDailyMetrics({ metrics })
      .then(() => reload())
      .catch(() => {
        dailySyncKeyRef.current = ''
      })
  }, [from, to, loading, periodSources, reload])

  const applyRange = (next: { from: string; to: string }): void => {
    setFrom(next.from)
    setTo(next.to)
    setShortcut(null)
  }

  const applyShortcut = (days: KpiRangeShortcut): void => {
    const next = rollingKpiRange(days)
    setFrom(next.from)
    setTo(next.to)
    setShortcut(days)
  }

  return (
    <StandardTabChrome
      tabId="kpi"
      userId={_props.user?.id || ''}
      defaults={DEFAULT_KPI_LAYOUT}
      labels={{
        side: 'KPI сотрудника',
        botB: 'Нагрузка: сотрудник vs ИИ',
        botC: 'Динамика показателей',
        botA: 'Проблемные зоны',
        main: 'KPI ИИ-агентов'
      }}
      chromeTiles={summaryTilesAsChrome(tiles, tileFilter === 'all' ? null : tileFilter, (id) =>
        setTileFilter((current) => toggleSimpleTile(current, id))
      )}
      widgets={{
        filters: (
        <>
        <SpecFilters layout="row">
          <KpiRangePicker from={from} to={to} shortcut={shortcut} onApply={applyRange} onShortcut={applyShortcut} />
        </SpecFilters>
        {!tiles.length && loading ? (
          <p className="kpi-dash-status-banner">Загружаем показатели…</p>
        ) : null}
        {notice ? <p className="kpi-dash-status-banner">{notice}</p> : null}
        {error ? <p className="kpi-dash-status-banner error">{error}</p> : null}
        </>
        ),
        side: (
          <KpiEmployeePanel
            metrics={dashboard?.employeeKpi ?? []}
            loading={loading}
            onDetails={() => _props.onOpenProcesses?.()}
          />
        ),
        main: (
        <div className="kpi-dash-main-wrap">
        <div className="spec-table-toolbar kpi-dash-table-toolbar">
          <h3 className="kpi-dash-table-title">KPI ИИ-агентов</h3>
          {dashboard?.periodLabel ? <span className="spec-v04-muted">{dashboard.periodLabel}</span> : null}
          <label className="spec-filter-input spec-filter-search kpi-dash-agent-search">
            <SpecIconSearch />
            <input
              className="wp-search"
              type="search"
              value={agentQuery}
              onChange={(event) => setAgentQuery(event.target.value)}
              placeholder="Поиск по агентам…"
            />
          </label>
        </div>
        <div className="spec-v04-table-wrap wp-card kpi-dash-main-table">
            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th>Агент</th>
                  <th>Процесс</th>
                  <th>Выполнение</th>
                  <th>SLA</th>
                  <th>Загрузка</th>
                  <th>Автоматизация</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {loading && !agents.length ? (
                  <tr>
                    <td colSpan={7} className="spec-v04-empty">
                      Загружаем…
                    </td>
                  </tr>
                ) : null}
                {!loading && !agents.length ? (
                  <tr>
                    <td colSpan={7} className="spec-v04-empty">
                      {agentQuery.trim()
                        ? 'Нет агентов по поиску'
                        : tileFilter !== 'all'
                          ? 'Нет агентов по выбранной плитке'
                          : 'Нет данных за период'}
                    </td>
                  </tr>
                ) : null}
                {agents.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <div className="kpi-dash-agent-name">
                        <strong>{row.name}</strong>
                        <span className="wp-code">{row.code}</span>
                      </div>
                    </td>
                    <td>{row.process}</td>
                    <td>
                      <SpecProgress value={row.completionPct} />
                    </td>
                    <td>{row.slaPct}%</td>
                    <td>{row.loadPct}%</td>
                    <td>{row.automationPct}%</td>
                    <td>
                      <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
        </div>
        </div>
        ),
        botA: <KpiProblemZonesTable zones={dashboard?.problemZones ?? []} loading={loading} />,
        botB: (
        <SpecPanel title="Нагрузка: сотрудник vs ИИ">
          <div className="kpi-widget-fill">
            <div className="kpi-compare-legend">
              <span className="emp">Сотрудник (ч)</span>
              <span className="ai">ИИ (ч)</span>
            </div>
            <div className="kpi-compare-chart kpi-compare-chart--dense">
              {(dashboard?.workloadCompare ?? []).map((row) => {
                const max = Math.max(row.employee, row.ai, 1)
                return (
                  <div key={row.id} className="kpi-compare-row">
                    <span className="kpi-compare-label">{row.label}</span>
                    <div className="kpi-compare-track">
                      <i className="emp" style={{ width: `${(row.employee / max) * 100}%` }} title={`${row.employee} ч`} />
                      <i className="ai" style={{ width: `${(row.ai / max) * 100}%` }} title={`${row.ai} ч`} />
                    </div>
                    <span className="kpi-compare-values">
                      <em className="emp">{row.employee}</em>
                      <span className="kpi-compare-sep">/</span>
                      <em className="ai">{row.ai}</em>
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </SpecPanel>
        ),
        botC: (
        <SpecPanel title={dashboard?.dynamics.title ?? 'Динамика показателей'}>
          <div className="kpi-widget-fill">
            {dashboard?.dynamics ? (
              <KpiPeriodDynamicsChart dynamics={dashboard.dynamics} />
            ) : loading ? (
              <p className="spec-v04-muted">Загружаем…</p>
            ) : null}
          </div>
        </SpecPanel>
        )
      }}
    />
  )
}
