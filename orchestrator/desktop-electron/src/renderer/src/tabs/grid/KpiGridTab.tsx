import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import { ApiError } from '../../api/types'
import { FioSuggest } from '../../components/FioSuggest'
import { StandardTabChrome } from './TabChromeGrid'
import { DEFAULT_KPI_LAYOUT } from './useTabChromeLayout'
import type { UserProfile } from '../../api/types'
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { SpecPill, SpecProgress } from '../../workplace/specV04Components'
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
import { OrchSlotMain } from '../../layout/GridSlots'
import { PositionKpiBuildPage } from '../../pages/PositionKpiBuildPage'
import { useKpiProtection, writeKpiUnlock } from '../../workplace/kpiProtection'
import { usePositionCompensation } from '../../workplace/usePositionCompensation'
import { useKpiPin } from '../../workplace/useKpiPin'
import { kpiPageTone, overallKpiPercent, useKpiPageTone } from '../../workplace/kpiPageTone'
import { usePositionKpi } from '../../workplace/usePositionKpi'
import { KpiEmployeePanel, KpiMethodOffer } from './KpiEmployeePanel'
import { KpiMetricCodeModal } from './KpiMetricCodeModal'
import { KpiDailyRunPanel, KpiDailyWaitingTile } from './KpiDailyRunPanel'
import { sameAgentTitle, useKpiDailyRun } from './useKpiDailyRun'
import { KpiFactModal } from './KpiFactModal'
import './kpiGrid.css'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'

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

const KPI_GENERATOR_PLATFORM_ID = 'f856136c-d75a-493b-8814-99bf6b06d721'
const KPI_GENERATOR_TITLE = 'генератор модулей kpi'
const KPI_RUNNER_TITLE = 'запуск модулей kpi'

function sameRunnerTitle(title: string): boolean {
  return title.trim().toLowerCase().replace(/ё/g, 'е') === KPI_RUNNER_TITLE
}

function kpiGeneratorTask(position: string, department: string, fio: string): string {
  const place = department ? `, подразделение «${department}»` : ''
  const who = fio.trim() ? ` Сотрудник, который открыл этот экран: «${fio.trim()}».` : ''
  return (
    `Считай только должность «${position}»${place}.${who} ` +
    'Модули запускай только с --fio этого человека. ' +
    'Другие должности и других держателей не обходи, даже если план в materials/agent.md ' +
    'говорит «для каждого profile_id» и «каждого из people», и даже если журнал прошлого запуска их перечисляет. ' +
    'Выполни план из materials/agent.md только для этой должности и этого сотрудника.'
  )
}

