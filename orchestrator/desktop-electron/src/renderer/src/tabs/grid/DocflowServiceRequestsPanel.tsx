import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GraduationCap, HardHat, Megaphone, Monitor, Package, Plus, Store, Wrench } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import {
  loadServiceRequestPage,
  SERVICE_REQUESTS,
  type ServiceRequestId,
  type ServiceRequestOption,
  type ServiceRequestRow
} from '../../workplace/fetchDocflowServiceRequests'
import type { DocflowKindId } from '../../workplace/docflowDocumentCreate'
import { DocflowOpenFormBar } from './DocflowOpenFormBar'
import { DocflowSearch, SortTh, useDocflowTable } from './docflowTableTools'

const ICONS = {
  service_1c: Wrench,
  service_it: Monitor,
  service_exploitation: HardHat,
  service_development: GraduationCap,
  service_nomenclature: Package,
  service_market: Store,
  service_pr: Megaphone
} as const

function cell(value: string): string {
  return value.trim() || '—'
}

function when(value: string): string {
  if (!value.trim()) return '—'
  return formatCorrespondenceDate(value)
}

function mark(value: boolean): string {
  return value ? '✓' : ''
}

function statusTone(code: string): string {
  if (code === 'Исполнен' || code === 'Закрыта') return 'is-done'
  if (code === 'НаИсполнении' || code === 'НаСогласовании') return 'is-work'
  if (code === 'Отклонено' || code === 'Отменен' || code === 'Аннулирован') return 'is-stop'
  return 'is-draft'
}

function cellClass(key: string): string | undefined {
  if (key === 'confirmed') return 'docflow-check'
  if (key === 'kind' || key === 'resolution' || key === 'organization' || key === 'executor') return 'is-wide'
  if (key === 'status') return 'is-status'
  return undefined
}

type Column = {
  key: string
  label: string
  value: (row: ServiceRequestRow) => string
  title?: (row: ServiceRequestRow) => string
}

const COLUMNS: Record<ServiceRequestId, Column[]> = {
  service_1c: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'responsible', label: 'Автор', value: (row) => cell(row.responsible) },
    { key: 'department', label: 'Подразделение', value: (row) => cell(row.department) },
    { key: 'kind', label: 'Вид заявки', value: (row) => cell(row.kind), title: (row) => row.kindPath },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'executor', label: 'Фактический исполнитель', value: (row) => cell(row.executor) },
    { key: 'resolution', label: 'Резолюция', value: (row) => cell(row.resolution) },
    { key: 'acceptedAt', label: 'Дата принятия', value: (row) => when(row.acceptedAt) },
    { key: 'due', label: 'Срок исполнения', value: (row) => when(row.due) },
    { key: 'doneAt', label: 'Дата исполнения', value: (row) => when(row.doneAt) },
    { key: 'confirmed', label: 'Испол.', value: (row) => mark(row.confirmed) },
    { key: 'organization', label: 'Организация', value: (row) => cell(row.organization) }
  ],
  service_it: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'responsible', label: 'Автор', value: (row) => cell(row.responsible) },
    { key: 'department', label: 'Подразделение', value: (row) => cell(row.department) },
    { key: 'kind', label: 'Вид заявки', value: (row) => cell(row.kind), title: (row) => row.kindPath },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'hours', label: 'Время выполнения (в часах)', value: (row) => cell(row.hours) },
    { key: 'executor', label: 'Фактический исполнитель', value: (row) => cell(row.executor) },
    { key: 'resolution', label: 'Резолюция', value: (row) => cell(row.resolution) },
    { key: 'acceptedAt', label: 'Дата принятия', value: (row) => when(row.acceptedAt) },
    { key: 'doneAt', label: 'Дата исполнения', value: (row) => when(row.doneAt) },
    { key: 'confirmed', label: 'Подтверждение об исполнении', value: (row) => mark(row.confirmed) },
    { key: 'organization', label: 'Организация', value: (row) => cell(row.organization) }
  ],
  service_exploitation: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'responsible', label: 'Автор', value: (row) => cell(row.responsible) },
    { key: 'kind', label: 'Вид заявки', value: (row) => cell(row.kind), title: (row) => row.kindPath },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'executor', label: 'Фактический исполнитель', value: (row) => cell(row.executor) },
    { key: 'plannedAt', label: 'Дата исполнения (план)', value: (row) => when(row.plannedAt) },
    { key: 'doneAt', label: 'Дата исполнения (факт)', value: (row) => when(row.doneAt) },
    { key: 'confirmed', label: 'Исполнение подтверждено', value: (row) => mark(row.confirmed) }
  ],
  service_development: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'responsible', label: 'Автор', value: (row) => cell(row.responsible) },
    { key: 'department', label: 'Подразделение', value: (row) => cell(row.department) },
    { key: 'kind', label: 'Вид заявки', value: (row) => cell(row.kind), title: (row) => row.kindPath },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'executor', label: 'Фактический исполнитель', value: (row) => cell(row.executor) },
    { key: 'resolution', label: 'Резолюция', value: (row) => cell(row.resolution) },
    { key: 'acceptedAt', label: 'Дата принятия', value: (row) => when(row.acceptedAt) },
    { key: 'plannedAt', label: 'Срок исполнения плановый', value: (row) => when(row.plannedAt) },
    { key: 'doneAt', label: 'Срок исполнения фактический', value: (row) => when(row.doneAt) },
    { key: 'confirmed', label: 'Испол.', value: (row) => mark(row.confirmed) }
  ],
  service_nomenclature: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'responsible', label: 'Автор', value: (row) => cell(row.responsible) },
    { key: 'department', label: 'Подразделение', value: (row) => cell(row.department) },
    { key: 'kind', label: 'Вид заявки', value: (row) => cell(row.kind), title: (row) => row.kindPath },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'text', label: 'Содержание', value: (row) => cell(row.text) },
    { key: 'executorDepartment', label: 'Подразделение исполнитель', value: (row) => cell(row.executorDepartment) },
    { key: 'due', label: 'Желаемый срок', value: (row) => when(row.due) },
    { key: 'doneAt', label: 'Дата исполнения', value: (row) => when(row.doneAt) },
    { key: 'organization', label: 'Организация', value: (row) => cell(row.organization) }
  ],
  service_market: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'text', label: 'Наименование', value: (row) => cell(row.text) },
    { key: 'kind', label: 'Категория', value: (row) => cell(row.kind) },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'responsible', label: 'Менеджер', value: (row) => cell(row.responsible) },
    { key: 'organization', label: 'Партнёр', value: (row) => cell(row.organization) },
    { key: 'department', label: 'Подразделение', value: (row) => cell(row.department) },
    { key: 'executor', label: 'Принял заявку', value: (row) => cell(row.executor) },
    { key: 'due', label: 'Срок отработки', value: (row) => when(row.due) },
    { key: 'doneAt', label: 'Срок факт', value: (row) => when(row.doneAt) },
    { key: 'resolution', label: 'Описание', value: (row) => cell(row.resolution) }
  ],
  service_pr: [
    { key: 'number', label: 'Номер', value: (row) => cell(row.number) },
    { key: 'date', label: 'Дата', value: (row) => when(row.date) },
    { key: 'responsible', label: 'Автор', value: (row) => cell(row.responsible) },
    { key: 'department', label: 'Подразделение', value: (row) => cell(row.department) },
    { key: 'kind', label: 'Вид заявки', value: (row) => cell(row.kind), title: (row) => row.kindPath },
    { key: 'status', label: 'Статус', value: (row) => cell(row.status) },
    { key: 'text', label: 'Содержание', value: (row) => cell(row.text) },
    { key: 'executor', label: 'Фактический исполнитель', value: (row) => cell(row.executor) },
    { key: 'resolution', label: 'Резолюция', value: (row) => cell(row.resolution) },
    { key: 'due', label: 'Желаемый срок', value: (row) => when(row.due) },
    { key: 'doneAt', label: 'Дата исполнения', value: (row) => when(row.doneAt) },
    { key: 'organization', label: 'Организация', value: (row) => cell(row.organization) }
  ]
}

