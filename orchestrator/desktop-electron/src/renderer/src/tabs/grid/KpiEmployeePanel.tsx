import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { LockKeyhole } from 'lucide-react'
import type { PositionKpiCompensation, PositionKpiMethodology } from '../../api/types'
import { PinWizard, type PinWizardFailure } from '../../components/PinCode'
import type { WorkplaceKpiEmployeeMetric } from '../../workplace/workplaceKpiTypes'

function sparklinePath(points: number[], width: number, height: number, max: number): string {
  if (!points.length) return ''
  const yMax = Math.max(1, max)
  const step = points.length > 1 ? width / (points.length - 1) : width
  return points
    .map((value, index) => {
      const x = index * step
      const y = height - (value / yMax) * (height - 8) - 4
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function sparklineArea(points: number[], width: number, height: number, max: number): string {
  const line = sparklinePath(points, width, height, max)
  if (!line) return ''
  // sparklinePath отдаёт список точек для polyline, а d обязан начинаться с moveto.
  return `M ${line.split(' ').join(' L ')} L ${width},${height} L 0,${height} Z`
}

function yMaxForMetric(metric: WorkplaceKpiEmployeeMetric): number {
  if (metric.id === 'quality') return 5
  return 100
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
  const width = 200
  const height = 52
  const yMax = yMaxForMetric(metric)
  const points = metric.sparklinePoints.length ? metric.sparklinePoints : [0]
  const color = metric.sparklineColor || '#1565c0'
  const trendClass =
    metric.trendPositive === false && metric.trendUp ? 'is-warn-up' : metric.trendPositive ? 'is-good' : 'is-bad'

  return (
    <article className="kpi-employee-tile">
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
          <span className={`kpi-employee-trend ${trendClass}`} aria-hidden>
            {metric.trendUp ? '↑' : '↓'} {metric.trendDelta}
          </span>
        ) : null}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="kpi-employee-spark" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <path d={sparklineArea(points, width, height, yMax)} fill={`url(#${gradId})`} />
        <polyline points={sparklinePath(points, width, height, yMax)} fill="none" stroke={color} strokeWidth="2" />
      </svg>
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
  homeX: number
  homeY: number
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  phase: number
  pulse: number
}

/** Запас холста вокруг полосы суммы: сюда точки выбиваются за край. */
const NOISE_BLEED_X = 10
const NOISE_BLEED_Y = 7

function gauss(): number {
  return Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random())
}

/**
 * Скрытая сумма как в Сбере: облако мелких точек без ровных краёв.
 * Каждая точка бродит вокруг своего места, мерцает и то растёт, то сжимается;
 * у краёв точек меньше, а вылетевшие за полосу бледнеют.
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
      const count = Math.round((bandW * bandH) / 26)
      dots = Array.from({ length: count }, () => {
        const homeX = NOISE_BLEED_X + Math.random() * bandW + gauss() * 2.5
        const homeY = height / 2 + gauss() * bandH * 0.36
        return {
          homeX,
          homeY,
          x: homeX,
          y: homeY,
          vx: gauss() * 2,
          vy: gauss() * 1.5,
          radius: 0.5 + Math.random() * 0.6,
          phase: Math.random() * Math.PI * 2,
          pulse: 0.6 + Math.random() * 1.1
        }
      })
    }

    const edgeFade = (x: number, y: number): number => {
      const outX = Math.max(NOISE_BLEED_X - x, x - (width - NOISE_BLEED_X), 0)
      const outY = Math.max(NOISE_BLEED_Y - y, y - (height - NOISE_BLEED_Y), 0)
      return Math.exp(-(outX * outX + outY * outY) / 18)
    }

    const draw = (now: number): void => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      const t = now / 1000
      ctx.clearRect(0, 0, width, height)
      ctx.fillStyle = getComputedStyle(canvas).color
      for (const dot of dots) {
        dot.vx = (dot.vx + (Math.random() - 0.5) * 14 * dt - (dot.x - dot.homeX) * 0.9 * dt) * 0.99
        dot.vy = (dot.vy + (Math.random() - 0.5) * 10 * dt - (dot.y - dot.homeY) * 0.9 * dt) * 0.99
        dot.x += dot.vx * dt
        dot.y += dot.vy * dt
        const wave = 0.5 + 0.5 * Math.sin(t * dot.pulse + dot.phase)
        ctx.globalAlpha = (0.35 + 0.55 * wave) * edgeFade(dot.x, dot.y)
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
  const total =
    compensation.total ??
    (compensation.salary != null ? compensation.salary + (compensation.bonus ?? 0) : null)
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
      <span className="kpi-salary-caption">
        {visible
          ? `Оклад ${formatMoney(compensation.salary, compensation.currency)} · Премия ${formatMoney(
              compensation.bonus,
              compensation.currency
            )}`
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
