import { useEffect, useRef, useState } from 'react'
import { Paperclip, Printer, SquarePen, X } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import type { AssignmentRegistryRow } from '../../workplace/assignmentRegistryTypes'
import type { ClosureCheckAssignment } from '../../components/agentfeed/docflowActions'
import { forgetAssignmentCard, loadAssignmentCard, type AssignmentCard } from '../../workplace/fetchDocflowAssignments'
import { buildAssignmentCardPrintHtml } from '../../workplace/registryPrint'
import { AssignmentDocflowTasks, AssignmentFileList } from './AssignmentDocflowTasks'

const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

type CardTab = 'tasks' | 'lines'

function useDocflowCard(
  user: UserProfile,
  refKey: string
): { card: AssignmentCard | null; error: string; reload: () => void } {
  const [card, setCard] = useState<AssignmentCard | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const userRef = useRef(user)
  userRef.current = user

  useEffect(() => {
    let alive = true
    setCard(null)
    setError('')
    if (!GUID_RE.test(refKey)) {
      setError('Поручение ещё не записано в 1С — задач в Документообороте нет')
      return
    }
    void loadAssignmentCard(userRef.current, refKey)
      .then((result) => {
        if (alive) setCard(result)
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось прочитать задачи')
      })
    return () => {
      alive = false
    }
  }, [refKey, tick])

  return {
    card,
    error,
    reload: () => {
      forgetAssignmentCard(refKey)
      setTick((value) => value + 1)
    }
  }
}

function TasksTab({
  card,
  error,
  check,
  onTaskChanged
}: {
  card: AssignmentCard | null
  error: string
  check?: ClosureCheckAssignment
  onTaskChanged?: () => void
}): React.JSX.Element {
  if (error) return <p className="registry-detail-tasks-empty">{error}</p>
  if (!card) return <p className="registry-detail-tasks-empty">Загрузка задач из Документооборота…</p>
  return (
    <>
      <AssignmentDocflowTasks card={card} check={check} onTaskChanged={onTaskChanged} />
      {card.files.length ? (
        <>
          <h4 className="registry-detail-tasks-title">
            <Paperclip size={14} aria-hidden /> Файлы поручения ({card.files.length})
          </h4>
          <AssignmentFileList files={card.files} />
        </>
      ) : null}
    </>
  )
}

function LinesTab({ row, loading }: { row: AssignmentRegistryRow; loading: boolean }): React.JSX.Element {
  if (loading && !row.lines.length) {
    return <p className="registry-detail-tasks-empty">Загрузка мероприятий из 1С…</p>
  }
  if (!row.lines.length) {
    return (
      <p className="registry-detail-tasks-empty">Мероприятия не пришли из 1С — обновите реестр или дождитесь догрузки.</p>
    )
  }
  return (
    <ul className="registry-detail-tasks">
      {row.lines.map((line, index) => (
        <li key={`${row.id}-${line.line}`} className="registry-detail-task">
          <div className="registry-detail-task-head">
            <span className="registry-detail-task-num">Мероприятие {line.line || index + 1}</span>
            {line.priority && line.priority !== '—' ? (
              <span className="registry-detail-task-priority">{line.priority}</span>
            ) : null}
          </div>
          <p className="registry-detail-task-text">{line.text}</p>
          <dl className="registry-detail-task-meta">
            <div>
              <dt>Исполнитель</dt>
              <dd>{line.executor}</dd>
            </div>
            <div>
              <dt>Срок</dt>
              <dd>{line.due !== '—' ? line.due : '—'}</dd>
            </div>
          </dl>
        </li>
      ))}
    </ul>
  )
}

function DetailField({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <div className="registry-detail-field">
      <span className="registry-detail-label">{label}</span>
      <span className="registry-detail-value">{value || '—'}</span>
    </div>
  )
}

export function AssignmentsRegistryDetailPanel({
  user,
  row,
  linesLoading = false,
  onClose,
  onOpenForm,
  check
}: {
  user: UserProfile
  row: AssignmentRegistryRow | null
  linesLoading?: boolean
  onClose: () => void
  onOpenForm?: () => void
  check?: ClosureCheckAssignment
}): React.JSX.Element {
  const [tab, setTab] = useState<CardTab>('tasks')
  const { card, error, reload } = useDocflowCard(user, row?.refKey ?? '')

  if (!row) {
    return (
      <aside className="registry-detail-panel registry-detail-panel--empty">
        <p className="registry-detail-placeholder">
          Выберите строку в таблице, чтобы открыть карточку поручения и список задач.
        </p>
      </aside>
    )
  }

  const tabButton = (id: CardTab, label: string, count: number | null): React.JSX.Element => (
    <button
      type="button"
      role="tab"
      aria-selected={tab === id}
      className={`registry-detail-tab${tab === id ? ' is-active' : ''}`}
      onClick={() => setTab(id)}
    >
      {label}
      {count ? <span>{count}</span> : null}
    </button>
  )

  return (
    <aside className={`registry-detail-panel tone-${row.tone}`}>
      <div className="registry-detail-head">
        <div>
          <h3 className="registry-detail-title">{row.number}</h3>
          <p className="registry-detail-subtitle">{row.topic}</p>
        </div>
        <div className="registry-detail-head-actions">
          {onOpenForm && GUID_RE.test(row.refKey) ? (
            <button type="button" className="registry-detail-close" title="Открыть форму" onClick={onOpenForm}>
              <SquarePen size={16} aria-hidden />
            </button>
          ) : null}
          <button
            type="button"
            className="registry-detail-close"
            title="Печать карточки поручения"
            onClick={() => void window.api.printDialog({ html: buildAssignmentCardPrintHtml(row) })}
          >
            <Printer size={16} aria-hidden />
          </button>
          <button type="button" className="registry-detail-close" title="Закрыть" onClick={onClose}>
            <X size={16} aria-hidden />
          </button>
        </div>
      </div>

      <div className="registry-detail-scroll">
        <div className="registry-detail-grid">
          <DetailField label="Статус" value={row.status} />
          <DetailField label="Дата" value={row.date} />
          <DetailField label="Руководитель" value={row.manager} />
          <DetailField label="Организация" value={row.organization} />
          <DetailField label="Основание" value={row.basis} />
          <DetailField label="Срок устранения" value={row.fullRemediationDue} />
          <DetailField label="Еженедельный отчёт" value={row.weeklyReportDate} />
          <DetailField label="Итоговый доклад" value={row.finalReportDate} />
          <DetailField label="Кто доложит" value={row.reporter} />
          <DetailField label="Секретарь" value={row.secretary} />
        </div>

        <div className="registry-detail-tabs" role="tablist">
          {tabButton('tasks', 'Задачи', card?.tasks.length ?? null)}
          {tabButton('lines', 'Мероприятия', row.lines.length)}
        </div>

        {tab === 'tasks' ? (
          <TasksTab card={card} error={error} check={check} onTaskChanged={reload} />
        ) : (
          <LinesTab row={row} loading={linesLoading} />
        )}
      </div>
    </aside>
  )
}
