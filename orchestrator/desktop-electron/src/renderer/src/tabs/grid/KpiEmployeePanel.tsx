import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, LockKeyhole } from 'lucide-react'
import type { PositionKpiCompensation, PositionKpiMethodology } from '../../api/types'
import { PinWizard, type PinWizardFailure } from '../../components/PinCode'
import type { WorkplaceKpiEmployeeMetric } from '../../workplace/workplaceKpiTypes'

const CHART_W = 200
const CHART_H = 40
const CHART_PAD = 5

function yMaxForMetric(metric: WorkplaceKpiEmployeeMetric, points: number[]): number {
  if (metric.id === 'quality') return 5
  return Math.max(100, metric.planValue ?? 0, ...points)
}

/** Одна точка — ровная линия через всю плитку, а не клин из угла. */
function chartPoints(values: number[]): number[] {
  if (!values.length) return []
  return values.length === 1 ? [values[0], values[0]] : values
}

function chartY(value: number, max: number): number {
  return CHART_H - CHART_PAD - (Math.min(value, max) / Math.max(1, max)) * (CHART_H - CHART_PAD * 2)
}

/** Плавная кривая: каждый отрезок — кубическая Безье с опорами посередине по X. */
function smoothLine(values: number[], max: number): string {
  const step = CHART_W / (values.length - 1)
  return values
    .map((value, index) => {
      const x = index * step
      const y = chartY(value, max)
      if (index === 0) return `M ${x.toFixed(1)} ${y.toFixed(1)}`
      const px = (index - 1) * step
      const py = chartY(values[index - 1], max)
      const mid = (px + x) / 2
      return `C ${mid.toFixed(1)} ${py.toFixed(1)} ${mid.toFixed(1)} ${y.toFixed(1)} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

function KpiTrendChart({
  metric,
  gradId
}: {
  metric: WorkplaceKpiEmployeeMetric
  gradId: string
}): React.JSX.Element | null {
  const values = chartPoints(metric.sparklinePoints)
  if (!values.length) return <div className="kpi-trend kpi-trend--empty" aria-hidden />
  const max = yMaxForMetric(metric, values)
  const line = smoothLine(values, max)
  const lastY = chartY(values[values.length - 1], max)
  const planY = metric.planValue != null ? chartY(metric.planValue, max) : null
  const color = metric.sparklineColor || '#1565c0'
  return (
    <div className="kpi-trend" style={{ '--kpi-trend-color': color } as React.CSSProperties} aria-hidden>
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop className="kpi-trend-stop" offset="0%" stopOpacity="0.34" />
            <stop className="kpi-trend-stop" offset="100%" stopOpacity="0" />
          </linearGradient>
        </defs>
        {planY != null ? (
          <line className="kpi-trend-plan" x1="0" x2={CHART_W} y1={planY} y2={planY} vectorEffect="non-scaling-stroke" />
        ) : null}
        <path className="kpi-trend-area" d={`${line} L ${CHART_W} ${CHART_H} L 0 ${CHART_H} Z`} fill={`url(#${gradId})`} />
        <path className="kpi-trend-line" d={line} vectorEffect="non-scaling-stroke" />
      </svg>
      <i className="kpi-trend-dot" style={{ top: `${(lastY / CHART_H) * 100}%` }} />
    </div>
  )
}

function KpiEmployeeTile({
  metric,
  gradId,
  onInfo
}: {
  metric: WorkplaceKpiEmployeeMetric
  gradId: string
  onInfo?: (code: string) => void
}): React.JSX.Element {
  const trendClass =
    metric.trendPositive === false && metric.trendUp ? 'is-warn-up' : metric.trendPositive ? 'is-good' : 'is-bad'

  return (
    <article className="kpi-employee-tile kpi-metric-tile">
      <div className="kpi-employee-tile-head">
        <span className="kpi-employee-tile-title">{metric.title}</span>
        {onInfo ? (
          <button
            type="button"
            className="kpi-employee-info"
            title="Как считается этот показатель"
            aria-label={`Как считается «${metric.title}»`}
            onClick={() => onInfo(metric.id)}
          >
            i
          </button>
        ) : null}
      </div>
      <div className="kpi-employee-tile-values">
        <strong>{metric.displayValue}</strong>
        {metric.trendDelta ? (
          <span className={`kpi-employee-trend ${trendClass}`}>{metric.trendDelta}</span>
        ) : null}
        {metric.weight ? <span className="kpi-metric-weight">вес {metric.weight}%</span> : null}
      </div>
      <KpiTrendChart metric={metric} gradId={gradId} />
      {metric.footerText ? <p className="kpi-employee-footer">{metric.footerText}</p> : null}
    </article>
  )
}

function formatMoney(value: number | null, currency: string): string {
  if (value == null) return 'нет данных'
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: currency || 'RUB',
    maximumFractionDigits: 0
  }).format(value)
}

