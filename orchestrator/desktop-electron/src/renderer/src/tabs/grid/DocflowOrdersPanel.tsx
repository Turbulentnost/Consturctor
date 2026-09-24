import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Building2,
  CalendarRange,
  CheckCircle2,
  Circle,
  FileText,
  ScrollText,
  Search,
  ShieldCheck,
  Stamp,
  UserCheck,
  Users
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { loadDocflowApprovalSheet, type DocflowApprovalSheet } from '../../workplace/docflowCreate'
import {
  formatCorrespondenceDate,
  loadDocflowOrdersSession,
  type OrderKind,
  type OrderRow
} from '../../workplace/fetchDocflowCorrespondence'
import { SortTh, useDocflowTable } from './docflowTableTools'

const KINDS: { id: '' | OrderKind; title: string }[] = [
  { id: '', title: 'Все' },
  { id: 'order', title: 'Приказы' },
  { id: 'directive', title: 'Распоряжения' }
]

type PeriodId = 'all' | '7' | '30' | '90' | '180' | '365' | 'custom'

const PERIODS: { id: PeriodId; label: string }[] = [
  { id: 'all', label: 'Весь период' },
  { id: '7', label: 'За неделю' },
  { id: '30', label: 'За месяц' },
  { id: '90', label: 'За квартал' },
  { id: '180', label: 'За полгода' },
  { id: '365', label: 'За год' },
  { id: 'custom', label: 'Свой период' }
]

const SHEET_LIMIT = 5

function cell(value: string): string {
  return value.trim() || '—'
}

function orderSearchText(row: OrderRow): string {
  return [
    formatCorrespondenceDate(row.date),
    row.number,
    row.kindLabel,
    row.subject,
    row.organization,
    row.responsible,
    row.access,
    row.status,
    row.content
  ].join(' ')
}

function orderSortValue(row: OrderRow, key: string): string {
  const map: Record<string, string> = {
    date: row.date,
    number: row.number,
    kind: row.kindLabel,
    subject: row.subject,
    organization: row.organization,
    responsible: row.responsible,
    access: row.access,
    status: row.status || (row.posted ? 'Проведён' : '')
  }
  return map[key] ?? ''
}

function optionsOf(rows: OrderRow[], pick: (row: OrderRow) => string): string[] {
  const names = new Set(rows.map(pick).map((value) => value.trim()).filter(Boolean))
  return [...names].sort((left, right) => left.localeCompare(right, 'ru'))
}

