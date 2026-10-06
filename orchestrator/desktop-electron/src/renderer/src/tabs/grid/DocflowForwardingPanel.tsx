import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Boxes,
  Building2,
  CheckCircle2,
  Circle,
  ClipboardList,
  Gauge,
  Layers,
  MapPin,
  Package,
  Route,
  Truck,
  UserCheck,
  Warehouse,
  XCircle
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import { ATTACHED_FILES } from '../../workplace/docflowAttachments'
import { DocflowAttachments } from './DocflowAttachments'
import {
  loadForwardingCard,
  loadForwardingPage,
  type ForwardingCard,
  type ForwardingOption,
  type ForwardingRow
} from '../../workplace/fetchDocflowForwarding'
import type { DocflowKindId } from '../../workplace/docflowDocumentCreate'
import { DocflowOpenFormBar } from './DocflowOpenFormBar'
import { DocflowSearch, SortTh, useDocflowTable } from './docflowTableTools'

const FALLBACK_STATUSES: ForwardingOption[] = [
  { code: 'Подготовлен', label: 'Подготовлен' },
  { code: 'НаСогласовании', label: 'На согласовании' },
  { code: 'Согласовано', label: 'Согласовано' },
  { code: 'Отклонено', label: 'Отклонено' }
]

function cell(value: string): string {
  return value.trim() || '—'
}

function onlyDay(value: string): string {
  return value ? formatCorrespondenceDate(value).slice(0, 10) : '—'
}

function measure(value: number, unit: string): string {
  return value ? `${value.toLocaleString('ru-RU')} ${unit}` : ''
}

function searchText(row: ForwardingRow): string {
  return [
    row.date,
    row.number,
    row.status,
    row.kind,
    row.way,
    row.address,
    row.warehouse,
    row.responsible,
    row.department,
    row.consignee,
    row.counterparty,
    row.city,
    row.transport,
    row.contact,
    row.phone,
    row.deliveryNote,
    row.passenger,
    row.tripPurpose
  ].join(' ')
}

function sortValue(row: ForwardingRow, key: string): string | number {
  const map: Record<string, string | number> = {
    date: row.date,
    number: row.number,
    kind: row.kind,
    way: row.way,
    doneAt: row.doneAt,
    window: row.window,
    consignee: row.consignee,
    address: row.address,
    warehouse: row.warehouse,
    responsible: row.responsible,
    weight: row.weight,
    status: row.status
  }
  return map[key] ?? ''
}

function optionsOf(rows: ForwardingRow[], pick: (row: ForwardingRow) => string): { value: string; label: string }[] {
  const names = new Set(rows.map(pick).map((value) => value.trim()).filter(Boolean))
  return [...names].sort((left, right) => left.localeCompare(right, 'ru')).map((name) => ({ value: name, label: name }))
}

