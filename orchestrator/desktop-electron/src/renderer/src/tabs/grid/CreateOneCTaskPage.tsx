import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import { OrchSlotMain } from '../../layout/GridSlots'
import { useSpecV04Sources } from '../../workplace/useSpecV04Data'
import { openWorkplaceTab } from '../../workplace/workplaceNav'
import {
  documentLabel,
  launchDocflowProcess,
  loadDocflowCatalog,
  loadDocflowUsers,
  DOCFLOW_BASIS_KINDS,
  DOCFLOW_PROCESSES,
  prepareDocflowProcess,
  searchDocflowDocuments,
  type DocflowBasisDocument,
  type DocflowBasisKind,
  type DocflowPerformerDraft,
  type DocflowProcessDef,
  type DocflowProcessId
} from '../../workplace/docflowCreate'
import { FioCombobox } from './FioCombobox'
import './docflowGrid.css'
import './createOneCTask.css'

type Step = 'basis' | 'process' | 'fields' | 'review' | 'done'

const STEPS: { id: Exclude<Step, 'done'>; title: string }[] = [
  { id: 'basis', title: 'Документ-основание' },
  { id: 'process', title: 'Процесс' },
  { id: 'fields', title: 'Задача' },
  { id: 'review', title: 'Проверка и запуск' }
]

