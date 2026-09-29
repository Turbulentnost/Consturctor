import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Check, Paperclip, Send, Trash2, UserCheck } from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import { OrchSlotMain } from '../../layout/GridSlots'
import { useGridDataRefreshContext } from '../../workplace/GridDataRefreshContext'
import { addWorkingDays, clockTime, formatRuDateTime, isoDay } from '../../workplace/docflowCreate'
import { PLATFORM_PRIORITY_LABEL, type PlatformPriority } from '../../workplace/platformTasks'
import { openWorkplaceTab } from '../../workplace/workplaceNav'
import { FioCombobox } from './FioCombobox'
import './docflowGrid.css'
import './createOneCTask.css'

type Assignee = { fio: string; user_id: string; position: string; department: string }

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export function CreatePlatformTaskPage({ user }: { user: UserProfile }): React.JSX.Element {
  const { softRefresh } = useGridDataRefreshContext()
  const [assignees, setAssignees] = useState<Assignee[]>([])
  const [assigneesError, setAssigneesError] = useState('')
  const [loadingAssignees, setLoadingAssignees] = useState(true)
  const [syncing, setSyncing] = useState(false)

  const [now, setNow] = useState(() => new Date())
  const [fio, setFio] = useState('')
  const [dueDate, setDueDate] = useState(() => isoDay(addWorkingDays(new Date(), 2)))
  const [dueTime, setDueTime] = useState(() => clockTime(new Date()))
  const [priority, setPriority] = useState<PlatformPriority>('normal')
  const [description, setDescription] = useState('')
  const [files, setFiles] = useState<string[]>([])

  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState<{ fio: string; warning: string } | null>(null)

  const loadAssignees = (): void => {
    setLoadingAssignees(true)
    setAssigneesError('')
    void api
      .listPlatformAssignees()
      .then(setAssignees)
      .catch((err: unknown) => setAssigneesError(err instanceof Error ? err.message : 'Список сотрудников не загрузился'))
      .finally(() => setLoadingAssignees(false))
  }

  useEffect(loadAssignees, [user.id])

  // Дата постановки — момент отправки; до отправки показываем текущее время.
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const hints = useMemo(() => assignees.map((item) => item.fio), [assignees])
  const picked = assignees.find((item) => item.fio === fio.trim()) ?? null

  const syncOrg = (): void => {
    setSyncing(true)
    void api
      .syncPlatformOrg()
      .then(loadAssignees)
      .catch((err: unknown) => setAssigneesError(err instanceof Error ? err.message : 'Оргструктура не обновилась'))
      .finally(() => setSyncing(false))
  }

  const pickFiles = async (): Promise<void> => {
    const paths = await window.api.openFile({ title: 'Прикрепить файлы', properties: ['openFile', 'multiSelections'] })
    if (paths.length) setFiles((current) => [...current, ...paths.filter((path) => !current.includes(path))].slice(0, 10))
  }

  const validate = (): string => {
    if (!picked) return 'Выберите исполнителя из списка'
    if (!description.trim()) return 'Опишите задачу'
    if (!dueDate) return 'Укажите срок исполнения'
    const due = new Date(`${dueDate}T${dueTime || '18:00'}`)
    if (Number.isNaN(due.getTime()) || due.getTime() <= Date.now()) return 'Срок исполнения должен быть позже текущего момента'
    return ''
  }

  const submit = async (): Promise<void> => {
    const problem = validate()
    setError(problem)
    if (problem || !picked || sending) return
    setSending(true)
    try {
      const task = await api.createPlatformTask({
        assignee_fio: picked.fio,
        description: description.trim(),
        priority,
        due_at: new Date(`${dueDate}T${dueTime || '18:00'}`).toISOString()
      })
      const failed: string[] = []
      for (const path of files) {
        try {
          await api.uploadPlatformTaskFile(task.id, path)
        } catch {
          failed.push(fileName(path))
        }
      }
      softRefresh()
      setSent({
        fio: picked.fio,
        warning: failed.length ? `Не загрузились файлы: ${failed.join(', ')}` : ''
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Задача не создана')
    } finally {
      setSending(false)
    }
  }

  const reset = (): void => {
    const current = new Date()
    setSent(null)
    setFio('')
    setDescription('')
    setFiles([])
    setPriority('normal')
    setDueDate(isoDay(addWorkingDays(current, 2)))
    setDueTime(clockTime(current))
    setError('')
  }

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="tcx-page">
        <div className="tcx-body">
          <div className="tcx-main">
            <header className="tcx-head">
              <h2>Новая задача в платформе</h2>
              <p>
                Задача уходит сотруднику в Оркестратор, он получит уведомление. Руководителям по оргструктуре 1С задачи
                ставить нельзя.
              </p>
            </header>

            {sent ? (
              <div className="tcx-panel tcx-done">
                <span className="tcx-done-icon" aria-hidden>
                  <Check size={22} />
                </span>
                <h2>Задача поставлена</h2>
                <p>
                  {sent.fio} получит уведомление. Задача появится у вас обоих во вкладке «Задачи» → «Платформа».
                </p>
                {sent.warning ? <p className="tcx-status tcx-status-error">{sent.warning}</p> : null}
              </div>
            ) : (
              <div className="tcx-panel tcx-ptask">
                <label className="tcx-ptask-field tcx-ptask-field--wide">
                  <span>Исполнитель *</span>
                  <FioCombobox
                    value={fio}
                    hints={hints}
                    placeholder={loadingAssignees ? 'Загружаем сотрудников…' : 'Начните вводить фамилию'}
                    onChange={setFio}
                  />
                  {picked ? (
                    <small>
                      <UserCheck size={13} aria-hidden /> {[picked.position, picked.department].filter(Boolean).join(' · ')}
                    </small>
                  ) : null}
                </label>
                {assigneesError ? (
                  <div className="tcx-ptask-field--wide tcx-status tcx-status-error">
                    {assigneesError}{' '}
                    <button type="button" className="spec-btn-outline" disabled={syncing} onClick={syncOrg}>
                      {syncing ? 'Загружаем оргструктуру из 1С… (около 2 минут)' : 'Загрузить оргструктуру из 1С'}
                    </button>
                  </div>
                ) : null}

                <label className="tcx-ptask-field">
                  <span>Срок исполнения *</span>
                  <span className="tcx-row-due">
                    <input
                      className="onec-reconnect-input"
                      type="date"
                      value={dueDate}
                      onChange={(event) => setDueDate(event.target.value)}
                    />
                    <input
                      className="onec-reconnect-input"
                      type="time"
                      value={dueTime}
                      onChange={(event) => setDueTime(event.target.value)}
                    />
                  </span>
                  <small>По умолчанию — через 2 рабочих дня</small>
                </label>

                <label className="tcx-ptask-field">
                  <span>Приоритет</span>
                  <select
                    className={`wp-select tcx-priority is-${priority}`}
                    value={priority}
                    onChange={(event) => setPriority(event.target.value as PlatformPriority)}
                  >
                    {(Object.keys(PLATFORM_PRIORITY_LABEL) as PlatformPriority[]).map((id) => (
                      <option key={id} value={id}>
                        {PLATFORM_PRIORITY_LABEL[id]}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="tcx-ptask-field">
                  <span>Дата постановки</span>
                  <strong className="tcx-ptask-posted">{formatRuDateTime(now)}</strong>
                  <small>Ставится автоматически при отправке</small>
                </div>

                <label className="tcx-ptask-field tcx-ptask-field--wide">
                  <span>Описание *</span>
                  <textarea
                    className="onec-reconnect-input tcx-ptask-text"
                    rows={6}
                    maxLength={4000}
                    value={description}
                    placeholder="Что нужно сделать и какой результат ожидается"
                    onChange={(event) => setDescription(event.target.value)}
                  />
                  <small>{description.length}/4000</small>
                </label>

                <div className="tcx-ptask-field tcx-ptask-field--wide">
                  <span>Файлы</span>
                  <div className="tcx-ptask-files">
                    {files.map((path) => (
                      <span key={path} className="tcx-ptask-file" title={path}>
                        <Paperclip size={13} aria-hidden /> {fileName(path)}
                        <button
                          type="button"
                          aria-label={`Убрать ${fileName(path)}`}
                          onClick={() => setFiles((current) => current.filter((item) => item !== path))}
                        >
                          <Trash2 size={13} aria-hidden />
                        </button>
                      </span>
                    ))}
                    <button type="button" className="tcx-add" disabled={files.length >= 10} onClick={() => void pickFiles()}>
                      <Paperclip size={15} aria-hidden /> Прикрепить файлы
                    </button>
                  </div>
                  <small>До 10 файлов, каждый до 25 МБ</small>
                </div>
              </div>
            )}

            {error ? <p className="tcx-status tcx-status-error">{error}</p> : null}

            <footer className="tcx-actions">
              <button type="button" className="spec-btn-outline" onClick={() => openWorkplaceTab('tasks')}>
                <ArrowLeft size={15} aria-hidden /> К задачам
              </button>
              <span className="tcx-actions-gap" />
              {sent ? (
                <button type="button" className="spec-btn-launch" onClick={reset}>
                  Поставить ещё
                </button>
              ) : (
                <button type="button" className="spec-btn-launch" disabled={sending} onClick={() => void submit()}>
                  {sending ? 'Отправляем…' : 'Отправить задачу'} <Send size={15} aria-hidden />
                </button>
              )}
            </footer>
          </div>

          <aside className="tcx-side">
            <div className="tcx-panel">
              <h3 className="tcx-side-title">Краткая информация</h3>
              <dl className="tcx-side-list">
                <dt>Постановщик</dt>
                <dd>{user.fio || '—'}</dd>
                <dt>Исполнитель</dt>
                <dd>{picked?.fio || '—'}</dd>
                <dt>Срок</dt>
                <dd>{dueDate ? `${dueDate.split('-').reverse().join('.')} ${dueTime}` : '—'}</dd>
                <dt>Приоритет</dt>
                <dd>{PLATFORM_PRIORITY_LABEL[priority]}</dd>
                <dt>Файлов</dt>
                <dd>{files.length || '—'}</dd>
              </dl>
            </div>
          </aside>
        </div>
      </section>
    </OrchSlotMain>
  )
}