function StatusPill({ row }: { row: Pick<ForwardingRow, 'status' | 'statusCode'> }): React.JSX.Element {
  const tone =
    row.statusCode === 'Согласовано'
      ? 'is-ok'
      : row.statusCode === 'Отклонено'
        ? 'is-bad'
        : row.statusCode === 'НаСогласовании'
          ? 'is-wait'
          : 'is-muted'
  const Icon = row.statusCode === 'Отклонено' ? XCircle : row.statusCode === 'Согласовано' ? CheckCircle2 : Circle
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

function ForwardingCardView({ card, user }: { card: ForwardingCard; user: UserProfile }): React.JSX.Element {
  const { order: row, cargo, devices, orders, bases, stats } = card
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>
            {onlyDay(row.date)}
            {row.window ? ` · ${row.window}` : ''}
          </p>
        </div>
        <StatusPill row={row} />
      </header>
      {row.address ? <p className="docflow-side-subject">{row.address}</p> : null}
      <div className="docflow-side-scroll">
        <DocflowAttachments user={user} entity={ATTACHED_FILES.forwarding} ownerId={row.id} />
        <section className="docflow-card-block">
          <h4>Доставка</h4>
          <dl className="docflow-detail-list">
            <Fact label="Тип заявки" value={row.kind} />
            <Fact label="Способ" value={row.way} />
            <Fact label="Дата выполнения" value={row.doneAt ? onlyDay(row.doneAt) : ''} />
            <Fact label="Окно доставки" value={row.window} />
            <Fact label="Склад" value={row.warehouse} />
            <Fact label="Зона" value={row.zone} />
            <Fact label="Город" value={row.city} />
            <Fact label="Терминал" value={row.terminal} />
            <Fact label="Транспорт" value={row.transport} />
            <Fact label="Погрузка" value={row.loading} />
            <Fact label="Маршрут" value={[row.routeFrom, row.routeTo].filter(Boolean).join(' → ')} />
          </dl>
        </section>
        <section className="docflow-card-block">
          <h4>Участники</h4>
          <dl className="docflow-detail-list">
            <Fact label="Ответственный" value={row.responsible} />
            <Fact label="Подразделение" value={row.department} />
            <Fact label="Грузоотправитель" value={row.shipper} />
            <Fact label="Грузополучатель" value={row.consignee} />
            <Fact label="Адрес грузополучателя" value={row.consigneeAddress} />
            <Fact label="Контрагент" value={row.counterparty} />
            <Fact label="Плательщик" value={row.payer} />
            <Fact label="Направление плательщика" value={row.payerDirection} />
            <Fact label="Контакт" value={row.contact} />
            <Fact label="Телефон" value={row.phone} />
          </dl>
        </section>
        <section className="docflow-card-block">
          <h4>
            <Gauge size={14} aria-hidden /> Груз
          </h4>
          <dl className="docflow-detail-list">
            <Fact label="Мест" value={row.places ? String(row.places) : ''} />
            <Fact label="Вес" value={measure(row.weight, 'кг')} />
            <Fact label="Объём" value={measure(row.volume, 'м³')} />
            <Fact label="Габариты" value={row.size} />
            <Fact label="Стоимость груза" value={measure(row.cargoCost, '₽')} />
            <Fact label="Комплектность отгрузки" value={row.complete ? 'Да' : 'Нет'} />
            <Fact label="Процесс запущен" value={row.processStarted ? 'Да' : 'Нет'} />
            <Fact label="Нужно согласование исп. директора" value={row.needsDirector ? 'Да' : ''} />
            <Fact label="Проведено" value={row.posted ? 'Да' : 'Нет'} />
          </dl>
        </section>
        {row.passenger || row.tripPurpose ? (
          <section className="docflow-card-block">
            <h4>Пассажирская перевозка</h4>
            <dl className="docflow-detail-list">
              <Fact label="Пассажир" value={row.passenger} />
              <Fact label="Телефон" value={row.passengerPhone} />
              <Fact label="Цель поездки" value={row.tripPurpose} />
            </dl>
          </section>
        ) : null}
        {devices.length ? (
          <section className="docflow-card-block">
            <h4>
              <Package size={14} aria-hidden /> Приборы
              <span>{stats.devices}</span>
            </h4>
            <ol className="docflow-lines">
              {devices.map((item) => (
                <li key={item.n}>
                  <p>{item.name || '—'}</p>
                  <div>
                    {item.serial ? <span>{item.serial}</span> : null}
                    {item.order ? <span>{item.order}</span> : null}
                    {item.places ? <span>мест {item.places}</span> : null}
                    {item.packingList ? <span>упак. лист {item.packingList}</span> : null}
                    {item.module ? <span>{item.module}</span> : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {cargo.length ? (
          <section className="docflow-card-block">
            <h4>
              <Boxes size={14} aria-hidden /> Габариты груза
              <span>
                {[measure(stats.cargoWeight, 'кг'), measure(stats.cargoVolume, 'м³')].filter(Boolean).join(' · ') ||
                  stats.cargo}
              </span>
            </h4>
            <ol className="docflow-lines">
              {cargo.map((item) => (
                <li key={item.n}>
                  <p>{item.name || '—'}</p>
                  <div>
                    {item.length || item.width || item.height ? (
                      <span>{[item.length, item.width, item.height].filter(Boolean).join(' × ')}</span>
                    ) : null}
                    {item.weight ? <span>{measure(item.weight, 'кг')}</span> : null}
                    {item.volume ? <span>{measure(item.volume, 'м³')}</span> : null}
                    {item.order ? <span>{item.order}</span> : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {orders.length ? (
          <section className="docflow-card-block">
            <h4>
              <ClipboardList size={14} aria-hidden /> Заказы на доставку
              <span>{orders.length}</span>
            </h4>
            <ol className="docflow-lines">
              {orders.map((item) => (
                <li key={item.n}>
                  <p>{item.order || '—'}</p>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {bases.length ? (
          <section className="docflow-card-block">
            <h4>
              <Route size={14} aria-hidden /> Основания
              <span>{bases.length}</span>
            </h4>
            <ol className="docflow-lines">
              {bases.map((item) => (
                <li key={item.n}>
                  <p>{item.title || '—'}</p>
                  <div>{item.kind ? <span>{item.kind}</span> : null}</div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {row.deliveryNote || row.specialTerms || row.comment ? (
          <section className="docflow-card-block">
            <h4>Примечания</h4>
            {row.deliveryNote ? <p>{row.deliveryNote}</p> : null}
            {row.specialTerms && row.specialTerms !== row.deliveryNote ? (
              <p className="docflow-muted">{row.specialTerms}</p>
            ) : null}
            {row.comment ? <p className="docflow-muted">{row.comment}</p> : null}
          </section>
        ) : null}
      </div>
    </>
  )
}

export function DocflowForwardingPanel({
  user,
  from,
  to,
  onOpenDocument
}: {
  user: UserProfile
  from: string
  to: string
  onOpenDocument?: (kind: DocflowKindId, refKey: string) => void
}): React.JSX.Element {
  const [rows, setRows] = useState<ForwardingRow[]>([])
  const [statuses, setStatuses] = useState<ForwardingOption[]>(FALLBACK_STATUSES)
  const [kindList, setKindList] = useState<ForwardingOption[]>([])
  const [wayList, setWayList] = useState<ForwardingOption[]>([])
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
  const [way, setWay] = useState('')
  const [warehouse, setWarehouse] = useState('')
  const [responsible, setResponsible] = useState('')
  const [department, setDepartment] = useState('')
  const [consignee, setConsignee] = useState('')
  const [city, setCity] = useState('')
  const [transport, setTransport] = useState('')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [card, setCard] = useState<ForwardingCard | null>(null)
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
      const scope = `${from}:${to}:${status}:${kind}:${way}`
      setLoading(true)
      setError('')
      try {
        const page = await loadForwardingPage(user, { from, to, skip, status, kind, way })
        if (scopeRef.current !== scope) return
        setRows((prev) => {
          const base = reset ? [] : prev
          const seen = new Set(base.map((row) => row.id))
          return [...base, ...page.rows.filter((row) => !seen.has(row.id))]
        })
        if (page.statuses.length) setStatuses(page.statuses)
        if (page.kinds.length) setKindList(page.kinds)
        if (page.ways.length) setWayList(page.ways)
        setNextSkip(page.nextSkip)
        setHasMore(page.hasMore)
      } catch (err) {
        if (scopeRef.current === scope) {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить поручения экспедитору')
        }
      } finally {
        if (scopeRef.current === scope) {
          loadingRef.current = false
          setLoading(false)
        }
      }
    },
    [user, from, to, status, kind, way]
  )

  useEffect(() => {
    scopeRef.current = `${from}:${to}:${status}:${kind}:${way}`
    setRows([])
    setNextSkip(0)
    setHasMore(false)
    setError('')
    setSelectedId('')
    setCard(null)
    void fetchPage(0, true)
  }, [fetchPage, from, to, status, kind, way, reload])

  const warehouses = useMemo(() => optionsOf(rows, (row) => row.warehouse), [rows])
  const responsibles = useMemo(() => optionsOf(rows, (row) => row.responsible), [rows])
  const departments = useMemo(() => optionsOf(rows, (row) => row.department), [rows])
  const consignees = useMemo(() => optionsOf(rows, (row) => row.consignee), [rows])
  const cities = useMemo(() => optionsOf(rows, (row) => row.city), [rows])
  const transports = useMemo(() => optionsOf(rows, (row) => row.transport), [rows])

  const listed = useMemo(
    () =>
      rows.filter((row) => {
        if (warehouse && row.warehouse !== warehouse) return false
        if (responsible && row.responsible !== responsible) return false
        if (department && row.department !== department) return false
        if (consignee && row.consignee !== consignee) return false
        if (city && row.city !== city) return false
        if (transport && row.transport !== transport) return false
        return true
      }),
    [rows, warehouse, responsible, department, consignee, city, transport]
  )
  const table = useDocflowTable(listed, {
    text: searchText,
    value: sortValue,
    initialSort: { key: 'date', dir: 'desc' },
    query
  })
  const visible = table.rows

  const filtered = Boolean(warehouse || responsible || department || consignee || city || transport || query.trim())

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

  const openCard = (row: ForwardingRow): void => {
    cardForRef.current = row.id
    setSelectedId(row.id)
    setCard(null)
    setCardError('')
    setCardLoading(true)
    void loadForwardingCard(user, row.id)
      .then((result) => {
        if (cardForRef.current === row.id) setCard(result)
      })
      .catch((err: unknown) => {
        if (cardForRef.current === row.id) {
          setCardError(err instanceof Error ? err.message : 'Не удалось открыть поручение')
        }
      })
      .finally(() => {
        if (cardForRef.current === row.id) setCardLoading(false)
      })
  }

  const resetFilters = (): void => {
    setWarehouse('')
    setResponsible('')
    setDepartment('')
    setConsignee('')
    setCity('')
    setTransport('')
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
            placeholder="Номер, адрес, груз, получатель…"
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
            label="Тип заявки"
            value={kind}
            options={kindList.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setKind}
          />
          <FilterSelect
            icon={<Truck size={13} aria-hidden />}
            label="Способ"
            value={way}
            options={wayList.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setWay}
          />
          <FilterSelect
            icon={<Warehouse size={13} aria-hidden />}
            label="Склад"
            value={warehouse}
            options={warehouses}
            onChange={setWarehouse}
          />
          <FilterSelect
            icon={<UserCheck size={13} aria-hidden />}
            label="Ответственный"
            value={responsible}
            options={responsibles}
            onChange={setResponsible}
          />
          <FilterSelect
            icon={<Building2 size={13} aria-hidden />}
            label="Подразделение"
            value={department}
            options={departments}
            onChange={setDepartment}
          />
          <FilterSelect
            icon={<Package size={13} aria-hidden />}
            label="Грузополучатель"
            value={consignee}
            options={consignees}
            onChange={setConsignee}
          />
          {cities.length ? (
            <FilterSelect
              icon={<MapPin size={13} aria-hidden />}
              label="Город"
              value={city}
              options={cities}
              onChange={setCity}
            />
          ) : null}
          <FilterSelect
            icon={<Truck size={13} aria-hidden />}
            label="Транспорт"
            value={transport}
            options={transports}
            onChange={setTransport}
          />
          {filtered ? (
            <button type="button" className="docflow-retry" onClick={resetFilters}>
              Сбросить
            </button>
          ) : null}
          <span>{`${visible.length} из ${rows.length}${hasMore ? '+' : ''}`}</span>
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
            {rows.length ? 'Под выбранные фильтры поручений нет' : 'Нет поручений экспедитору за выбранный период'}
          </p>
        ) : null}
        <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
          {visible.length ? (
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <SortTh label="Дата" sortKey="date" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Номер" sortKey="number" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Тип заявки" sortKey="kind" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Способ" sortKey="way" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Выполнить" sortKey="doneAt" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Окно" sortKey="window" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Адрес" sortKey="address" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Грузополучатель" sortKey="consignee" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Склад" sortKey="warehouse" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Ответственный" sortKey="responsible" sort={table.sort} onSort={table.toggleSort} />
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
                    onDoubleClick={() => onOpenDocument?.('forwarding', row.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        openCard(row)
                      }
                    }}
                  >
                    <td>{onlyDay(row.date)}</td>
                    <td>{cell(row.number)}</td>
                    <td title={row.kind}>{cell(row.kind)}</td>
                    <td>{cell(row.way)}</td>
                    <td>{onlyDay(row.doneAt)}</td>
                    <td>{cell(row.window)}</td>
                    <td title={row.address}>{cell(row.address)}</td>
                    <td title={row.consignee}>{cell(row.consignee)}</td>
                    <td title={row.warehouse}>{cell(row.warehouse)}</td>
                    <td>{cell(row.responsible)}</td>
                    <td>
                      <StatusPill row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {loading ? (
            <p className="docflow-status">{rows.length ? 'Загружаем ещё…' : 'Загружаем поручения из 1С…'}</p>
          ) : null}
          {!loading && !hasMore && rows.length ? (
            <p className="docflow-status docflow-end">Показаны все поручения за период</p>
          ) : null}
        </div>
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка поручения экспедитору">
        {selected ? (
          <DocflowOpenFormBar
            refKey={selected.id}
            onOpen={onOpenDocument && (() => onOpenDocument('forwarding', selected.id))}
          />
        ) : null}
        {!selected ? (
          <p className="docflow-status">Выберите поручение, чтобы увидеть карточку</p>
        ) : cardLoading ? (
          <p className="docflow-status">Загружаем поручение № {selected.number} из 1С…</p>
        ) : cardError ? (
          <p className="docflow-status docflow-status-error">
            {cardError}
            <button type="button" className="docflow-retry" onClick={() => openCard(selected)}>
              Повторить
            </button>
          </p>
        ) : card ? (
          <ForwardingCardView card={card} user={user} />
        ) : null}
      </aside>
    </div>
  )
}
