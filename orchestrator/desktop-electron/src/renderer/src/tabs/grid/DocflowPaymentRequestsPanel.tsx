import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Banknote,
  Building2,
  CheckCircle2,
  Circle,
  Coins,
  CreditCard,
  FileCheck2,
  Layers,
  PenLine,
  Target,
  UserCheck,
  Users,
  Wallet,
  XCircle
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import {
  formatAmount,
  loadPaymentRequestCard,
  loadPaymentRequestPage,
  type PaymentRequestCard,
  type PaymentRequestOption,
  type PaymentRequestRow
} from '../../workplace/fetchDocflowPaymentRequests'
import { DocflowSearch, SortTh, useDocflowTable } from './docflowTableTools'

const FALLBACK_STATUSES: PaymentRequestOption[] = [
  { code: 'НеСогласована', label: 'Не согласована' },
  { code: 'Согласована', label: 'Согласована' },
  { code: 'КОплате', label: 'К оплате' },
  { code: 'Отклонена', label: 'Отклонена' }
]

function cell(value: string): string {
  return value.trim() || '—'
}

function onlyDay(value: string): string {
  return value ? formatCorrespondenceDate(value).slice(0, 10) : '—'
}

function searchText(row: PaymentRequestRow): string {
  return [
    row.date,
    row.number,
    row.status,
    row.operation,
    String(row.amount),
    row.currency,
    row.recipient,
    row.organization,
    row.department,
    row.requestedBy,
    row.author,
    row.cfo,
    row.cashFlowItem,
    row.purpose,
    row.comment
  ].join(' ')
}

function sortValue(row: PaymentRequestRow, key: string): string | number {
  const map: Record<string, string | number> = {
    date: row.date,
    number: row.number,
    operation: row.operation,
    amount: row.amount,
    recipient: row.recipient,
    organization: row.organization,
    department: row.department,
    requestedBy: row.requestedBy,
    paymentDate: row.paymentDate,
    status: row.status
  }
  return map[key] ?? ''
}

function optionsOf(rows: PaymentRequestRow[], pick: (row: PaymentRequestRow) => string): { value: string; label: string }[] {
  const names = new Set(rows.map(pick).map((value) => value.trim()).filter(Boolean))
  return [...names].sort((left, right) => left.localeCompare(right, 'ru')).map((name) => ({ value: name, label: name }))
}

function StatusPill({ row }: { row: Pick<PaymentRequestRow, 'status' | 'statusCode'> }): React.JSX.Element {
  const tone =
    row.statusCode === 'КОплате'
      ? 'is-ok'
      : row.statusCode === 'Отклонена'
        ? 'is-bad'
        : row.statusCode === 'Согласована'
          ? 'is-wait'
          : 'is-muted'
  const Icon = row.statusCode === 'Отклонена' ? XCircle : row.statusCode === 'КОплате' ? CheckCircle2 : Circle
  return (
    <span className={`docflow-pill ${tone}`}>
      <Icon size={12} aria-hidden />
      {row.status || '—'}
    </span>
  )
}

