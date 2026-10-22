import { useCallback, useEffect, useMemo, useState } from 'react'
import { Inbox, MailOpen, Plus, Send, type LucideIcon } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { DOCFLOW_REFRESH_EVENT, publishDocflowBusy } from '../../layout/DocflowRefreshButton'
import { OrchSlotMain } from '../../layout/GridSlots'
import { KpiRangePicker, type KpiRangeShortcut } from '../../pages/KpiRangePicker'
import { rollingKpiRange } from '../../workplace/kpiPeriod'
import { peekProtocolFocus } from '../../workplace/protocolFocus'
import {
  correspondenceInPeriod,
  forgetDocflowCorrespondenceSession,
  forgetDocflowOrdersSession,
  formatCorrespondenceDate,
  loadDocflowCorrespondenceSession,
  openIncomingLetter,
  type CorrespondenceKind,
  type CorrespondenceRow
} from '../../workplace/fetchDocflowCorrespondence'
import { clearDocflowPages } from '../../workplace/docflowPageCache'
import { ATTACHED_FILES } from '../../workplace/docflowAttachments'
import { forgetDocflowMemos } from '../../workplace/fetchDocflowMemos'
import { DocflowAttachments } from './DocflowAttachments'
import { DocflowAssignmentsPanel } from './DocflowAssignmentsPanel'
import { DocflowIncentiveOrdersPanel } from './DocflowIncentiveOrdersPanel'
import { DocflowForwardingPanel } from './DocflowForwardingPanel'
import { DocflowMemosPanel } from './DocflowMemosPanel'
import { DocflowOrdersPanel } from './DocflowOrdersPanel'
import { DocflowPaymentRequestsPanel } from './DocflowPaymentRequestsPanel'
import { DocflowProtocolsPanel } from './DocflowProtocolsPanel'
import { DocflowServiceRequestsPanel } from './DocflowServiceRequestsPanel'
import { DocflowSearch, SortTh, useDocflowTable } from './docflowTableTools'
import './docflowGrid.css'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'
import {
  loadDocflowCreateSchema,
  type DocflowFormRequest,
  type DocflowKindId,
  type DocflowKindSchema
} from '../../workplace/docflowDocumentCreate'
import { erpActorFio } from '../../workplace/userContext'
import type { MeetingEvent } from '../../utils/outlookMeetings'
import { DocflowCreateDialog } from './DocflowCreateDialog'
import { DocflowOpenFormBar } from './DocflowOpenFormBar'
import { MeetingProtocolForm } from './MeetingProtocolForm'
import { useDocflowDock } from './DocflowDock'
import { DOCFLOW_JOURNALS, type JournalId } from './docflowJournals'

type CreateTarget = DocflowKindId | 'protocol'

const CREATE_BUTTONS: Record<JournalId, { target: CreateTarget; label: string }[]> = {
  correspondence: [],
  memos: [{ target: 'memo', label: 'Создать записку' }],
  orders: [
    { target: 'order', label: 'Приказ' },
    { target: 'directive', label: 'Распоряжение' }
  ],
  incentives: [{ target: 'incentive', label: 'Создать приказ' }],
  assignments: [{ target: 'assignment', label: 'Создать поручение' }],
  protocols: [{ target: 'protocol', label: 'Создать протокол' }],
  payments: [{ target: 'payment', label: 'Создать заявку' }],
  forwarding: [{ target: 'forwarding', label: 'Создать поручение' }],
  requests: []
}

