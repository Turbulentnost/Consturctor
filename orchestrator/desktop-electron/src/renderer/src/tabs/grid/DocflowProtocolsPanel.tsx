import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart3,
  Building2,
  CheckCircle2,
  Circle,
  ClipboardList,
  Crown,
  DoorOpen,
  Gavel,
  Layers,
  ListChecks,
  Lock,
  MessagesSquare,
  PenLine,
  Search,
  Tag,
  Users,
  XCircle
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import {
  loadProtocolCard,
  loadProtocolPage,
  type ProtocolCard,
  type ProtocolOption,
  type ProtocolPlanRow,
  type ProtocolRow
} from '../../workplace/fetchDocflowProtocols'

const FALLBACK_STATUSES: ProtocolOption[] = [
  { code: 'Подготовлен', label: 'Подготовлен' },
  { code: 'НаИсполнении', label: 'На исполнении' },
  { code: 'Закрыт', label: 'Закрыт' }
]
const FALLBACK_KINDS: ProtocolOption[] = [
  { code: 'Отчетное', label: 'Отчётное' },
  { code: 'Внеплановое', label: 'Внеплановое' },
  { code: 'Селекторное', label: 'Селекторное' }
]

function cell(value: string): string {
  return value.trim() || '—'
}

function day(value: string): string {
  if (!value) return '—'
  return formatCorrespondenceDate(value).replace(/ 00:00$/, '')
}

function onlyDay(value: string): string {
  return value ? formatCorrespondenceDate(value).slice(0, 10) : '—'
}

function optionsOf(rows: ProtocolRow[], pick: (row: ProtocolRow) => string[]): { value: string; label: string }[] {
  const names = new Set(rows.flatMap(pick).map((value) => value.trim()).filter(Boolean))
  return [...names].sort((left, right) => left.localeCompare(right, 'ru')).map((name) => ({ value: name, label: name }))
}