function FilterSelect({
  icon,
  label,
  value,
  options,
  onChange
}: {
  icon: React.ReactNode
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}): React.JSX.Element {
  return (
    <label>
      {icon}
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Все</option>
        {options.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function Fact({ label, value }: { label: string; value: string }): React.JSX.Element | null {
  if (!value.trim()) return null
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

function PaymentRequestCardView({ card }: { card: PaymentRequestCard }): React.JSX.Element {
  const { request: row, breakdown, accounts, documents, employees, stats } = card
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>{onlyDay(row.date)}</p>
        </div>
        <StatusPill row={row} />
      </header>
      <p className="docflow-side-subject">
        {formatAmount(row.amount, row.currency)}
        {row.operation ? ` · ${row.operation}` : ''}
      </p>
      <div className="docflow-side-scroll">
        <section className="docflow-card-block">
          <h4>Основное</h4>
          <dl className="docflow-detail-list">
            <Fact label="Получатель" value={row.recipient} />
            <Fact label="Организация" value={row.organization} />
            <Fact label="Подразделение" value={row.department} />
            <Fact label="ЦФО" value={row.cfo} />
            <Fact label="Статья ДДС" value={row.cashFlowItem} />
            <Fact label="Форма оплаты" value={row.paymentForm} />
            <Fact label="Приоритет" value={row.priority} />
            <Fact label="Заявил" value={row.requestedBy} />
            <Fact label="Решение принял" value={row.decidedBy} />
            <Fact label="Автор" value={row.author} />
            <Fact label="Желательная дата" value={row.wantedDate ? onlyDay(row.wantedDate) : ''} />
            <Fact label="Дата платежа" value={row.paymentDate ? onlyDay(row.paymentDate) : ''} />
            <Fact label="Сверх лимита" value={row.overLimit ? 'Да' : ''} />
            <Fact label="Для производства" value={row.forProduction ? 'Да' : ''} />
            <Fact label="Закрыта" value={row.closed ? 'Да' : ''} />
            <Fact label="Проведена" value={row.posted ? 'Да' : 'Нет'} />
          </dl>
        </section>
        {row.purpose ? (
          <section className="docflow-card-block">
            <h4>Назначение платежа</h4>
            <p>{row.purpose}</p>
          </section>
        ) : null}
        <section className="docflow-card-block">
          <h4>
            <Coins size={14} aria-hidden /> Расшифровка платежа
            <span>
              {stats.breakdown
                ? `${formatAmount(stats.breakdownAmount, row.currency)}${stats.vatAmount ? ` · НДС ${formatAmount(stats.vatAmount)}` : ''}`
                : 'нет'}
            </span>
          </h4>
          {breakdown.length ? (
            <ol className="docflow-lines">
              {breakdown.map((item) => (
                <li key={item.n}>
                  <p>{formatAmount(item.amount, row.currency)}</p>
                  <div>
                    {item.partner || item.counterparty ? <span>{item.partner || item.counterparty}</span> : null}
                    {item.cashFlowItem ? <span>{item.cashFlowItem}</span> : null}
                    {item.expenseItem ? <span>{item.expenseItem}</span> : null}
                    {item.department ? <span>{item.department}</span> : null}
                    {item.vat ? <span>НДС {formatAmount(item.vat)}{item.vatRate ? ` (${item.vatRate})` : ''}</span> : null}
                  </div>
                  {item.comment ? <p className="docflow-muted">{item.comment}</p> : null}
                </li>
              ))}
            </ol>
          ) : (
            <p className="docflow-muted">В заявке нет расшифровки.</p>
          )}
        </section>
        {accounts.length ? (
          <section className="docflow-card-block">
            <h4>
              <Wallet size={14} aria-hidden /> Распределение по счетам
              <span>{accounts.length}</span>
            </h4>
            <ol className="docflow-lines">
              {accounts.map((item) => (
                <li key={item.n}>
                  <p>{formatAmount(item.amount, row.currency)}</p>
                  <div>{item.date ? <span>{onlyDay(item.date)}</span> : null}</div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {documents.length ? (
          <section className="docflow-card-block">
            <h4>
              <FileCheck2 size={14} aria-hidden /> Подтверждающие документы
              <span>{documents.length}</span>
            </h4>
            <ol className="docflow-lines">
              {documents.map((item) => (
                <li key={item.n}>
                  <p>
                    {item.kind || 'Документ'}
                    {item.number ? ` № ${item.number}` : ''}
                  </p>
                  <div>
                    {item.date ? <span>{onlyDay(item.date)}</span> : null}
                    {item.amount ? <span>{formatAmount(item.amount, row.currency)}</span> : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {employees.length ? (
          <section className="docflow-card-block">
            <h4>
              <Users size={14} aria-hidden /> Лицевые счета сотрудников
              <span>{employees.length}</span>
            </h4>
            <ol className="docflow-lines">
              {employees.map((item) => (
                <li key={item.n}>
                  <p>{item.person || '—'}</p>
                  <div>
                    {item.account ? <span>{item.account}</span> : null}
                    <span>{formatAmount(item.amount, row.currency)}</span>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {row.comment ? (
          <section className="docflow-card-block">
            <h4>Комментарий</h4>
            <p>{row.comment}</p>
          </section>
        ) : null}
      </div>
    </>
  )
}

export function DocflowPaymentRequestsPanel({
  user,
  from,
  to
}: {
  user: UserProfile
  from: string
  to: string
}): React.JSX.Element {
  const [rows, setRows] = useState<PaymentRequestRow[]>([])
  const [statuses, setStatuses] = useState<PaymentRequestOption[]>(FALLBACK_STATUSES)
  const [operationList, setOperationList] = useState<PaymentRequestOption[]>([])
  const [formList, setFormList] = useState<PaymentRequestOption[]>([])
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [status, setStatus] = useState('')
  const [operation, setOperation] = useState('')
  const [paymentForm, setPaymentForm] = useState('')
  const [organization, setOrganization] = useState('')
  const [department, setDepartment] = useState('')
  const [recipient, setRecipient] = useState('')
  const [requestedBy, setRequestedBy] = useState('')
  const [author, setAuthor] = useState('')
  const [cfo, setCfo] = useState('')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [card, setCard] = useState<PaymentRequestCard | null>(null)
  const [cardLoading, setCardLoading] = useState(false)
  const [cardError, setCardError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)
  const scopeRef = useRef('')
  const cardForRef = useRef('')

  const fetchPage = useCallback(
    async (skip: number, reset: boolean): Promise<void> => {
      if (loadingRef.current && !reset) return
      loadingRef.current = true
      const scope = `${from}:${to}:${status}:${operation}:${paymentForm}`
      setLoading(true)
      setError('')
      try {
        const page = await loadPaymentRequestPage(user, { from, to, skip, status, operation, paymentForm })
        if (scopeRef.current !== scope) return
        setRows((prev) => {
          const base = reset ? [] : prev
          const seen = new Set(base.map((row) => row.id))
          return [...base, ...page.rows.filter((row) => !seen.has(row.id))]
        })
        if (page.statuses.length) setStatuses(page.statuses)
        if (page.operations.length) setOperationList(page.operations)
        if (page.paymentForms.length) setFormList(page.paymentForms)
        setNextSkip(page.nextSkip)
        setHasMore(page.hasMore)
      } catch (err) {
        if (scopeRef.current === scope) {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить заявки на расходование ДС')
        }
      } finally {
        if (scopeRef.current === scope) {
          loadingRef.current = false
          setLoading(false)
        }
      }
    },
    [user, from, to, status, operation, paymentForm]
  )

  useEffect(() => {
    scopeRef.current = `${from}:${to}:${status}:${operation}:${paymentForm}`
    setRows([])
    setNextSkip(0)
    setHasMore(false)
    setError('')
    setSelectedId('')
    setCard(null)
    void fetchPage(0, true)
  }, [fetchPage, from, to, status, operation, paymentForm, reload])

  const organizations = useMemo(() => optionsOf(rows, (row) => row.organization), [rows])
  const departments = useMemo(() => optionsOf(rows, (row) => row.department), [rows])
  const recipients = useMemo(() => optionsOf(rows, (row) => row.recipient), [rows])
  const requesters = useMemo(() => optionsOf(rows, (row) => row.requestedBy), [rows])
  const authors = useMemo(() => optionsOf(rows, (row) => row.author), [rows])
  const cfos = useMemo(() => optionsOf(rows, (row) => row.cfo), [rows])

  const listed = useMemo(
    () =>
      rows.filter((row) => {
        if (organization && row.organization !== organization) return false
        if (department && row.department !== department) return false
        if (recipient && row.recipient !== recipient) return false
        if (requestedBy && row.requestedBy !== requestedBy) return false
        if (author && row.author !== author) return false
        if (cfo && row.cfo !== cfo) return false
        return true
      }),
    [rows, organization, department, recipient, requestedBy, author, cfo]
  )
  const table = useDocflowTable(listed, {
    text: searchText,
    value: sortValue,
    initialSort: { key: 'date', dir: 'desc' },
    query
  })
  const visible = table.rows
  const visibleAmount = useMemo(() => visible.reduce((sum, row) => sum + row.amount, 0), [visible])

  const filtered = Boolean(
    organization || department || recipient || requestedBy || author || cfo || query.trim()
  )

  const onScroll = (): void => {
    const node = scrollRef.current
    if (!node || !hasMore || loadingRef.current) return
    if (node.scrollTop + node.clientHeight >= node.scrollHeight - 80) void fetchPage(nextSkip, false)
  }

  useEffect(() => {
    // Фильтр оставил мало строк и прокрутки нет — догружаем следующие страницы сами.
    const node = scrollRef.current
    if (!node || !hasMore || loading || error) return
    if (node.scrollHeight <= node.clientHeight + 8) void fetchPage(nextSkip, false)
  }, [visible.length, hasMore, loading, error, nextSkip, fetchPage])

  const openCard = (row: PaymentRequestRow): void => {
    cardForRef.current = row.id
    setSelectedId(row.id)
    setCard(null)
    setCardError('')
    setCardLoading(true)
    void loadPaymentRequestCard(user, row.id)
      .then((result) => {
        if (cardForRef.current === row.id) setCard(result)
      })
      .catch((err: unknown) => {
        if (cardForRef.current === row.id) {
          setCardError(err instanceof Error ? err.message : 'Не удалось открыть заявку')
        }
      })
      .finally(() => {
        if (cardForRef.current === row.id) setCardLoading(false)
      })
  }

  const resetFilters = (): void => {
    setOrganization('')
    setDepartment('')
    setRecipient('')
    setRequestedBy('')
    setAuthor('')
    setCfo('')
    setQuery('')
  }

  const selected = rows.find((row) => row.id === selectedId) || null

  return (
    <div className="docflow-split docflow-split-orders">
      <div className="docflow-table-card wp-card">
        <div className="docflow-order-filters">
          <DocflowSearch
            value={query}
            onChange={setQuery}
            placeholder="Номер, получатель, назначение…"
            found={visible.length}
            total={listed.length}
          />
          <FilterSelect
            icon={<Circle size={13} aria-hidden />}
            label="Статус"
            value={status}
            options={statuses.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setStatus}
          />
          <FilterSelect
            icon={<Layers size={13} aria-hidden />}
            label="Операция"
            value={operation}
            options={operationList.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setOperation}
          />
          <FilterSelect
            icon={<CreditCard size={13} aria-hidden />}
            label="Форма оплаты"
            value={paymentForm}
            options={formList.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setPaymentForm}
          />
          <FilterSelect
            icon={<Banknote size={13} aria-hidden />}
            label="Получатель"
            value={recipient}
            options={recipients}
            onChange={setRecipient}
          />
          <FilterSelect
            icon={<Building2 size={13} aria-hidden />}
            label="Организация"
            value={organization}
            options={organizations}
            onChange={setOrganization}
          />
          <FilterSelect
            icon={<Users size={13} aria-hidden />}
            label="Подразделение"
            value={department}
            options={departments}
            onChange={setDepartment}
          />
          <FilterSelect
            icon={<Target size={13} aria-hidden />}
            label="ЦФО"
            value={cfo}
            options={cfos}
            onChange={setCfo}
          />
          <FilterSelect
            icon={<UserCheck size={13} aria-hidden />}
            label="Заявил"
            value={requestedBy}
            options={requesters}
            onChange={setRequestedBy}
          />
          <FilterSelect
            icon={<PenLine size={13} aria-hidden />}
            label="Автор"
            value={author}
            options={authors}
            onChange={setAuthor}
          />
          {filtered ? (
            <button type="button" className="docflow-retry" onClick={resetFilters}>
              Сбросить
            </button>
          ) : null}
          <span>
            {`${visible.length} из ${rows.length}${hasMore ? '+' : ''}`}
            {visibleAmount ? ` · на ${formatAmount(visibleAmount)}` : ''}
          </span>
        </div>
        {error ? (
          <p className="docflow-status docflow-status-error">
            {error}
            <button type="button" className="docflow-retry" onClick={() => setReload((value) => value + 1)}>
              Повторить
            </button>
          </p>
        ) : null}
        {!loading && !error && !visible.length ? (
          <p className="docflow-status">
            {rows.length ? 'Под выбранные фильтры заявок нет' : 'Нет заявок на расходование ДС за выбранный период'}
          </p>
        ) : null}
        <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
          {visible.length ? (
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <SortTh label="Дата" sortKey="date" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Номер" sortKey="number" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Операция" sortKey="operation" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Сумма" sortKey="amount" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Получатель" sortKey="recipient" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Организация" sortKey="organization" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Подразделение" sortKey="department" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Заявил" sortKey="requestedBy" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Дата платежа" sortKey="paymentDate" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Статус" sortKey="status" sort={table.sort} onSort={table.toggleSort} />
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr
                    key={row.id}
                    className={`docflow-row${selectedId === row.id ? ' is-selected' : ''}`}
                    tabIndex={0}
                    onClick={() => openCard(row)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        openCard(row)
                      }
                    }}
                  >
                    <td>{onlyDay(row.date)}</td>
                    <td>{cell(row.number)}</td>
                    <td title={row.operation}>{cell(row.operation)}</td>
                    <td className="docflow-num">{formatAmount(row.amount, row.currency)}</td>
                    <td title={row.recipient}>{cell(row.recipient)}</td>
                    <td title={row.organization}>{cell(row.organization)}</td>
                    <td title={row.department}>{cell(row.department)}</td>
                    <td>{cell(row.requestedBy)}</td>
                    <td>{onlyDay(row.paymentDate)}</td>
                    <td>
                      <StatusPill row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {loading ? (
            <p className="docflow-status">{rows.length ? 'Загружаем ещё…' : 'Загружаем заявки из 1С…'}</p>
          ) : null}
          {!loading && !hasMore && rows.length ? (
            <p className="docflow-status docflow-end">Показаны все заявки за период</p>
          ) : null}
        </div>
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка заявки на расходование ДС">
        {!selected ? (
          <p className="docflow-status">Выберите заявку, чтобы увидеть карточку</p>
        ) : cardLoading ? (
          <p className="docflow-status">Загружаем заявку № {selected.number} из 1С…</p>
        ) : cardError ? (
          <p className="docflow-status docflow-status-error">
            {cardError}
            <button type="button" className="docflow-retry" onClick={() => openCard(selected)}>
              Повторить
            </button>
          </p>
        ) : card ? (
          <PaymentRequestCardView card={card} />
        ) : null}
      </aside>
    </div>
  )
}
