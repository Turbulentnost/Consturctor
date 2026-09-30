import { useId, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Eye, EyeOff } from 'lucide-react'
import type { PositionKpiCompensation, PositionKpiMethodology } from '../../api/types'
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
  return `M ${line} L ${width},${height} L 0,${height} Z`
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
  const toggle = visible ? onHide : onShow
  return (
    <article className={`kpi-employee-tile kpi-salary-tile${visible ? ' is-visible' : ''}`}>
      <div className="kpi-employee-tile-head">
        <span className="kpi-employee-tile-title">ЗП</span>
        <button
          type="button"
          className="kpi-salary-eye"
          title={visible ? 'Скрыть зарплату' : 'Показать зарплату'}
          aria-label={visible ? 'Скрыть зарплату' : 'Показать зарплату'}
          onClick={toggle}
        >
          {visible ? <Eye size={18} /> : <EyeOff size={18} />}
        </button>
      </div>
      {visible ? (
        <div className="kpi-salary-values">
          <div>
            <span>Оклад</span>
            <strong>{formatMoney(compensation.salary, compensation.currency)}</strong>
          </div>
          <div>
            <span>Премия</span>
            <strong>{formatMoney(compensation.bonus, compensation.currency)}</strong>
          </div>
        </div>
      ) : (
        <button type="button" className="kpi-salary-mask" onClick={onShow} disabled={loading}>
          <strong>{loading ? 'Загрузка…' : '••• ••• ₽'}</strong>
          <span>Оклад + премия</span>
        </button>
      )}
    </article>
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
  compensationUnlocking,
  compensationError,
  onUnlockCompensation,
  onHideCompensation,
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
  compensationUnlocking?: boolean
  compensationError?: string
  onUnlockCompensation: (pin: string) => Promise<boolean>
  onHideCompensation: () => void
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
  const [pinOpen, setPinOpen] = useState(false)
  const [pin, setPin] = useState('')

  const closePin = (): void => {
    if (compensationUnlocking) return
    setPinOpen(false)
    setPin('')
  }

  const submitPin = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    if (!pin) return
    if (await onUnlockCompensation(pin)) closePin()
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
          loading={compensationLoading}
          onShow={() => setPinOpen(true)}
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
      {pinOpen
        ? createPortal(
            <div className="kpi-form-modal" role="dialog" aria-modal="true" aria-labelledby="kpi-salary-pin-title">
              <button className="kpi-form-modal-backdrop" type="button" aria-label="Закрыть" onClick={closePin} />
              <form className="kpi-form-modal-card kpi-pin-modal-card" onSubmit={(event) => void submitPin(event)}>
                <div className="kpi-pin-icon" aria-hidden>
                  <EyeOff size={22} />
                </div>
                <h3 id="kpi-salary-pin-title">Показать зарплату</h3>
                <p className="kpi-form-modal-lead">Введите PIN-код для просмотра оклада и премии.</p>
                <input
                  className="kpi-pin-input"
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={4}
                  value={pin}
                  onChange={(event) => setPin(event.target.value.replace(/\D/g, '').slice(0, 4))}
                  placeholder="••••"
                  aria-label="PIN-код"
                  autoFocus
                />
                {compensationError ? <p className="kpi-form-modal-error">{compensationError}</p> : null}
                <div className="kpi-form-modal-actions">
                  <button className="btn-primary" type="submit" disabled={compensationUnlocking || pin.length !== 4}>
                    {compensationUnlocking ? 'Проверяем…' : 'Показать'}
                  </button>
                  <button className="spec-btn-outline" type="button" onClick={closePin} disabled={compensationUnlocking}>
                    Отмена
                  </button>
                </div>
              </form>
            </div>,
            document.body
          )
        : null}
    </section>
  )
}
