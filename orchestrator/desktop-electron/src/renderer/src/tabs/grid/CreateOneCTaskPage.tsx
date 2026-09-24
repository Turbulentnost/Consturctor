import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  ChartColumn,
  Check,
  CirclePlay,
  ClipboardList,
  Eye,
  FileText,
  Handshake,
  Inbox,
  Info,
  Plus,
  Scale,
  ScrollText,
  Search,
  Send,
  Stamp,
  Trash2,
  UserCheck,
  Users,
  type LucideIcon
} from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import { OrchSlotMain } from '../../layout/GridSlots'
import { useSpecV04Sources } from '../../workplace/useSpecV04Data'
import { openWorkplaceTab } from '../../workplace/workplaceNav'
import {
  DOCFLOW_BASIS_KINDS,
  DOCFLOW_PRIORITY_LABEL,
  DOCFLOW_PROCESSES,
  documentLabel,
  formatRuDate,
  formatRuDateTime,
  isoDay,
  launchDocflowProcess,
  loadDocflowCatalog,
  loadDocflowUsers,
  newTaskRow,
  prepareDocflowProcess,
  searchDocflowDocuments,
  taskTitle,
  type DocflowBasisDocument,
  type DocflowBasisKind,
  type DocflowPriority,
  type DocflowProcessDef,
  type DocflowProcessId,
  type DocflowTaskRowDraft
} from '../../workplace/docflowCreate'
import { FioCombobox } from './FioCombobox'
import './docflowGrid.css'
import './createOneCTask.css'

type Step = 'basis' | 'process' | 'tasks' | 'review' | 'done'
type StepId = Exclude<Step, 'done'>
type RowStatus = { state: 'pending' | 'ok' | 'error'; message: string }

const STEPS: { id: StepId; title: string }[] = [
  { id: 'basis', title: 'Документ' },
  { id: 'process', title: 'Процесс' },
  { id: 'tasks', title: 'Параметры задачи' },
  { id: 'review', title: 'Проверка и запуск' }
]

const KIND_ICONS: Record<string, LucideIcon> = {
  protocol: FileText,
  memo: ClipboardList,
  order: Stamp,
  directive: ScrollText,
  contract: Handshake,
  request: ClipboardList,
  incoming: Inbox,
  outgoing: Send
}

const PROCESS_ICONS: Record<string, LucideIcon> = {
  performance: CirclePlay,
  acquaintance: Eye,
  consideration: Scale
}

/** Есть в макете, в ДО пока не подключены. */
const UPCOMING_PROCESSES = [
  { id: 'approval', label: 'Согласование', hint: 'Последовательное или параллельное согласование документа.', icon: Users },
  { id: 'control', label: 'Контроль', hint: 'Постановка на контроль сроков, качества и рисков исполнения.', icon: ChartColumn }
]

const PROCESS_RECIPIENTS: Record<DocflowProcessId, { who: string; what: string }[]> = {
  performance: [
    { who: 'Исполнители', what: 'задача «Исполнить»' },
    { who: 'Проверяющий', what: 'задача «Проверить исполнение»' }
  ],
  acquaintance: [{ who: 'Участники', what: 'задача «Ознакомиться»' }],
  consideration: [
    { who: 'Рассматривающий', what: 'задача «Рассмотреть»' },
    { who: 'Вы', what: 'задача «Обработать резолюцию»' }
  ]
}

/** Готовые периоды: «последние N» от сегодняшнего дня. «Свой период» — даты из календаря. */
const PERIODS = [
  { id: 'all', label: 'За всё время', days: 0, months: 0 },
  { id: 'week', label: 'За последнюю неделю', days: 7, months: 0 },
  { id: 'month', label: 'За последний месяц', days: 0, months: 1 },
  { id: 'quarter', label: 'За последние 3 месяца', days: 0, months: 3 },
  { id: 'half', label: 'За последние полгода', days: 0, months: 6 },
  { id: 'year', label: 'За последний год', days: 0, months: 12 },
  { id: 'custom', label: 'Свой период', days: 0, months: 0 }
]

