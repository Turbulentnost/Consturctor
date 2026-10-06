import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
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
  Paperclip,
  PenLine,
  Pencil,
  Save,
  Search,
  Tag,
  Users,
  X,
  XCircle
} from 'lucide-react'
import type { UserProfile } from '../../api/types'
import {
  formatProtocolDay,
  useBoardReportReadiness,
  type BoardReportReadiness
} from '../../workplace/boardReportReadiness'
import { DocflowFileOpenButton } from './DocflowAttachments'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import {
  forgetProtocolCard,
  loadProtocolCard,
  loadProtocolPage,
  saveProtocolEdit,
  type ProtocolCard,
  type ProtocolFile,
  type ProtocolOption,
  type ProtocolPlanRow,
  type ProtocolRow,
  type ProtocolTask
} from '../../workplace/fetchDocflowProtocols'
import {
  changedFields,
  headerDraft,
  PeopleList,
  ProtocolHeaderForm,
  TaskEditor,
  taskDrafts,
  taskPayload,
  tasksChanged,
  type HeaderDraft,
  type TaskDraft
} from './DocflowProtocolEdit'
import { ProtocolAudioBadge, ProtocolAudioSupplement } from './DocflowProtocolAudio'
import { SortTh, useDocflowTable } from './docflowTableTools'
import {
  useRegisterGlobalSearch,
  type GlobalSearchEntry
} from '../../layout/globalSearch'

const GLOBAL_SEARCH_SOURCE = 'grid:docflow:protocols'

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

function protocolSearchText(row: ProtocolRow): string {
  return [
    row.date,
    row.time,
    row.number,
    row.topic,
    row.kind,
    row.head,
    row.room,
    row.department,
    row.project,
    row.preparedBy,
    row.status,
    row.comment,
    ...row.participants
  ].join(' ')
}

