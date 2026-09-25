import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { RefreshCw, Search, X } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { SpecPill } from '../../workplace/specV04Components'
import type { SpecTaskRow } from '../../workplace/specV04DemoData'
import { loadClosedOneCTasks } from '../../workplace/fetchClosedOneCTasks'
import { formatSurnameInitials } from '../../workplace/tileFilters'
import { DOCFLOW_KIND_LABEL, DOCFLOW_KIND_TONE, docflowTaskKind } from '../../workplace/docflowTaskKind'
import { rowMatchesWords } from './docflowTableTools'

function cell(value: string | undefined): string {
  return (value || '').trim() || '—'
}

/** Закрытые задачи 1С за период: отдельный запрос с include_done. */
export function ClosedOneCTasksModal({
  open,
  user,
  erpFio,
  from,
  to,
  onClose
}: {
  open: boolean
  user: UserProfile
  erpFio: string
  from: string
  to: string
  onClose: () => void
}): React.JSX.Element | null {
  const titleId = useId()
  const [rows, setRows] = useState<SpecTaskRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [reload, setReload] = useState(0)

  const load = useCallback(() => {
    let alive = true
    setLoading(true)
    setError('')
    void loadClosedOneCTasks(user, erpFio, { from, to })
      .then((result) => {
        if (!alive) return
        setRows(result.rows)
        setError(result.error)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setRows([])
        setError(err instanceof Error ? err.message : 'Не удалось загрузить закрытые задачи')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [user, erpFio, from, to])

  useEffect(() => {
    if (!open) return
    return load()
  }, [open, load, reload])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const visible = useMemo(() => {
    if (!query.trim()) return rows
    return rows.filter((row) =>
      rowMatchesWords(
        [row.title, row.source, row.process, row.author, row.performer, row.deadline, row.status]
          .filter(Boolean)
          .join(' '),
        query
      )
    )
  }, [rows, query])

  if (!open) return null

  return createPortal(
    <div className="modal-overlay closed-tasks-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card closed-tasks-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="closed-tasks-head">
          <div>
            <h4 className="modal-title" id={titleId}>
              Закрытые задачи 1С
            </h4>
            <p className="modal-note">
              Период {from} — {to}. Исполненные задачи документооборота, их нет в основной таблице.
            </p>
          </div>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            <X size={16} aria-hidden />
          </button>
        </header>

        <div className="closed-tasks-toolbar">
          <label className="docflow-search">
            <Search size={14} aria-hidden />
            <input
              type="search"
              value={query}
              placeholder="Задача, автор, исполнитель…"
              onChange={(event) => setQuery(event.target.value)}
            />
            {query.trim() ? (
              <span className="docflow-search-count">
                {visible.length} из {rows.length}
              </span>
            ) : null}
          </label>
          <span className="spec-v04-muted">{loading ? 'Загружаем…' : `${rows.length} закрытых`}</span>
          <button
            type="button"
            className="today-refresh-btn"
            title="Перечитать закрытые задачи из 1С"
            disabled={loading}
            onClick={() => setReload((value) => value + 1)}
          >
            <RefreshCw size={14} aria-hidden />
          </button>
        </div>

        <div className="closed-tasks-body">
          {error ? <p className="today-table-status today-table-error today-table-banner">{error}</p> : null}
          <table className="spec-v04-table">
            <thead>
              <tr>
                <th>Задача</th>
                <th>Тип</th>
                <th>От кого</th>
                <th>Исполнитель</th>
                <th>Срок</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {!visible.length ? (
                <tr>
                  <td colSpan={6} className="spec-v04-empty">
                    {loading
                      ? 'Загружаем закрытые задачи из 1С…'
                      : query.trim()
                        ? 'Ничего не найдено по этим словам'
                        : 'Нет закрытых задач за выбранный период'}
                  </td>
                </tr>
              ) : null}
              {visible.map((row) => {
                const kind = row.sourceKind === 'docflow' ? row.docflowKind ?? docflowTaskKind(row.step, row.taskName) : null
                return (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.title}</strong>
                    </td>
                    <td>
                      {kind ? <SpecPill tone={DOCFLOW_KIND_TONE[kind]}>{DOCFLOW_KIND_LABEL[kind]}</SpecPill> : '—'}
                    </td>
                    <td>{cell(formatSurnameInitials(row.author || ''))}</td>
                    <td>{cell(formatSurnameInitials(row.performer || row.executor))}</td>
                    <td>{cell(row.deadline)}</td>
                    <td>
                      <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="modal-actions">
          <button type="button" className="btn-light" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
