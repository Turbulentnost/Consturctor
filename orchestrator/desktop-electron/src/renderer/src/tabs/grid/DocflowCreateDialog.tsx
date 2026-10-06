import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, FileText, Paperclip, Plus, Trash2, Upload, X } from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import {
  createDocflowDocument,
  displayValue,
  formatFileSize,
  initialValues,
  lookupDocflowCatalog,
  missingFields,
  readUploadFile,
  recallLastValues,
  rememberLastValues,
  type DocflowField,
  type DocflowKindSchema,
  type DocflowUploadFile
} from '../../workplace/docflowDocumentCreate'
import { erpActorFio } from '../../workplace/userContext'
import { FioCombobox } from './FioCombobox'
import './docflowCreate.css'

const USERS_CATALOG = 'Catalog_Пользователи'
const LOOKUP_DELAY_MS = 300

type Row = Record<string, string> & { __key: string }

function newRow(): Row {
  return { __key: `row-${Date.now()}-${Math.random().toString(36).slice(2, 7)}` }
}

function nowLabel(): string {
  return new Date().toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function RefInput({
  user,
  kind,
  field,
  value,
  userHints,
  onChange
}: {
  user: UserProfile
  kind: DocflowKindSchema['id']
  field: DocflowField
  value: string
  userHints: string[]
  onChange: (value: string) => void
}): React.JSX.Element {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [hints, setHints] = useState<string[]>([])
  const [active, setActive] = useState(false)
  const isUsers = field.catalog === USERS_CATALOG
  const lastQuery = useRef<string | null>(null)

  useEffect(() => {
    if (!active || isUsers || !field.catalog) return
    const query = value.trim()
    if (lastQuery.current === query) return
    const timer = window.setTimeout(() => {
      lastQuery.current = query
      void lookupDocflowCatalog(user, kind, field.catalog || '', query).then((items) => {
        if (lastQuery.current !== query) return
        setHints(items.map((item) => item.name))
      })
    }, LOOKUP_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [active, user, kind, field.catalog, isUsers, value])

  return (
    <div className="df1c-ref" ref={boxRef} onFocusCapture={() => setActive(true)}>
      <FioCombobox
        value={value}
        hints={isUsers ? userHints : hints}
        placeholder={field.hint || (isUsers ? 'ФИО' : 'Начните вводить…')}
        onChange={onChange}
      />
      {value ? (
        <button
          type="button"
          className="df1c-ref-btn"
          title="Очистить"
          tabIndex={-1}
          onClick={() => onChange('')}
        >
          <X size={13} aria-hidden />
        </button>
      ) : null}
      <button
        type="button"
        className="df1c-ref-btn"
        title="Выбрать из списка 1С"
        tabIndex={-1}
        onClick={() => boxRef.current?.querySelector('input')?.focus()}
      >
        <ChevronDown size={14} aria-hidden />
      </button>
    </div>
  )
}

function FieldInput({
  user,
  kind,
  field,
  value,
  userHints,
  onChange
}: {
  user: UserProfile
  kind: DocflowKindSchema['id']
  field: DocflowField
  value: string
  userHints: string[]
  onChange: (value: string) => void
}): React.JSX.Element {
  if (field.type === 'ref') {
    return <RefInput user={user} kind={kind} field={field} value={value} userHints={userHints} onChange={onChange} />
  }
  if (field.type === 'enum') {
    return (
      <select className="df1c-input" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="" />
        {(field.options || []).map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    )
  }
  if (field.type === 'textarea') {
    return (
      <textarea
        className="df1c-input df1c-textarea"
        rows={4}
        value={value}
        placeholder={field.hint}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }
  return (
    <input
      className={`df1c-input${field.type === 'number' ? ' df1c-number' : ''}${field.type === 'date' ? ' df1c-date' : ''}`}
      type={field.type === 'date' ? 'date' : 'text'}
      inputMode={field.type === 'number' ? 'decimal' : undefined}
      value={value}
      placeholder={field.hint}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

export function DocflowCreateDialog({
  open,
  user,
  schema,
  onClose,
  onCreated
}: {
  open: boolean
  user: UserProfile
  schema: DocflowKindSchema | null
  onClose: () => void
  onCreated: (message: string) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [autofilled, setAutofilled] = useState<string[]>([])
  const [tables, setTables] = useState<Record<string, Row[]>>({})
  const [files, setFiles] = useState<DocflowUploadFile[]>([])
  const [tab, setTab] = useState<'main' | 'files'>('main')
  const [confirming, setConfirming] = useState(false)
  const [showMissing, setShowMissing] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [userHints, setUserHints] = useState<string[]>([])
  const [openedAt, setOpenedAt] = useState(nowLabel)

  useEffect(() => {
    if (!open || !schema) return
    const base = initialValues(schema, erpActorFio(user))
    const last = recallLastValues(user.id, schema)
    setValues({ ...base, ...last })
    setAutofilled(Object.keys(last))
    setTables(Object.fromEntries(schema.tables.map((table) => [table.key, []])))
    setFiles([])
    setTab('main')
    setConfirming(false)
    setShowMissing(false)
    setBusy(false)
    setError('')
    setOpenedAt(nowLabel())
  }, [open, schema, user])

  useEffect(() => {
    if (!open || !schema?.fields.some((field) => field.catalog === USERS_CATALOG)) return
    let cancelled = false
    void api.searchUsers('', 20000).then((items) => {
      if (!cancelled) setUserHints(items)
    })
    return () => {
      cancelled = true
    }
  }, [open, schema])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  if (!open || !schema) return null

  const maxFiles = schema.max_files || 10
  const maxBytes = (schema.max_file_mb || 20) * 1024 * 1024
  const missing = missingFields(schema, values)
  const missingKeys = new Set(missing.map((field) => field.key))

  const setValue = (key: string, value: string): void => {
    setValues((current) => ({ ...current, [key]: value }))
    setAutofilled((current) => current.filter((item) => item !== key))
    setConfirming(false)
  }

  const clearAutofill = (): void => {
    const base = initialValues(schema, erpActorFio(user))
    setValues((current) => {
      const next = { ...current }
      for (const key of autofilled) next[key] = base[key] || ''
      return next
    })
    setAutofilled([])
  }

  const addFiles = async (list: FileList | File[]): Promise<void> => {
    if (!schema.files) return
    const incoming = Array.from(list)
    const problems: string[] = []
    const accepted: DocflowUploadFile[] = []
    for (const file of incoming) {
      if (file.size > maxBytes) problems.push(`«${file.name}» больше ${schema.max_file_mb || 20} МБ`)
      else if (!file.size) problems.push(`«${file.name}» пустой`)
      else {
        try {
          accepted.push(await readUploadFile(file))
        } catch (err) {
          problems.push(err instanceof Error ? err.message : `«${file.name}» не прочитан`)
        }
      }
    }
    const names = new Set(files.map((file) => file.name))
    const merged = [...files, ...accepted.filter((file) => !names.has(file.name))]
    if (merged.length > maxFiles) problems.push(`Не больше ${maxFiles} файлов`)
    setFiles(merged.slice(0, maxFiles))
    setError(problems.join('; '))
    setConfirming(false)
    if (accepted.length) setTab('files')
  }

  const patchRow = (tableKey: string, rowKey: string, column: string, value: string): void => {
    setTables((current) => ({
      ...current,
      [tableKey]: (current[tableKey] || []).map((row) => (row.__key === rowKey ? { ...row, [column]: value } : row))
    }))
  }

  const askConfirm = (): void => {
    if (missing.length) {
      setShowMissing(true)
      setTab('main')
      setError(`Заполните: ${missing.map((field) => field.label).join(', ')}`)
      return
    }
    setError('')
    setConfirming(true)
  }

  async function submit(): Promise<void> {
    if (!schema) return
    setBusy(true)
    setError('')
    try {
      const payloadTables = Object.fromEntries(
        Object.entries(tables).map(([key, rows]) => [
          key,
          rows.map(({ __key: _drop, ...rest }) => rest).filter((row) => Object.values(row).some((v) => v.trim()))
        ])
      )
      const result = await createDocflowDocument(user, schema.id, values, payloadTables, files)
      if (!result.ok) {
        setError(result.error)
        setConfirming(false)
        return
      }
      rememberLastValues(user.id, schema, values)
      onCreated(result.summary)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  const renderField = (field: DocflowField, wide = false): React.JSX.Element => {
    const invalid = showMissing && missingKeys.has(field.key)
    return (
      <div
        key={field.key}
        className={`df1c-row${wide ? ' df1c-row--wide' : ''}${invalid ? ' is-invalid' : ''}${
          field.required ? ' is-required' : ''
        }${autofilled.includes(field.key) ? ' is-autofilled' : ''}`}
      >
        <label className="df1c-label" title={field.required ? 'Обязательное поле' : undefined}>
          {field.label}:
        </label>
        <div className="df1c-control">
          <FieldInput
            user={user}
            kind={schema.id}
            field={field}
            value={values[field.key] || ''}
            userHints={userHints}
            onChange={(value) => setValue(field.key, value)}
          />
        </div>
      </div>
    )
  }

  const left = schema.fields.filter((field) => (field.side || 'left') === 'left')
  const right = schema.fields.filter((field) => field.side === 'right')
  const wide = schema.fields.filter((field) => field.side === 'wide')
  const topic = values.ТемаСлужебнойЗаписки || values.theme || values.Заголовок || ''

  return createPortal(
    <div className="modal-overlay df1c-overlay" onClick={() => !busy && onClose()} role="presentation">
      <div
        className={`df1c-window${dragging ? ' is-dragging' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        onDragOver={(event) => {
          if (!schema.files || !event.dataTransfer.types.includes('Files')) return
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
          setDragging(false)
        }}
        onDrop={(event) => {
          if (!schema.files) return
          event.preventDefault()
          setDragging(false)
          void addFiles(event.dataTransfer.files)
        }}
      >
        <header className="df1c-title">
          <h2 id={titleId}>{schema.title} (создание)</h2>
          <button type="button" className="df1c-close" title="Закрыть" disabled={busy} onClick={onClose}>
            <X size={18} aria-hidden />
          </button>
        </header>

        <nav className="df1c-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'main'}
            className={tab === 'main' ? 'is-active' : ''}
            onClick={() => setTab('main')}
          >
            Основное
          </button>
          {schema.files ? (
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'files'}
              className={tab === 'files' ? 'is-active' : ''}
              onClick={() => setTab('files')}
            >
              Файлы{files.length ? ` (${files.length})` : ''}
            </button>
          ) : null}
        </nav>

        <div className="df1c-toolbar">
          {confirming ? (
            <div className="df1c-confirm">
              <span>
                Записать черновик{topic ? ` «${topic.trim().slice(0, 60)}»` : ''} в 1С
                {files.length ? `, файлов: ${files.length}` : ''}?
              </span>
              <button type="button" className="df1c-btn df1c-btn--primary" disabled={busy} onClick={() => void submit()}>
                {busy ? 'Записываем…' : 'Да, записать'}
              </button>
              <button type="button" className="df1c-btn" disabled={busy} onClick={() => setConfirming(false)}>
                Вернуться
              </button>
            </div>
          ) : (
            <>
              <button type="button" className="df1c-btn df1c-btn--primary" disabled={busy} onClick={askConfirm}>
                Записать в 1С
              </button>
              {schema.files ? (
                <button type="button" className="df1c-btn" onClick={() => fileInputRef.current?.click()}>
                  <Paperclip size={14} aria-hidden /> Прикрепить файл
                </button>
              ) : null}
              <button type="button" className="df1c-btn" disabled={busy} onClick={onClose}>
                Отмена
              </button>
              {autofilled.length ? (
                <span className="df1c-autofill-note">
                  Заполнено как в прошлом документе
                  <button type="button" onClick={clearAutofill}>
                    очистить
                  </button>
                </span>
              ) : null}
            </>
          )}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files?.length) void addFiles(event.target.files)
            event.target.value = ''
          }}
        />

        {error ? <p className="df1c-error">{error}</p> : null}

        <div className="df1c-body">
          {tab === 'main' ? (
            <>
              <div className="df1c-columns">
                <div className="df1c-col">
                  <div className="df1c-row">
                    <label className="df1c-label">Номер:</label>
                    <div className="df1c-control df1c-inline">
                      <input className="df1c-input df1c-readonly" value="присвоит 1С" readOnly tabIndex={-1} />
                      <span className="df1c-inline-label">от:</span>
                      <input className="df1c-input df1c-readonly" value={openedAt} readOnly tabIndex={-1} />
                    </div>
                  </div>
                  {left.map((field) => renderField(field))}
                </div>
                <div className="df1c-col">{right.map((field) => renderField(field))}</div>
              </div>
              {wide.map((field) => renderField(field, true))}

              {schema.tables.map((table) => (
                <section key={table.key} className="df1c-table">
                  <div className="df1c-table-head">
                    <h3>{table.label}</h3>
                    <button
                      type="button"
                      className="df1c-btn"
                      onClick={() =>
                        setTables((current) => ({ ...current, [table.key]: [...(current[table.key] || []), newRow()] }))
                      }
                    >
                      <Plus size={14} aria-hidden /> Добавить
                    </button>
                  </div>
                  {(tables[table.key] || []).length ? (
                    <table>
                      <thead>
                        <tr>
                          <th className="df1c-num">N</th>
                          {table.columns.map((column) => (
                            <th key={column.key}>{column.label}</th>
                          ))}
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {(tables[table.key] || []).map((row, index) => (
                          <tr key={row.__key}>
                            <td className="df1c-num">{index + 1}</td>
                            {table.columns.map((column) => (
                              <td key={column.key}>
                                <FieldInput
                                  user={user}
                                  kind={schema.id}
                                  field={column}
                                  value={row[column.key] || ''}
                                  userHints={userHints}
                                  onChange={(value) => patchRow(table.key, row.__key, column.key, value)}
                                />
                              </td>
                            ))}
                            <td>
                              <button
                                type="button"
                                className="df1c-icon-btn"
                                title="Удалить строку"
                                onClick={() =>
                                  setTables((current) => ({
                                    ...current,
                                    [table.key]: (current[table.key] || []).filter((item) => item.__key !== row.__key)
                                  }))
                                }
                              >
                                <Trash2 size={14} aria-hidden />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="df1c-muted">Строк нет — 1С получит одну строку на всю сумму документа.</p>
                  )}
                </section>
              ))}

              {schema.base === 'do' ? (
                <p className="df1c-muted">
                  Документ создаётся в 1С:Документообороте под вашей учёткой. Файлы и маршрут согласования — в самой 1С.
                </p>
              ) : (
                <p className="df1c-muted">
                  Документ запишется черновиком: провести и отправить на согласование можно в 1С.
                </p>
              )}
            </>
          ) : (
            <div className="df1c-files">
              <button type="button" className="df1c-drop" onClick={() => fileInputRef.current?.click()}>
                <Upload size={22} aria-hidden />
                <strong>Перетащите файлы сюда или нажмите, чтобы выбрать</strong>
                <span>
                  До {maxFiles} файлов, каждый до {schema.max_file_mb || 20} МБ. Прикрепятся к документу сразу после
                  записи.
                </span>
              </button>
              {files.length ? (
                <ul className="df1c-file-list">
                  {files.map((file) => (
                    <li key={file.name}>
                      <FileText size={16} aria-hidden />
                      <span className="df1c-file-name" title={file.name}>
                        {file.name}
                      </span>
                      <span className="df1c-muted">{formatFileSize(file.size)}</span>
                      <button
                        type="button"
                        className="df1c-icon-btn"
                        title="Убрать файл"
                        onClick={() => setFiles((current) => current.filter((item) => item.name !== file.name))}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </div>

        {confirming ? (
          <footer className="df1c-summary">
            {schema.fields
              .filter((field) => (values[field.key] || '').trim())
              .slice(0, 8)
              .map((field) => (
                <span key={field.key}>
                  <b>{field.label}:</b> {displayValue(field, values[field.key] || '').slice(0, 80)}
                </span>
              ))}
          </footer>
        ) : null}

        {dragging ? (
          <div className="df1c-drag-cover" aria-hidden>
            <Upload size={28} />
            Отпустите, чтобы прикрепить
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  )
}