function protocolSortValue(row: ProtocolRow, key: string): string {
  const map: Record<string, string> = {
    date: row.date,
    time: row.time,
    number: row.number,
    topic: row.topic,
    kind: row.kind,
    head: row.head,
    participants: row.participants.join(', '),
    room: row.room,
    status: row.status
  }
  return map[key] ?? ''
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

function fileSize(size: number): string {
  if (size <= 0) return ''
  return size >= 1024 * 1024 ? `${(size / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(size / 1024))} КБ`
}

function FileChips({ files }: { files: ProtocolFile[] }): React.JSX.Element | null {
  if (!files.length) return null
  return (
    <div className="docflow-chips docflow-files">
      {files.map((file) => (
        <DocflowFileOpenButton key={file.id} file={file}>
          <Paperclip size={11} aria-hidden />
          {file.name || '—'}
        </DocflowFileOpenButton>
      ))}
    </div>
  )
}

function TaskList({ tasks, empty }: { tasks: ProtocolTask[]; empty: string }): React.JSX.Element {
  if (!tasks.length) return <p className="docflow-status">{empty}</p>
  return (
    <ol className="docflow-lines">
      {tasks.map((task, index) => (
        <li key={`${task.n}-${index}`} value={task.n || index + 1} className={task.overdue ? 'is-overdue' : ''}>
          <p>{task.text || '—'}</p>
          <div>
            <span className={`docflow-pill ${task.executed ? 'is-ok' : task.overdue ? 'is-bad' : 'is-wait'}`}>
              {task.executed ? (
                <CheckCircle2 size={11} aria-hidden />
              ) : task.overdue ? (
                <AlertTriangle size={11} aria-hidden />
              ) : (
                <Circle size={11} aria-hidden />
              )}
              {task.status}
            </span>
            {task.responsible ? <span>{task.responsible}</span> : null}
            {task.due ? <span className={task.overdue ? 'is-overdue' : ''}>срок {onlyDay(task.due)}</span> : null}
            {task.doneAt ? <span>исполнена {onlyDay(task.doneAt)}</span> : null}
            {task.setAt ? <span>поставлена {onlyDay(task.setAt)}</span> : null}
            {task.priority ? <span>{task.priority}</span> : null}
            {task.sent && task.source !== 'docflow' ? <span>отправлена исполнителю</span> : null}
            {task.author ? <span>автор {task.author}</span> : null}
          </div>
          <FileChips files={task.files} />
          {task.note ? <p className="docflow-muted">{task.note}</p> : null}
        </li>
      ))}
    </ol>
  )
}

function taskCounts(tasks: ProtocolTask[]): string {
  if (!tasks.length) return 'нет'
  const done = tasks.filter((task) => task.executed).length
  const overdue = tasks.filter((task) => task.overdue).length
  return [String(tasks.length), done ? `выполнено ${done}` : '', overdue ? `просрочено ${overdue}` : ''].filter(Boolean).join(' · ')
}

/** Верхний список вкладки в форме 1С — задачи Документооборота; строки таблицы протокола — ниже. */
function DocflowTaskBlock({
  title,
  tasks,
  empty,
  note
}: {
  title: string
  tasks: ProtocolTask[]
  empty: string
  note: string
}): React.JSX.Element {
  return (
    <section className="docflow-card-block">
      <h4>
        <ListChecks size={14} aria-hidden /> {title}
        <span>{taskCounts(tasks)}</span>
      </h4>
      {note ? (
        <p className="docflow-status docflow-status-error">
          <AlertTriangle size={12} aria-hidden /> {note}
        </p>
      ) : null}
      <TaskList tasks={tasks} empty={empty} />
    </section>
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

type CardTab = 'main' | 'agenda' | 'control' | 'assigned' | 'decisions' | 'attendees' | 'plan' | 'files'

type Notice = { tone: 'ok' | 'error'; text: string }

function ProtocolCardView({ card, onSaved }: { card: ProtocolCard; onSaved: () => Promise<void> }): React.JSX.Element {
  const {
    protocol: row,
    agenda,
    decisions,
    controlTasks,
    assignedTasks,
    controlDocflow,
    assignedDocflow,
    controlRegister,
    assignedRegister,
    baseProtocol,
    docflowNote,
    files,
    periodDone,
    periodPlan,
    planFact,
    stats,
    edit
  } = card
  const [tab, setTab] = useState<CardTab>('main')
  const [editing, setEditing] = useState(false)
  const [header, setHeader] = useState<HeaderDraft>(() => headerDraft(row))
  const [controlDraft, setControlDraft] = useState<TaskDraft[]>([])
  const [assignedDraft, setAssignedDraft] = useState<TaskDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const planRows = periodDone.length + periodPlan.length + planFact.length
  const people = useMemo(() => {
    const names = [
      row.head,
      row.responsible,
      row.preparedBy,
      ...row.participants,
      ...[...assignedTasks, ...assignedDocflow, ...controlDocflow, ...assignedRegister, ...controlRegister].map(
        (task) => task.responsible
      )
    ]
    return [...new Set(names.map((name) => name.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right, 'ru'))
  }, [row, assignedTasks, assignedDocflow, controlDocflow, assignedRegister, controlRegister])
  const baseLabel = baseProtocol ? `№ ${baseProtocol.number || 'протокола-основания'}` : ''
  const controlDocflowBlock = (
    <DocflowTaskBlock
      title={`Документооборот · по протоколу ${baseLabel || '-основанию'}`}
      tasks={controlDocflow}
      note={baseProtocol ? docflowNote : ''}
      empty={
        baseProtocol
          ? `В Документообороте нет задач по протоколу ${baseLabel}.`
          : 'У протокола нет протокола-основания — задач с прошлого совещания на контроле нет.'
      }
    />
  )
  const assignedDocflowBlock = (
    <DocflowTaskBlock
      title="Документооборот · по этому протоколу"
      tasks={assignedDocflow}
      note={docflowNote}
      empty="В Документооборот задачи по этому протоколу ещё не отправлены."
    />
  )

  const onAudioDone = useCallback(() => {
    void onSaved().catch(() => setNotice({ tone: 'error', text: 'Агент закончил, но перечитать карточку не удалось — откройте протокол заново' }))
  }, [onSaved])

  const startEdit = (): void => {
    if (!edit.allowed) {
      setNotice({ tone: 'error', text: edit.reason || 'Этот протокол сейчас нельзя править' })
      return
    }
    setHeader(headerDraft(row))
    setControlDraft(taskDrafts(controlTasks))
    setAssignedDraft(taskDrafts(assignedTasks))
    setNotice(null)
    setEditing(true)
    if (tab !== 'main' && tab !== 'control' && tab !== 'assigned') setTab('main')
  }

  const cancelEdit = (): void => {
    setEditing(false)
    setNotice(null)
  }

  const save = async (): Promise<void> => {
    const head = changedFields(row, header)
    const control = taskPayload(controlDraft)
    const assigned = taskPayload(assignedDraft)
    const problem = head.error || control.error || assigned.error
    if (problem) {
      setNotice({ tone: 'error', text: problem })
      if (control.error) setTab('control')
      else if (assigned.error) setTab('assigned')
      else setTab('main')
      return
    }
    const change = {
      fields: head.fields,
      controlTasks: !edit.controlBlock && tasksChanged(controlTasks, controlDraft) ? control.tasks : undefined,
      assignedTasks: !edit.assignedBlock && tasksChanged(assignedTasks, assignedDraft) ? assigned.tasks : undefined
    }
    if (!Object.keys(change.fields).length && !change.controlTasks && !change.assignedTasks) {
      setEditing(false)
      setNotice({ tone: 'ok', text: 'Изменений нет' })
      return
    }
    setSaving(true)
    setNotice(null)
    try {
      const summary = await saveProtocolEdit(row.id, change)
      setEditing(false)
      setNotice({ tone: 'ok', text: summary })
      await onSaved().catch(() =>
        setNotice({ tone: 'ok', text: `${summary}. Перечитать карточку не удалось — откройте протокол заново` })
      )
    } catch (err) {
      setNotice({ tone: 'error', text: err instanceof Error ? err.message : 'Не удалось сохранить протокол в 1С' })
    } finally {
      setSaving(false)
    }
  }
  // Разделы повторяют вкладки формы протокола в 1С; пустые не показываем, кроме задач.
  const tabs: { id: CardTab; label: string; icon: React.ReactNode; count?: number; overdue?: number }[] = [
    { id: 'main', label: 'Основное', icon: <ClipboardList size={12} aria-hidden /> },
    ...(agenda.length ? [{ id: 'agenda' as CardTab, label: 'Повестка', icon: <MessagesSquare size={12} aria-hidden />, count: agenda.length }] : []),
    {
      id: 'control',
      label: 'Задачи для контроля',
      icon: <ListChecks size={12} aria-hidden />,
      count: stats.controlTasks,
      overdue: stats.controlOverdue
    },
    {
      id: 'assigned',
      label: 'Поставленные задачи',
      icon: <ListChecks size={12} aria-hidden />,
      count: stats.assignedTasks,
      overdue: stats.assignedOverdue
    },
    ...(decisions.length ? [{ id: 'decisions' as CardTab, label: 'Решения', icon: <Gavel size={12} aria-hidden />, count: decisions.length }] : []),
    ...(row.participants.length
      ? [{ id: 'attendees' as CardTab, label: 'Присутствующие', icon: <Users size={12} aria-hidden />, count: row.participants.length }]
      : []),
    ...(planRows ? [{ id: 'plan' as CardTab, label: 'План-факт', icon: <BarChart3 size={12} aria-hidden />, count: planRows }] : []),
    ...(files.length ? [{ id: 'files' as CardTab, label: 'Файлы', icon: <Paperclip size={12} aria-hidden />, count: files.length }] : [])
  ]
  return (
    <>
      <header className="docflow-detail-head">
        <div>
          <h3>
            № {cell(row.number)}
            <ProtocolAudioBadge row={row} />
          </h3>
          <p>
            {onlyDay(row.date)}
            {row.time ? ` · ${row.time}` : ''}
          </p>
        </div>
        <div className="docflow-detail-actions">
          <StatusPill row={row} />
          {editing ? (
            <>
              <button type="button" className="docflow-edit-btn is-primary" disabled={saving} onClick={() => void save()}>
                <Save size={14} aria-hidden /> {saving ? 'Сохраняем…' : 'Сохранить'}
              </button>
              <button type="button" className="docflow-edit-btn" disabled={saving} title="Отменить правку" onClick={cancelEdit}>
                <X size={14} aria-hidden />
              </button>
            </>
          ) : edit.author ? (
            <button
              type="button"
              className={`docflow-edit-btn${edit.allowed ? '' : ' is-locked'}`}
              title={edit.allowed ? 'Редактировать протокол' : edit.reason}
              aria-label="Редактировать протокол"
              onClick={startEdit}
            >
              <Pencil size={14} aria-hidden />
            </button>
          ) : null}
        </div>
      </header>
      {editing ? null : <ProtocolAudioSupplement row={row} onFinished={onAudioDone} />}
      {notice ? (
        <p className={`docflow-edit-notice${notice.tone === 'error' ? ' is-error' : ''}`}>
          {notice.text}
          <button type="button" className="docflow-retry" onClick={() => setNotice(null)}>
            ×
          </button>
        </p>
      ) : null}
      {editing ? <PeopleList people={people} /> : null}
      {row.topic ? <p className="docflow-side-subject">{row.topic}</p> : null}
      {row.secret ? (
        <p className="docflow-secret-note">
          <Lock size={12} aria-hidden /> Секретно: {row.access || 'ограниченный доступ'} — вы автор или ответственный
        </p>
      ) : null}
      <nav className="docflow-card-tabs" aria-label="Разделы протокола">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? 'is-active' : ''}
            onClick={() => setTab(item.id)}
          >
            {item.icon}
            {item.label}
            {item.count ? <b>{item.count}</b> : null}
            {item.overdue ? <em title="просроченных задач">{item.overdue}</em> : null}
          </button>
        ))}
      </nav>
      <div className="docflow-side-scroll">
        {tab === 'main' && editing ? (
          <ProtocolHeaderForm row={row} draft={header} accessOptions={edit.accessOptions} disabled={saving} onChange={setHeader} />
        ) : null}
        {tab === 'main' && !editing ? (
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
        ) : null}
        {tab === 'agenda' ? (
          <section className="docflow-card-block">
            <h4>
              <MessagesSquare size={14} aria-hidden /> Повестка совещания
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
                  <FileChips files={item.files} />
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {tab === 'control' ? controlDocflowBlock : null}
        {tab === 'assigned' ? assignedDocflowBlock : null}
        {tab === 'control' && editing ? (
          <TaskEditor
            title="Задачи для контроля · таблица протокола"
            drafts={controlDraft}
            assigned={false}
            block={edit.controlBlock}
            disabled={saving}
            onChange={setControlDraft}
          />
        ) : null}
        {tab === 'assigned' && editing ? (
          <TaskEditor
            title="Поставленные задачи · таблица протокола"
            drafts={assignedDraft}
            assigned
            block={edit.assignedBlock}
            disabled={saving}
            onChange={setAssignedDraft}
          />
        ) : null}
        {tab === 'control' && !editing && controlRegister.length ? (
          <section className="docflow-card-block">
            <h4>
              <ListChecks size={14} aria-hidden /> Регистр задач протокола {baseLabel || '-основания'}
              <span>{taskCounts(controlRegister)}</span>
            </h4>
            <TaskList tasks={controlRegister} empty="" />
          </section>
        ) : null}
        {tab === 'assigned' && !editing && assignedRegister.length ? (
          <section className="docflow-card-block">
            <h4>
              <ListChecks size={14} aria-hidden /> Регистр задач протокола в 1С
              <span>{taskCounts(assignedRegister)}</span>
            </h4>
            <TaskList tasks={assignedRegister} empty="" />
          </section>
        ) : null}
        {tab === 'control' && !editing && controlTasks.length ? (
          <section className="docflow-card-block">
            <h4>
              <ListChecks size={14} aria-hidden /> Таблица протокола в 1С
              <span>{taskCounts(controlTasks)}</span>
            </h4>
            <TaskList tasks={controlTasks} empty="" />
          </section>
        ) : null}
        {tab === 'assigned' && !editing && assignedTasks.length ? (
          <section className="docflow-card-block">
            <h4>
              <ListChecks size={14} aria-hidden /> Таблица протокола в 1С
              <span>{taskCounts(assignedTasks)}</span>
            </h4>
            <TaskList tasks={assignedTasks} empty="" />
          </section>
        ) : null}
        {tab === 'decisions' ? (
          <section className="docflow-card-block">
            <h4>
              <Gavel size={14} aria-hidden /> Решения
              <span>
                {`исполнено ${stats.decisionsDone} из ${stats.decisions}${stats.decisionsCancelled ? ` · отменено ${stats.decisionsCancelled}` : ''}`}
              </span>
            </h4>
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
          </section>
        ) : null}
        {tab === 'attendees' ? (
          <section className="docflow-card-block">
            <h4>
              <Users size={14} aria-hidden /> Присутствующие
              <span>{row.participants.length}</span>
            </h4>
            <div className="docflow-chips">
              {row.participants.map((name) => (
                <span key={name}>{name}</span>
              ))}
            </div>
          </section>
        ) : null}
        {tab === 'plan' ? (
          <>
            <PlanBlock title="План-факт" rows={planFact} />
            <PlanBlock title="Выполнение задач за период" rows={periodDone} />
            <PlanBlock title="План задач на период" rows={periodPlan} />
          </>
        ) : null}
        {tab === 'files' ? (
          <section className="docflow-card-block">
            <h4>
              <Paperclip size={14} aria-hidden /> Файлы протокола
              <span>{files.length}</span>
            </h4>
            <ul className="docflow-lines">
              {files.map((file) => (
                <li key={file.id}>
                  <DocflowFileOpenButton file={file}>{file.name || '—'}</DocflowFileOpenButton>
                  <div>
                    {fileSize(file.size) ? <span>{fileSize(file.size)}</span> : null}
                    {file.created ? <span>{onlyDay(file.created)}</span> : null}
                    {file.signed ? <span>подписан ЭП</span> : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  )
}

function BoardReadyBar({
  loading,
  error,
  readiness
}: {
  loading: boolean
  error: string
  readiness: BoardReportReadiness
}): React.JSX.Element {
  const width = readiness.total ? readiness.percent : 0
  const caption = readiness.protocolNumber
    ? `${readiness.protocolNumber}${readiness.protocolDate ? ` · ${formatProtocolDay(readiness.protocolDate)}` : ''}${
        readiness.currentMonth ? '' : ' · последний протокол'
      }`
    : 'Протокол совета директоров по ГК'
  return (
    <div className="ready-bar" title="Поставленные задачи: управленческая отчётность за 2 рабочих дня до совета директоров по ГК">
      <div className="ready-bar-head">
        <span>Готовность к совету директоров</span>
        <em>{loading ? 'считаем…' : error ? error : caption}</em>
        <strong>{loading ? '—' : `${readiness.percent}%`}</strong>
      </div>
      <div className="ready-bar-track" role="progressbar" aria-valuenow={width} aria-valuemin={0} aria-valuemax={100}>
        <i style={{ width: `${width}%` }} />
      </div>
      <small>{loading ? '' : readiness.total ? `выполнено ${readiness.done} из ${readiness.total}` : 'поставленных задач нет'}</small>
    </div>
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
  const board = useBoardReportReadiness(user)
  const [rows, setRows] = useState<ProtocolRow[]>([])
  const [statuses, setStatuses] = useState<ProtocolOption[]>(FALLBACK_STATUSES)
  const [kinds, setKinds] = useState<ProtocolOption[]>(FALLBACK_KINDS)
  const [nextSkip, setNextSkip] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [hiddenSecret, setHiddenSecret] = useState(0)
  const [ownSecret, setOwnSecret] = useState(0)
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
        setOwnSecret((prev) => (reset ? page.ownSecret : prev + page.ownSecret))
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

  // Поиск по словам и сортировка колонок — в useDocflowTable ниже.
  const listed = useMemo(
    () =>
      rows.filter((row) => {
        if (topic && row.topic !== topic) return false
        if (head && row.head !== head) return false
        if (department && row.department !== department) return false
        if (room && row.room !== room) return false
        if (preparedBy && row.preparedBy !== preparedBy) return false
        if (project && row.project !== project) return false
        if (participant && !row.participants.includes(participant)) return false
        return true
      }),
    [rows, topic, head, department, room, preparedBy, project, participant]
  )
  const table = useDocflowTable(listed, {
    text: protocolSearchText,
    value: protocolSortValue,
    initialSort: { key: 'date', dir: 'desc' },
    query
  })
  const visible = table.rows
  const globalSearchEntries = useMemo<GlobalSearchEntry[]>(
    () =>
      visible.map((row) => {
        const targetId = `protocol:${row.id}`
        return {
          id: `docflow:${targetId}`,
          source: GLOBAL_SEARCH_SOURCE,
          pageKey: 'docflow',
          kind: 'entity',
          targetId,
          sectionId: 'protocols',
          title: row.topic || `Протокол № ${cell(row.number)}`,
          subtitle: [onlyDay(row.date), row.time, row.kind, row.status].filter(Boolean).join(' · '),
          keywords: [
            row.number,
            row.head,
            row.room,
            row.department,
            row.project,
            row.preparedBy,
            row.responsible,
            row.access,
            row.comment,
            ...row.participants
          ]
        }
      }),
    [visible]
  )
  useRegisterGlobalSearch(GLOBAL_SEARCH_SOURCE, globalSearchEntries)

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

  const refreshCard = async (id: string): Promise<void> => {
    forgetProtocolCard(id)
    const fresh = await loadProtocolCard(user, id)
    setRows((prev) => prev.map((item) => (item.id === id ? fresh.protocol : item)))
    if (cardForRef.current === id) setCard(fresh)
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
        {board.enabled ? <BoardReadyBar loading={board.loading} error={board.error} readiness={board.readiness} /> : null}
        <div className="docflow-order-filters">
          <label className="docflow-search">
            <Search size={14} aria-hidden />
            <input
              type="search"
              value={query}
              placeholder="Номер, тема, участник…"
              onChange={(event) => setQuery(event.target.value)}
            />
            {query.trim() ? (
              <span className="docflow-search-count">
                {visible.length} из {listed.length}
              </span>
            ) : null}
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
            {ownSecret ? (
              <em className="docflow-secret-note" title="Ваши конфиденциальные протоколы — вы автор или ответственный">
                <Lock size={12} aria-hidden /> секретно {ownSecret}
              </em>
            ) : null}
            {hiddenSecret ? (
              <em className="docflow-secret-note" title="Чужие конфиденциальные протоколы не показываются">
                скрыто {hiddenSecret}
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
                  <SortTh label="Дата" sortKey="date" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Время" sortKey="time" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Номер" sortKey="number" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Тема" sortKey="topic" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Вид" sortKey="kind" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Руководитель" sortKey="head" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Участники" sortKey="participants" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Место" sortKey="room" sort={table.sort} onSort={table.toggleSort} />
                  <SortTh label="Статус" sortKey="status" sort={table.sort} onSort={table.toggleSort} />
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr
                    key={row.id}
                    data-search-id={`protocol:${row.id}`}
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
                    <td>
                      {cell(row.number)}
                      <ProtocolAudioBadge row={row} />
                      {row.secret ? (
                        <em className="docflow-secret-note" title={`Секретно: ${row.access || 'ограниченный доступ'}`}>
                          <Lock size={12} aria-hidden /> секретно
                        </em>
                      ) : null}
                    </td>
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
          <ProtocolCardView key={card.protocol.id} card={card} onSaved={() => refreshCard(card.protocol.id)} />
        ) : null}
      </aside>
    </div>
  )
}