interface NoiseDot {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  phase: number
  pulse: number
  /** Может выйти за внутреннюю рамку; остальные от неё отражаются. */
  escaper: boolean
}

/** Отступ внешней рамки от внутренней: зона, куда долетают только «беглецы». */
const NOISE_BLEED_X = 10
const NOISE_BLEED_Y = 7
const NOISE_ESCAPERS = 0.2

/**
 * Скрытая сумма как в Сбере. Две рамки: внутренняя — полоса суммы, сквозь неё
 * проходят лишь некоторые точки; внешняя — стенка, за неё не выходит никто.
 * Точки бродят случайно, мерцают и то растут, то сжимаются.
 */
function MoneyNoise(): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    let width = 0
    let height = 0
    let dots: NoiseDot[] = []
    let frame = 0
    let last = performance.now()

    const seed = (): void => {
      const ratio = window.devicePixelRatio || 1
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = Math.max(1, Math.round(width * ratio))
      canvas.height = Math.max(1, Math.round(height * ratio))
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      const bandW = Math.max(0, width - NOISE_BLEED_X * 2)
      const bandH = Math.max(0, height - NOISE_BLEED_Y * 2)
      const count = Math.round((bandW * bandH) / 58)
      dots = Array.from({ length: count }, () => ({
        x: NOISE_BLEED_X + Math.random() * bandW,
        y: NOISE_BLEED_Y + Math.random() * bandH,
        vx: (Math.random() - 0.5) * 6,
        vy: (Math.random() - 0.5) * 4,
        radius: 0.9 + Math.random() * 0.7,
        phase: Math.random() * Math.PI * 2,
        pulse: 0.6 + Math.random() * 1.1,
        escaper: Math.random() < NOISE_ESCAPERS
      }))
    }

    const bounce = (dot: NoiseDot, minX: number, maxX: number, minY: number, maxY: number): void => {
      if (dot.x < minX || dot.x > maxX) {
        dot.vx = -dot.vx
        dot.x = Math.min(maxX, Math.max(minX, dot.x))
      }
      if (dot.y < minY || dot.y > maxY) {
        dot.vy = -dot.vy
        dot.y = Math.min(maxY, Math.max(minY, dot.y))
      }
    }

    const draw = (now: number): void => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      const t = now / 1000
      ctx.clearRect(0, 0, width, height)
      ctx.fillStyle = getComputedStyle(canvas).color
      for (const dot of dots) {
        dot.vx = (dot.vx + (Math.random() - 0.5) * 14 * dt) * 0.99
        dot.vy = (dot.vy + (Math.random() - 0.5) * 10 * dt) * 0.99
        dot.x += dot.vx * dt
        dot.y += dot.vy * dt
        if (dot.escaper) {
          const r = dot.radius * 1.3
          bounce(dot, r, width - r, r, height - r)
        } else {
          bounce(dot, NOISE_BLEED_X, width - NOISE_BLEED_X, NOISE_BLEED_Y, height - NOISE_BLEED_Y)
        }
        const wave = 0.5 + 0.5 * Math.sin(t * dot.pulse + dot.phase)
        ctx.globalAlpha = 0.35 + 0.55 * wave
        ctx.beginPath()
        ctx.arc(dot.x, dot.y, dot.radius * (0.7 + 0.6 * wave), 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      frame = window.requestAnimationFrame(draw)
    }

    seed()
    frame = window.requestAnimationFrame(draw)
    const observer = new ResizeObserver(() => seed())
    observer.observe(canvas)
    return () => {
      observer.disconnect()
      window.cancelAnimationFrame(frame)
    }
  }, [])

  return <canvas ref={canvasRef} className="kpi-money-noise" aria-hidden />
}