function StatusPill({ row }: { row: Pick<ProtocolRow, 'status' | 'statusCode'> }): React.JSX.Element {
  const tone = row.statusCode === 'Закрыт' ? 'is-ok' : row.statusCode === 'НаИсполнении' ? 'is-wait' : 'is-muted'
  return (
    <span className={`docflow-pill ${tone}`}>
      {row.statusCode === 'Закрыт' ? <CheckCircle2 size={12} aria-hidden /> : <Circle size={12} aria-hidden />}
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

function PlanBlock({ title, rows }: { title: string; rows: ProtocolPlanRow[] }): React.JSX.Element | null {
  if (!rows.length) return null
  return (
    <section className="docflow-card-block">
      <h4>
        <BarChart3 size={14} aria-hidden /> {title}
        <span>{rows.length}</span>
      </h4>
      <ol className="docflow-lines">
        {rows.map((row) => (
          <li key={row.n}>
            <p>{row.text || '—'}</p>
            <div>
              {row.responsible ? <span>{row.responsible}</span> : null}
              {row.plan || row.fact ? (
                <span>
                  план {row.plan || '—'} · факт {row.fact || '—'}
                  {row.unit ? ` ${row.unit}` : ''}
                  {row.deviation && row.deviation !== '0' ? ` · откл. ${row.deviation}` : ''}
                </span>
              ) : null}
              {row.done ? (
                <span className="docflow-pill is-ok">
                  <CheckCircle2 size={11} aria-hidden /> выполнено
                </span>
              ) : null}
            </div>
            {row.comment ? <p className="docflow-muted">{row.comment}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  )
}

function ProtocolCardView({ card }: { card: ProtocolCard }): React.JSX.Element {
  const { protocol: row, agenda, decisions, tasks, periodDone, periodPlan, planFact, stats } = card
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(row.number)}</h3>
          <p>
            {onlyDay(row.date)}
            {row.time ? ` · ${row.time}` : ''}
          </p>
        </div>
        <StatusPill row={row} />
      </header>
      {row.topic ? <p className="docflow-side-subject">{row.topic}</p> : null}
      <div className="docflow-side-scroll">
        <section className="docflow-card-block">
          <h4>Основное</h4>
          <dl className="docflow-detail-list">
            <Fact label="Вид совещания" value={row.kind} />
            <Fact label="Руководитель" value={row.head} />
            <Fact label="Подразделение" value={row.department} />
            <Fact label="Место" value={row.room} />
            <Fact label="Подготовил" value={row.preparedBy} />
            <Fact label="Ответственный" value={row.responsible} />
            <Fact label="Проект" value={row.project} />
            <Fact label="Гриф" value={row.access} />
            <Fact label="Следующее совещание" value={row.nextMeeting ? onlyDay(row.nextMeeting) : ''} />
            <Fact label="Задачи разосланы" value={row.tasksSent ? 'Да' : 'Нет'} />
            <Fact label="Комментарий" value={row.comment} />
          </dl>
        </section>
        {row.participants.length ? (
          <section className="docflow-card-block">
            <h4>
              <Users size={14} aria-hidden /> Участники
              <span>{row.participants.length}</span>
            </h4>
            <div className="docflow-chips">
              {row.participants.map((name) => (
                <span key={name}>{name}</span>
              ))}
            </div>
          </section>
        ) : null}
        {agenda.length ? (
          <section className="docflow-card-block">
            <h4>
              <MessagesSquare size={14} aria-hidden /> Повестка
              <span>{agenda.length}</span>
            </h4>
            <ol className="docflow-lines">
              {agenda.map((item) => (
                <li key={item.n}>
                  <p>{item.text || '—'}</p>
                  <div>
                    {item.responsible ? <span>{item.responsible}</span> : null}
                    {item.attachments ? <span>приложения: {item.attachments}</span> : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        <section className="docflow-card-block">
          <h4>
            <Gavel size={14} aria-hidden /> Решения
            <span>
              {stats.decisions
                ? `исполнено ${stats.decisionsDone} из ${stats.decisions}${stats.decisionsCancelled ? ` · отменено ${stats.decisionsCancelled}` : ''}`
                : 'нет'}
            </span>
          </h4>
          {decisions.length ? (
            <ul className="docflow-route">
              {decisions.map((item) => (
                <li key={item.n} className={item.doneAt && !item.cancelled ? 'is-done' : item.cancelled ? 'is-cancelled' : ''}>
                  {item.cancelled ? (
                    <XCircle size={14} aria-hidden />
                  ) : item.doneAt ? (
                    <CheckCircle2 size={14} aria-hidden />
                  ) : (
                    <Circle size={14} aria-hidden />
                  )}
                  <div>
                    <strong className="docflow-route-text">{item.text || '—'}</strong>
                    <span>
                      {[
                        item.start ? `с ${onlyDay(item.start)}` : '',
                        item.finish ? `до ${onlyDay(item.finish)}` : '',
                        item.doneAt ? `исполнено ${onlyDay(item.doneAt)}` : '',
                        item.sent ? 'отправлено' : ''
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                    {item.result ? <em>Результат: {item.result}</em> : null}
                    {item.cancelled ? (
                      <em>
                        Отменено{item.cancelledBy ? ` (${item.cancelledBy})` : ''}
                        {item.cancelReason ? `: ${item.cancelReason}` : ''}
                      </em>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="docflow-muted">В протоколе нет решений.</p>
          )}
        </section>
        {tasks.length ? (
          <section className="docflow-card-block">
            <h4>
              <ListChecks size={14} aria-hidden /> Задачи протокола
              <span>{`выполнено ${stats.tasksDone} из ${stats.tasks}`}</span>
            </h4>
            <ul className="docflow-route">
              {tasks.map((task, index) => (
                <li key={`${task.n}-${index}`} className={task.doneAt ? 'is-done' : ''}>
                  {task.doneAt ? <CheckCircle2 size={14} aria-hidden /> : <Circle size={14} aria-hidden />}
                  <div>
                    <strong className="docflow-route-text">
                      {task.n ? `${task.n}. ` : ''}
                      {task.text || '—'}
                    </strong>
                    <span>
                      {[
                        task.responsible,
                        task.setAt ? `поставлена ${onlyDay(task.setAt)}` : '',
                        task.doneAt ? `исполнена ${onlyDay(task.doneAt)}` : '',
                        task.priority,
                        task.permanent ? 'постоянная' : ''
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                    {task.note ? <em>{task.note}</em> : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <PlanBlock title="Выполнение задач за период" rows={periodDone} />
        <PlanBlock title="План задач на период" rows={periodPlan} />
        <PlanBlock title="План-факт" rows={planFact} />
      </div>
    </>
  )
}

export function DocflowProtocolsPanel({
  user,
  from,
  to
}: {
  user: UserProfile
  from: string
  to: string
}): React.JSX.Element {
  const [rows, setRows] = useState<ProtocolRow[]>([])
  const [statuses, setStatuses] = useState<ProtocolOption[]>(FALLBACK_STATUSES)
  const [kinds, setKinds] = useState<ProtocolOption[]>(FALLBACK_KINDS)
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [hiddenSecret, setHiddenSecret] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
  const [topic, setTopic] = useState('')
  const [head, setHead] = useState('')
  const [department, setDepartment] = useState('')
  const [room, setRoom] = useState('')
  const [preparedBy, setPreparedBy] = useState('')
  const [project, setProject] = useState('')
  const [participant, setParticipant] = useState('')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [card, setCard] = useState<ProtocolCard | null>(null)
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
      const scope = `${from}:${to}:${status}:${kind}`
      setLoading(true)
      setError('')
      try {
        const page = await loadProtocolPage(user, { from, to, skip, status, kind })
        if (scopeRef.current !== scope) return
        setRows((prev) => {
          const base = reset ? [] : prev
          const seen = new Set(base.map((row) => row.id))
          return [...base, ...page.rows.filter((row) => !seen.has(row.id))]
        })
        setHiddenSecret((prev) => (reset ? page.hiddenSecret : prev + page.hiddenSecret))
        if (page.statuses.length) setStatuses(page.statuses)
        if (page.kinds.length) setKinds(page.kinds)
        setNextSkip(page.nextSkip)
        setHasMore(page.hasMore)
      } catch (err) {
        if (scopeRef.current === scope) setError(err instanceof Error ? err.message : 'Не удалось загрузить протоколы')
      } finally {
        if (scopeRef.current === scope) {
          loadingRef.current = false
          setLoading(false)
        }
      }
    },
    [user, from, to, status, kind]
  )

  useEffect(() => {
    scopeRef.current = `${from}:${to}:${status}:${kind}`
    setRows([])
    setNextSkip(0)
    setHasMore(false)
    setSelectedId('')
    setCard(null)
    void fetchPage(0, true)
  }, [fetchPage, from, to, status, kind, reload])

  const topics = useMemo(() => optionsOf(rows, (row) => [row.topic]), [rows])
  const heads = useMemo(() => optionsOf(rows, (row) => [row.head]), [rows])
  const departments = useMemo(() => optionsOf(rows, (row) => [row.department]), [rows])
  const rooms = useMemo(() => optionsOf(rows, (row) => [row.room]), [rows])
  const preparers = useMemo(() => optionsOf(rows, (row) => [row.preparedBy]), [rows])
  const projects = useMemo(() => optionsOf(rows, (row) => [row.project]), [rows])
  const participants = useMemo(() => optionsOf(rows, (row) => row.participants), [rows])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (topic && row.topic !== topic) return false
      if (head && row.head !== head) return false
      if (department && row.department !== department) return false
      if (room && row.room !== room) return false
      if (preparedBy && row.preparedBy !== preparedBy) return false
      if (project && row.project !== project) return false
      if (participant && !row.participants.includes(participant)) return false
      if (needle) {
        const blob = [row.number, row.topic, row.comment, row.head, ...row.participants].join(' ').toLowerCase()
        if (!blob.includes(needle)) return false
      }
      return true
    })
  }, [rows, topic, head, department, room, preparedBy, project, participant, query])

  const filtered = Boolean(topic || head || department || room || preparedBy || project || participant || query.trim())

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

  const openCard = (row: ProtocolRow): void => {
    cardForRef.current = row.id
    setSelectedId(row.id)
    setCard(null)
    setCardError('')
    setCardLoading(true)
    void loadProtocolCard(user, row.id)
      .then((result) => {
        if (cardForRef.current === row.id) setCard(result)
      })
      .catch((err: unknown) => {
        if (cardForRef.current === row.id) setCardError(err instanceof Error ? err.message : 'Не удалось открыть протокол')
      })
      .finally(() => {
        if (cardForRef.current === row.id) setCardLoading(false)
      })
  }

  const resetFilters = (): void => {
    setTopic('')
    setHead('')
    setDepartment('')
    setRoom('')
    setPreparedBy('')
    setProject('')
    setParticipant('')
    setQuery('')
  }

  const selected = rows.find((row) => row.id === selectedId) || null

  return (
    <div className="docflow-split docflow-split-orders">
      <div className="docflow-table-card wp-card">
        <div className="docflow-order-filters">
          <label className="docflow-search">
            <Search size={14} aria-hidden />
            <input
              type="search"
              value={query}
              placeholder="Номер, тема, участник…"
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
          <FilterSelect
            icon={<Layers size={13} aria-hidden />}
            label="Вид"
            value={kind}
            options={kinds.map((item) => ({ value: item.code, label: item.label }))}
            onChange={setKind}
          />
          <FilterSelect icon={<Tag size={13} aria-hidden />} label="Тема" value={topic} options={topics} onChange={setTopic} />
          <FilterSelect icon={<Crown size={13} aria-hidden />} label="Руководитель" value={head} options={heads} onChange={setHead} />
          <FilterSelect icon={<Users size={13} aria-hidden />} label="Участник" value={participant} options={participants} onChange={setParticipant} />
          <FilterSelect icon={<Building2 size={13} aria-hidden />} label="Подразделение" value={department} options={departments} onChange={setDepartment} />
          <FilterSelect icon={<DoorOpen size={13} aria-hidden />} label="Место" value={room} options={rooms} onChange={setRoom} />
          <FilterSelect icon={<PenLine size={13} aria-hidden />} label="Подготовил" value={preparedBy} options={preparers} onChange={setPreparedBy} />
          {projects.length ? (
            <FilterSelect icon={<ClipboardList size={13} aria-hidden />} label="Проект" value={project} options={projects} onChange={setProject} />
          ) : null}
          {filtered ? (
            <button type="button" className="docflow-retry" onClick={resetFilters}>
              Сбросить
            </button>
          ) : null}
          <span>
            {`${visible.length} из ${rows.length}${hasMore ? '+' : ''}`}
            {hiddenSecret ? (
              <em className="docflow-secret-note" title="Конфиденциальные протоколы не показываются">
                <Lock size={12} aria-hidden /> скрыто {hiddenSecret}
              </em>
            ) : null}
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
            {rows.length ? 'Под выбранные фильтры протоколов нет' : 'Нет протоколов за выбранный период'}
          </p>
        ) : null}
        <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
          {visible.length ? (
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Время</th>
                  <th>Номер</th>
                  <th>Тема</th>
                  <th>Вид</th>
                  <th>Руководитель</th>
                  <th>Участники</th>
                  <th>Место</th>
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
                    <td>{onlyDay(row.date)}</td>
                    <td>{cell(row.time)}</td>
                    <td>{cell(row.number)}</td>
                    <td title={row.topic}>{cell(row.topic)}</td>
                    <td>{cell(row.kind)}</td>
                    <td>{cell(row.head)}</td>
                    <td title={row.participants.join(', ')}>{row.participants.length || '—'}</td>
                    <td title={row.room}>{cell(row.room)}</td>
                    <td>
                      <StatusPill row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {loading ? <p className="docflow-status">{rows.length ? 'Загружаем ещё…' : 'Загружаем протоколы из 1С…'}</p> : null}
          {!loading && !hasMore && rows.length ? <p className="docflow-status docflow-end">Показаны все протоколы за период</p> : null}
        </div>
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка протокола">
        {!selected ? (
          <p className="docflow-status">Выберите протокол, чтобы увидеть карточку</p>
        ) : cardLoading ? (
          <p className="docflow-status">Загружаем протокол № {selected.number} из 1С…</p>
        ) : cardError ? (
          <p className="docflow-status docflow-status-error">
            {cardError}
            <button type="button" className="docflow-retry" onClick={() => openCard(selected)}>
              Повторить
            </button>
          </p>
        ) : card ? (
          <ProtocolCardView card={card} />
        ) : null}
      </aside>
    </div>
  )
}
