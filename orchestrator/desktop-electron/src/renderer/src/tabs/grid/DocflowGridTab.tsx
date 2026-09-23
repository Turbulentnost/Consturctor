import { useEffect, useMemo, useState } from 'react'
import {
  ClipboardList,
  FileText,
  Inbox,
  Mail,
  NotebookPen,
  ScrollText,
  Send,
  type LucideIcon
} from 'lucide-react'
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
import { DocflowAssignmentsPanel } from './DocflowAssignmentsPanel'
import { DocflowMemosPanel } from './DocflowMemosPanel'
import { DocflowOrdersPanel } from './DocflowOrdersPanel'
import { DocflowProtocolsPanel } from './DocflowProtocolsPanel'
import './docflowGrid.css'

const JOURNALS: { id: string; title: string; hint: string; icon: LucideIcon; tone: string }[] = [
  { id: 'correspondence', title: 'Корреспонденция', hint: 'Входящие и исходящие письма', icon: Mail, tone: 'blue' },
  { id: 'memos', title: 'Служебные записки', hint: 'Кому, от кого, срок и маршрут', icon: FileText, tone: 'green' },
  { id: 'orders', title: 'Приказы и распоряжения', hint: 'Статус, гриф и согласующие', icon: ScrollText, tone: 'purple' },
  { id: 'assignments', title: 'Поручения', hint: 'Мероприятия, исполнители и сроки', icon: ClipboardList, tone: 'orange' },
  { id: 'protocols', title: 'Протоколы', hint: 'Совещания, решения и участники', icon: NotebookPen, tone: 'teal' }
]

type JournalId = 'correspondence' | 'memos' | 'orders' | 'assignments' | 'protocols'

const PERIOD_JOURNALS = new Set<JournalId>(['correspondence', 'memos', 'assignments', 'protocols'])

const MAIL_VIEWS: { id: CorrespondenceKind; title: string; hint: string; icon: LucideIcon }[] = [
  { id: 'incoming', title: 'Входящая', hint: 'письма, поступившие в компанию', icon: Inbox },
  { id: 'outgoing', title: 'Исходящая', hint: 'письма, отправленные из компании', icon: Send }
]

const SUBTITLES: Record<JournalId, string> = {
  correspondence: '',
  memos: 'Журнал 1С без конфиденциальных записок. Прокрутите вниз — подгрузятся следующие.',
  orders: 'Документы «Приказ» и «Распоряжение» из 1С: период, статус, гриф, ответственный и лист согласования',
  assignments: 'Поручения (ТД) из 1С: мероприятия, исполнители, сроки и отчёты. Прокрутите вниз — подгрузятся следующие.',
  protocols:
    'Протоколы совещаний 1С без конфиденциальных: повестка, решения, задачи и участники. Прокрутите вниз — подгрузятся следующие.'
}

function cell(value: string): string {
  return value.trim() || '—'
}

function CorrespondenceCard({ row }: { row: CorrespondenceRow }): React.JSX.Element {
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>{formatCorrespondenceDate(row.date)}</p>
        </div>
      </header>
      {row.comment ? <p className="docflow-side-subject">{row.comment}</p> : null}
      <div className="docflow-side-scroll">
        <section className="docflow-card-block">
          <h4>Реквизиты</h4>
          <dl className="docflow-detail-list">
            {row.fields.map((field) => (
              <div key={field.label}>
                <dt>{field.label}</dt>
                <dd>{field.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </>
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
  const [selectedId, setSelectedId] = useState('')

  const activeJournal = JOURNALS.find((item) => item.id === journal) || JOURNALS[0]
  const activeMail = MAIL_VIEWS.find((item) => item.id === kind) || MAIL_VIEWS[0]
  const ActiveIcon = activeJournal.icon

  useEffect(() => {
    setSelectedId('')
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

  const rows = useMemo(() => correspondenceInPeriod(cachedRows, from, to), [cachedRows, from, to])
  const selected = rows.find((row) => (row.id || `${row.number}-${row.date}`) === selectedId) || null

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="docflow-page">
        <aside className="docflow-nav" aria-label="Журналы документооборота 1С">
          <p className="docflow-nav-kicker">Журналы 1С</p>
          {JOURNALS.map((item) => {
            const Icon = item.icon
            return (
              <button
                key={item.id}
                type="button"
                className={`docflow-nav-item${journal === item.id ? ' is-active' : ''}`}
                onClick={() => setJournal(item.id as JournalId)}
              >
                <span className={`docflow-nav-icon tone-${item.tone}`} aria-hidden>
                  <Icon size={18} strokeWidth={2} />
                </span>
                <span className="docflow-nav-text">
                  <strong>{item.title}</strong>
                  <span>{item.hint}</span>
                </span>
              </button>
            )
          })}
        </aside>

        <div className="docflow-main">
          <header className="docflow-head">
            <div className="docflow-head-title">
              <span className={`docflow-nav-icon tone-${activeJournal.tone}`} aria-hidden>
                <ActiveIcon size={20} strokeWidth={2} />
              </span>
              <div>
                <h2>{activeJournal.title}</h2>
                <p>
                  {journal === 'correspondence'
                    ? `${activeMail.title} корреспонденция — ${activeMail.hint}`
                    : SUBTITLES[journal]}
                </p>
              </div>
            </div>
            {PERIOD_JOURNALS.has(journal) ? (
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
                {MAIL_VIEWS.map((item) => {
                  const Icon = item.icon
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="tab"
                      aria-selected={kind === item.id}
                      className={`docflow-kind-btn${kind === item.id ? ' is-active' : ''}`}
                      onClick={() => setKind(item.id)}
                    >
                      <Icon size={18} aria-hidden />
                      <span>
                        <strong>{item.title}</strong>
                        <span>{item.hint}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
              <div className="docflow-split">
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
                          {rows.map((row) => {
                            const key = row.id || `${row.number}-${row.date}`
                            return (
                              <tr
                                key={key}
                                className={`docflow-row${selectedId === key ? ' is-selected' : ''}`}
                                tabIndex={0}
                                onClick={() => setSelectedId(key)}
                                onKeyDown={(event) => {
                                  if (event.key === 'Enter' || event.key === ' ') {
                                    event.preventDefault()
                                    setSelectedId(key)
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
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </div>
                <aside className="docflow-side wp-card" aria-label="Карточка письма">
                  {selected ? (
                    <CorrespondenceCard row={selected} />
                  ) : (
                    <p className="docflow-status">Выберите письмо, чтобы увидеть карточку</p>
                  )}
                </aside>
              </div>
            </>
          ) : journal === 'memos' ? (
            <DocflowMemosPanel user={user} from={from} to={to} />
          ) : journal === 'orders' ? (
            <DocflowOrdersPanel user={user} />
          ) : journal === 'assignments' ? (
            <DocflowAssignmentsPanel user={user} from={from} to={to} />
          ) : journal === 'protocols' ? (
            <DocflowProtocolsPanel user={user} from={from} to={to} />
          ) : (
            <div className="docflow-table-card wp-card docflow-placeholder">
              <span className={`docflow-nav-icon docflow-placeholder-icon tone-${activeJournal.tone}`} aria-hidden>
                <ActiveIcon size={26} strokeWidth={1.8} />
              </span>
              <p>Журнал «{activeJournal.title}» ещё не подключён.</p>
              <p className="spec-v04-muted">Этот журнал ещё не читает документы из 1С.</p>
            </div>
          )}
        </div>
      </section>
    </OrchSlotMain>
  )
}
