import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Ban,
  Building2,
  CheckCircle2,
  Circle,
  ShieldCheck,
  UserCheck,
  Users,
  XCircle
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import {
  loadIncentiveOrderCard,
  loadIncentiveOrderPage,
  type IncentiveOrderOption,
  type IncentiveOrderRow
} from '../../workplace/fetchDocflowIncentiveOrders'
import { formatAmount } from '../../workplace/fetchDocflowPaymentRequests'
import { DocflowSearch, SortTh, useDocflowTable } from './docflowTableTools'

function cell(value: string): string {
  return value.trim() || '—'
}

function onlyDay(value: string): string {
  return value ? formatCorrespondenceDate(value).slice(0, 10) : '—'
}

function searchText(row: IncentiveOrderRow): string {
  return [
    row.date,
    row.number,
    row.status,
    row.employee,
    row.employeeDepartment,
    row.organization,
    row.department,
    row.responsible,
    row.author,
    row.approver,
    row.title,
    row.task,
    row.comment,
    String(row.percent)
  ].join(' ')
}

function sortValue(row: IncentiveOrderRow, key: string): string | number {
  const map: Record<string, string | number> = {
    date: row.date,
    number: row.number,
    employee: row.employee,
    percent: row.percent,
    amount: row.amount,
    employeeDepartment: row.employeeDepartment,
    organization: row.organization,
    approver: row.approver,
    task: row.task,
    status: row.status
  }
  return map[key] ?? ''
}

function optionsOf(
  rows: IncentiveOrderRow[],
  pick: (row: IncentiveOrderRow) => string
): { value: string; label: string }[] {
  const names = new Set(rows.map(pick).map((value) => value.trim()).filter(Boolean))
  return [...names].sort((left, right) => left.localeCompare(right, 'ru')).map((name) => ({ value: name, label: name }))
}

/** «Не утвержден»/«Не согласован» — отказ, «На утверждении»/«На согласовании» — ещё в работе. */
function statusTone(status: string): string {
  if (status.startsWith('Не ') || status === 'Отклонен') return 'is-bad'
  if (status.startsWith('На ')) return 'is-wait'
  if (status) return 'is-ok'
  return 'is-muted'
}

