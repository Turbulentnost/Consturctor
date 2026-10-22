import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import type { PositionKpiFactBreakdown } from '../../api/types'

function columnWeight(name: string): number {
  const text = name.trim().toLowerCase()
  if (/совещ|тема|содержан|назван/.test(text)) return 5
  if (text.includes('статус')) return 2.4
  if (text === 'протокол' || text === 'номер') return 2.6
  if (/дата|план|^срок$|закрыт/.test(text)) return 2.1
  if (text === 'орган' || text === 'серия' || text === 'тип') return 1.3
  return 1.8
}

function isWideColumn(name: string): boolean {
  return /совещ|тема|содержан|назван|статус/.test(name.trim().toLowerCase())
}

function cellTone(value: string): string {
  const text = value.trim().toLowerCase()
  if (text === 'да') return 'is-yes'
  if (text === 'нет') return 'is-no'
  return ''
}

function yes(row: string[], columns: string[], name: string): boolean {
  const index = columns.indexOf(name)
  return index >= 0 && (row[index] || '').trim().toLowerCase() === 'да'
}

/** Строка не красная: она в факте, либо срок ещё не наступил. */
export function rowIncluded(columns: string[], rows: string[][], row: string[]): boolean {
  if (columns.includes('Возврат') && !columns.includes('Вовремя')) {
    return !yes(row, columns, 'Возврат')
  }
  if (['В периоде', 'Вовремя', 'Активное', 'Контроль'].every((name) => columns.includes(name))) {
    let period = 0
    let onTime = 0
    let active = 0
    let control = 0
    for (const item of rows) {
      if (yes(item, columns, 'В периоде')) {
        period += 1
        if (yes(item, columns, 'Вовремя')) onTime += 1
      }
      if (yes(item, columns, 'Активное')) {
        active += 1
        if (yes(item, columns, 'Контроль')) control += 1
      }
    }
    const kpi31 = period ? onTime / period : 1
    const kpi32 = active ? control / active : 1
    if (kpi32 <= kpi31) return !yes(row, columns, 'Активное') || yes(row, columns, 'Контроль')
    return !yes(row, columns, 'В периоде') || yes(row, columns, 'Вовремя')
  }
  if (columns.includes('Вовремя') && columns.includes('Срок наступил')) {
    return !yes(row, columns, 'Срок наступил') || yes(row, columns, 'Вовремя')
  }
  if (columns.includes('Вовремя')) return yes(row, columns, 'Вовремя')
  return true
}

export function KpiFactModal({
  position,
  code,
  month,
  onClose
}: {
  position: string
  code: string
  month: string
  onClose: () => void
}): React.JSX.Element {
  const titleId = useId()
  const [detail, setDetail] = useState<PositionKpiFactBreakdown | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setDetail(null)
    setError('')
    void api
      .getPositionKpiFact(position, code, month)
      .then((next) => {
        if (alive) setDetail(next)
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось открыть расчёт показателя')
      })
    return () => {
      alive = false
    }
  }, [position, code, month])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card kpi-fact-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="kpi-code-head">
          <div>
            <h3 id={titleId}>{detail?.name || 'Как сформировался факт'}</h3>
            {detail?.period ? <p>{detail.period}</p> : null}
          </div>
          <button type="button" className="kpi-code-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>

        {!detail && !error ? <p className="spec-v04-muted">Открываем лист отчёта…</p> : null}
        {error ? <p className="kpi-code-error">{error}</p> : null}

        {detail ? (
          <div className="kpi-code-body">
            {detail.summary.length ? (
              <dl className="kpi-fact-summary">
                {detail.summary.map((item) => (
                  <div key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}

            <section>
              <h4>Как сформировался факт</h4>
              <p className="kpi-fact-text">{detail.factText || 'В отчёте нет пояснения к факту.'}</p>
            </section>

            <section>
              <h4>
                Строки расчёта
                <span>{detail.rows.length ? `${detail.rows.length}` : 'нет строк'}</span>
              </h4>
              {detail.columns.length && detail.rows.length ? (
                <div className="kpi-fact-table-wrap">
                  <table className="kpi-fact-table">
                    <colgroup>
                      {detail.columns.map((column) => {
                        const total = detail.columns.reduce((sum, name) => sum + columnWeight(name), 0)
                        return <col key={column} style={{ width: `${(columnWeight(column) / total) * 100}%` }} />
                      })}
                    </colgroup>
                    <thead>
                      <tr>
                        {detail.columns.map((column) => (
                          <th key={column} className={isWideColumn(column) ? 'is-wide' : undefined}>
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {detail.rows.map((row, index) => {
                        const included = rowIncluded(detail.columns, detail.rows, row)
                        return (
                          <tr key={`${row[0] || 'row'}-${index}`} className={included ? undefined : 'is-miss'}>
                            {detail.columns.map((column, cell) => {
                              const value = row[cell] ?? ''
                              return (
                                <td key={column} className={[cellTone(value), isWideColumn(column) ? 'is-wide' : ''].filter(Boolean).join(' ')}>
                                  {value}
                                </td>
                              )
                            })}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="spec-v04-muted">В листе отчёта нет построчного расчёта.</p>
              )}
            </section>
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  )
}