function searchText(row: ServiceRequestRow): string {
  return [
    row.date,
    when(row.date),
    when(row.due),
    when(row.acceptedAt),
    when(row.plannedAt),
    when(row.doneAt),
    row.number,
    row.status,
    row.kind,
    row.kindPath,
    row.documentType,
    row.text,
    row.organization,
    row.responsible,
    row.department,
    row.executor,
    row.executorDepartment,
    row.resolution,
    row.room,
    row.building,
    row.phone,
    row.person,
    row.position,
    row.priority,
    row.accounts
  ].join(' ')
}

function sortValue(row: ServiceRequestRow, key: string): string {
  const column = Object.values(COLUMNS)
    .flat()
    .find((item) => item.key === key)
  if (key === 'date' || key.endsWith('At')) {
    const raw: Record<string, string> = {
      date: row.date,
      acceptedAt: row.acceptedAt,
      plannedAt: row.plannedAt,
      doneAt: row.doneAt,
      due: row.due
    }
    return raw[key] ?? ''
  }
  return column ? column.value(row) : ''
}

export function DocflowServiceRequestsPanel({
  user,
  from,
  to,
  reload,
  onOpenDocument,
  onCreate
}: {
  user: UserProfile
  from: string
  to: string
  reload: number
  onOpenDocument?: (kind: DocflowKindId, refKey: string) => void
  onCreate?: (kind: DocflowKindId) => void
}): React.JSX.Element {
  const [service, setService] = useState<ServiceRequestId>('service_exploitation')
  const [rows, setRows] = useState<ServiceRequestRow[]>([])
  const [statuses, setStatuses] = useState<ServiceRequestOption[]>([])
  const [status, setStatus] = useState('')
  const [skip, setSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const loadingRef = useRef(false)
  const generation = useRef(0)
  const active = SERVICE_REQUESTS.find((item) => item.id === service) || SERVICE_REQUESTS[2]

  const fetchPage = useCallback(
    (nextSkip: number, replace: boolean) => {
      if (!replace && loadingRef.current) return
      const ticket = replace ? ++generation.current : generation.current
      loadingRef.current = true
      setLoading(true)
      setError('')
      void loadServiceRequestPage(user, { service, from, to, skip: nextSkip, status })
        .then((page) => {
          if (ticket !== generation.current) return
          setRows((current) => (replace ? page.rows : [...current, ...page.rows]))
          setStatuses(page.statuses)
          setSkip(page.nextSkip)
          setHasMore(page.hasMore)
          if (replace) setSelectedId(page.rows[0]?.id || '')
        })
        .catch((err: unknown) => {
          if (ticket !== generation.current) return
          if (replace) setRows([])
          setHasMore(false)
          setError(err instanceof Error ? err.message : 'Не удалось прочитать заявки')
        })
        .finally(() => {
          if (ticket !== generation.current) return
          loadingRef.current = false
          setLoading(false)
        })
    },
    [user, service, from, to, status]
  )

  useEffect(() => {
    setRows([])
    setSkip(0)
    setHasMore(false)
    setSelectedId('')
    fetchPage(0, true)
  }, [fetchPage, reload])

  const table = useDocflowTable(rows, {
    text: searchText,
    value: sortValue,
    initialSort: { key: 'date', dir: 'desc' }
  })
  const visible = table.rows
  const selected = useMemo(() => rows.find((row) => row.id === selectedId) || null, [rows, selectedId])

  const onScroll = (): void => {
    const node = scrollRef.current
    if (!node || !hasMore || loadingRef.current) return
    if (node.scrollTop + node.clientHeight >= node.scrollHeight - 80) fetchPage(skip, false)
  }

  const query = table.query.trim()

  useEffect(() => {
    if (!hasMore || loading || error) return
    if (!visible.length) {
      if (query) fetchPage(skip, false)
      return
    }
    const node = scrollRef.current
    if (!node || node.scrollHeight <= node.clientHeight + 8) fetchPage(skip, false)
  }, [visible.length, hasMore, loading, error, skip, fetchPage, query])

  return (
    <div className="docflow-requests">
      <div className="docflow-kind" role="tablist" aria-label="Служба">
        {SERVICE_REQUESTS.map((item) => {
          const Icon = ICONS[item.id]
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={service === item.id}
              className={`docflow-kind-btn${service === item.id ? ' is-active' : ''}`}
              onClick={() => setService(item.id)}
            >
              <Icon size={18} aria-hidden />
              <span>
                <strong>{item.hint}</strong>
              </span>
            </button>
          )
        })}
      </div>
      <div className="docflow-table-card wp-card">
          <div className="docflow-request-head">
            <h2>{active.title}</h2>
            <div className="docflow-request-actions">
              {onCreate ? (
                <button
                  type="button"
                  className="docflow-edit-btn is-primary docflow-create-btn"
                  onClick={() => onCreate(active.kind)}
                >
                  <Plus size={14} aria-hidden /> {active.create}
                </button>
              ) : null}
              {selected ? (
                <DocflowOpenFormBar
                  refKey={selected.id}
                  hint="двойной щелчок по строке"
                  onOpen={onOpenDocument && (() => onOpenDocument(selected.formKind, selected.id))}
                />
              ) : null}
            </div>
          </div>
          <div className="docflow-order-filters">
            <DocflowSearch
              value={table.query}
              onChange={table.setQuery}
              placeholder="Номер, вид, текст, автор, исполнитель…"
              found={visible.length}
              total={rows.length}
            />
            <label>
              Статус
              <select value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="">Все</option>
                {statuses.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {error ? <p className="docflow-status docflow-status-error">{error}</p> : null}
          {!error && !visible.length ? (
            <p className="docflow-status">
              {hasMore || loading
                ? rows.length
                  ? 'Ищем заявку в журнале…'
                  : 'Загружаем из 1С…'
                : rows.length
                  ? 'Под этот поиск заявок нет. Расширьте период сверху.'
                  : 'За выбранные даты заявок нет. Расширьте период сверху.'}
            </p>
          ) : null}
          <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
            {visible.length ? (
              <table className="docflow-table">
                <thead>
                  <tr>
                    {COLUMNS[service].map((column) => (
                      <SortTh
                        key={column.key}
                        label={column.label}
                        sortKey={column.key}
                        sort={table.sort}
                        onSort={table.toggleSort}
                      />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <tr
                      key={row.id}
                      className={row.id === selectedId ? 'is-selected' : ''}
                      onClick={() => setSelectedId(row.id)}
                      onDoubleClick={() => onOpenDocument?.(row.formKind, row.id)}
                    >
                      {COLUMNS[service].map((column) => (
                        <td key={column.key} className={cellClass(column.key)} title={column.title?.(row) || undefined}>
                          {column.key === 'confirmed' ? (
                            <input type="checkbox" checked={row.confirmed} readOnly aria-label={column.label} />
                          ) : column.key === 'status' ? (
                            <span className={`docflow-req-status ${statusTone(row.statusCode)}`}>{column.value(row)}</span>
                          ) : (
                            column.value(row)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
      </div>
    </div>
  )
}
