import { useEffect, useState } from 'react'
import { Lock, Plus, Trash2 } from 'lucide-react'
import type {
  ProtocolEditFields,
  ProtocolEditTask,
  ProtocolRow,
  ProtocolTask
} from '../../workplace/fetchDocflowProtocols'
import { listMeetingRooms, newProtocolRowKey, searchMeetingThemes } from '../../workplace/meetingProtocolCreate'

const KIND_OPTIONS = [
  { value: 'Отчетное', label: 'Отчётное' },
  { value: 'Внеплановое', label: 'Внеплановое' },
  { value: 'Селекторное', label: 'Селекторное' }
]
const PRIORITIES = ['Высокий', 'Средний', 'Низкий']
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/

export type HeaderDraft = {
  topic: string
  kind: string
  timeStart: string
  timeEnd: string
  nextMeeting: string
  head: string
  responsible: string
  room: string
  access: string
  department: string
  project: string
  comment: string
}

export type TaskDraft = {
  key: string
  line: number
  n: string
  text: string
  responsible: string
  responsibleKey: string
  due: string
  priority: string
  note: string
  sent: boolean
}

export function headerDraft(row: ProtocolRow): HeaderDraft {
  return {
    topic: row.topic,
    kind: row.kindCode,
    timeStart: row.timeStart,
    timeEnd: row.timeEnd,
    nextMeeting: row.nextMeeting.slice(0, 10),
    head: row.head,
    responsible: row.responsible,
    room: row.room,
    access: row.access,
    department: row.department,
    project: row.project,
    comment: row.comment
  }
}

/** Только изменённые поля: неизменённые ФИО и справочники сервер заново не ищет. */
export function changedFields(row: ProtocolRow, draft: HeaderDraft): { fields: ProtocolEditFields; error: string } {
  const base = headerDraft(row)
  const pairs: [keyof HeaderDraft, keyof ProtocolEditFields][] = [
    ['topic', 'topic'],
    ['kind', 'meeting_type'],
    ['timeStart', 'time_start'],
    ['timeEnd', 'time_end'],
    ['nextMeeting', 'next_meeting_date'],
    ['head', 'leader'],
    ['responsible', 'responsible'],
    ['room', 'room'],
    ['access', 'access'],
    ['department', 'department'],
    ['project', 'project'],
    ['comment', 'comment']
  ]
  const fields: ProtocolEditFields = {}
  for (const [key, target] of pairs) {
    if (draft[key].trim() !== base[key].trim()) fields[target] = draft[key].trim()
  }
  for (const time of [draft.timeStart, draft.timeEnd]) {
    if (time.trim() && !TIME_RE.test(time.trim())) return { fields, error: `Время «${time}» — нужно ЧЧ:ММ` }
  }
  if (draft.timeStart && draft.timeEnd && draft.timeStart >= draft.timeEnd) {
    return { fields, error: 'Окончание совещания должно быть позже начала' }
  }
  if (!draft.head.trim()) return { fields, error: 'Укажите руководителя совещания' }
  if (!draft.responsible.trim()) return { fields, error: 'Укажите ответственного за протокол' }
  if (!KIND_OPTIONS.some((item) => item.value === draft.kind)) return { fields, error: 'Выберите вид совещания' }
  return { fields, error: '' }
}

export function taskDrafts(tasks: ProtocolTask[]): TaskDraft[] {
  return tasks.map((task) => ({
    key: `line-${task.line}`,
    line: task.line,
    n: task.n ? String(task.n) : '',
    text: task.text,
    responsible: task.responsible,
    responsibleKey: task.responsibleKey,
    due: task.due.slice(0, 10),
    priority: task.priority,
    note: task.note,
    sent: task.sent
  }))
}

export function newTaskDraft(drafts: TaskDraft[]): TaskDraft {
  const next = drafts.reduce((max, item) => Math.max(max, Number(item.n) || 0), 0) + 1
  return {
    key: newProtocolRowKey(),
    line: 0,
    n: String(next),
    text: '',
    responsible: '',
    responsibleKey: '',
    due: '',
    priority: '',
    note: '',
    sent: false
  }
}