function StatusPill({ row }: { row: Pick<IncentiveOrderRow, 'status' | 'cancelled'> }): React.JSX.Element {
  const status = row.status
  const tone = row.cancelled ? 'is-muted' : statusTone(status)
  const Icon = tone === 'is-bad' ? XCircle : tone === 'is-ok' ? CheckCircle2 : Circle
  return (
    <span className={`docflow-pill ${tone}`}>
      <Icon size={12} aria-hidden />
      {row.cancelled ? `${status || '—'} · аннулирован` : status || '—'}
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

function IncentiveOrderCardView({ row }: { row: IncentiveOrderRow }): React.JSX.Element {
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>{onlyDay(row.date)}</p>
        </div>
        <StatusPill row={row} />
      </header>
      {row.title ? <p className="docflow-side-subject">{row.title}</p> : null}
      <div className="docflow-side-scroll">
        <section className="docflow-card-block">
          <h4>Мера</h4>
          <dl className="docflow-detail-list">
            <Fact label="Сотрудник" value={row.employee} />
            <Fact label="Подразделение сотрудника" value={row.employeeDepartment} />
            <Fact label="Процент депремирования" value={row.percent ? `${row.percent}%` : ''} />
            <Fact label="Сумма депремирования" value={row.amount ? `${formatAmount(row.amount)} ₽` : ''} />
            <Fact label="Период зарплаты" value={row.salaryPeriod} />
            <Fact label="Дисциплинарное взыскание" value={row.discipline} />
          </dl>
        </section>
        <section className="docflow-card-block">
          <h4>Согласование</h4>
          <dl className="docflow-detail-list">
            <Fact label="Состояние" value={row.status} />
            <Fact label="Регистрация" value={row.registration} />
            <Fact label="Согласование" value={row.approval} />
            <Fact label="Утверждение" value={row.confirmation} />
            <Fact label="Исполнение" value={row.performance} />
            <Fact label="Утверждающий руководитель" value={row.approver} />
            <Fact label="Контролирующий руководитель" value={row.controller} />
            <Fact label="Ответственный" value={row.responsible} />
            <Fact label="Автор" value={row.author} />
            <Fact label="Организация" value={row.organization} />
            <Fact label="Подразделение документа" value={row.department} />
          </dl>
        </section>
        {row.task || row.taskAuthor ? (
          <section className="docflow-card-block">
            <h4>Основание</h4>
            <dl className="docflow-detail-list">
              <Fact label="Не выполненная задача" value={row.task} />
              <Fact label="Автор задачи" value={row.taskAuthor} />
            </dl>
          </section>
        ) : null}
        {row.cancelled || row.cancelReason ? (
          <section className="docflow-card-block">
            <h4>
              <Ban size={14} aria-hidden /> Аннулирование
            </h4>
            <dl className="docflow-detail-list">
              <Fact label="Аннулирован" value={row.cancelled ? 'Да' : 'Нет'} />
              <Fact label="Причина" value={row.cancelReason} />
              <Fact label="Кем" value={row.cancelledBy} />
              <Fact label="Когда" value={row.cancelledAt ? onlyDay(row.cancelledAt) : ''} />
            </dl>
          </section>
        ) : null}
        {row.summary && row.summary !== row.title ? (
          <section className="docflow-card-block">
            <h4>Содержание</h4>
            <p>{row.summary}</p>
          </section>
        ) : null}
        {row.comment ? (
          <section className="docflow-card-block">
            <h4>Комментарий</h4>
            <p className="docflow-muted">{row.comment}</p>
          </section>
        ) : null}
      </div>
    </>
  )
}

export function DocflowIncentiveOrdersPanel({
  user,
  from,
  to
}: {
  user: UserProfile
  from: string
  to: string
}): React.JSX.Element {
  const [rows, setRows] = useState<IncentiveOrderRow[]>([])
  const [statuses, setStatuses] = useState<IncentiveOrderOption[]>([])
  const [total, setTotal] = useState(0)
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [status, setStatus] = useState('')
  const [employee, setEmployee] = useState('')
  const [employeeDepartment, setEmployeeDepartment] = useState('')
  const [organization, setOrganization] = useState('')
  const [approver, setApprover] = useState('')
  const [author, setAuthor] = useState('')
  const [cancelled, setCancelled] = useState('')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [card, setCard] = useState<IncentiveOrderRow | null>(null)
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
      const scope = `${from}:${to}:${status}`
      setLoading(true)
      setError('')
      try {
        const page = await loadIncentiveOrderPage(user, { from, to, skip, status })
        if (scopeRef.current !== scope) return
        setRows((prev) => {
          const base = reset ? [] : prev
          const seen = new Set(base.map((row) => row.id))
          return [...base, ...page.rows.filter((row) => !seen.has(row.id))]
        })
        if (page.statuses.length) setStatuses(page.statuses)
        setTotal(page.total)
        setNextSkip(page.nextSkip)
        setHasMore(page.hasMore)
      } catch (err) {
        if (scopeRef.current === scope) {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить приказы')
        }
      } finally {
        if (scopeRef.current === scope) {
          loadingRef.current = false
          setLoading(false)
        }
      }
    },
    [user, from, to, status]
  )

  useEffect(() => {
    scopeRef.current = `${from}:${to}:${status}`
    setRows([])
    setTotal(0)
    setNextSkip(0)
    setHasMore(false)
    setError('')
    setSelectedId('')
    setCard(null)
    void fetchPage(0, true)
  }, [fetchPage, from, to, status, reload])

  const employees = useMemo(() => optionsOf(rows, (row) => row.employee), [rows])
  const employeeDepartments = useMemo(() => optionsOf(rows, (row) => row.employeeDepartment), [rows])
  const organizations = useMemo(() => optionsOf(rows, (row) => row.organization), [rows])
  const approvers = useMemo(() => optionsOf(rows, (row) => row.approver), [rows])
  const authors = useMemo(() => optionsOf(rows, (row) => row.author), [rows])

  const listed = useMemo(
    () =>
      rows.filter((row) => {
        if (employee && row.employee !== employee) return false
        if (employeeDepartment && row.employeeDepartment !== employeeDepartment) return false
        if (organization && row.organization !== organization) return false
        if (approver && row.approver !== approver) return false
        if (author && row.author !== author) return false
        if (cancelled === 'yes' && !row.cancelled) return false
        if (cancelled === 'no' && row.cancelled) return false
        return true
      }),
    [rows, employee, employeeDepartment, organization, approver, author, cancelled]
  )
  const table = useDocflowTable(listed, {
    text: searchText,
    value: sortValue,
    initialSort: { key: 'date', dir: 'desc' },
    query
  })
  const visible = table.rows

  const filtered = Boolean(
    employee || employeeDepartment || organization || approver || author || cancelled || query.trim()
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

  const openCard = (row: IncentiveOrderRow): void => {
    cardForRef.current = row.id
    setSelectedId(row.id)
    setCard(null)
    setCardError('')
    setCardLoading(true)
    void loadIncentiveOrderCard(user, row.id)
      .then((result) => {
        if (cardForRef.current === row.id) setCard(result)
      })
      .catch((err: unknown) => {
        if (cardForRef.current === row.id) {
          setCardError(err instanceof Error ? err.message : 'Не удалось открыть приказ')
        }
      })
      .finally(() => {
        if (cardForRef.current === row.id) setCardLoading(false)
      })
  }

  const resetFilters = (): void => {
    setEmployee('')
    setEmployeeDepartment('')
    setOrganization('')
    setApprover('')
    setAuthor('')
    setCancelled('')
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
            placeholder="Номер, сотрудник, основание…"
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
            icon={<Users size={13} aria-hidden />}
            label="Сотрудник"
            value={employee}
            options={employees}
            onChange={setEmployee}
          />
          <FilterSelect
            icon={<Users size={13} aria-hidden />}
            label="Подразделение"
            value={employeeDepartment}
            options={employeeDepartments}
            onChange={setEmployeeDepartment}
          />
          <FilterSelect
            icon={<Building2 size={13} aria-hidden />}
            label="Организация"
            value={organization}
            options={organizations}
            onChange={setOrganization}
          />
          <FilterSelect
            icon={<ShieldCheck size={13} aria-hidden />}
            label="Утверждающий"
            value={approver}
            options={approvers}
            onChange={setApprover}
          />
          <FilterSelect
            icon={<UserCheck size={13} aria-hidden />}
            label="Подготовил"
            value={author}
            options={authors}
            onChange={setAuthor}
          />
          <FilterSelect
            icon={<Ban size={13} aria-hidden />}
            label="Аннулирован"
            value={cancelled}
            options={[
              { value: 'no', label: 'Действующие' },
              { value: 'yes', label: 'Аннулированные' }
            ]}
            onChange={setCancelled}
          />
          {filtered ? (
            <button type="button" className="docflow-retry" onClick={resetFilters}>
              Сбросить
            </button>
          ) : null}
          <span>{`${visible.length} из ${total || rows.length}`}</span>
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
            {rows.length ? 'Под выбранные фильтры приказов нет' : 'Нет приказов за выбранный период'}
          </p>
        ) : null}
        <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
          {visible.length ? (
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <SortTh label="Дата" sortKey="date" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Номер" sortKey="number" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Сотрудник" sortKey="employee" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Процент" sortKey="percent" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh
                    label="Подразделение"
                    sortKey="employeeDepartment"
                    sort={table.sort}
                    onSort={table.toggleSort}
                  />
                  <SortTh label="Организация" sortKey="organization" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Утверждающий" sortKey="approver" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Основание" sortKey="task" sort={table.sort} onSort={table.toggleSort} />
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
                    <td title={row.employee}>{cell(row.employee)}</td>
                    <td className="docflow-num">{row.percent ? `${row.percent}%` : '—'}</td>
                    <td title={row.employeeDepartment}>{cell(row.employeeDepartment)}</td>
                    <td title={row.organization}>{cell(row.organization)}</td>
                    <td title={row.approver}>{cell(row.approver)}</td>
                    <td title={row.task}>{cell(row.task)}</td>
                    <td>
                      <StatusPill row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {loading ? (
            <p className="docflow-status">
              {rows.length ? 'Загружаем ещё…' : 'Загружаем приказы из Документооборота…'}
            </p>
          ) : null}
          {!loading && !hasMore && rows.length ? (
            <p className="docflow-status docflow-end">Показаны все приказы за период</p>
          ) : null}
        </div>
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка приказа о мерах материального стимулирования">
        {!selected ? (
          <p className="docflow-status">Выберите приказ, чтобы увидеть карточку</p>
        ) : cardLoading ? (
          <p className="docflow-status">Загружаем приказ № {selected.number}…</p>
        ) : cardError ? (
          <p className="docflow-status docflow-status-error">
            {cardError}
            <button type="button" className="docflow-retry" onClick={() => openCard(selected)}>
              Повторить
            </button>
          </p>
        ) : card ? (
          <IncentiveOrderCardView row={card} />
        ) : null}
      </aside>
    </div>
  )
}