function presetRange(periodId: string): { from: string; to: string } {
  const preset = PERIODS.find((item) => item.id === periodId)
  if (!preset || (!preset.days && !preset.months)) return { from: '', to: '' }
  const today = new Date()
  const from = new Date(today)
  if (preset.days) from.setDate(from.getDate() - preset.days)
  if (preset.months) from.setMonth(from.getMonth() - preset.months)
  return { from: isoDay(from), to: isoDay(today) }
}

const PAGE_SIZE = 8

/** Сотрудник, а не служебная учётка: минимум два слова кириллицей. */
function isPersonFio(value: string): boolean {
  return value.trim().split(/\s+/).filter((part) => /^[А-ЯЁ][а-яё-]+$/.test(part)).length >= 2
}

const ALL_EMPLOYEES_LIMIT = 20000
let employeesSession: Promise<string[]> | null = null

/**
 * Все пользователи ДО одним запросом за сеанс; фильтр по вводу — локально.
 * Если ДО не ответил, берём справочник ERP (через шлюз он бывает урезан).
 */
function loadAllEmployees(user: UserProfile): Promise<string[]> {
  if (!employeesSession) {
    employeesSession = loadDocflowUsers(user)
      .then(async (res) => (res.ok && res.value.users?.length ? res.value.users : api.searchUsers('', ALL_EMPLOYEES_LIMIT)))
      .then((items) => {
        const people = items.filter(isPersonFio)
        if (!people.length) employeesSession = null
        return people
      })
  }
  return employeesSession
}

function DocumentCard({ doc, kindLabel }: { doc: DocflowBasisDocument; kindLabel: string }): React.JSX.Element {
  return (
    <div className="tcx-doc-card">
      <div className="tcx-doc-card-head">
        <span className="tcx-doc-icon" aria-hidden>
          <FileText size={18} />
        </span>
        <div>
          <strong>{documentLabel(doc)}</strong>
          <span>
            {kindLabel}
            {doc.reg_date ? ` · ${formatRuDate(doc.reg_date)}` : ''}
          </span>
        </div>
      </div>
      {doc.title ? (
        <dl>
          <dt>Заголовок</dt>
          <dd>{doc.title}</dd>
        </dl>
      ) : null}
      {doc.author ? (
        <dl>
          <dt>Автор</dt>
          <dd>{doc.author}</dd>
        </dl>
      ) : null}
    </div>
  )
}