function blankNew(item: TaskDraft): boolean {
  return !item.line && ![item.text, item.responsible, item.due, item.priority, item.note].some((value) => value.trim())
}

export function taskPayload(drafts: TaskDraft[]): { tasks: ProtocolEditTask[]; error: string } {
  const tasks: ProtocolEditTask[] = []
  for (const [index, item] of drafts.entries()) {
    if (blankNew(item)) continue
    if (!item.text.trim()) return { tasks, error: `Задача № ${item.n || index + 1}: введите текст или удалите строку` }
    tasks.push({
      line: item.line,
      n: Number(item.n) || index + 1,
      text: item.text.trim(),
      responsible: item.responsible.trim(),
      ...(item.responsibleKey ? { responsible_key: item.responsibleKey } : {}),
      due: item.due,
      priority: item.priority,
      note: item.note.trim()
    })
  }
  return { tasks, error: '' }
}

export function tasksChanged(original: ProtocolTask[], drafts: TaskDraft[]): boolean {
  return JSON.stringify(taskPayload(taskDrafts(original)).tasks) !== JSON.stringify(taskPayload(drafts).tasks)
}

function Field({
  label,
  wide,
  children
}: {
  label: string
  wide?: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <label className={wide ? 'is-wide' : ''}>
      <span>{label}</span>
      {children}
    </label>
  )
}

