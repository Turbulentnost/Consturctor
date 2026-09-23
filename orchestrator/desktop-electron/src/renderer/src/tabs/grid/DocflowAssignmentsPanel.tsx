import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Circle,
  ClipboardList,
  Crown,
  Flag,
  Paperclip,
  Search,
  UserCheck,
  Users
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import {
  loadAssignmentCard,
  loadAssignmentPage,
  type AssignmentCard,
  type AssignmentRow,
  type AssignmentStatus
} from '../../workplace/fetchDocflowAssignments'

const FALLBACK_STATUSES: AssignmentStatus[] = [
  { code: 'Создано', label: 'Создано' },
  { code: 'ВРаботе', label: 'В работе' },
  { code: 'НаПроверке', label: 'На проверке' },
  { code: 'Принято', label: 'Принято' },
  { code: 'Отменено', label: 'Отменено' }
]
const PRIORITY_ORDER = ['Критический', 'Высокий', 'Средний', 'Низкий']

function cell(value: string): string {
  return value.trim() || '—'
}

function day(value: string): string {
  if (!value) return '—'
  return formatCorrespondenceDate(value).replace(/ 00:00$/, '')
}

function namesText(names: string[]): string {
  if (!names.length) return '—'
  return names.length > 2 ? `${names.slice(0, 2).join(', ')} и ещё ${names.length - 2}` : names.join(', ')
}

function optionsOf(rows: AssignmentRow[], pick: (row: AssignmentRow) => string[]): string[] {
  const names = new Set(rows.flatMap(pick).map((value) => value.trim()).filter(Boolean))
  return [...names].sort((left, right) => left.localeCompare(right, 'ru'))
}

function statusTone(row: Pick<AssignmentRow, 'statusCode' | 'open' | 'overdue'>): string {
  if (row.statusCode === 'Отменено') return 'is-muted'
  if (!row.open) return 'is-ok'
  if (row.overdue) return 'is-bad'
  return 'is-wait'
}

function StatusPill({ row }: { row: Pick<AssignmentRow, 'status' | 'statusCode' | 'open' | 'overdue'> }): React.JSX.Element {
  return (
    <span className={`docflow-pill ${statusTone(row)}`}>
      {row.open ? row.overdue ? <AlertTriangle size={12} aria-hidden /> : <Circle size={12} aria-hidden /> : <CheckCircle2 size={12} aria-hidden />}
      {row.status || '—'}
      {row.open && row.overdue ? ' · просрочено' : ''}
    </span>
  )
}

