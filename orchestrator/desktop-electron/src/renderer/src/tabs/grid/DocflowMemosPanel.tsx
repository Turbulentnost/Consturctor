import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, Circle, Clock3, Lock, User, Users } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import { loadMemoCard, loadMemoPage, type MemoCard, type MemoRow } from '../../workplace/fetchDocflowMemos'

function cell(value: string): string {
  return value.trim() || '—'
}

function dateOrDash(value: string): string {
  return value ? formatCorrespondenceDate(value) : '—'
}

function assigneeText(names: string[]): string {
  if (!names.length) return '—'
  return names.length > 2 ? `${names.slice(0, 2).join(', ')} и ещё ${names.length - 2}` : names.join(', ')
}

function StatusPill({ approved, status }: { approved: boolean; status: string }): React.JSX.Element {
  return (
    <span className={`docflow-pill${approved ? ' is-ok' : ' is-wait'}`}>
      {approved ? <CheckCircle2 size={12} aria-hidden /> : <Clock3 size={12} aria-hidden />}
      {status || (approved ? 'Согласована' : 'Не согласована')}
    </span>
  )
}

function MemoCardView({ card }: { card: MemoCard }): React.JSX.Element {
  const { memo, tasks, route } = card
  const hidden = new Set(['Number', 'Date', 'Статус', 'ТемаСлужебнойЗаписки', 'ТекстСлужебнойЗаписки'])
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>№ {cell(memo.number)}</h3>
          <p>{dateOrDash(memo.date)}</p>
        </div>
        <StatusPill approved={memo.approved} status={memo.status} />
      </header>
      {memo.subject ? <p className="docflow-side-subject">{memo.subject}</p> : null}
      <div className="docflow-side-scroll">
        <section className="docflow-card-block">
          <h4>
            <Users size={14} aria-hidden /> Маршрут
            <span>
              {route.total ? `исполнено ${route.executed} из ${route.total}` : 'задач нет'}
              {route.due ? ` · срок ${dateOrDash(route.due)}` : ''}
            </span>
          </h4>
          {tasks.length ? (
            <ul className="docflow-route">
              {tasks.map((task, index) => (
                <li key={`${task.id}-${index}`} className={task.executed ? 'is-done' : ''}>
                  {task.executed ? <CheckCircle2 size={14} aria-hidden /> : <Circle size={14} aria-hidden />}
                  <div>
                    <strong>{cell(task.performer || 'Роль / группа исполнителей')}</strong>
                    <span>
                      {[task.step, task.due ? `срок ${dateOrDash(task.due)}` : '', task.doneAt ? `выполнено ${dateOrDash(task.doneAt)}` : '']
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                    {task.description ? <em>{task.description}</em> : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="docflow-muted">По этой записке в 1С нет открытых задач согласования.</p>
          )}
          {!route.historyComplete && tasks.length ? (
            <p className="docflow-muted">Показаны открытые задачи. Историю исполненных 1С отдаёт по паролю сессии.</p>
          ) : null}
        </section>
        {memo.text ? (
          <section className="docflow-card-block">
            <h4>Текст</h4>
            <p className="docflow-card-text">{memo.text}</p>
          </section>
        ) : null}
        <section className="docflow-card-block">
          <h4>Реквизиты</h4>
          <dl className="docflow-detail-list">
            {memo.fields
              .filter((field) => !hidden.has(field.key))
              .map((field) => (
                <div key={field.key}>
                  <dt>{field.label}</dt>
                  <dd>
                    {/^(Date|Дата|Срок)/.test(field.key) ? formatCorrespondenceDate(field.value) : field.value}
                  </dd>
                </div>
              ))}
          </dl>
        </section>
      </div>
    </>
  )
}

export function DocflowMemosPanel({
  user,
  from,
  to
}: {
  user: UserProfile
  from: string
  to: string
}): React.JSX.Element {
  const [rows, setRows] = useState<MemoRow[]>([])
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [hiddenSecret, setHiddenSecret] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [assignee, setAssignee] = useState('')
  const [author, setAuthor] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [card, setCard] = useState<MemoCard | null>(null)
  const [cardLoading, setCardLoading] = useState(false)
  const [cardError, setCardError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)
  const periodRef = useRef('')
  const cardForRef = useRef('')

  const fetchPage = useCallback(
    async (skip: number, reset: boolean): Promise<void> => {
      if (loadingRef.current) return
      loadingRef.current = true
      const period = `${from}:${to}`
      setLoading(true)
      setError('')
      try {
        const page = await loadMemoPage(user, { from, to, skip })
        if (periodRef.current !== period) return
        setRows((prev) => {
          const base = reset ? [] : prev
          const seen = new Set(base.map((row) => row.id))
          return [...base, ...page.rows.filter((row) => !seen.has(row.id))]
        })
        setHiddenSecret((prev) => (reset ? page.hiddenSecret : prev + page.hiddenSecret))
        setNextSkip(page.nextSkip)
        setHasMore(page.hasMore)
      } catch (err) {
        if (periodRef.current === period) setError(err instanceof Error ? err.message : 'Не удалось загрузить служебные записки')
      } finally {
        loadingRef.current = false
        setLoading(false)
      }
    },
    [user, from, to]
  )

  useEffect(() => {
    periodRef.current = `${from}:${to}`
    loadingRef.current = false
    setRows([])
    setNextSkip(0)
    setHasMore(false)
    setSelectedId('')
    setCard(null)
    void fetchPage(0, true)
  }, [fetchPage, from, to, reload])

  const assignees = useMemo(() => {
    const names = new Set(rows.flatMap((row) => row.assignees))
    return [...names].sort((left, right) => left.localeCompare(right, 'ru'))
  }, [rows])
  const authors = useMemo(() => {
    const names = new Set(rows.map((row) => row.fromWhom).filter(Boolean))
    return [...names].sort((left, right) => left.localeCompare(right, 'ru'))
  }, [rows])
  const visible = useMemo(
    () =>
      rows.filter(
        (row) => (!assignee || row.assignees.includes(assignee)) && (!author || row.fromWhom === author)
      ),
    [rows, assignee, author]
  )

  const onScroll = (): void => {
    const node = scrollRef.current
    if (!node || !hasMore || loadingRef.current) return
    if (node.scrollTop + node.clientHeight >= node.scrollHeight - 80) void fetchPage(nextSkip, false)
  }

  useEffect(() => {
    // Фильтр оставил мало строк и скролла нет — догружаем, пока есть что грузить.
    const node = scrollRef.current
    if (!node || !hasMore || loading || error) return
    if (node.scrollHeight <= node.clientHeight + 8) void fetchPage(nextSkip, false)
  }, [visible.length, hasMore, loading, error, nextSkip, fetchPage])

  const openCard = (row: MemoRow): void => {
    cardForRef.current = row.id
    setSelectedId(row.id)
    setCard(null)
    setCardError('')
    setCardLoading(true)
    void loadMemoCard(user, row.id)
      .then((result) => {
        if (cardForRef.current === row.id) setCard(result)
      })
      .catch((err: unknown) => {
        if (cardForRef.current === row.id) {
          setCardError(err instanceof Error ? err.message : 'Не удалось открыть служебную записку')
        }
      })
      .finally(() => {
        if (cardForRef.current === row.id) setCardLoading(false)
      })
  }

  const selected = rows.find((row) => row.id === selectedId) || null

  return (
    <div className="docflow-split">
      <div className="docflow-table-card wp-card">
        <div className="docflow-order-filters">
          <label>
            <Users size={14} aria-hidden />
            Кому
            <select value={assignee} onChange={(event) => setAssignee(event.target.value)}>
              <option value="">Все</option>
              {assignees.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <User size={14} aria-hidden />
            От кого
            <select value={author} onChange={(event) => setAuthor(event.target.value)}>
              <option value="">Все</option>
              {authors.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <span>
            {`${visible.length} из ${rows.length}${hasMore ? '+' : ''}`}
            {hiddenSecret ? (
              <em className="docflow-secret-note" title="Конфиденциальные служебные записки не показываются">
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
          <p className="docflow-status">Нет служебных записок за выбранный период</p>
        ) : null}
        <div className="docflow-table-scroll" ref={scrollRef} onScroll={onScroll}>
          {visible.length ? (
            <table className="spec-v04-table docflow-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Номер</th>
                  <th>Тема</th>
                  <th>Кому</th>
                  <th>От кого</th>
                  <th>Срок</th>
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
                    <td>{dateOrDash(row.date)}</td>
                    <td>{cell(row.number)}</td>
                    <td title={row.subject}>{cell(row.subject)}</td>
                    <td title={row.assignees.join(', ')}>{assigneeText(row.assignees)}</td>
                    <td>{cell(row.fromWhom)}</td>
                    <td>{dateOrDash(row.due)}</td>
                    <td>
                      <StatusPill approved={row.approved} status={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {loading ? <p className="docflow-status">{rows.length ? 'Загружаем ещё…' : 'Загружаем служебные записки из 1С…'}</p> : null}
          {!loading && !hasMore && rows.length ? <p className="docflow-status docflow-end">Показаны все записки за период</p> : null}
        </div>
      </div>
      <aside className="docflow-side wp-card" aria-label="Карточка служебной записки">
        {!selected ? (
          <p className="docflow-status">Выберите служебную записку, чтобы увидеть карточку</p>
        ) : cardLoading ? (
          <p className="docflow-status">Загружаем служебную записку № {selected.number} из 1С…</p>
        ) : cardError ? (
          <p className="docflow-status docflow-status-error">
            {cardError}
            <button type="button" className="docflow-retry" onClick={() => openCard(selected)}>
              Повторить
            </button>
          </p>
        ) : card ? (
          <MemoCardView card={card} />
        ) : null}
      </aside>
    </div>
  )
}