export function KpiGridTab(_props: {
  user?: UserProfile
  onOpenProcesses?: () => void
  onOpenDecisions?: () => void
  onRunAgent?: (workflowId: string, title: string, message: string) => void
  onOpenRun?: (workflowId: string, title: string) => void
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
  const [launchingGenerator, setLaunchingGenerator] = useState(false)
  const [launchError, setLaunchError] = useState('')
  const dailyRun = useKpiDailyRun(_props.user, positionKpi.reload)
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

  const launchGenerator = async (): Promise<void> => {
    if (launchingGenerator) return
    setLaunchError('')
    setLaunchingGenerator(true)
    try {
      const fromBoard = workflowBoard.agents.find((item) => sameAgentTitle(item.title, KPI_GENERATOR_TITLE))
      let workflowId = ''
      let title = 'Генератор модулей KPI'
      if (fromBoard?.id) {
        const record = await api.getWorkflow(fromBoard.id).catch(() => null)
        const notes = record?.notes || ''
        if (!record || notes.includes(KPI_GENERATOR_PLATFORM_ID) || sameAgentTitle(record.title, KPI_GENERATOR_TITLE)) {
          workflowId = fromBoard.id
          title = record?.title || fromBoard.title || title
        }
      }
      if (!workflowId) {
        const rows = await api.listWorkflows()
        const candidates = rows.filter(
          (item) => item.phase === 'done' && (sameAgentTitle(item.title, KPI_GENERATOR_TITLE) || item.title.toLowerCase().includes('генератор модулей'))
        )
        for (const item of candidates) {
          const record = await api.getWorkflow(item.id)
          if ((record.notes || '').includes(KPI_GENERATOR_PLATFORM_ID) || sameAgentTitle(record.title, KPI_GENERATOR_TITLE)) {
            workflowId = record.id
            title = record.title || item.title
            break
          }
        }
      }
      if (!workflowId || !_props.onRunAgent) {
        setLaunchError('В «Моих агентах» нет карточки «Генератор модулей KPI».')
        return
      }
      const position = (positionKpi.methodology?.position || _props.user?.position || '').trim()
      const department = (positionKpi.methodology?.department || _props.user?.department || '').trim()
      const fio = (_props.user?.fio || '').trim()
      if (!position) {
        setLaunchError('У пользователя не указана должность.')
        return
      }
      _props.onRunAgent(workflowId, title, kpiGeneratorTask(position, department, fio))
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : 'Не удалось запустить агента')
    } finally {
      setLaunchingGenerator(false)
    }
  }

  const launchRunner = async (): Promise<void> => {
    if (launchingGenerator) return
    setLaunchError('')
    setLaunchingGenerator(true)
    try {
      const fromBoard = workflowBoard.agents.find((item) => sameRunnerTitle(item.title))
      let workflowId = fromBoard?.id || ''
      let title = fromBoard?.title || 'Запуск модулей KPI'
      if (!workflowId) {
        const rows = await api.listWorkflows()
        const match = rows
          .filter((item) => item.phase === 'done' && sameRunnerTitle(item.title))
          .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))[0]
        workflowId = match?.id || ''
        title = match?.title || title
      }
      if (!workflowId || !_props.onRunAgent) {
        setLaunchError('В «Моих агентах» нет карточки «Запуск модулей KPI».')
        return
      }
      const position = (positionKpi.methodology?.position || _props.user?.position || '').trim()
      const department = (positionKpi.methodology?.department || _props.user?.department || '').trim()
      const fio = (_props.user?.fio || '').trim()
      if (!position) {
        setLaunchError('У пользователя не указана должность.')
        return
      }
      _props.onRunAgent(workflowId, title, kpiGeneratorTask(position, department, fio))
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : 'Не удалось запустить агента')
    } finally {
      setLaunchingGenerator(false)
    }
  }

  const downloadDailyReport = async (): Promise<void> => {
    const month = (dailyRun.today?.day || '').slice(0, 7)
    const result = await api.downloadKpiTodayReport(selfFio, month)
    if (!result.ok && !result.canceled) {
      setFormNote(result.error || 'Не удалось скачать отчёт ИЦПП')
    }
  }

  const dashboard = useMemo(
    () => mergeEmployeeKpiAndZones(data, periodSources, from, to, workflowBoard),
    [data, periodSources, from, to, workflowBoard]
  )

  const agents = useMemo(() => {
    const rows = dashboard?.agents ?? []
    const q = agentQuery.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((row) =>
      [row.name, row.code, row.process, row.status].some((value) => value.toLowerCase().includes(q))
    )
  }, [dashboard, agentQuery])
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
      <KpiFactModal
        position={_props.user?.position || ''}
        code={codeFor}
        month={(positionKpi.snap?.periodFrom || '').slice(0, 7)}
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
          <div className="kpi-tiles-stack">
            <KpiMethodOffer
              methodologyStatus={positionKpi.methodologyStatus}
              methodology={positionKpi.methodology}
              busy={launchingGenerator}
              error={launchError}
              onCalculate={() => void launchGenerator()}
            />
            <KpiDailyRunPanel
              daily={dailyRun}
              onDownloadReport={() => void downloadDailyReport()}
              onOpenChat={_props.onOpenRun ? () => _props.onOpenRun?.(dailyRun.workflowId, dailyRun.title) : undefined}
            />
            <div className="kpi-two-tier-tiles" ref={tilesRef}>
            <KpiEmployeePanel
              variant="bar"
              leadTile={
                dailyRun.phase === 'waiting' ? (
                  <KpiDailyWaitingTile
                    day={dailyRun.today?.day ? dailyRun.today.day.split('-').reverse().join('.') : 'сегодня'}
                  />
                ) : null
              }
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
              onOpenCalc={() => void launchRunner()}
              calcBusy={launchingGenerator}
              calcError={launchError}
              onInfo={(code) => setCodeFor(code)}
            />
            </div>
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
                      {agentQuery.trim() ? 'Нет агентов по поиску' : 'Нет данных за период'}
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
