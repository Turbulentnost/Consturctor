import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import { ApiError } from '../../api/types'
import { FioSuggest } from '../../components/FioSuggest'
import { StandardTabChrome } from './TabChromeGrid'
import { DEFAULT_KPI_LAYOUT } from './useTabChromeLayout'
import type { UserProfile } from '../../api/types'
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { SpecPill, SpecProgress, SpecSummaryTiles } from '../../workplace/specV04Components'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { SpecIconSearch } from '../../workplace/specV04Icons'
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
import { OrchSlotMain } from '../../layout/GridSlots'
import { PositionKpiBuildPage } from '../../pages/PositionKpiBuildPage'
import { useKpiProtection, writeKpiUnlock } from '../../workplace/kpiProtection'
import { usePositionCompensation } from '../../workplace/usePositionCompensation'
import { useKpiPin } from '../../workplace/useKpiPin'
import { kpiPageTone, overallKpiPercent, useKpiPageTone } from '../../workplace/kpiPageTone'
import { usePositionKpi } from '../../workplace/usePositionKpi'
import { KpiEmployeePanel } from './KpiEmployeePanel'
import { KpiMetricCodeModal } from './KpiMetricCodeModal'
import './kpiGrid.css'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'

const LOADING_TILES: SpecSummaryTile[] = [
  { id: 'tasks', label: 'Выполнение задач', value: '—', tone: 'orange' },
  { id: 'sla', label: 'SLA', value: '—', tone: 'blue' },
  { id: 'load', label: 'Загрузка', value: '—', tone: 'purple' },
  { id: 'ai', label: 'Эффективность ИИ', value: '—', tone: 'green' },
  { id: 'auto', label: 'Доля автоматизации', value: '—', tone: 'yellow' },
  { id: 'quality', label: 'Качество', value: '—', tone: 'lilac' }
]