function PriorityTag({ value }: { value: string }): React.JSX.Element | null {
  if (!value) return null
  const tone = value === 'Критический' ? 'is-bad' : value === 'Высокий' ? 'is-wait' : 'is-muted'
  return (
    <span className={`docflow-pill ${tone}`}>
      <Flag size={11} aria-hidden />
      {value}
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

function AssignmentCardView({ card }: { card: AssignmentCard }): React.JSX.Element {
  const { assignment: row, tasks, files, progress } = card
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>{formatCorrespondenceDate(row.date)}</p>
        </div>
        <StatusPill row={row} />
      </header>
      {row.topic ? <p className="docflow-side-subject">{row.topic}</p> : null}
      <div className="docflow-side-scroll">
        <section className="docflow-card-block">
          <h4>Основное</h4>
          <dl className="docflow-detail-list">
            <Fact label="Руководитель" value={row.head} />
            <Fact label="Организация" value={row.organization} />
            <Fact label="Кто доложит" value={row.reporter} />
            <Fact label="Секретарь РК" value={row.secretary} />
            <Fact label="Срок устранения" value={row.due ? day(row.due) : ''} />
            <Fact label="Еженедельный отчёт" value={row.weeklyReport ? day(row.weeklyReport) : ''} />
            <Fact label="Итоговый доклад" value={row.finalReport ? day(row.finalReport) : ''} />
            <Fact label="Проведён" value={row.posted ? 'Да' : 'Нет'} />
          </dl>
        </section>
        {row.basis ? (
          <section className="docflow-card-block">
            <h4>Основание</h4>
            <p className="docflow-card-text">{row.basis}</p>
          </section>
        ) : null}
        <section className="docflow-card-block">
          <h4>
            <ClipboardList size={14} aria-hidden /> Мероприятия
            <span>
              {progress.lines}
              {progress.overdueLines ? ` · просрочено ${progress.overdueLines}` : ''}
            </span>
          </h4>
          {row.lines.length ? (
            <ol className="docflow-lines">
              {row.lines.map((line) => (
                <li key={line.n} className={line.overdue ? 'is-overdue' : ''}>
                  <p>{line.text || '—'}</p>
                  <div>
                    <span>
                      <UserCheck size={12} aria-hidden /> {cell(line.executor)}
                    </span>
                    <span className={line.overdue ? 'is-overdue' : ''}>срок {day(line.due)}</span>
                    <PriorityTag value={line.priority} />
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="docflow-muted">В поручении нет мероприятий.</p>
          )}
        </section>
        <section className="docflow-card-block">
          <h4>
            <Users size={14} aria-hidden /> Задачи исполнителей
            <span>{progress.tasks ? `выполнено ${progress.tasksDone} из ${progress.tasks}` : 'задач нет'}</span>
          </h4>
          {tasks.length ? (
            <ul className="docflow-route">
              {tasks.map((task) => (
                <li key={task.id} className={task.executed ? 'is-done' : ''}>
                  {task.executed ? <CheckCircle2 size={14} aria-hidden /> : <Circle size={14} aria-hidden />}
                  <div>
                    <strong>{cell(task.performer)}</strong>
                    <span>
                      {[task.due ? `срок ${day(task.due)}` : '', task.doneAt ? `выполнено ${day(task.doneAt)}` : '']
                        .filter(Boolean)
                        .join(' · ') || task.title}
                    </span>
                    {task.result ? <em>{task.result}</em> : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="docflow-muted">По поручению в 1С не созданы задачи исполнителям.</p>
          )}
        </section>
        {files.length ? (
          <section className="docflow-card-block">
            <h4>
              <Paperclip size={14} aria-hidden /> Файлы
              <span>{files.length}</span>
            </h4>
            <ul className="docflow-files">
              {files.map((file) => (
                <li key={file.id}>
                  <strong>{file.name}{file.extension ? `.${file.extension}` : ''}</strong>
                  <span>{file.created ? day(file.created) : ''}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  )
}

export function DocflowAssignmentsPanel({
  user,
  from,
  to
}: {
  user: UserProfile
  from: string
  to: string
}): React.JSX.Element {
  const [rows, setRows] = useState<AssignmentRow[]>([])
  const [statuses, setStatuses] = useState<AssignmentStatus[]>(FALLBACK_STATUSES)
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [status, setStatus] = useState('')
  const [head, setHead] = useState('')
  const [executor, setExecutor] = useState('')
  const [organization, setOrganization] = useState('')
  const [reporter, setReporter] = useState('')
  const [priority, setPriority] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [card, setCard] = useState<AssignmentCard | null>(null)
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
        const page = await loadAssignmentPage(user, { from, to, skip, status })
        if (scopeRef.current !== scope) return
        setRows((prev) => {
          const base = reset ? [] : prev
          const seen = new Set(base.map((row) => row.id))
          return [...base, ...page.rows.filter((row) => !seen.has(row.id))]
        })
        if (page.statuses.length) setStatuses(page.statuses)
        setNextSkip(page.nextSkip)
        setHasMore(page.hasMore)
      } catch (err) {
        if (scopeRef.current === scope) setError(err instanceof Error ? err.message : 'Не удалось загрузить поручения')
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
    setNextSkip(0)
    setHasMore(false)
    setSelectedId('')
    setCard(null)
    void fetchPage(0, true)
  }, [fetchPage, from, to, status, reload])

  const heads = useMemo(() => optionsOf(rows, (row) => [row.head]), [rows])
  const executors = useMemo(() => optionsOf(rows, (row) => row.executors), [rows])
  const organizations = useMemo(() => optionsOf(rows, (row) => [row.organization]), [rows])
  const reporters = useMemo(() => optionsOf(rows, (row) => [row.reporter]), [rows])
  const priorities = useMemo(() => {
    const found = new Set(rows.flatMap((row) => row.lines.map((line) => line.priority)).filter(Boolean))
    return PRIORITY_ORDER.filter((item) => found.has(item))
  }, [rows])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (head && row.head !== head) return false
      if (executor && !row.executors.includes(executor)) return false
      if (organization && row.organization !== organization) return false
      if (reporter && row.reporter !== reporter) return false
      if (priority && !row.lines.some((line) => line.priority === priority)) return false
      if (overdueOnly && !(row.open && row.overdue)) return false
      if (needle) {
        const blob = [row.number, row.topic, row.basis, ...row.lines.map((line) => line.text)].join(' ').toLowerCase()
        if (!blob.includes(needle)) return false
      }
      return true
    })
  }, [rows, head, executor, organization, reporter, priority, overdueOnly, query])

  const filtered = Boolean(head || executor || organization || reporter || priority || overdueOnly || query.trim())

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

  const openCard = (row: AssignmentRow): void => {
    cardForRef.current = row.id
    setSelectedId(row.id)
    setCard(null)
    setCardError('')
    setCardLoading(true)
    void loadAssignmentCard(user, row.id)
      .then((result) => {
        if (cardForRef.current === row.id) setCard(result)
      })
      .catch((err: unknown) => {
        if (cardForRef.current === row.id) setCardError(err instanceof Error ? err.message : 'Не удалось открыть поручение')
      })
      .finally(() => {
        if (cardForRef.current === row.id) setCardLoading(false)
      })
  }

  const resetFilters = (): void => {
    setHead('')
    setExecutor('')
    setOrganization('')
    setReporter('')
    setPriority('')
    setOverdueOnly(false)
    setQuery('')
  }

  const selected = rows.find((row) => row.id === selectedId) || null
  const asOptions = (names: string[]): { value: string; label: string }[] => names.map((name) => ({ value: name, label: name }))

  return (
    <div className="docflow-split docflow-split-orders">
      <div className="docflow-table-card wp-card">
        <div className="docflow-order-filters">
          <label className="docflow-search">
            <Search size={14} aria-hidden />
            <input
              type="search"
              value={query}
              placeholder="Номер, о чём, мероприятие…"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <FilterSelect
            icon={<Circle size={13} aria-hidden />}
            label="Статус"
            value={status}
            options={statuses.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setStatus}
          />
          <FilterSelect icon={<Crown size={13} aria-hidden />} label="Руководитель" value={head} options={asOptions(heads)} onChange={setHead} />
          <FilterSelect icon={<UserCheck size={13} aria-hidden />} label="Исполнитель" value={executor} options={asOptions(executors)} onChange={setExecutor} />
          <FilterSelect icon={<Users size={13} aria-hidden />} label="Кто доложит" value={reporter} options={asOptions(reporters)} onChange={setReporter} />
          <FilterSelect icon={<Building2 size={13} aria-hidden />} label="Организация" value={organization} options={asOptions(organizations)} onChange={setOrganization} />
          <FilterSelect icon={<Flag size={13} aria-hidden />} label="Приоритет" value={priority} options={asOptions(priorities)} onChange={setPriority} />
          <label className="docflow-check">
            <input type="checkbox" checked={overdueOnly} onChange={(event) => setOverdueOnly(event.target.checked)} />
            <AlertTriangle size={13} aria-hidden />
            Только просроченные
          </label>
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
            {rows.length ? 'Под выбранные фильтры поручений нет' : 'Нет поручений за выбранный период'}
          </p>
        ) : null}
        <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
          {visible.length ? (
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Номер</th>
                  <th>О чём</th>
                  <th>Руководитель</th>
                  <th>Исполнители</th>
                  <th>Срок</th>
                  <th>Приоритет</th>
                  <th>Статус</th>
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
                    <td>{day(row.date)}</td>
                    <td>{cell(row.number)}</td>
                    <td title={row.topic}>{cell(row.topic)}</td>
                    <td>{cell(row.head)}</td>
                    <td title={row.executors.join(', ')}>{namesText(row.executors)}</td>
                    <td className={row.open && row.overdue ? 'docflow-cell-overdue' : undefined}>{day(row.due)}</td>
                    <td>{row.priority ? <PriorityTag value={row.priority} /> : '—'}</td>
                    <td>
                      <StatusPill row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {loading ? <p className="docflow-status">{rows.length ? 'Загружаем ещё…' : 'Загружаем поручения из 1С…'}</p> : null}
          {!loading && !hasMore && rows.length ? <p className="docflow-status docflow-end">Показаны все поручения за период</p> : null}
        </div>
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка поручения">
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
          <AssignmentCardView card={card} />
        ) : null}
      </aside>
    </div>
  )
}