export function ProtocolHeaderForm({
  row,
  draft,
  accessOptions,
  disabled,
  onChange
}: {
  row: ProtocolRow
  draft: HeaderDraft
  accessOptions: string[]
  disabled: boolean
  onChange: (draft: HeaderDraft) => void
}): React.JSX.Element {
  const [rooms, setRooms] = useState<string[]>([])
  const [themes, setThemes] = useState<string[]>([])
  const set = (key: keyof HeaderDraft) => (event: { target: { value: string } }) =>
    onChange({ ...draft, [key]: event.target.value })

  useEffect(() => {
    let alive = true
    void listMeetingRooms().then((items) => {
      if (alive) setRooms(items.map((item) => item.name))
    })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const query = draft.topic.trim()
    if (query.length < 3 || query === row.topic) return
    let alive = true
    const timer = window.setTimeout(() => {
      void searchMeetingThemes(query).then((items) => {
        if (alive) setThemes(items.map((item) => item.title))
      })
    }, 350)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [draft.topic, row.topic])

  const access = accessOptions.includes(draft.access) || !draft.access ? accessOptions : [draft.access, ...accessOptions]
  return (
    <section className="docflow-card-block">
      <h4>Основное — правка</h4>
      <fieldset className="docflow-edit-form" disabled={disabled}>
        <Field label="Тема" wide>
          <input value={draft.topic} list="protocol-edit-themes" onChange={set('topic')} />
          <datalist id="protocol-edit-themes">
            {themes.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <small>Тема выбирается из справочника 1С «Темы совещаний» — само название темы здесь не переименовать.</small>
        </Field>
        <Field label="Вид совещания">
          <select value={draft.kind} onChange={set('kind')}>
            {KIND_OPTIONS.some((item) => item.value === draft.kind) ? null : <option value="">—</option>}
            {KIND_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Время">
          <div className="docflow-edit-pair">
            <input type="time" value={draft.timeStart} onChange={set('timeStart')} />
            <input type="time" value={draft.timeEnd} onChange={set('timeEnd')} />
          </div>
        </Field>
        <Field label="Руководитель">
          <input value={draft.head} list="protocol-edit-people" onChange={set('head')} />
        </Field>
        <Field label="Ответственный">
          <input value={draft.responsible} list="protocol-edit-people" onChange={set('responsible')} />
        </Field>
        <Field label="Подразделение">
          <input value={draft.department} onChange={set('department')} />
        </Field>
        <Field label="Место">
          <input value={draft.room} list="protocol-edit-rooms" onChange={set('room')} />
          <datalist id="protocol-edit-rooms">
            {rooms.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </Field>
        <Field label="Проект">
          <input value={draft.project} onChange={set('project')} />
        </Field>
        <Field label="Гриф">
          <select value={draft.access} onChange={set('access')}>
            {draft.access ? null : <option value="">—</option>}
            {access.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Следующее совещание">
          <input type="date" value={draft.nextMeeting} onChange={set('nextMeeting')} />
        </Field>
        <Field label="Подготовил">
          <input value={row.preparedBy} readOnly title="Автор протокола не меняется" />
        </Field>
        <Field label="Комментарий" wide>
          <textarea rows={3} value={draft.comment} onChange={set('comment')} />
        </Field>
      </fieldset>
    </section>
  )
}

/** Подсказки ФИО для руководителя, ответственного и исполнителей задач — общие для всех вкладок правки. */
export function PeopleList({ people }: { people: string[] }): React.JSX.Element {
  return (
    <datalist id="protocol-edit-people">
      {people.map((name) => (
        <option key={name} value={name} />
      ))}
    </datalist>
  )
}

export function TaskEditor({
  title,
  drafts,
  assigned,
  block,
  disabled,
  onChange
}: {
  title: string
  drafts: TaskDraft[]
  assigned: boolean
  block: string
  disabled: boolean
  onChange: (drafts: TaskDraft[]) => void
}): React.JSX.Element {
  const update = (key: string, patch: Partial<TaskDraft>): void =>
    onChange(drafts.map((item) => (item.key === key ? { ...item, ...patch } : item)))
  const remove = (key: string): void => onChange(drafts.filter((item) => item.key !== key))
  return (
    <section className="docflow-card-block">
      <h4>
        {title} — правка
        <span>{drafts.length || 'нет'}</span>
      </h4>
      {block ? (
        <p className="docflow-status docflow-status-error">
          <Lock size={12} aria-hidden /> {block}
        </p>
      ) : (
        <fieldset className="docflow-task-edit" disabled={disabled}>
          {drafts.map((item) =>
            item.sent ? (
              <div key={item.key} className="docflow-task-row is-locked">
                <p>
                  <b>{item.n || '—'}.</b> {item.text || '—'}
                </p>
                <small>
                  <Lock size={11} aria-hidden /> Отправлена исполнителю{item.responsible ? ` (${item.responsible})` : ''} — изменить
                  или удалить можно только в 1С
                </small>
              </div>
            ) : (
              <div key={item.key} className="docflow-task-row">
                <div className="docflow-task-line">
                  <input
                    className="docflow-task-n"
                    type="number"
                    min={1}
                    value={item.n}
                    title="№ пункта протокола"
                    onChange={(event) => update(item.key, { n: event.target.value })}
                  />
                  <textarea
                    rows={2}
                    value={item.text}
                    placeholder="Текст задачи"
                    onChange={(event) => update(item.key, { text: event.target.value })}
                  />
                  <button type="button" className="docflow-task-remove" title="Удалить задачу" onClick={() => remove(item.key)}>
                    <Trash2 size={14} aria-hidden />
                  </button>
                </div>
                <div className="docflow-task-line">
                  <input
                    value={item.responsible}
                    list="protocol-edit-people"
                    placeholder={assigned ? 'Исполнитель (ФИО из 1С)' : 'Ответственный'}
                    onChange={(event) => update(item.key, { responsible: event.target.value, responsibleKey: '' })}
                  />
                  <input
                    type="date"
                    value={item.due}
                    title="Срок исполнения"
                    onChange={(event) => update(item.key, { due: event.target.value })}
                  />
                  <select value={item.priority} title="Приоритет" onChange={(event) => update(item.key, { priority: event.target.value })}>
                    <option value="">Приоритет —</option>
                    {(PRIORITIES.includes(item.priority) || !item.priority ? PRIORITIES : [item.priority, ...PRIORITIES]).map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
                <input
                  value={item.note}
                  placeholder="Примечание"
                  onChange={(event) => update(item.key, { note: event.target.value })}
                />
              </div>
            )
          )}
          <button type="button" className="docflow-task-add" onClick={() => onChange([...drafts, newTaskDraft(drafts)])}>
            <Plus size={14} aria-hidden /> Добавить задачу
          </button>
          {assigned ? (
            <p className="docflow-muted">
              Исполнитель ищется в справочнике физических лиц 1С по ФИО. Новые задачи сохраняются неотправленными — рассылка
              исполнителям делается в 1С.
            </p>
          ) : null}
        </fieldset>
      )}
    </section>
  )
}