export function CreateOneCTaskPage({ user }: { user: UserProfile }): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const me = (user.fio || '').trim()

  const [step, setStep] = useState<Step>('basis')
  const [catalog, setCatalog] = useState<{ kinds: DocflowBasisKind[]; processes: DocflowProcessDef[] }>({
    kinds: DOCFLOW_BASIS_KINDS,
    processes: DOCFLOW_PROCESSES
  })
  const [catalogError, setCatalogError] = useState('')
  const [fioHints, setFioHints] = useState<string[]>([])

  const [kindId, setKindId] = useState('')
  const [typeId, setTypeId] = useState('')
  const [query, setQuery] = useState('')
  const [period, setPeriod] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [onlyMine, setOnlyMine] = useState(true)
  const [documents, setDocuments] = useState<DocflowBasisDocument[]>([])
  const [page, setPage] = useState(0)
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [documentPicked, setDocumentPicked] = useState<DocflowBasisDocument | null>(null)

  const [processId, setProcessId] = useState<DocflowProcessId | ''>('')
  const [preparing, setPreparing] = useState(false)
  const [prepareError, setPrepareError] = useState('')
  const [defaultTitle, setDefaultTitle] = useState('')

  const [rows, setRows] = useState<DocflowTaskRowDraft[]>(() => [newTaskRow()])
  const [verifier, setVerifier] = useState(me)
  const [rowsError, setRowsError] = useState('')

  const [confirmed, setConfirmed] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [statuses, setStatuses] = useState<Record<string, RowStatus>>({})
  const [doneRows, setDoneRows] = useState<{ row: DocflowTaskRowDraft; message: string }[]>([])

  useEffect(() => {
    let alive = true
    void loadDocflowCatalog(user).then((res) => {
      if (!alive) return
      if (!res.ok) {
        setCatalogError(res.error)
        return
      }
      const loaded = res.value.kinds ?? []
      setCatalog((current) => ({
        ...current,
        kinds: current.kinds.map((item) => ({
          ...item,
          types: loaded.find((row) => row.id === item.id)?.types ?? []
        }))
      }))
    })
    void loadAllEmployees(user).then((items) => {
      if (alive) setFioHints(items)
    })
    return () => {
      alive = false
    }
  }, [user])

  const kind = catalog.kinds.find((item) => item.id === kindId) ?? null
  const process = catalog.processes.find((item) => item.id === processId) ?? null
  const sampleTaskIds = useMemo(
    () =>
      data.erpTasks
        .filter((row) => row.sourceKind === 'docflow' && /исполн/i.test(row.step || '') && row.refKey)
        .map((row) => row.refKey as string)
        .slice(0, 6),
    [data.erpTasks]
  )

  // Поиск сразу при выборе вида, автора и уточнённого вида; по тексту — с паузой.
  useEffect(() => {
    if (!kind) return
    let alive = true
    const timer = window.setTimeout(
      () => {
        setSearching(true)
        setSearchError('')
        void searchDocflowDocuments(user, {
          kind: kind.id,
          documentTypeId: typeId,
          query,
          onlyMine,
          dateFrom,
          dateTo
        })
          .then((res) => {
            if (!alive) return
            setSearched(true)
            setPage(0)
            if (res.ok) setDocuments(res.value.documents ?? [])
            else {
              setDocuments([])
              setSearchError(res.error)
            }
          })
          .finally(() => {
            if (alive) setSearching(false)
          })
      },
      query.trim() ? 400 : 0
    )
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [user, kind?.id, typeId, query, onlyMine, dateFrom, dateTo])

  const visibleDocs = documents
  const pickPeriod = (id: string): void => {
    setPeriod(id)
    if (id === 'custom') return
    const range = presetRange(id)
    setDateFrom(range.from)
    setDateTo(range.to)
  }
  const pickDate = (edge: 'from' | 'to', value: string): void => {
    setPeriod('custom')
    if (edge === 'from') setDateFrom(value)
    else setDateTo(value)
  }
  const pageCount = Math.max(1, Math.ceil(visibleDocs.length / PAGE_SIZE))
  const pageDocs = visibleDocs.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)

  const pickKind = (id: string): void => {
    setKindId(id)
    setTypeId('')
    setDocuments([])
    setSearched(false)
    setSearchError('')
    setDocumentPicked(null)
    setProcessId('')
  }

  const goTasks = (): void => {
    if (!kind || !documentPicked || !processId) return
    setPreparing(true)
    setPrepareError('')
    void prepareDocflowProcess(user, { kind: kind.id, process: processId, document: documentPicked })
      .then((res) => {
        if (!res.ok) {
          setPrepareError(res.error)
          return
        }
        setDefaultTitle(res.value.name || documentLabel(documentPicked))
        setStep('tasks')
      })
      .finally(() => setPreparing(false))
  }

  const patchRow = (key: string, patch: Partial<DocflowTaskRowDraft>): void => {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const filledRows = rows.filter((row) => row.fio.trim())

  const validateRows = (): string => {
    if (!filledRows.length) return 'Укажите исполнителя хотя бы в одной строке'
    for (const [index, row] of filledRows.entries()) {
      if (!row.dueDate) return `Строка ${index + 1}: укажите срок исполнения`
      const due = new Date(`${row.dueDate}T${row.dueTime || '23:59'}`)
      if (due.getTime() <= row.postedAt.getTime()) return `Строка ${index + 1}: срок раньше даты постановки`
    }
    if (process?.verifier && !verifier.trim()) return 'Укажите проверяющего'
    return ''
  }

  const goReview = (): void => {
    const problem = validateRows()
    setRowsError(problem)
    if (!problem) {
      setConfirmed(false)
      setStatuses({})
      setStep('review')
    }
  }

  const launchAll = async (): Promise<void> => {
    if (!kind || !documentPicked || !processId || !confirmed || launching) return
    setLaunching(true)
    const created: { row: DocflowTaskRowDraft; message: string }[] = []
    for (const row of filledRows) {
      if (statuses[row.key]?.state === 'ok') continue
      setStatuses((current) => ({ ...current, [row.key]: { state: 'pending', message: 'Запускаем…' } }))
      const res = await launchDocflowProcess(user, {
        kind: kind.id,
        process: processId,
        document: documentPicked,
        title: taskTitle(row, defaultTitle),
        row,
        verifier,
        sampleTaskIds
      })
      const status: RowStatus = res.ok
        ? { state: 'ok', message: 'Задача создана в 1С' }
        : { state: 'error', message: res.error }
      setStatuses((current) => ({ ...current, [row.key]: status }))
      if (res.ok) created.push({ row, message: res.value.summary })
    }
    setLaunching(false)
    if (created.length) setDoneRows((current) => [...current, ...created])
    const failed = filledRows.filter((row) => !created.some((item) => item.row.key === row.key))
    if (!failed.length) setStep('done')
    else setRows(failed)
  }

  const resetAll = (): void => {
    setStep('basis')
    pickKind('')
    setQuery('')
    setRows([newTaskRow()])
    setVerifier(me)
    setStatuses({})
    setDoneRows([])
  }

  const stepIndex = step === 'done' ? STEPS.length : STEPS.findIndex((item) => item.id === step)
  const canOpen = (index: number): boolean =>
    step !== 'done' && !launching && index < stepIndex

  const recipients = processId ? PROCESS_RECIPIENTS[processId] : []

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="tcx-page">
        <nav className="tcx-roadmap" aria-label="Шаги создания задачи">
          {STEPS.map((item, index) => {
            const state = index < stepIndex ? 'done' : index === stepIndex ? 'active' : 'todo'
            return (
              <button
                key={item.id}
                type="button"
                className={`tcx-roadmap-step is-${state}`}
                disabled={!canOpen(index)}
                onClick={() => setStep(item.id)}
              >
                <span className="tcx-roadmap-dot">{state === 'done' ? <Check size={14} /> : index + 1}</span>
                <span className="tcx-roadmap-label">
                  {index + 1}. {item.title}
                </span>
              </button>
            )
          })}
        </nav>

        <div className="tcx-body">
          <div className="tcx-main">
            {step === 'basis' ? (
              <>
                <header className="tcx-head">
                  <h2>Шаг 1. Выберите документ-основание</h2>
                  <p>Задача в 1С запускается по документу. Выберите тип документа и найдите нужный.</p>
                </header>
                <div className="tcx-kinds" role="radiogroup" aria-label="Вид документа-основания">
                  {catalog.kinds.map((item) => {
                    const Icon = KIND_ICONS[item.id] ?? FileText
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="radio"
                        aria-checked={kindId === item.id}
                        className={`tcx-card${kindId === item.id ? ' is-active' : ''}`}
                        onClick={() => pickKind(item.id)}
                      >
                        <span className="tcx-card-icon" aria-hidden>
                          <Icon size={18} />
                        </span>
                        <span className="tcx-card-text">
                          <strong>{item.label}</strong>
                          <span>{item.hint}</span>
                        </span>
                      </button>
                    )
                  })}
                </div>

                {kind ? (
                  <div className="tcx-panel tcx-search">
                    <div className="tcx-search-bar">
                      <label className="tcx-search-input">
                        <Search size={16} aria-hidden />
                        <input
                          type="search"
                          value={query}
                          placeholder="Номер или заголовок документа…"
                          onChange={(event) => setQuery(event.target.value)}
                        />
                      </label>
                      {kind.types.length > 1 ? (
                        <select className="wp-select" value={typeId} onChange={(event) => setTypeId(event.target.value)}>
                          <option value="">Все виды</option>
                          {kind.types.map((type) => (
                            <option key={type.id} value={type.id}>
                              {type.name}
                            </option>
                          ))}
                        </select>
                      ) : null}
                      <div className="tcx-period" role="group" aria-label="Период документа">
                        <select className="wp-select" value={period} onChange={(event) => pickPeriod(event.target.value)}>
                          {PERIODS.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label}
                            </option>
                          ))}
                        </select>
                        <label>
                          с
                          <input
                            className="onec-reconnect-input"
                            type="date"
                            value={dateFrom}
                            max={dateTo || undefined}
                            onChange={(event) => pickDate('from', event.target.value)}
                          />
                        </label>
                        <label>
                          по
                          <input
                            className="onec-reconnect-input"
                            type="date"
                            value={dateTo}
                            min={dateFrom || undefined}
                            onChange={(event) => pickDate('to', event.target.value)}
                          />
                        </label>
                      </div>
                      <select
                        className="wp-select"
                        value={onlyMine ? 'mine' : 'all'}
                        onChange={(event) => setOnlyMine(event.target.value === 'mine')}
                      >
                        <option value="mine">Я автор</option>
                        <option value="all">Все авторы</option>
                      </select>
                    </div>
                    {catalogError ? (
                      <p className="tcx-note">Точные виды из 1С не загрузились, поиск идёт по всем видам группы.</p>
                    ) : null}
                    {searchError ? <p className="tcx-status tcx-status-error">{searchError}</p> : null}
                    {searching && !documents.length ? <p className="tcx-status">Ищем документы в 1С…</p> : null}
                    {searched && !searching && !searchError && !visibleDocs.length ? (
                      <p className="tcx-status">Документы не найдены. Уточните запрос, период или выберите «Все авторы».</p>
                    ) : null}
                    {pageDocs.length ? (
                      <>
                        <table className="tcx-table">
                          <thead>
                            <tr>
                              <th aria-label="Выбор" />
                              <th>Документ</th>
                              <th>Заголовок</th>
                              <th>Дата</th>
                              <th>Автор</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pageDocs.map((doc) => {
                              const active = documentPicked?.id === doc.id
                              return (
                                <tr
                                  key={doc.id}
                                  className={active ? 'is-selected' : undefined}
                                  tabIndex={0}
                                  onClick={() => setDocumentPicked(doc)}
                                  onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') setDocumentPicked(doc)
                                  }}
                                >
                                  <td>
                                    <span className={`tcx-radio${active ? ' is-on' : ''}`} aria-hidden />
                                  </td>
                                  <td title={doc.name}>
                                    <strong>{doc.name || doc.reg_number || '—'}</strong>
                                  </td>
                                  <td title={doc.title}>{doc.title || '—'}</td>
                                  <td>{formatRuDate(doc.reg_date)}</td>
                                  <td>{doc.author || '—'}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                        <div className="tcx-pager">
                          <span>
                            Показано {page * PAGE_SIZE + 1}–{Math.min(visibleDocs.length, (page + 1) * PAGE_SIZE)} из{' '}
                            {visibleDocs.length}
                          </span>
                          <div>
                            <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Назад">
                              ‹
                            </button>
                            {Array.from({ length: pageCount }, (_, index) => index)
                              .filter((index) => Math.abs(index - page) <= 2 || index === 0 || index === pageCount - 1)
                              .map((index) => (
                                <button
                                  key={index}
                                  type="button"
                                  className={index === page ? 'is-active' : undefined}
                                  onClick={() => setPage(index)}
                                >
                                  {index + 1}
                                </button>
                              ))}
                            <button
                              type="button"
                              disabled={page >= pageCount - 1}
                              onClick={() => setPage(page + 1)}
                              aria-label="Вперёд"
                            >
                              ›
                            </button>
                          </div>
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : (
                  <p className="tcx-status">Выберите вид документа, чтобы найти основание.</p>
                )}
              </>
            ) : null}

            {step === 'process' && kind && documentPicked ? (
              <>
                <header className="tcx-head">
                  <h2>Шаг 2. Выберите процесс</h2>
                  <p>По документу «{documentLabel(documentPicked)}» доступны следующие процессы.</p>
                </header>
                <div className="tcx-processes" role="radiogroup" aria-label="Процесс">
                  {catalog.processes.map((item) => {
                    const Icon = PROCESS_ICONS[item.id] ?? CirclePlay
                    const allowed = kind.processes.includes(item.id)
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="radio"
                        aria-checked={processId === item.id}
                        disabled={!allowed}
                        title={allowed ? undefined : `Для вида «${kind.label}» не используется`}
                        className={`tcx-card tcx-card--tall${processId === item.id ? ' is-active' : ''}`}
                        onClick={() => setProcessId(item.id)}
                      >
                        <span className="tcx-card-icon" aria-hidden>
                          <Icon size={20} />
                        </span>
                        <strong>{item.label}</strong>
                        <span>{item.hint}</span>
                      </button>
                    )
                  })}
                  {UPCOMING_PROCESSES.map((item) => (
                    <button key={item.id} type="button" disabled className="tcx-card tcx-card--tall">
                      <span className="tcx-card-icon" aria-hidden>
                        <item.icon size={20} />
                      </span>
                      <strong>
                        {item.label} <em className="tcx-soon">скоро</em>
                      </strong>
                      <span>{item.hint}</span>
                    </button>
                  ))}
                </div>
                {process ? (
                  <div className="tcx-panel tcx-about">
                    <div>
                      <h3>
                        <Info size={16} aria-hidden /> О процессе «{process.label}»
                      </h3>
                      <p>{process.hint}</p>
                    </div>
                    <div>
                      <h3>Кто получит задачи?</h3>
                      <ul>
                        {recipients.map((item) => (
                          <li key={item.who}>
                            <UserCheck size={15} aria-hidden /> {item.who} — {item.what}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ) : null}
                {prepareError ? <p className="tcx-status tcx-status-error">{prepareError}</p> : null}
              </>
            ) : null}

            {step === 'tasks' && process && documentPicked ? (
              <>
                <header className="tcx-head">
                  <h2>Шаг 3. Задачи по документу</h2>
                  <p>
                    Каждая строка — отдельная задача в 1С. Дата постановки ставится автоматически, срок по умолчанию —
                    через 2 рабочих дня.
                  </p>
                </header>
                {process.verifier ? (
                  <div className="tcx-panel tcx-verifier">
                    <label>
                      <span>Проверяющий</span>
                      <FioCombobox
                        value={verifier}
                        hints={fioHints}
                        placeholder="Кто проверит исполнение"
                        onChange={setVerifier}
                      />
                    </label>
                  </div>
                ) : null}
                <div className="tcx-panel tcx-rows">
                  <div className="tcx-row tcx-row--head" aria-hidden>
                    <span>№</span>
                    <span>Исполнитель</span>
                    <span>Описание задачи</span>
                    <span>Срок исполнения</span>
                    <span>Приоритет</span>
                    <span>Постановка</span>
                    <span />
                  </div>
                  {rows.map((row, index) => (
                    <div key={row.key} className="tcx-row">
                      <span className="tcx-row-num">{index + 1}</span>
                      <FioCombobox
                        value={row.fio}
                        hints={fioHints}
                        placeholder="Выберите сотрудника"
                        onChange={(fio) => patchRow(row.key, { fio })}
                      />
                      <input
                        className="onec-reconnect-input"
                        value={row.description}
                        placeholder="Что нужно сделать"
                        onChange={(event) => patchRow(row.key, { description: event.target.value })}
                      />
                      <span className="tcx-row-due">
                        <input
                          className="onec-reconnect-input"
                          type="date"
                          value={row.dueDate}
                          onChange={(event) => patchRow(row.key, { dueDate: event.target.value })}
                        />
                        <input
                          className="onec-reconnect-input"
                          type="time"
                          value={row.dueTime}
                          onChange={(event) => patchRow(row.key, { dueTime: event.target.value })}
                        />
                      </span>
                      <select
                        className={`wp-select tcx-priority is-${row.priority}`}
                        value={row.priority}
                        onChange={(event) => patchRow(row.key, { priority: event.target.value as DocflowPriority })}
                      >
                        {(Object.keys(DOCFLOW_PRIORITY_LABEL) as DocflowPriority[]).map((id) => (
                          <option key={id} value={id}>
                            {DOCFLOW_PRIORITY_LABEL[id]}
                          </option>
                        ))}
                      </select>
                      <span className="tcx-row-posted" title="Дата постановки задачи">
                        {formatRuDateTime(row.postedAt)}
                      </span>
                      <button
                        type="button"
                        className="tcx-icon-btn"
                        title="Убрать строку"
                        disabled={rows.length <= 1}
                        onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}
                      >
                        <Trash2 size={15} aria-hidden />
                      </button>
                    </div>
                  ))}
                  <button type="button" className="tcx-add" onClick={() => setRows((current) => [...current, newTaskRow()])}>
                    <Plus size={15} aria-hidden /> Добавить задачу
                  </button>
                </div>
                {rowsError ? <p className="tcx-status tcx-status-error">{rowsError}</p> : null}
              </>
            ) : null}

            {step === 'review' && process && kind && documentPicked ? (
              <>
                <header className="tcx-head">
                  <h2>Шаг 4. Проверка и запуск</h2>
                  <p>После запуска задачи сразу появятся у сотрудников в 1С:Документооборот.</p>
                </header>
                <div className="tcx-panel">
                  <table className="tcx-table tcx-table--review">
                    <thead>
                      <tr>
                        <th>№</th>
                        <th>Исполнитель</th>
                        <th>Задача</th>
                        <th>Срок</th>
                        <th>Приоритет</th>
                        <th>Постановка</th>
                        <th>Статус</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filledRows.map((row, index) => {
                        const status = statuses[row.key]
                        return (
                          <tr key={row.key}>
                            <td>{index + 1}</td>
                            <td>{row.fio}</td>
                            <td title={row.description}>{taskTitle(row, defaultTitle)}</td>
                            <td>
                              {formatRuDate(row.dueDate)} {row.dueTime}
                            </td>
                            <td>{DOCFLOW_PRIORITY_LABEL[row.priority]}</td>
                            <td>{formatRuDateTime(row.postedAt)}</td>
                            <td className={status ? `tcx-state is-${status.state}` : undefined} title={status?.message}>
                              {status ? status.message : 'Готова к запуску'}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                  {process.verifier ? <p className="tcx-note">Проверяющий по всем задачам: {verifier}</p> : null}
                  <label className="tcx-confirm">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      disabled={launching}
                      onChange={(event) => setConfirmed(event.target.checked)}
                    />
                    Понимаю, что задачи сразу уйдут этим сотрудникам в 1С
                  </label>
                </div>
              </>
            ) : null}

            {step === 'done' ? (
              <div className="tcx-panel tcx-done">
                <span className="tcx-done-icon" aria-hidden>
                  <Check size={22} />
                </span>
                <h2>Задачи созданы в 1С:Документооборот</h2>
                <ul>
                  {doneRows.map((item) => (
                    <li key={item.row.key}>
                      {item.row.fio} — {taskTitle(item.row, defaultTitle)}, срок {formatRuDate(item.row.dueDate)}{' '}
                      {item.row.dueTime}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <footer className="tcx-actions">
              {step === 'basis' ? (
                <button type="button" className="spec-btn-outline" onClick={() => openWorkplaceTab('tasks')}>
                  <ArrowLeft size={15} aria-hidden /> К задачам
                </button>
              ) : null}
              {step === 'process' ? (
                <button type="button" className="spec-btn-outline" onClick={() => setStep('basis')}>
                  <ArrowLeft size={15} aria-hidden /> Назад
                </button>
              ) : null}
              {step === 'tasks' ? (
                <button type="button" className="spec-btn-outline" onClick={() => setStep('process')}>
                  <ArrowLeft size={15} aria-hidden /> Назад
                </button>
              ) : null}
              {step === 'review' ? (
                <button type="button" className="spec-btn-outline" disabled={launching} onClick={() => setStep('tasks')}>
                  <ArrowLeft size={15} aria-hidden /> Назад
                </button>
              ) : null}
              <span className="tcx-actions-gap" />
              {step === 'basis' ? (
                <button type="button" className="spec-btn-launch" disabled={!documentPicked} onClick={() => setStep('process')}>
                  Далее: процесс <ArrowRight size={15} aria-hidden />
                </button>
              ) : null}
              {step === 'process' ? (
                <button type="button" className="spec-btn-launch" disabled={!processId || preparing} onClick={goTasks}>
                  {preparing ? 'Готовим процесс в 1С…' : 'Далее: параметры'} <ArrowRight size={15} aria-hidden />
                </button>
              ) : null}
              {step === 'tasks' ? (
                <button type="button" className="spec-btn-launch" onClick={goReview}>
                  Далее: проверка <ArrowRight size={15} aria-hidden />
                </button>
              ) : null}
              {step === 'review' ? (
                <button
                  type="button"
                  className="spec-btn-launch"
                  disabled={!confirmed || launching}
                  onClick={() => void launchAll()}
                >
                  {launching ? 'Запускаем в 1С…' : `Запустить в 1С (${filledRows.length})`}
                </button>
              ) : null}
              {step === 'done' ? (
                <>
                  <button type="button" className="spec-btn-outline" onClick={resetAll}>
                    Создать ещё
                  </button>
                  <button type="button" className="spec-btn-launch" onClick={() => openWorkplaceTab('tasks')}>
                    К задачам
                  </button>
                </>
              ) : null}
            </footer>
          </div>

          <aside className="tcx-side">
            {step === 'basis' ? (
              <div className="tcx-panel">
                <h3 className="tcx-side-title">Выбрано</h3>
                {documentPicked && kind ? (
                  <>
                    <DocumentCard doc={documentPicked} kindLabel={kind.label} />
                    <button type="button" className="spec-btn-outline tcx-side-btn" onClick={() => setDocumentPicked(null)}>
                      Сбросить выбор
                    </button>
                  </>
                ) : (
                  <p className="tcx-note">Документ не выбран</p>
                )}
              </div>
            ) : null}
            {step !== 'basis' && documentPicked && kind ? (
              <div className="tcx-panel">
                <h3 className="tcx-side-title">{step === 'process' ? 'Выбран документ' : 'Краткая информация'}</h3>
                <DocumentCard doc={documentPicked} kindLabel={kind.label} />
                {process && step !== 'process' ? (
                  <dl className="tcx-side-list">
                    <dt>Процесс</dt>
                    <dd>{process.label}</dd>
                    <dt>Задач</dt>
                    <dd>{filledRows.length || '—'}</dd>
                    <dt>Исполнители</dt>
                    <dd>{filledRows.map((row) => row.fio).join(', ') || '—'}</dd>
                    {process.verifier ? (
                      <>
                        <dt>Проверяющий</dt>
                        <dd>{verifier || '—'}</dd>
                      </>
                    ) : null}
                    <dt>Автор</dt>
                    <dd>{me || '—'}</dd>
                  </dl>
                ) : null}
              </div>
            ) : null}
          </aside>
        </div>
      </section>
    </OrchSlotMain>
  )
}