function newPerformer(): DocflowPerformerDraft {
  return { key: `p-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, fio: '', due: '', note: '' }
}

/** Сотрудник, а не служебная учётка: минимум два слова кириллицей. */
function isPersonFio(value: string): boolean {
  return value.trim().split(/\s+/).filter((part) => /^[А-ЯЁ][а-яё-]+$/.test(part)).length >= 2
}

const ALL_EMPLOYEES_LIMIT = 20000
let employeesSession: Promise<string[]> | null = null

/**
 * Все пользователи ДО одним запросом за сеанс; фильтр по вводу — локально.
 * Если ДО не ответил, берём справочник ERP (через шлюз он бывает урезан).
 */
function loadAllEmployees(user: UserProfile): Promise<string[]> {
  if (!employeesSession) {
    employeesSession = loadDocflowUsers(user)
      .then(async (res) => (res.ok && res.value.users?.length ? res.value.users : api.searchUsers('', ALL_EMPLOYEES_LIMIT)))
      .then((items) => {
        const people = items.filter(isPersonFio)
        if (!people.length) employeesSession = null
        return people
      })
  }
  return employeesSession
}

function formatDay(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '')
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value || '—'
}

export function CreateOneCTaskPage({ user }: { user: UserProfile }): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const me = (user.fio || '').trim()

  const [step, setStep] = useState<Step>('basis')
  const [catalog, setCatalog] = useState<{ kinds: DocflowBasisKind[]; processes: DocflowProcessDef[] }>({
    kinds: DOCFLOW_BASIS_KINDS,
    processes: DOCFLOW_PROCESSES
  })
  const [catalogError, setCatalogError] = useState('')
  const [fioHints, setFioHints] = useState<string[]>([])
  const [kindId, setKindId] = useState('')
  const [typeId, setTypeId] = useState('')
  const [query, setQuery] = useState('')
  const [onlyMine, setOnlyMine] = useState(true)
  const [documents, setDocuments] = useState<DocflowBasisDocument[]>([])
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [documentPicked, setDocumentPicked] = useState<DocflowBasisDocument | null>(null)

  const [processId, setProcessId] = useState<DocflowProcessId | ''>('')
  const [preparing, setPreparing] = useState(false)
  const [prepareError, setPrepareError] = useState('')

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [due, setDue] = useState('')
  const [performers, setPerformers] = useState<DocflowPerformerDraft[]>(() => [newPerformer()])
  const [verifier, setVerifier] = useState(me)
  const [fieldsError, setFieldsError] = useState('')

  const [confirmed, setConfirmed] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState('')
  const [launchSummary, setLaunchSummary] = useState('')

  useEffect(() => {
    let alive = true
    void loadDocflowCatalog(user).then((res) => {
      if (!alive) return
      if (!res.ok) {
        setCatalogError(res.error)
        return
      }
      const loaded = res.value.kinds ?? []
      setCatalog((current) => ({
        ...current,
        kinds: current.kinds.map((item) => ({
          ...item,
          types: loaded.find((row) => row.id === item.id)?.types ?? []
        }))
      }))
    })
    return () => {
      alive = false
    }
  }, [user])

  useEffect(() => {
    let alive = true
    void loadAllEmployees(user).then((items) => {
      if (alive) setFioHints(items)
    })
    return () => {
      alive = false
    }
  }, [user])

  const kind = catalog?.kinds.find((item) => item.id === kindId) ?? null
  const processDefs = useMemo(
    () => (catalog?.processes ?? []).filter((item) => kind?.processes.includes(item.id)),
    [catalog, kind]
  )
  const process = catalog?.processes.find((item) => item.id === processId) ?? null
  const sampleTaskIds = useMemo(
    () =>
      data.erpTasks
        .filter((row) => row.sourceKind === 'docflow' && /исполн/i.test(row.step || '') && row.refKey)
        .map((row) => row.refKey as string)
        .slice(0, 6),
    [data.erpTasks]
  )

  const pickKind = (id: string): void => {
    setKindId(id)
    setTypeId('')
    setDocuments([])
    setSearched(false)
    setSearchError('')
    setDocumentPicked(null)
    setProcessId('')
  }

  const runSearch = (): void => {
    if (!kind || searching) return
    setSearching(true)
    setSearchError('')
    void searchDocflowDocuments(user, { kind: kind.id, documentTypeId: typeId, query, onlyMine })
      .then((res) => {
        setSearched(true)
        if (res.ok) setDocuments(res.value.documents ?? [])
        else {
          setDocuments([])
          setSearchError(res.error)
        }
      })
      .finally(() => setSearching(false))
  }

  const goFields = (): void => {
    if (!kind || !documentPicked || !processId) return
    setPreparing(true)
    setPrepareError('')
    void prepareDocflowProcess(user, { kind: kind.id, process: processId, document: documentPicked })
      .then((res) => {
        if (!res.ok) {
          setPrepareError(res.error)
          return
        }
        setTitle((current) => current || res.value.name || documentLabel(documentPicked))
        setDescription((current) => current || res.value.description || '')
        setStep('fields')
      })
      .finally(() => setPreparing(false))
  }

  const filledPerformers = performers.filter((item) => item.fio.trim())
  const validateFields = (): string => {
    if (!title.trim()) return 'Укажите название задачи'
    if (!due) return 'Укажите срок'
    if (!filledPerformers.length) return 'Укажите, кому ставится задача'
    if (process && !process.multiple && filledPerformers.length > 1) {
      return `«${process.label}» назначается одному сотруднику`
    }
    if (process?.verifier && !verifier.trim()) return 'Укажите проверяющего'
    return ''
  }

  const goReview = (): void => {
    const problem = validateFields()
    setFieldsError(problem)
    if (!problem) {
      setConfirmed(false)
      setLaunchError('')
      setStep('review')
    }
  }

  const launch = (): void => {
    if (!kind || !documentPicked || !processId || !confirmed || launching) return
    setLaunching(true)
    setLaunchError('')
    void launchDocflowProcess(user, {
      kind: kind.id,
      process: processId,
      document: documentPicked,
      title,
      description,
      due,
      performers,
      verifier,
      sampleTaskIds
    })
      .then((res) => {
        if (!res.ok) {
          setLaunchError(res.error)
          return
        }
        setLaunchSummary(res.value.summary || 'Процесс запущен в документообороте.')
        setStep('done')
      })
      .finally(() => setLaunching(false))
  }

  const resetAll = (): void => {
    setStep('basis')
    pickKind('')
    setQuery('')
    setTitle('')
    setDescription('')
    setDue('')
    setPerformers([newPerformer()])
    setVerifier(me)
    setLaunchSummary('')
  }

  const patchPerformer = (key: string, patch: Partial<DocflowPerformerDraft>): void => {
    setPerformers((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)))
  }

  const stepIndex = STEPS.findIndex((item) => item.id === step)
  const stepValue = (id: Exclude<Step, 'done'>): string => {
    if (id === 'basis') return documentPicked ? documentLabel(documentPicked) : kind?.label || ''
    if (id === 'process') return process?.label || ''
    if (id === 'fields') return title && step !== 'fields' ? title : ''
    return ''
  }

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="docflow-page tc-page">
        <aside className="docflow-nav" aria-label="Шаги создания задачи">
          <p className="docflow-nav-kicker">Новая задача в 1С</p>
          {STEPS.map((item, index) => {
            const done = step === 'done' || index < stepIndex
            const active = item.id === step
            return (
              <button
                key={item.id}
                type="button"
                className={`docflow-nav-item tc-step${active ? ' is-active' : ''}${done ? ' is-done' : ''}`}
                disabled={!done || step === 'done'}
                onClick={() => setStep(item.id)}
              >
                <strong>
                  {index + 1}. {item.title}
                </strong>
                <span>{stepValue(item.id) || (active ? 'сейчас' : '—')}</span>
              </button>
            )
          })}
          <button type="button" className="spec-btn-outline tc-back" onClick={() => openWorkplaceTab('tasks')}>
            ← К задачам
          </button>
        </aside>

        <div className="docflow-main tc-main">
          {step === 'basis' ? (
            <>
              <header className="docflow-head">
                <div>
                  <h2>На основании какого документа?</h2>
                  <p>Задача в документообороте запускается по документу. По умолчанию ищем документы, где автор — вы.</p>
                </div>
              </header>
              {catalog ? (
                <div className="tc-kinds" role="radiogroup" aria-label="Вид документа-основания">
                  {catalog.kinds.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="radio"
                      aria-checked={kindId === item.id}
                      className={`docflow-kind-btn${kindId === item.id ? ' is-active' : ''}`}
                      onClick={() => pickKind(item.id)}
                    >
                      <strong>{item.label}</strong>
                      <span>{item.hint}</span>
                    </button>
                  ))}
                </div>
              ) : null}

              {kind ? (
                <div className="wp-card tc-search">
                  <div className="tc-search-bar">
                    {kind.types.length > 1 ? (
                      <select
                        className="wp-select"
                        value={typeId}
                        onChange={(event) => setTypeId(event.target.value)}
                        aria-label="Вид документа в 1С"
                      >
                        <option value="">Все виды: {kind.label.toLowerCase()}</option>
                        {kind.types.map((type) => (
                          <option key={type.id} value={type.id}>
                            {type.name}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    <input
                      className="onec-reconnect-input tc-search-input"
                      type="search"
                      value={query}
                      placeholder={`Номер или заголовок: ${kind.label.toLowerCase()}`}
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') runSearch()
                      }}
                    />
                    <label className="tc-check">
                      <input type="checkbox" checked={onlyMine} onChange={(event) => setOnlyMine(event.target.checked)} />
                      Только где я автор
                    </label>
                    <button type="button" className="spec-btn-launch" disabled={searching} onClick={runSearch}>
                      {searching ? 'Ищем…' : 'Найти'}
                    </button>
                  </div>
                  {catalogError ? (
                    <p className="spec-v04-muted tc-note">
                      Точные виды «{kind.label.toLowerCase()}» из 1С не загрузились, поиск идёт по всем. {catalogError}
                    </p>
                  ) : null}
                  {searchError ? <p className="docflow-status docflow-status-error">{searchError}</p> : null}
                  {searched && !searchError && !documents.length ? (
                    <p className="docflow-status">Документы не найдены. Уточните запрос или снимите «Только где я автор».</p>
                  ) : null}
                  {documents.length ? (
                    <div className="docflow-table-scroll tc-docs">
                      <table className="spec-v04-table docflow-table">
                        <thead>
                          <tr>
                            <th>Документ</th>
                            <th>Заголовок</th>
                            <th>Дата</th>
                            <th>Автор</th>
                          </tr>
                        </thead>
                        <tbody>
                          {documents.map((doc) => (
                            <tr
                              key={doc.id}
                              className={`docflow-row${documentPicked?.id === doc.id ? ' selected' : ''}`}
                              tabIndex={0}
                              onClick={() => setDocumentPicked(doc)}
                              onKeyDown={(event) => {
                                if (event.key === 'Enter') setDocumentPicked(doc)
                              }}
                            >
                              <td title={doc.name}>
                                <strong>{doc.name || doc.reg_number || '—'}</strong>
                              </td>
                              <td title={doc.title}>{doc.title || '—'}</td>
                              <td>{formatDay(doc.reg_date)}</td>
                              <td>{doc.author || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <footer className="tc-actions">
                <button
                  type="button"
                  className="spec-btn-launch"
                  disabled={!documentPicked}
                  onClick={() => setStep('process')}
                >
                  Далее: процесс
                </button>
              </footer>
            </>
          ) : null}

          {step === 'process' && kind && documentPicked ? (
            <>
              <header className="docflow-head">
                <div>
                  <h2>Какую задачу поставить?</h2>
                  <p>
                    По документу «{documentLabel(documentPicked)}» запускаются процессы, которые используются для вида «
                    {kind.label}».
                  </p>
                </div>
              </header>
              <div className="tc-kinds" role="radiogroup" aria-label="Процесс">
                {processDefs.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="radio"
                    aria-checked={processId === item.id}
                    className={`docflow-kind-btn${processId === item.id ? ' is-active' : ''}`}
                    onClick={() => setProcessId(item.id)}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.hint}</span>
                  </button>
                ))}
              </div>
              {prepareError ? <p className="docflow-status docflow-status-error">{prepareError}</p> : null}
              <footer className="tc-actions">
                <button type="button" className="spec-btn-outline" onClick={() => setStep('basis')}>
                  Назад
                </button>
                <button type="button" className="spec-btn-launch" disabled={!processId || preparing} onClick={goFields}>
                  {preparing ? 'Готовим процесс в 1С…' : 'Далее: поля задачи'}
                </button>
              </footer>
            </>
          ) : null}

          {step === 'fields' && process ? (
            <>
              <header className="docflow-head">
                <div>
                  <h2>{process.label}</h2>
                  <p>{process.hint}</p>
                </div>
              </header>
              <div className="wp-card tc-form">
                <label className="tc-field tc-field--wide">
                  <span className="modal-label">Название задачи *</span>
                  <input
                    className="onec-reconnect-input"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </label>
                <label className="tc-field tc-field--wide">
                  <span className="modal-label">Описание</span>
                  <textarea
                    className="onec-reconnect-input tc-textarea"
                    rows={3}
                    value={description}
                    placeholder="Что нужно сделать и какой результат ожидается"
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
                <label className="tc-field">
                  <span className="modal-label">Срок *</span>
                  <input
                    className="onec-reconnect-input"
                    type="date"
                    value={due}
                    onChange={(event) => setDue(event.target.value)}
                  />
                </label>
                {process.verifier ? (
                  <label className="tc-field">
                    <span className="modal-label">Проверяющий *</span>
                    <FioCombobox
                      value={verifier}
                      hints={fioHints}
                      placeholder="Начните вводить фамилию"
                      onChange={setVerifier}
                    />
                  </label>
                ) : null}

                <div className="tc-field tc-field--wide">
                  <div className="tc-performers-head">
                    <span className="modal-label">
                      {process.id === 'acquaintance'
                        ? 'Кто ознакомится *'
                        : process.id === 'consideration'
                          ? 'Кто рассмотрит *'
                          : 'Исполнители *'}
                    </span>
                    {process.multiple ? (
                      <button
                        type="button"
                        className="btn-light tc-add"
                        onClick={() => setPerformers((current) => [...current, newPerformer()])}
                      >
                        <Plus size={14} aria-hidden /> Добавить
                      </button>
                    ) : null}
                  </div>
                  <ul className="tc-performers">
                    {(process.multiple ? performers : performers.slice(0, 1)).map((item, index) => (
                      <li key={item.key} className="tc-performer">
                        <FioCombobox
                          value={item.fio}
                          hints={fioHints}
                          placeholder="Начните вводить фамилию"
                          onChange={(fio) => patchPerformer(item.key, { fio })}
                        />
                        {process.id === 'performance' ? (
                          <>
                            <input
                              className="onec-reconnect-input"
                              type="date"
                              value={item.due}
                              title="Личный срок (по умолчанию — общий)"
                              onChange={(event) => patchPerformer(item.key, { due: event.target.value })}
                            />
                            <input
                              className="onec-reconnect-input"
                              value={item.note}
                              placeholder={
                                index === 0 && performers.length > 1 ? 'Ответственный · пояснение' : 'Пояснение исполнителю'
                              }
                              onChange={(event) => patchPerformer(item.key, { note: event.target.value })}
                            />
                          </>
                        ) : null}
                        {process.multiple ? (
                          <button
                            type="button"
                            className="registry-create-line-remove"
                            title="Убрать"
                            disabled={performers.length <= 1}
                            onClick={() =>
                              setPerformers((current) => current.filter((row) => row.key !== item.key))
                            }
                          >
                            <Trash2 size={14} aria-hidden />
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                  {process.id === 'performance' ? (
                    <p className="spec-v04-muted tc-note">
                      Если исполнителей несколько, первый в списке — ответственный.
                    </p>
                  ) : null}
                </div>
              </div>
              {fieldsError ? <p className="docflow-status docflow-status-error">{fieldsError}</p> : null}
              <footer className="tc-actions">
                <button type="button" className="spec-btn-outline" onClick={() => setStep('process')}>
                  Назад
                </button>
                <button type="button" className="spec-btn-launch" onClick={goReview}>
                  Далее: проверка
                </button>
              </footer>
            </>
          ) : null}

          {step === 'review' && process && kind && documentPicked ? (
            <>
              <header className="docflow-head">
                <div>
                  <h2>Проверьте перед запуском</h2>
                  <p>После запуска задачи сразу появятся у сотрудников в 1С:Документооборот.</p>
                </div>
              </header>
              <div className="wp-card tc-review">
                <dl className="docflow-detail-list">
                  <div>
                    <dt>Основание</dt>
                    <dd>
                      {kind.label}: {documentLabel(documentPicked)}
                      {documentPicked.title ? ` — ${documentPicked.title}` : ''}
                    </dd>
                  </div>
                  <div>
                    <dt>Процесс</dt>
                    <dd>{process.label}</dd>
                  </div>
                  <div>
                    <dt>Название</dt>
                    <dd>{title}</dd>
                  </div>
                  <div>
                    <dt>Описание</dt>
                    <dd>{description || '—'}</dd>
                  </div>
                  <div>
                    <dt>Срок</dt>
                    <dd>{formatDay(due)}</dd>
                  </div>
                  <div>
                    <dt>Задачи получат</dt>
                    <dd>
                      {filledPerformers
                        .map((item, index) => {
                          const extra = [
                            process.id === 'performance' && index === 0 && filledPerformers.length > 1
                              ? 'ответственный'
                              : '',
                            item.due ? `срок ${formatDay(item.due)}` : ''
                          ]
                            .filter(Boolean)
                            .join(', ')
                          return extra ? `${item.fio} (${extra})` : item.fio
                        })
                        .join('\n')}
                    </dd>
                  </div>
                  {process.verifier ? (
                    <div>
                      <dt>Проверяющий</dt>
                      <dd>{verifier}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Автор</dt>
                    <dd>{me || '—'}</dd>
                  </div>
                </dl>
                <label className="tc-check tc-confirm">
                  <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
                  Понимаю, что задачи сразу уйдут этим сотрудникам в 1С
                </label>
              </div>
              {launchError ? <p className="docflow-status docflow-status-error">{launchError}</p> : null}
              <footer className="tc-actions">
                <button type="button" className="spec-btn-outline" disabled={launching} onClick={() => setStep('fields')}>
                  Назад
                </button>
                <button type="button" className="spec-btn-launch" disabled={!confirmed || launching} onClick={launch}>
                  {launching ? 'Запускаем в 1С…' : 'Запустить в 1С'}
                </button>
              </footer>
            </>
          ) : null}

          {step === 'done' ? (
            <div className="wp-card tc-done">
              <h2>Готово</h2>
              <p>{launchSummary}</p>
              <footer className="tc-actions">
                <button type="button" className="spec-btn-outline" onClick={resetAll}>
                  Создать ещё
                </button>
                <button type="button" className="spec-btn-launch" onClick={() => openWorkplaceTab('tasks')}>
                  К задачам
                </button>
              </footer>
            </div>
          ) : null}
        </div>
      </section>
    </OrchSlotMain>
  )
}