function blankMeeting(): MeetingEvent {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  const start = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:00`
  return { id: `manual-${now.getTime()}`, subject: '', start, end: '', location: '', organizer: '', attendees: '', owner: '' }
}

const PERIOD_JOURNALS = new Set<JournalId>([
  'correspondence',
  'memos',
  'incentives',
  'assignments',
  'protocols',
  'payments',
  'forwarding',
  'requests'
])

const MAIL_VIEWS: { id: CorrespondenceKind; title: string; hint: string; icon: LucideIcon }[] = [
  { id: 'incoming', title: 'Входящая', hint: 'письма, поступившие в компанию', icon: Inbox },
  { id: 'outgoing', title: 'Исходящая', hint: 'письма, отправленные из компании', icon: Send }
]

const SUBTITLES: Record<JournalId, string> = {
  correspondence: '',
  memos: 'Журнал 1С без конфиденциальных записок. Прокрутите вниз — подгрузятся следующие.',
  orders: 'Документы «Приказ» и «Распоряжение» из 1С: период, статус, гриф, ответственный и лист согласования',
  incentives:
    'Внутренние документы Документооборота вида «Приказ о мерах материального стимулирования»: сотрудник, процент депремирования, утверждающий и невыполненная задача.',
  assignments: 'Поручения (ТД) из 1С: мероприятия, исполнители, сроки и отчёты. Прокрутите вниз — подгрузятся следующие.',
  protocols:
    'Протоколы совещаний 1С без конфиденциальных: повестка, решения, задачи и участники. Прокрутите вниз — подгрузятся следующие.',
  payments:
    'Заявки на расходование ДС из 1С: статус, хозяйственная операция, сумма, получатель и расшифровка платежа. Прокрутите вниз — подгрузятся следующие.',
  forwarding:
    'Поручения экспедитору из 1С: тип заявки, способ доставки, груз, склад и ответственные. Прокрутите вниз — подгрузятся следующие.',
  requests:
    'Списки 1С: сопровождение, IT, эксплуатация, служба развития, создание номенклатуры, потребность рынка и сектор рекламы и PR. Прокрутите таблицу вправо — колонок больше, чем помещается на экран.'
}

function cell(value: string): string {
  return value.trim() || '—'
}

function correspondenceSearchText(row: CorrespondenceRow): string {
  return [
    formatCorrespondenceDate(row.date),
    row.number,
    row.organization,
    row.emailFrom,
    row.emailTo,
    row.partner,
    row.addressee,
    row.department,
    row.incomingNumber,
    row.direction,
    row.comment
  ].join(' ')
}

function correspondenceSortValue(row: CorrespondenceRow, key: string): string {
  const map: Record<string, string> = {
    date: row.date,
    number: row.number,
    organization: row.organization,
    emailFrom: row.emailFrom,
    emailTo: row.emailTo,
    partner: row.partner,
    addressee: row.addressee,
    department: row.department,
    incomingNumber: row.incomingNumber,
    direction: row.direction,
    comment: row.comment
  }
  return map[key] ?? ''
}

function CorrespondenceCard({
  row,
  user,
  kind,
  onOpenDocument
}: {
  row: CorrespondenceRow
  user: UserProfile
  kind: CorrespondenceKind
  onOpenDocument: (kind: DocflowKindId, refKey: string) => void
}): React.JSX.Element {
  const [opening, setOpening] = useState(false)
  const [letterError, setLetterError] = useState('')

  useEffect(() => setLetterError(''), [row.id])

  const openLetter = async (): Promise<void> => {
    if (opening) return
    setOpening(true)
    setLetterError('')
    try {
      await openIncomingLetter(user, row)
    } catch (err) {
      setLetterError(err instanceof Error ? err.message : 'Не удалось открыть письмо')
    } finally {
      setOpening(false)
    }
  }

  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>{formatCorrespondenceDate(row.date)}</p>
        </div>
        {kind === 'incoming' ? (
          <div className="docflow-detail-actions">
            <button
              type="button"
              className="docflow-edit-btn"
              disabled={opening}
              title="Открыть письмо, из которого зарегистрирован документ"
              onClick={() => void openLetter()}
            >
              <MailOpen size={14} aria-hidden /> {opening ? 'Открываем…' : 'Открыть письмо'}
            </button>
          </div>
        ) : null}
      </header>
      <DocflowOpenFormBar refKey={row.id} onOpen={() => onOpenDocument(kind, row.id)} />
      {letterError ? <p className="docflow-edit-notice is-error">{letterError}</p> : null}
      {row.comment ? <p className="docflow-side-subject">{row.comment}</p> : null}
      <div className="docflow-side-scroll">
        <DocflowAttachments
          user={user}
          entity={kind === 'incoming' ? ATTACHED_FILES.incoming : ATTACHED_FILES.outgoing}
          ownerId={row.id}
        />
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
  const openedProtocol = peekProtocolFocus()
  const protocolDay = (openedProtocol?.date || '').slice(0, 10)
  const periodFrom = protocolDay && protocolDay < initial.from ? protocolDay : initial.from
  const periodTo = protocolDay && protocolDay > initial.to ? protocolDay : initial.to
  const { journal, setJournal } = useDocflowDock()
  useEffect(() => {
    if (openedProtocol) setJournal('protocols')
    // Только вход на вкладку: очистка фокуса протокола не должна сбрасывать журнал.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [kind, setKind] = useState<CorrespondenceKind>('incoming')
  const [from, setFrom] = useState(periodFrom)
  const [to, setTo] = useState(periodTo)
  const [shortcut, setShortcut] = useState<KpiRangeShortcut | null>(
    protocolDay && (protocolDay < initial.from || protocolDay > initial.to) ? null : '7'
  )
  const [cachedRows, setCachedRows] = useState<CorrespondenceRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [protocolOpen, setProtocolOpen] = useState(false)
  const [formRequest, setFormRequest] = useState<DocflowFormRequest | null>(null)
  const [createSchemas, setCreateSchemas] = useState<DocflowKindSchema[]>([])
  const [createNotice, setCreateNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [savedWhileOpen, setSavedWhileOpen] = useState(false)
  const [protocolMeeting, setProtocolMeeting] = useState<MeetingEvent>(blankMeeting)

  const createButtons =
    journal === 'correspondence'
      ? [{ target: kind as CreateTarget, label: kind === 'incoming' ? 'Зарегистрировать входящее' : 'Создать исходящее' }]
      : CREATE_BUTTONS[journal]

  const openForm = (next: DocflowFormRequest): void => {
    setCreateNotice(null)
    if (createSchemas.some((item) => item.id === next.kind)) {
      setFormRequest(next)
      return
    }
    void loadDocflowCreateSchema(user)
      .then((schemas) => {
        setCreateSchemas(schemas)
        if (schemas.some((item) => item.id === next.kind)) setFormRequest(next)
        else setCreateNotice({ text: 'Форма этого документа в 1С недоступна', error: true })
      })
      .catch((err: unknown) =>
        setCreateNotice({ text: err instanceof Error ? err.message : 'Не удалось открыть форму', error: true })
      )
  }

  const openCreate = (target: CreateTarget): void => {
    if (target === 'protocol') {
      setCreateNotice(null)
      setProtocolMeeting(blankMeeting())
      setProtocolOpen(true)
      return
    }
    openForm({ mode: 'create', kind: target })
  }

  const openDocument = (docKind: DocflowKindId, refKey: string): void => {
    if (refKey) openForm({ mode: 'edit', kind: docKind, refKey })
  }

  const refreshJournal = useCallback((): void => {
    forgetDocflowCorrespondenceSession(user, 'incoming')
    forgetDocflowCorrespondenceSession(user, 'outgoing')
    forgetDocflowOrdersSession(user)
    forgetDocflowMemos()
    clearDocflowPages()
    setRefreshing(true)
    setReloadKey((value) => value + 1)
  }, [user])

  const onCreated = (text: string): void => {
    setCreateNotice({ text, error: false })
    refreshJournal()
  }

  const onFormSaved = (text: string): void => {
    setCreateNotice({ text, error: false })
    setSavedWhileOpen(true)
  }

  const closeForm = (): void => {
    setFormRequest(null)
    if (savedWhileOpen) refreshJournal()
    setSavedWhileOpen(false)
  }

  const activeJournal = DOCFLOW_JOURNALS.find((item) => item.id === journal) || DOCFLOW_JOURNALS[0]
  const activeMail = MAIL_VIEWS.find((item) => item.id === kind) || MAIL_VIEWS[0]
  const ActiveIcon = activeJournal.icon

  useEffect(() => {
    setSelectedId('')
    if (journal !== 'correspondence') {
      setLoading(false)
      return
    }
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
        if (!alive) return
        setLoading(false)
        setRefreshing(false)
      })
    return () => {
      alive = false
    }
  }, [user, journal, kind, reloadKey])

  useEffect(() => {
    if (journal !== 'correspondence') setRefreshing(false)
  }, [journal, reloadKey])

  useEffect(() => {
    publishDocflowBusy(loading || refreshing)
  }, [loading, refreshing])

  useEffect(() => {
    const onRefresh = (): void => refreshJournal()
    window.addEventListener(DOCFLOW_REFRESH_EVENT, onRefresh)
    return () => window.removeEventListener(DOCFLOW_REFRESH_EVENT, onRefresh)
  }, [refreshJournal])

  useEffect(() => setCreateNotice(null), [journal])

  const periodRows = useMemo(() => correspondenceInPeriod(cachedRows, from, to), [cachedRows, from, to])
  const table = useDocflowTable(periodRows, {
    text: correspondenceSearchText,
    value: correspondenceSortValue,
    initialSort: { key: 'date', dir: 'desc' }
  })
  const rows = table.rows
  const globalSearchEntries = useMemo<GlobalSearchEntry[]>(
    () =>
      journal === 'correspondence'
        ? rows.map((row) => {
            const stableId = row.id || `${row.number}-${row.date}`
            const targetId = `correspondence:${stableId}`
            return {
              id: `docflow:${targetId}`,
              source: 'grid:docflow:correspondence',
              pageKey: 'docflow',
              kind: 'entity',
              targetId,
              sectionId: 'correspondence',
              title: row.comment || `Корреспонденция № ${cell(row.number)}`,
              subtitle: [formatCorrespondenceDate(row.date), row.organization, row.direction]
                .filter(Boolean)
                .join(' · '),
              keywords: [
                row.number,
                row.emailFrom,
                row.emailTo,
                row.partner,
                row.addressee,
                row.department,
                row.incomingNumber,
                kind
              ]
            }
          })
        : [],
    [journal, rows, kind]
  )
  useRegisterGlobalSearch('grid:docflow:correspondence', globalSearchEntries)
  const selected = rows.find((row) => (row.id || `${row.number}-${row.date}`) === selectedId) || null

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="docflow-page">
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
            <div className="docflow-head-tools">
              {createButtons.map((button) => (
                <button
                  key={button.target}
                  type="button"
                  className="docflow-edit-btn is-primary docflow-create-btn"
                  onClick={() => openCreate(button.target)}
                >
                  <Plus size={14} aria-hidden /> {button.label}
                </button>
              ))}
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
            </div>
          </header>
          {createNotice ? (
            <p className={`docflow-edit-notice${createNotice.error ? ' is-error' : ''}`}>{createNotice.text}</p>
          ) : null}

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
                  <div className="docflow-order-filters">
                    <DocflowSearch
                      value={table.query}
                      onChange={table.setQuery}
                      placeholder="Номер, организация, тема, email…"
                      found={rows.length}
                      total={periodRows.length}
                    />
                    <span>{`${rows.length} из ${periodRows.length}`}</span>
                  </div>
                  {loading ? <p className="docflow-status">Загружаем из 1С…</p> : null}
                  {error && !loading ? <p className="docflow-status docflow-status-error">{error}</p> : null}
                  {!loading && !error && !rows.length ? (
                    <p className="docflow-status">
                      {table.query.trim()
                        ? 'Ничего не найдено по этим словам'
                        : `Нет ${kind === 'incoming' ? 'входящей' : 'исходящей'} корреспонденции за выбранный период`}
                    </p>
                  ) : null}
                  {rows.length ? (
                    <div className="docflow-table-scroll">
                      <table className="spec-v04-table docflow-table">
                        <thead>
                          <tr>
                            <SortTh label="Дата" sortKey="date" sort={table.sort} onSort={table.toggleSort} />
                            <SortTh label="Номер" sortKey="number" sort={table.sort} onSort={table.toggleSort} />
                            <SortTh
                              label="Организация"
                              sortKey="organization"
                              sort={table.sort}
                              onSort={table.toggleSort}
                            />
                            <SortTh
                              label="Email отправителя"
                              sortKey="emailFrom"
                              sort={table.sort}
                              onSort={table.toggleSort}
                            />
                            {kind === 'incoming' ? (
                              <>
                                <SortTh label="Партнёр" sortKey="partner" sort={table.sort} onSort={table.toggleSort} />
                                <SortTh label="Кому" sortKey="addressee" sort={table.sort} onSort={table.toggleSort} />
                                <SortTh
                                  label="Подразделение"
                                  sortKey="department"
                                  sort={table.sort}
                                  onSort={table.toggleSort}
                                />
                              </>
                            ) : (
                              <>
                                <SortTh
                                  label="Email получателя"
                                  sortKey="emailTo"
                                  sort={table.sort}
                                  onSort={table.toggleSort}
                                />
                                <SortTh label="Партнёр" sortKey="partner" sort={table.sort} onSort={table.toggleSort} />
                                <SortTh
                                  label="Номер входящий"
                                  sortKey="incomingNumber"
                                  sort={table.sort}
                                  onSort={table.toggleSort}
                                />
                              </>
                            )}
                            <SortTh label="Направление" sortKey="direction" sort={table.sort} onSort={table.toggleSort} />
                            <SortTh label="Комментарий" sortKey="comment" sort={table.sort} onSort={table.toggleSort} />
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row) => {
                            const key = row.id || `${row.number}-${row.date}`
                            return (
                              <tr
                                key={key}
                                data-search-id={`correspondence:${key}`}
                                className={`docflow-row${selectedId === key ? ' is-selected' : ''}`}
                                tabIndex={0}
                                onClick={() => setSelectedId(key)}
                                onDoubleClick={() => openDocument(kind, row.id)}
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
                    <CorrespondenceCard row={selected} user={user} kind={kind} onOpenDocument={openDocument} />
                  ) : (
                    <p className="docflow-status">Выберите письмо, чтобы увидеть карточку</p>
                  )}
                </aside>
              </div>
            </>
          ) : journal === 'memos' ? (
            <DocflowMemosPanel key={reloadKey} user={user} from={from} to={to} onOpenDocument={openDocument} />
          ) : journal === 'orders' ? (
            <DocflowOrdersPanel key={reloadKey} user={user} onOpenDocument={openDocument} />
          ) : journal === 'incentives' ? (
            <DocflowIncentiveOrdersPanel key={reloadKey} user={user} from={from} to={to} onOpenDocument={openDocument} />
          ) : journal === 'assignments' ? (
            <DocflowAssignmentsPanel key={reloadKey} user={user} from={from} to={to} onOpenDocument={openDocument} />
          ) : journal === 'protocols' ? (
            <DocflowProtocolsPanel key={reloadKey} user={user} from={from} to={to} />
          ) : journal === 'payments' ? (
            <DocflowPaymentRequestsPanel key={reloadKey} user={user} from={from} to={to} onOpenDocument={openDocument} />
          ) : journal === 'forwarding' ? (
            <DocflowForwardingPanel key={reloadKey} user={user} from={from} to={to} onOpenDocument={openDocument} />
          ) : journal === 'requests' ? (
            <DocflowServiceRequestsPanel
              key={reloadKey}
              user={user}
              from={from}
              to={to}
              reload={reloadKey}
              onOpenDocument={openDocument}
              onCreate={openCreate}
            />
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
      <DocflowCreateDialog
        user={user}
        request={formRequest}
        schemas={createSchemas}
        onClose={closeForm}
        onRequest={openForm}
        onSaved={onFormSaved}
      />
      {protocolOpen ? (
        <MeetingProtocolForm
          open
          meeting={protocolMeeting}
          actorFio={erpActorFio(user)}
          onClose={() => setProtocolOpen(false)}
          onCreated={(result) =>
            onCreated(result.number ? `Создан протокол ${result.number}` : result.summary || 'Протокол создан в 1С')
          }
        />
      ) : null}
    </OrchSlotMain>
  )
}
