import { useEffect, useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import type { UserProfile } from '../../api/types'
import { OrchSlotMain } from '../../layout/GridSlots'
import { KpiRangePicker, type KpiRangeShortcut } from '../../pages/KpiRangePicker'
import { rollingKpiRange } from '../../workplace/kpiPeriod'
import {
  correspondenceInPeriod,
  formatCorrespondenceDate,
  loadDocflowCorrespondenceSession,
  type CorrespondenceKind,
  type CorrespondenceRow
} from '../../workplace/fetchDocflowCorrespondence'
import './docflowGrid.css'

const JOURNALS = [
  {
    id: 'correspondence',
    title: 'Корреспонденция',
    hint: 'Входящие и исходящие письма из 1С'
  },
  {
    id: 'memos',
    title: 'Служебные записки',
    hint: 'Журнал служебных записок 1С'
  },
  {
    id: 'orders',
    title: 'Приказы и распоряжения',
    hint: 'Приказы, распоряжения и проекты'
  },
  {
    id: 'assignments',
    title: 'Поручения',
    hint: 'Поручения (ТД) из 1С'
  },
  {
    id: 'protocols',
    title: 'Протоколы',
    hint: 'Протоколы совещаний'
  }
] as const

type JournalId = (typeof JOURNALS)[number]['id']

const MAIL_VIEWS: { id: CorrespondenceKind; title: string; hint: string }[] = [
  { id: 'incoming', title: 'Входящая', hint: 'письма, поступившие в компанию' },
  { id: 'outgoing', title: 'Исходящая', hint: 'письма, отправленные из компании' }
]

function cell(value: string): string {
  return value.trim() || '—'
}

function CorrespondenceDetail({
  row,
  onClose
}: {
  row: CorrespondenceRow
  onClose: () => void
}): React.JSX.Element {
  const titleId = useId()
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const title = row.number || 'Документ'
  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card docflow-detail"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="docflow-detail-head">
          <div>
            <h3 id={titleId}>{title}</h3>
            <p>{formatCorrespondenceDate(row.date)}</p>
          </div>
          <button type="button" className="docflow-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <dl className="docflow-detail-list">
          {row.fields.map((field) => (
            <div key={field.label}>
              <dt>{field.label}</dt>
              <dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>,
    document.body
  )
}

export function DocflowGridTab({ user }: { user: UserProfile }): React.JSX.Element {
  const initial = rollingKpiRange('7')
  const [journal, setJournal] = useState<JournalId>('correspondence')
  const [kind, setKind] = useState<CorrespondenceKind>('incoming')
  const [from, setFrom] = useState(initial.from)
  const [to, setTo] = useState(initial.to)
  const [shortcut, setShortcut] = useState<KpiRangeShortcut | null>('7')
  const [cachedRows, setCachedRows] = useState<CorrespondenceRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<CorrespondenceRow | null>(null)

  const activeJournal = JOURNALS.find((item) => item.id === journal) || JOURNALS[0]
  const activeMail = MAIL_VIEWS.find((item) => item.id === kind) || MAIL_VIEWS[0]

  useEffect(() => {
    setSelected(null)
    if (journal !== 'correspondence') return
    let alive = true
    setLoading(true)
    setError('')
    setCachedRows([])
    void loadDocflowCorrespondenceSession(user, kind)
      .then((result) => {
        if (!alive) return
        setCachedRows(result.rows)
        setError(result.error)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setCachedRows([])
        setError(err instanceof Error ? err.message : 'Не удалось загрузить корреспонденцию')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [user, journal, kind])

  const rows = useMemo(
    () => correspondenceInPeriod(cachedRows, from, to),
    [cachedRows, from, to]
  )

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="docflow-page">
        <aside className="docflow-nav" aria-label="Журналы документооборота 1С">
          <p className="docflow-nav-kicker">Журналы 1С</p>
          {JOURNALS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`docflow-nav-item${journal === item.id ? ' is-active' : ''}`}
              onClick={() => setJournal(item.id)}
            >
              <strong>{item.title}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </aside>

        <div className="docflow-main">
          <header className="docflow-head">
            <div>
              <h2>{activeJournal.title}</h2>
              <p>
                {journal === 'correspondence'
                  ? `${activeMail.title} корреспонденция — ${activeMail.hint}`
                  : activeJournal.hint}
              </p>
            </div>
            {journal === 'correspondence' ? (
              <KpiRangePicker
                from={from}
                to={to}
                shortcut={shortcut}
                onApply={(next) => {
                  setFrom(next.from)
                  setTo(next.to)
                  setShortcut(null)
                }}
                onShortcut={(days) => {
                  const next = rollingKpiRange(days)
                  setFrom(next.from)
                  setTo(next.to)
                  setShortcut(days)
                }}
              />
            ) : null}
          </header>

          {journal === 'correspondence' ? (
            <>
              <div className="docflow-kind" role="tablist" aria-label="Вид корреспонденции">
                {MAIL_VIEWS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    aria-selected={kind === item.id}
                    className={`docflow-kind-btn${kind === item.id ? ' is-active' : ''}`}
                    onClick={() => setKind(item.id)}
                  >
                    <strong>{item.title}</strong>
                    <span>{item.hint}</span>
                  </button>
                ))}
              </div>
              <div className="docflow-table-card wp-card">
                {loading ? <p className="docflow-status">Загружаем из 1С…</p> : null}
                {error && !loading ? <p className="docflow-status docflow-status-error">{error}</p> : null}
                {!loading && !error && !rows.length ? (
                  <p className="docflow-status">
                    Нет {kind === 'incoming' ? 'входящей' : 'исходящей'} корреспонденции за выбранный период
                  </p>
                ) : null}
                {rows.length ? (
                  <div className="docflow-table-scroll">
                    <table className="spec-v04-table docflow-table">
                      <thead>
                        <tr>
                          <th>Дата</th>
                          <th>Номер</th>
                          <th>Организация</th>
                          <th>Email отправителя</th>
                          {kind === 'incoming' ? (
                            <>
                              <th>Партнёр</th>
                              <th>Кому</th>
                              <th>Подразделение</th>
                            </>
                          ) : (
                            <>
                              <th>Email получателя</th>
                              <th>Партнёр</th>
                              <th>Номер входящий</th>
                            </>
                          )}
                          <th>Направление</th>
                          <th>Комментарий</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => (
                          <tr
                            key={row.id || `${row.number}-${row.date}`}
                            className="docflow-row"
                            tabIndex={0}
                            onClick={() => setSelected(row)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                setSelected(row)
                              }
                            }}
                          >
                            <td>{formatCorrespondenceDate(row.date)}</td>
                            <td>{cell(row.number)}</td>
                            <td>{cell(row.organization)}</td>
                            <td>{cell(row.emailFrom)}</td>
                            {kind === 'incoming' ? (
                              <>
                                <td>{cell(row.partner)}</td>
                                <td>{cell(row.addressee)}</td>
                                <td>{cell(row.department)}</td>
                              </>
                            ) : (
                              <>
                                <td>{cell(row.emailTo)}</td>
                                <td>{cell(row.partner)}</td>
                                <td>{cell(row.incomingNumber)}</td>
                              </>
                            )}
                            <td>{cell(row.direction)}</td>
                            <td title={row.comment}>{cell(row.comment)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <div className="docflow-table-card wp-card docflow-placeholder">
              <p>Журнал «{activeJournal.title}» ещё не подключён.</p>
              <p className="spec-v04-muted">Сейчас из 1С загружается только корреспонденция.</p>
            </div>
          )}
        </div>
      </section>
      {selected ? <CorrespondenceDetail row={selected} onClose={() => setSelected(null)} /> : null}
    </OrchSlotMain>
  )
}
