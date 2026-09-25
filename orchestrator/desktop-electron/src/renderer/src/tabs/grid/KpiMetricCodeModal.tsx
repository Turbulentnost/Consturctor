import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import type { PositionKpiMetricDetail } from '../../api/types'

function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params)
  if (!entries.length) return '—'
  return entries.map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`).join('\n')
}

export function KpiMetricCodeModal({
  position,
  code,
  onClose
}: {
  position: string
  code: string
  onClose: () => void
}): React.JSX.Element {
  const titleId = useId()
  const [detail, setDetail] = useState<PositionKpiMetricDetail | null>(null)
  const [error, setError] = useState('')
  const [showTests, setShowTests] = useState(false)

  useEffect(() => {
    let alive = true
    setDetail(null)
    setError('')
    void api
      .getPositionKpiMetric(position, code)
      .then((next) => {
        if (alive) setDetail(next)
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось открыть код показателя')
      })
    return () => {
      alive = false
    }
  }, [position, code])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const source = detail?.dataSource
  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card kpi-code-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="kpi-code-head">
          <div>
            <h3 id={titleId}>{detail?.name || code}</h3>
            {detail ? (
              <p>
                Вес {detail.weight}%{detail.plan != null ? ` · план ${detail.plan}${detail.unit}` : ''}
              </p>
            ) : null}
          </div>
          <button type="button" className="kpi-code-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>

        {!detail && !error ? <p className="spec-v04-muted">Загружаем код показателя…</p> : null}
        {error ? <p className="kpi-code-error">{error}</p> : null}

        {detail ? (
          <div className="kpi-code-body">
            <p className="kpi-code-shared">{detail.sharedNote}</p>

            {detail.formulaHuman ? (
              <section>
                <h4>Формула</h4>
                <p>{detail.formulaHuman}</p>
              </section>
            ) : null}

            <section>
              <h4>Откуда берутся данные</h4>
              {source?.registry ? (
                <>
                  <p>
                    <strong>{source.registry.title}</strong> <code>{source.source}</code>
                    {source.registry.perEmployee ? ' · по каждому сотруднику' : ''}
                  </p>
                  <p className="spec-v04-muted">{source.registry.description}</p>
                  <pre className="kpi-code-params">{formatParams(source.params)}</pre>
                </>
              ) : Object.keys(source?.legacy || {}).length ? (
                <pre className="kpi-code-params">{formatParams(source?.legacy || {})}</pre>
              ) : (
                <p className="spec-v04-muted">Источник не указан.</p>
              )}
              {source?.errors.map((item) => (
                <p key={item} className="kpi-code-error">
                  {item}
                </p>
              ))}
              {source?.warnings.map((item) => (
                <p key={item} className="kpi-code-warn">
                  {item}
                </p>
              ))}
            </section>

            <section className="kpi-code-source">
              <h4>
                Код расчёта
                {detail.module ? (
                  <span>
                    {detail.module.name}
                    {detail.module.origin === 'builtin' ? ' · встроенный' : ' · сгенерирован по методике'}
                  </span>
                ) : null}
              </h4>
              {detail.module?.code ? (
                <pre className="kpi-code-pre">{detail.module.code}</pre>
              ) : (
                <p className="spec-v04-muted">Для этого показателя модуль расчёта ещё не подключён.</p>
              )}
              {detail.module?.tests ? (
                <>
                  <button type="button" className="kpi-code-toggle" onClick={() => setShowTests((value) => !value)}>
                    {showTests ? 'Скрыть тесты' : 'Показать тесты'}
                  </button>
                  {showTests ? <pre className="kpi-code-pre">{detail.module.tests}</pre> : null}
                </>
              ) : null}
            </section>
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  )
}