/** Форма премирования — помесячная: период внутри одного месяца расширяем до всего месяца. */
function bonusMonth(from: string, to: string): { from: string; to: string } {
  if (!from || !to || from.slice(0, 7) !== to.slice(0, 7)) return { from, to }
  const [yearText, monthText] = to.slice(0, 7).split('-')
  const year = Number(yearText)
  const month = Number(monthText)
  const last = new Date(year, month, 0).getDate()
  const mm = String(month).padStart(2, '0')
  return { from: `${year}-${mm}-01`, to: `${year}-${mm}-${String(last).padStart(2, '0')}` }
}

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
  const { from, to } = useWorkplacePeriod()
  const selfFio = (_props.user?.fio || '').trim()
  const [formOpen, setFormOpen] = useState(false)
  const [person, setPerson] = useState(selfFio)
  const [personPosition, setPersonPosition] = useState('')
  const [subjectError, setSubjectError] = useState('')
  const [formBusy, setFormBusy] = useState(false)
  const [formNote, setFormNote] = useState('')
  const [agentQuery, setAgentQuery] = useState('')
  const [tileFilter, setTileFilter] = useState('all')
  const protection = useKpiProtection(_props.user?.id || '')
  const [gateDismissed, setGateDismissed] = useState(false)
  const [gateOpen, setGateOpen] = useState(false)
  const [gatePassword, setGatePassword] = useState('')
  const [gateBusy, setGateBusy] = useState(false)
  const [gateError, setGateError] = useState('')
  const [inMoney, setInMoney] = useState(true)
  const { data, loading, error, notice, reload } = useWorkplaceKpiDashboard(from, to)
  const positionKpi = usePositionKpi(_props.user?.position || '')
  const positionCompensation = usePositionCompensation()
  const kpiPin = useKpiPin()
  const [buildingMethod, setBuildingMethod] = useState(false)
  const [codeFor, setCodeFor] = useState('')
  const tilesRef = useRef<HTMLDivElement>(null)
  const overallPct = overallKpiPercent(positionKpi.snap)
  const pageTone = kpiPageTone(
    overallPct,
    Boolean(positionKpi.error) || positionKpi.methodologyStatus === 'none'
  )
  useKpiPageTone(tilesRef, pageTone, !buildingMethod)

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('kpi:module-chat-state', { detail: buildingMethod }))
    if (!buildingMethod) return
    return () => {
      window.dispatchEvent(new CustomEvent('kpi:module-chat-state', { detail: false }))
    }
  }, [buildingMethod])

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
  const globalSearchEntries = useMemo<GlobalSearchEntry[]>(
    () =>
      agents.map((row) => ({
        id: `kpi:${row.id}`,
        source: 'grid:kpi',
        pageKey: 'kpi',
        kind: 'entity',
        targetId: row.id,
        title: row.name,
        subtitle: [row.process, row.status].filter(Boolean).join(' · '),
        keywords: [row.code, String(row.completionPct), String(row.slaPct), String(row.automationPct)]
      })),
    [agents]
  )
  useRegisterGlobalSearch('grid:kpi', globalSearchEntries)

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

  useEffect(() => {
    if (!formOpen) return
    const fio = person.trim()
    if (fio.split(/\s+/).filter(Boolean).length < 2) {
      setPersonPosition('')
      setSubjectError('')
      return
    }
    let alive = true
    const timer = window.setTimeout(() => {
      void api
        .getPositionKpiSubject(fio)
        .then((subject) => {
          if (!alive) return
          setPersonPosition(subject.position)
          setSubjectError('')
        })
        .catch((err: unknown) => {
          if (!alive) return
          setPersonPosition('')
          setSubjectError(err instanceof ApiError ? err.message : 'Не удалось определить должность')
        })
    }, 250)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [formOpen, person])

  const userId = _props.user?.id || ''
  const unlocked = Boolean(protection.unlockToken)
  const showGate =
    gateOpen || (protection.loaded && protection.enabled && !unlocked && !gateDismissed)

  const submitGate = async (): Promise<void> => {
    if (gateBusy || !gatePassword) return
    setGateBusy(true)
    setGateError('')
    try {
      const unlock = await api.unlockKpiMoney(gatePassword)
      writeKpiUnlock(userId, unlock)
      setGatePassword('')
      setGateOpen(false)
      setGateDismissed(true)
    } catch (err: unknown) {
      setGateError(err instanceof ApiError ? err.message : 'Не удалось проверить пароль')
    } finally {
      setGateBusy(false)
    }
  }

  const closeGate = (): void => {
    setGatePassword('')
    setGateError('')
    setGateOpen(false)
    setGateDismissed(true)
  }

  useEffect(() => {
    const openBonusForm = (): void => {
      setPerson((current) => current.trim() || selfFio)
      setFormNote('')
      setFormOpen(true)
    }
    window.addEventListener('kpi:open-bonus-form', openBonusForm)
    return () => window.removeEventListener('kpi:open-bonus-form', openBonusForm)
  }, [selfFio])

  const downloadForm = async (): Promise<void> => {
    if (formBusy) return
    setFormBusy(true)
    setFormNote('')
    const period = bonusMonth(from, to)
    const token = unlocked && inMoney ? protection.unlockToken : ''
    try {
      const result = await api.downloadPositionKpiForm(person.trim() || selfFio, period.from, period.to, token)
      if (result.canceled) return
      if (!result.ok) {
        if (token && /истёк|пароль KPI/i.test(result.error || '')) writeKpiUnlock(userId, null)
        setFormNote(result.error || 'Не удалось сохранить форму')
        return
      }
      setFormNote('Форма премирования сохранена')
      setFormOpen(false)
    } catch (err: unknown) {
      setFormNote(err instanceof Error ? err.message : 'Не удалось сохранить форму')
    } finally {
      setFormBusy(false)
    }
  }

  if (buildingMethod) {
    return (
      <OrchSlotMain spanAll heavyEmbed>
        <div className="kpi-method-slot">
          <PositionKpiBuildPage
            position={_props.user?.position || ''}
            onBack={() => setBuildingMethod(false)}
            onReady={() => {
              setBuildingMethod(false)
              positionKpi.reload()
            }}
          />
        </div>
      </OrchSlotMain>
    )
  }

  return (
    <>
    {codeFor ? (
      <KpiMetricCodeModal
        position={_props.user?.position || ''}
        code={codeFor}
        onClose={() => setCodeFor('')}
      />
    ) : null}
    <StandardTabChrome
      tabId="kpi"
      userId={_props.user?.id || ''}
      defaults={DEFAULT_KPI_LAYOUT}
      hideGlobalPeriod
      labels={{
        main: 'KPI ИИ-агентов'
      }}
      widgets={{
        tiles: (
          <div className="kpi-two-tier-tiles" ref={tilesRef}>
            <KpiEmployeePanel
              variant="bar"
              metrics={positionKpi.metrics}
              compensation={positionCompensation.compensation}
              compensationLoading={positionCompensation.loading}
              onUnlockCompensation={positionCompensation.unlock}
              onHideCompensation={positionCompensation.hide}
              pin={kpiPin}
              pinPromptAllowed={!showGate && !formOpen}
              loading={positionKpi.loading}
              needsMethodology={positionKpi.needsBuild}
              methodologyStatus={positionKpi.methodologyStatus}
              methodology={positionKpi.methodology}
              onCalculate={() => setBuildingMethod(true)}
              onInfo={(code) => setCodeFor(code)}
            />
            <SpecSummaryTiles
              tiles={tiles}
              activeId={tileFilter === 'all' ? null : tileFilter}
              onSelect={(id) => setTileFilter((current) => toggleSimpleTile(current, id))}
              className="kpi-agent-top-tiles"
            />
          </div>
        ),
        filters: (
        <>
        {protection.enabled ? (
          <div className="kpi-form-toolbar">
            {unlocked ? (
              <span className="kpi-protect-badge">
                Суммы в рублях открыты
                <button type="button" className="kpi-protect-lock" onClick={() => writeKpiUnlock(userId, null)}>
                  Закрыть
                </button>
              </span>
            ) : (
              <button className="spec-btn-outline kpi-protect-open" type="button" onClick={() => setGateOpen(true)}>
                Ввести пароль KPI
              </button>
            )}
          </div>
        ) : null}
        {showGate
          ? createPortal(
              <div className="kpi-form-modal" role="dialog" aria-modal="true" aria-labelledby="kpi-gate-title">
                <button className="kpi-form-modal-backdrop" type="button" aria-label="Закрыть" onClick={closeGate} />
                <form
                  className="kpi-form-modal-card"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void submitGate()
                  }}
                >
                  <h3 id="kpi-gate-title">Вход в модуль KPI</h3>
                  <p className="kpi-form-modal-lead">
                    Введите пароль KPI, чтобы выгружать форму премирования в рублях. Без пароля суммы скрыты.
                  </p>
                  <label className="spec-filter-input kpi-form-person">
                    <input
                      className="wp-search"
                      type="password"
                      autoComplete="current-password"
                      autoFocus
                      value={gatePassword}
                      onChange={(event) => setGatePassword(event.target.value)}
                      placeholder="Пароль KPI"
                    />
                  </label>
                  {gateError ? <p className="kpi-form-modal-error">{gateError}</p> : null}
                  <div className="kpi-form-modal-actions">
                    <button className="btn-primary" type="submit" disabled={gateBusy || !gatePassword}>
                      {gateBusy ? 'Проверяю…' : 'Войти'}
                    </button>
                    <button className="spec-btn-outline" type="button" onClick={closeGate}>
                      Без сумм
                    </button>
                  </div>
                </form>
              </div>,
              document.body
            )
          : null}
        {!tiles.length && loading ? (
          <p className="kpi-dash-status-banner">Загружаем показатели…</p>
        ) : null}
        {notice ? <p className="kpi-dash-status-banner">{notice}</p> : null}
        {formNote && !formOpen ? (
          <p className={`kpi-dash-status-banner${formNote.includes('сохранена') ? '' : ' error'}`}>{formNote}</p>
        ) : null}
        {error ? <p className="kpi-dash-status-banner error">{error}</p> : null}
        {formOpen
          ? createPortal(
              <div className="kpi-form-modal" role="dialog" aria-modal="true" aria-labelledby="kpi-form-title">
                <button className="kpi-form-modal-backdrop" type="button" aria-label="Закрыть" onClick={() => setFormOpen(false)} />
                <div className="kpi-form-modal-card">
                  <h3 id="kpi-form-title">Индивидуальные целевые показатели</h3>
                  <p className="kpi-form-modal-lead">
                    Форма за месяц выбранного периода. Цели подставятся по должности сотрудника.
                  </p>
                  <label className="spec-filter-input kpi-form-person">
                    <FioSuggest
                      value={person}
                      onChange={setPerson}
                      onSelect={(fio) => setPerson(fio)}
                      placeholder="ФИО, например Ильченко Екатерина Александровна"
                      inputClassName="wp-search"
                      autoFocus
                    />
                  </label>
                  {personPosition ? <p className="kpi-form-modal-position">{personPosition}</p> : null}
                  {subjectError ? <p className="kpi-form-modal-error">{subjectError}</p> : null}
                  {unlocked ? (
                    <label className="kpi-form-money">
                      <input type="checkbox" checked={inMoney} onChange={(event) => setInMoney(event.target.checked)} />
                      <span>В рублях: оклад и база премии из 1С:ЗУП</span>
                    </label>
                  ) : protection.enabled ? (
                    <p className="kpi-form-modal-lead">Форма будет в процентах. Для сумм в рублях введите пароль KPI.</p>
                  ) : null}
                  {formNote ? <p className="kpi-form-modal-error">{formNote}</p> : null}
                  <div className="kpi-form-modal-actions">
                    <button
                      className="btn-primary"
                      type="button"
                      disabled={formBusy || !person.trim()}
                      onClick={() => void downloadForm()}
                    >
                      {formBusy ? 'Готовлю…' : 'Скачать'}
                    </button>
                    <button className="spec-btn-outline" type="button" onClick={() => setFormOpen(false)}>
                      Отмена
                    </button>
                  </div>
                </div>
              </div>,
              document.body
            )
          : null}
        </>
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
                  <tr key={row.id} data-search-id={row.id}>
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
      }}
    />
    </>
  )
}