/** Купюра — по размеру как иконка карты в Сбере: плоская, почти прямые углы. */
function MoneyIcon(): React.JSX.Element {
  const id = useId().replace(/:/g, '')
  return (
    <svg className="kpi-money-icon" viewBox="0 0 28 18" aria-hidden>
      <defs>
        <linearGradient id={`${id}-note`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#d9e8dc" />
          <stop offset="100%" stopColor="#b9d3bf" />
        </linearGradient>
      </defs>
      <rect x="0.5" y="0.5" width="27" height="17" rx="1" fill={`url(#${id}-note)`} />
      <rect x="2" y="2" width="24" height="14" fill="none" stroke="#6f927a" strokeWidth="0.5" />
      <rect x="3.5" y="3.5" width="6" height="11" fill="#9dbca5" />
      <circle cx="18.5" cy="9" r="3.2" fill="none" stroke="#5d826a" strokeWidth="0.7" />
      <path
        d="M17.8 11.2V6.9h1.3a1.1 1.1 0 0 1 0 2.2h-1.9M16.9 10.2h2"
        fill="none"
        stroke="#3f6a4e"
        strokeWidth="0.7"
      />
    </svg>
  )
}

/** Глаз как в Сбере: при скрытой сумме перечёркнут, при показе черта уезжает. */
function MoneyEye({ open }: { open: boolean }): React.JSX.Element {
  return (
    <svg className={`kpi-money-eye-icon${open ? ' is-open' : ''}`} viewBox="0 0 24 24" aria-hidden>
      <path d="M2.4 12s3.5-6.4 9.6-6.4 9.6 6.4 9.6 6.4-3.5 6.4-9.6 6.4S2.4 12 2.4 12Z" />
      <circle cx="12" cy="12" r="3.1" />
      <path className="kpi-money-eye-slash" d="M4.6 4.6 19.4 19.4" />
    </svg>
  )
}

function salaryDate(value: string): string {
  const [year, month, day] = value.split('-')
  if (!year || !month || !day) return value
  return `${day}.${month}.${year}`
}

function KpiSalaryTile({
  compensation,
  loading,
  onShow,
  onHide
}: {
  compensation: PositionKpiCompensation
  loading?: boolean
  onShow: () => void
  onHide: () => void
}): React.JSX.Element {
  const visible = compensation.unlocked
  const history = compensation.history ?? []
  const historyKey = history.map((point) => `${point.effectiveFrom}:${point.total}`).join('|')
  const [index, setIndex] = useState(() => Math.max(0, history.length - 1))
  useEffect(() => {
    setIndex(Math.max(0, history.length - 1))
  }, [historyKey, history.length])
  const point = history[index]
  const salary = point?.salary ?? compensation.salary
  const bonus = point?.bonus ?? compensation.bonus
  const total = point?.total ?? compensation.total ?? (salary != null ? salary + (bonus ?? 0) : null)
  const when = point?.effectiveFrom || compensation.effectiveFrom
  return (
    <article className={`kpi-employee-tile kpi-salary-tile${visible ? ' is-visible' : ''}`}>
      <div className="kpi-salary-head">
        <MoneyIcon />
        <span className="kpi-salary-title">Зарплата</span>
        <button
          type="button"
          className="kpi-money-eye"
          title={visible ? 'Скрыть зарплату' : 'Показать зарплату'}
          aria-label={visible ? 'Скрыть зарплату' : 'Показать зарплату'}
          aria-pressed={visible}
          onClick={visible ? onHide : onShow}
          disabled={loading && !visible}
        >
          <MoneyEye open={visible} />
        </button>
      </div>
      {visible ? (
        <div className="kpi-salary-amount">
          <strong className="kpi-salary-total">{formatMoney(total, compensation.currency)}</strong>
        </div>
      ) : (
        <button
          type="button"
          className="kpi-salary-amount kpi-salary-mask"
          onClick={onShow}
          disabled={loading}
          aria-label="Показать зарплату"
        >
          {loading ? <span className="kpi-salary-wait">Загрузка…</span> : <MoneyNoise />}
        </button>
      )}
      {visible && history.length > 1 ? (
        <div className="kpi-salary-switch" role="group" aria-label="История изменения зарплаты">
          <button
            type="button"
            aria-label="Более ранний оклад"
            disabled={index === 0}
            onClick={() => setIndex((value) => Math.max(0, value - 1))}
          >
            <ChevronLeft size={14} />
          </button>
          <span>
            {index + 1} из {history.length}
            {when ? ` · ${salaryDate(when)}` : ''}
          </span>
          <button
            type="button"
            aria-label="Более поздний оклад"
            disabled={index >= history.length - 1}
            onClick={() => setIndex((value) => Math.min(history.length - 1, value + 1))}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      ) : null}
      <span className="kpi-salary-caption">
        {visible
          ? `Оклад ${formatMoney(salary, compensation.currency)} · Премия ${formatMoney(bonus, compensation.currency)}`
          : 'Оклад + премия'}
      </span>
    </article>
  )
}

type PinModal = null | { kind: 'create'; reveal: boolean } | { kind: 'unlock' }

function KpiPinDialog({
  modal,
  onClose,
  onCreate,
  onUnlock
}: {
  modal: Exclude<PinModal, null>
  onClose: () => void
  onCreate: (pin: string, repeat: string) => Promise<string>
  onUnlock: (pin: string) => Promise<string>
}): React.JSX.Element {
  const creating = modal.kind === 'create'
  const done = async (values: string[]): Promise<PinWizardFailure | null> => {
    if (creating) {
      const [pin, repeat] = values
      if (pin !== repeat) return { message: 'PIN-коды не совпадают. Придумайте ещё раз.' }
      const failure = await onCreate(pin, repeat)
      if (failure) return { message: failure }
      if (modal.reveal) await onUnlock(pin)
      onClose()
      return null
    }
    const failure = await onUnlock(values[0])
    if (failure) return { message: failure }
    onClose()
    return null
  }
  return createPortal(
    <div className="kpi-form-modal" role="dialog" aria-modal="true" aria-labelledby="kpi-salary-pin-title">
      <button className="kpi-form-modal-backdrop" type="button" aria-label="Закрыть" onClick={onClose} />
      <div className="kpi-form-modal-card kpi-pin-modal-card">
        <div className="kpi-pin-icon" aria-hidden>
          <LockKeyhole size={24} />
        </div>
        <h3 id="kpi-salary-pin-title">{creating ? 'Придумайте PIN-код' : 'Показать зарплату'}</h3>
        <p className="kpi-form-modal-lead">
          {creating
            ? 'Четыре цифры. Без этого кода оклад и премию на странице KPI не увидит никто, кроме вас.'
            : 'Введите свой PIN-код, чтобы увидеть оклад и премию.'}
        </p>
        <PinWizard
          steps={creating ? ['Придумайте PIN-код', 'Повторите PIN-код'] : ['Введите PIN-код']}
          onDone={done}
        />
        <p className="kpi-pin-hint">Сменить PIN-код можно в настройках, раздел «Безопасность».</p>
        <div className="kpi-form-modal-actions">
          <button className="spec-btn-outline" type="button" onClick={onClose}>
            {creating ? 'Позже' : 'Отмена'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

function metricWord(count: number): string {
  const tail = count % 100
  if (tail >= 11 && tail <= 14) return 'показателей'
  if (count % 10 === 1) return 'показатель'
  if (count % 10 >= 2 && count % 10 <= 4) return 'показателя'
  return 'показателей'
}

export function KpiEmployeePanel({
  metrics,
  compensation,
  compensationLoading,
  onUnlockCompensation,
  onHideCompensation,
  pin,
  pinPromptAllowed = true,
  loading,
  needsMethodology,
  methodologyStatus = needsMethodology ? 'needs_modules' : 'ready',
  methodology,
  onCalculate,
  onDetails,
  onInfo,
  variant = 'panel'
}: {
  metrics: WorkplaceKpiEmployeeMetric[]
  compensation: PositionKpiCompensation
  compensationLoading?: boolean
  /** Пустая строка — открыто, иначе текст ошибки. */
  onUnlockCompensation: (pin: string) => Promise<string>
  onHideCompensation: () => void
  pin: {
    loaded: boolean
    hasPin: boolean
    error: string
    create: (pin: string, repeat: string) => Promise<string>
  }
  /** Можно ли сразу при входе попросить придумать PIN (не поверх другого окна). */
  pinPromptAllowed?: boolean
  loading?: boolean
  /** Нет готового модуля расчёта KPI должности — не показываем заглушку. */
  needsMethodology?: boolean
  methodologyStatus?: 'none' | 'needs_modules' | 'ready'
  methodology?: PositionKpiMethodology | null
  onCalculate?: () => void
  onDetails?: () => void
  /** Открыть код, источник и формулу показателя. */
  onInfo?: (code: string) => void
  variant?: 'panel' | 'bar'
}): React.JSX.Element {
  const gradPrefix = useId().replace(/:/g, '')
  const pendingMetrics = (methodology?.metrics ?? []).filter((item) => !item.moduleReady)
  const [pinModal, setPinModal] = useState<PinModal>(null)
  const pinPrompted = useRef(false)

  useEffect(() => {
    if (pinPrompted.current || !pin.loaded || pin.hasPin || pin.error || !pinPromptAllowed) return
    pinPrompted.current = true
    setPinModal({ kind: 'create', reveal: false })
  }, [pin.loaded, pin.hasPin, pin.error, pinPromptAllowed])

  const showSalary = (): void => {
    if (!pin.loaded) return
    setPinModal(pin.hasPin ? { kind: 'unlock' } : { kind: 'create', reveal: true })
  }

  return (
    <section className={`kpi-employee-panel kpi-employee-panel--${variant}`}>
      {variant === 'panel' ? (
        <header className="kpi-employee-panel-head">
        <span className="kpi-employee-panel-icon" aria-hidden>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="#1565c0" />
            <path
              d="M12 11a3 3 0 100-6 3 3 0 000 6zM6 19c0-2.2 2.7-4 6-4s6 1.8 6 4"
              stroke="#fff"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </span>
        <h3 className="kpi-employee-panel-title">KPI сотрудника</h3>
        <button type="button" className="kpi-employee-panel-more" onClick={() => onDetails?.()} title="Подробнее">
          Подробнее →
        </button>
        </header>
      ) : null}
      <div className="kpi-employee-grid">
        <KpiSalaryTile
          compensation={compensation}
          loading={compensationLoading || !pin.loaded}
          onShow={showSalary}
          onHide={onHideCompensation}
        />
        {loading && !metrics.length ? (
          <p className="spec-v04-muted kpi-employee-loading">Загружаем KPI…</p>
        ) : metrics.map((m) => (
            <KpiEmployeeTile key={m.id} metric={m} gradId={`${gradPrefix}-${m.id}`} onInfo={onInfo} />
          ))}
      {methodologyStatus === 'needs_modules'
        ? pendingMetrics.map((item) => (
            <button
              key={item.code}
              type="button"
              className="kpi-employee-tile kpi-pending-tile"
              onClick={() => onCalculate?.()}
              title={[
                item.name,
                item.formulaHuman ? `Формула: ${item.formulaHuman}` : '',
                methodology?.sourceTitle ? `Источник: «${methodology.sourceTitle}»` : '',
                pendingMetrics.length > 1
                  ? `Агент напишет модули для ${pendingMetrics.length} ${metricWord(pendingMetrics.length)}`
                  : ''
              ]
                .filter(Boolean)
                .join('\n')}
            >
              <span className="kpi-employee-tile-title">{item.name}</span>
              <span className="kpi-pending-tile-state">
                Модуль не создан{item.weight ? ` · вес ${item.weight}%` : ''}
              </span>
              <span className="kpi-pending-tile-action">Создать модуль →</span>
            </button>
          ))
        : null}
      </div>
      {methodologyStatus === 'none' ? (
        <div className="kpi-employee-empty kpi-employee-empty--compact">
          <p>Не загружена методика расчета KPI. Обратитесь к администратору</p>
        </div>
      ) : null}
      {pinModal ? (
        <KpiPinDialog
          modal={pinModal}
          onClose={() => setPinModal(null)}
          onCreate={pin.create}
          onUnlock={onUnlockCompensation}
        />
      ) : null}
    </section>
  )
}