function isoDay(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Границы периода: пустые строки — фильтр по дате не применяется. */
function periodBounds(period: PeriodId, customFrom: string, customTo: string): { from: string; to: string } {
  if (period === 'all') return { from: '', to: '' }
  if (period === 'custom') return { from: customFrom, to: customTo }
  const to = new Date()
  const from = new Date()
  from.setDate(from.getDate() - (Number(period) - 1))
  return { from: isoDay(from), to: isoDay(to) }
}

function inBounds(row: OrderRow, from: string, to: string): boolean {
  if (!from && !to) return true
  const day = row.date.slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false
  if (from && day < from) return false
  if (to && day > to) return false
  return true
}

function StatusPill({ row }: { row: OrderRow }): React.JSX.Element {
  const done = row.posted || /действ|утвержд|исполн|заверш/i.test(row.status)
  const tone = done ? 'is-ok' : /отмен|аннулир|откл/i.test(row.status) ? 'is-muted' : 'is-wait'
  return (
    <span className={`docflow-pill ${tone}`}>
      {done ? <CheckCircle2 size={12} aria-hidden /> : <Circle size={12} aria-hidden />}
      {row.status || (row.posted ? 'Проведён' : 'Не проведён')}
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
  options: string[]
  onChange: (value: string) => void
}): React.JSX.Element {
  return (
    <label>
      {icon}
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Все</option>
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}

export function DocflowOrdersPanel({ user }: { user: UserProfile }): React.JSX.Element {
  const [rows, setRows] = useState<OrderRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [period, setPeriod] = useState<PeriodId>('all')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [kind, setKind] = useState<'' | OrderKind>('')
  const [status, setStatus] = useState('')
  const [access, setAccess] = useState('')
  const [responsible, setResponsible] = useState('')
  const [organization, setOrganization] = useState('')
  const [approver, setApprover] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [sheets, setSheets] = useState<Record<string, DocflowApprovalSheet>>({})
  const [sheetProgress, setSheetProgress] = useState('')
  const sheetsRef = useRef(sheets)
  sheetsRef.current = sheets

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    setRows([])
    setSelectedId('')
    void loadDocflowOrdersSession(user)
      .then((result) => {
        if (!alive) return
        setRows(result.rows)
        setError(result.error)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setRows([])
        setError(err instanceof Error ? err.message : 'Не удалось загрузить приказы и распоряжения')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [user])

  const bounds = useMemo(() => periodBounds(period, customFrom, customTo), [period, customFrom, customTo])
  const inPeriod = useMemo(() => rows.filter((row) => inBounds(row, bounds.from, bounds.to)), [rows, bounds])
  const byKind = useMemo(() => (kind ? inPeriod.filter((row) => row.kind === kind) : inPeriod), [inPeriod, kind])
  const statuses = useMemo(() => optionsOf(byKind, (row) => row.status), [byKind])
  const accesses = useMemo(() => optionsOf(byKind, (row) => row.access), [byKind])
  const responsibles = useMemo(() => optionsOf(byKind, (row) => row.responsible), [byKind])
  const organizations = useMemo(() => optionsOf(byKind, (row) => row.organization), [byKind])

  // Поиск по словам делает useDocflowTable ниже — здесь только выпадающие фильтры.
  const listed = useMemo(
    () =>
      byKind.filter((row) => {
        if (status && row.status !== status) return false
        if (access && row.access !== access) return false
        if (responsible && row.responsible !== responsible) return false
        if (organization && row.organization !== organization) return false
        return true
      }),
    [byKind, status, access, responsible, organization]
  )

  const approvers = useMemo(() => {
    const names = new Set<string>()
    for (const row of listed) {
      for (const item of sheets[row.id]?.items || []) {
        const name = item.name.trim()
        if (name) names.add(name)
      }
    }
    return [...names].sort((left, right) => left.localeCompare(right, 'ru'))
  }, [listed, sheets])

  const byApprover = useMemo(
    () =>
      approver
        ? listed.filter((row) => (sheets[row.id]?.items || []).some((item) => item.name.trim() === approver))
        : listed,
    [listed, approver, sheets]
  )
  const table = useDocflowTable(byApprover, {
    text: orderSearchText,
    value: orderSortValue,
    initialSort: { key: 'date', dir: 'desc' },
    query
  })
  const visible = table.rows

  const selected = visible.find((row) => row.id === selectedId) || listed.find((row) => row.id === selectedId) || null
  const selectedSheet = selected ? sheets[selected.id] : undefined
  const filtered = Boolean(
    query.trim() || kind || status || access || responsible || organization || approver || period !== 'all'
  )

  useEffect(() => {
    const selectedRow = listed.find((row) => row.id === selectedId) || null
    const queue = [
      ...(selectedRow ? [selectedRow] : []),
      ...listed.filter((row) => row.id !== selectedRow?.id).slice(0, SHEET_LIMIT)
    ]
    const pending = queue.filter((row) => !sheetsRef.current[row.id])
    if (!pending.length) return
    let alive = true
    setSheetProgress(`Листы согласования: 0 из ${pending.length}`)
    void (async () => {
      let done = 0
      for (const row of pending) {
        if (!alive) return
        const sheet = await loadDocflowApprovalSheet(user, {
          id: row.id,
          kind: row.kind,
          regNumber: row.number,
          title: row.subject
        })
        if (!alive) return
        done += 1
        setSheets((prev) => (prev[row.id] ? prev : { ...prev, [row.id]: sheet }))
        setSheetProgress(done >= pending.length ? '' : `Листы согласования: ${done} из ${pending.length}`)
        if (/парол|учётн|учетн|401|403/i.test(sheet.message)) return
      }
    })()
    return () => {
      alive = false
    }
  }, [user, listed, selectedId])

  const resetFilters = (): void => {
    setQuery('')
    setPeriod('all')
    setCustomFrom('')
    setCustomTo('')
    setKind('')
    setStatus('')
    setAccess('')
    setResponsible('')
    setOrganization('')
    setApprover('')
  }

  return (
    <div className="docflow-split docflow-split-orders">
      <div className="docflow-table-card wp-card">
        <div className="docflow-order-filters">
          <label className="docflow-search">
            <Search size={14} aria-hidden />
            <input
              type="search"
              value={query}
              placeholder="Номер, тема, содержание…"
              onChange={(event) => setQuery(event.target.value)}
            />
            {query.trim() ? (
              <span className="docflow-search-count">
                {visible.length} из {byApprover.length}
              </span>
            ) : null}
          </label>
          <label>
            <CalendarRange size={13} aria-hidden />
            Период
            <select value={period} onChange={(event) => setPeriod(event.target.value as PeriodId)}>
              {PERIODS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {period === 'custom' ? (
            <label className="docflow-dates">
              <input type="date" value={customFrom} onChange={(event) => setCustomFrom(event.target.value)} />
              <span>—</span>
              <input type="date" value={customTo} onChange={(event) => setCustomTo(event.target.value)} />
            </label>
          ) : null}
          <label>
            <ScrollText size={13} aria-hidden />
            Вид
            <select value={kind} onChange={(event) => setKind(event.target.value as '' | OrderKind)}>
              {KINDS.map((item) => (
                <option key={item.id || 'all'} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <FilterSelect icon={<Circle size={13} aria-hidden />} label="Статус" value={status} options={statuses} onChange={setStatus} />
          <FilterSelect icon={<ShieldCheck size={13} aria-hidden />} label="Гриф" value={access} options={accesses} onChange={setAccess} />
          <FilterSelect icon={<UserCheck size={13} aria-hidden />} label="Ответственный" value={responsible} options={responsibles} onChange={setResponsible} />
          <FilterSelect icon={<Building2 size={13} aria-hidden />} label="Организация" value={organization} options={organizations} onChange={setOrganization} />
          <FilterSelect icon={<Users size={13} aria-hidden />} label="Согласующий" value={approver} options={approvers} onChange={setApprover} />
          {filtered ? (
            <button type="button" className="docflow-retry" onClick={resetFilters}>
              Сбросить
            </button>
          ) : null}
          <span>
            {loading ? 'Загрузка…' : `${visible.length} из ${rows.length}`}
            {sheetProgress ? ` · ${sheetProgress}` : ''}
          </span>
        </div>
        {loading ? <p className="docflow-status">Загружаем приказы и распоряжения из 1С…</p> : null}
        {error && !loading ? <p className="docflow-status docflow-status-error">{error}</p> : null}
        {!loading && !error && !visible.length ? (
          <p className="docflow-status">
            {approver && listed.length && sheetProgress
              ? 'Загружаем листы согласования, чтобы отфильтровать по согласующему'
              : approver && listed.length
                ? 'Среди загруженных листов согласования нет такого согласующего'
                : rows.length
                  ? 'Под выбранные фильтры приказов и распоряжений нет'
                  : 'Нет приказов и распоряжений'}
          </p>
        ) : null}
        {visible.length ? (
          <div className="docflow-table-scroll">
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <SortTh label="Дата" sortKey="date" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Номер" sortKey="number" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Вид" sortKey="kind" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Тема" sortKey="subject" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Организация" sortKey="organization" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Ответственный" sortKey="responsible" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Гриф" sortKey="access" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Статус" sortKey="status" sort={table.sort} onSort={table.toggleSort} />
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr
                    key={row.id}
                    className={`docflow-row${selected?.id === row.id ? ' is-selected' : ''}`}
                    tabIndex={0}
                    onClick={() => setSelectedId(row.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setSelectedId(row.id)
                      }
                    }}
                  >
                    <td>{formatCorrespondenceDate(row.date)}</td>
                    <td>{cell(row.number)}</td>
                    <td>
                      <span className="docflow-pill is-muted">
                        {row.kind === 'order' ? <ScrollText size={11} aria-hidden /> : <FileText size={11} aria-hidden />}
                        {row.kindLabel}
                      </span>
                    </td>
                    <td title={row.subject}>{cell(row.subject)}</td>
                    <td>{cell(row.organization)}</td>
                    <td>{cell(row.responsible)}</td>
                    <td>{cell(row.access)}</td>
                    <td>
                      <StatusPill row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка приказа или распоряжения">
        {selected ? (
          <>
            <header className="docflow-detail-head">
              <div>
                <h3>№ {cell(selected.number)}</h3>
                <p>
                  {selected.kindLabel} · {formatCorrespondenceDate(selected.date)}
                </p>
              </div>
              <StatusPill row={selected} />
            </header>
            {selected.subject ? <p className="docflow-side-subject">{selected.subject}</p> : null}
            <div className="docflow-side-scroll">
              <section className="docflow-card-block">
                <h4>
                  <Stamp size={14} aria-hidden /> Согласующие
                  {selectedSheet?.items.length ? <span>{selectedSheet.items.length}</span> : null}
                </h4>
                {!selectedSheet ? <p className="docflow-muted">Загружаем лист согласования из документооборота…</p> : null}
                {selectedSheet && !selectedSheet.found ? (
                  <p className="docflow-muted">{selectedSheet.message || 'Лист согласования пуст'}</p>
                ) : null}
                {selectedSheet?.items.length ? (
                  <ul className="docflow-route">
                    {selectedSheet.items.map((item, index) => {
                      const ok = /соглас|подпис|утвержд/i.test(item.result)
                      return (
                        <li key={`${item.name}-${item.date}-${index}`} className={ok ? 'is-done' : ''}>
                          {ok ? <CheckCircle2 size={14} aria-hidden /> : <Circle size={14} aria-hidden />}
                          <div>
                            <strong>{cell(item.name)}</strong>
                            <span>
                              {[item.position, item.result, item.date ? formatCorrespondenceDate(item.date) : '']
                                .filter(Boolean)
                                .join(' · ') || '—'}
                            </span>
                            {item.comment ? <em>{item.comment}</em> : null}
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                ) : null}
              </section>
              <section className="docflow-card-block">
                <h4>Реквизиты</h4>
                <dl className="docflow-detail-list">
                  {selected.fields.map((field) => (
                    <div key={field.label}>
                      <dt>{field.label}</dt>
                      <dd>{field.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            </div>
          </>
        ) : (
          <p className="docflow-status">Выберите приказ или распоряжение, чтобы увидеть карточку</p>
        )}
      </aside>
    </div>
  )
}
