import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  ChevronDown,
  Copy,
  ExternalLink,
  FilePlus2,
  FileText,
  Lock,
  Paperclip,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  X
} from 'lucide-react'
import { api } from '../../api/client'
import type { UserProfile } from '../../api/types'
import {
  attachDocflowFiles,
  createDocflowDocument,
  displayValue,
  docflowBasisValues,
  formatFileSize,
  initialValues,
  lookupDocflowCatalog,
  postDocflowDocument,
  missingFields,
  readDocflowDocument,
  readUploadFile,
  recallLastValues,
  rememberLastValues,
  updateDocflowDocument,
  type DocflowCard,
  type DocflowField,
  type DocflowFormRequest,
  type DocflowKindId,
  type DocflowKindSchema,
  type DocflowTableRow,
  type DocflowUploadFile
} from '../../workplace/docflowDocumentCreate'
import { openDocflowAttachment } from '../../workplace/docflowAttachments'
import { erpActorFio } from '../../workplace/userContext'
import { FioCombobox } from './FioCombobox'
import './docflowCreate.css'

const USERS_CATALOG = 'Catalog_Пользователи'
const LOOKUP_DELAY_MS = 300

/** keys — GUID ссылок из 1С; ячейку поменяли — её GUID забываем и 1С ищет по введённому тексту. */
type Row = DocflowTableRow & { id: string }
type Pending = 'save' | 'save-close' | 'post' | 'post-close' | 'attach' | 'close' | null

function newRow(source?: DocflowTableRow): Row {
  return {
    cells: { ...(source?.cells || {}) },
    keys: { ...(source?.keys || {}) },
    id: `row-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  }
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

function dateLabel(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso || '')
  if (!match) return iso || ''
  const [, y, m, d, hh, mm] = match
  return `${d}.${m}.${y}${hh && `${hh}:${mm}` !== '00:00' ? ` ${hh}:${mm}` : ''}`
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
  kind: DocflowKindId
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
        <button type="button" className="df1c-ref-btn" title="Очистить" tabIndex={-1} onClick={() => onChange('')}>
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
  readOnly,
  onChange
}: {
  user: UserProfile
  kind: DocflowKindId
  field: DocflowField
  value: string
  userHints: string[]
  readOnly: boolean
  onChange: (value: string) => void
}): React.JSX.Element {
  if (readOnly) {
    const shown = field.type === 'date' ? dateLabel(value) : displayValue(field, value)
    if (field.type === 'textarea') {
      return <div className="df1c-input df1c-readonly df1c-textarea df1c-static">{shown}</div>
    }
    return <input className="df1c-input df1c-readonly" value={shown} readOnly title={shown} />
  }
  if (field.type === 'ref') {
    return <RefInput user={user} kind={kind} field={field} value={value} userHints={userHints} onChange={onChange} />
  }
  if (field.type === 'enum') {
    const known = !value || (field.options || []).some((item) => item.value === value)
    return (
      <select className="df1c-input" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="" />
        {known ? null : <option value={value}>{value}</option>}
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

/**
 * Форма документа как в 1С: создание, создание на основании, копия и открытие записанного.
 * Записанный черновик меняется только в тронутых полях; проведённый открывается на просмотр —
 * с него можно создать новый документ на основании, скопировать и прикрепить файлы.
 */
export function DocflowCreateDialog({
  user,
  request,
  schemas,
  onClose,
  onRequest,
  onSaved
}: {
  user: UserProfile
  request: DocflowFormRequest | null
  schemas: DocflowKindSchema[]
  onClose: () => void
  onRequest: (next: DocflowFormRequest) => void
  onSaved: (message: string) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const schema = request ? schemas.find((item) => item.id === request.kind) || null : null
  const editing = request?.mode === 'edit'
  const prefill = request?.mode === 'create' ? request.prefill : undefined
  const fields = schema ? (editing ? schema.edit_fields || schema.fields : schema.fields) : []

  const [card, setCard] = useState<DocflowCard | null>(null)
  const [cardLoading, setCardLoading] = useState(false)
  const [reload, setReload] = useState(0)
  const [values, setValues] = useState<Record<string, string>>({})
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [changed, setChanged] = useState<string[]>([])
  const [autofilled, setAutofilled] = useState<string[]>([])
  const [tables, setTables] = useState<Record<string, Row[]>>({})
  const [files, setFiles] = useState<DocflowUploadFile[]>([])
  const [tab, setTab] = useState<'main' | 'files'>('main')
  const [pending, setPending] = useState<Pending>(null)
  const [showMissing, setShowMissing] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [basisOpen, setBasisOpen] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [userHints, setUserHints] = useState<string[]>([])
  const [openedAt, setOpenedAt] = useState(nowLabel)

  const resetState = (): void => {
    setChanged([])
    setFiles([])
    setPending(null)
    setShowMissing(false)
    setBusy(false)
    setBasisOpen(false)
    setError('')
  }

  useEffect(() => {
    if (!request || !schema) return
    resetState()
    setTab('main')
    setNotice('')
    setOpenedAt(nowLabel())
    setCard(null)
    if (request.mode === 'create') {
      setCardLoading(false)
      const base = initialValues(schema, erpActorFio(user))
      const last = request.prefill ? {} : recallLastValues(user.id, schema)
      const given = request.prefill?.values || {}
      setValues({ ...base, ...last, ...given })
      setKeys({ ...(request.prefill?.keys || {}) })
      setAutofilled(request.prefill ? Object.keys(given) : Object.keys(last))
      setTables(
        Object.fromEntries(
          schema.tables.map((table) => [table.key, (request.prefill?.tables[table.key] || []).map((row) => newRow(row))])
        )
      )
    }
  }, [request, schema, user])

  useEffect(() => {
    if (!request || request.mode !== 'edit' || !schema) return
    let alive = true
    setCardLoading(true)
    setError('')
    void readDocflowDocument(user, request.kind, request.refKey)
      .then((loaded) => {
        if (!alive) return
        setCard(loaded)
        setValues(loaded.values)
        setKeys(loaded.keys)
        setAutofilled([])
        setChanged([])
        setTables(
          Object.fromEntries(schema.tables.map((table) => [table.key, (loaded.tables[table.key] || []).map((row) => newRow(row))]))
        )
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось открыть документ')
      })
      .finally(() => {
        if (alive) setCardLoading(false)
      })
    return () => {
      alive = false
    }
  }, [request, schema, user, reload])

  useEffect(() => {
    const needUsers =
      fields.some((field) => field.catalog === USERS_CATALOG) ||
      schema?.tables.some((table) => table.columns.some((column) => column.catalog === USERS_CATALOG))
    if (!request || !needUsers || userHints.length) return
    let cancelled = false
    void api.searchUsers('', 20000).then((items) => {
      if (!cancelled) setUserHints(items)
    })
    return () => {
      cancelled = true
    }
  }, [request, fields, schema, userHints.length])

  const dirty = changed.length > 0 || (!editing && files.length > 0)

  useEffect(() => {
    if (!request) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape' || busy) return
      if (basisOpen) setBasisOpen(false)
      else if (dirty && editing) setPending('close')
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [request, busy, basisOpen, dirty, editing, onClose])

  if (!request || !schema) return null

  const readOnly = editing && (!card || !card.editable)
  const maxFiles = schema.max_files || 10
  const maxBytes = (schema.max_file_mb || 20) * 1024 * 1024
  const missing = missingFields(fields, values)
  const missingKeys = new Set(missing.map((field) => field.key))
  const existingFiles = card?.files || []
  const basisTargets = (schema.basis_targets || []).filter((target) => schemas.some((item) => item.id === target.id))

  const markChanged = (key: string): void => {
    setChanged((current) => (current.includes(key) ? current : [...current, key]))
    setPending(null)
    setNotice('')
  }

  const setValue = (key: string, value: string): void => {
    setValues((current) => ({ ...current, [key]: value }))
    setKeys((current) => {
      if (!(key in current)) return current
      const next = { ...current }
      delete next[key]
      return next
    })
    setAutofilled((current) => current.filter((item) => item !== key))
    markChanged(key)
  }

  const clearAutofill = (): void => {
    const base = initialValues(schema, erpActorFio(user))
    setValues((current) => {
      const next = { ...current }
      for (const key of autofilled) next[key] = base[key] || ''
      return next
    })
    setKeys((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !autofilled.includes(key))))
    setAutofilled([])
  }

  const updateTable = (tableKey: string, update: (rows: Row[]) => Row[]): void => {
    setTables((current) => ({ ...current, [tableKey]: update(current[tableKey] || []) }))
    markChanged(tableKey)
  }

  const patchRow = (tableKey: string, rowKey: string, column: string, value: string): void => {
    updateTable(tableKey, (rows) =>
      rows.map((row) => {
        if (row.id !== rowKey) return row
        const refs = { ...row.keys }
        delete refs[column]
        return { ...row, cells: { ...row.cells, [column]: value }, keys: refs }
      })
    )
  }

  const addFiles = async (list: FileList | File[]): Promise<void> => {
    if (!schema.files) return
    const problems: string[] = []
    const accepted: DocflowUploadFile[] = []
    for (const file of Array.from(list)) {
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
    if (merged.length > maxFiles) problems.push(`Не больше ${maxFiles} файлов за раз`)
    setFiles(merged.slice(0, maxFiles))
    setError(problems.join('; '))
    setNotice('')
    if (!accepted.length) return
    setTab('files')
    setPending(editing ? 'attach' : null)
  }

  const payloadValues = (): Record<string, string> =>
    Object.fromEntries(fields.map((field) => [field.key, keys[field.key] || values[field.key] || '']))

  const payloadTables = (): Record<string, Record<string, string>[]> =>
    Object.fromEntries(
      schema.tables.map((table) => [
        table.key,
        (tables[table.key] || [])
          .map((row) =>
            Object.fromEntries(table.columns.map((column) => [column.key, row.keys[column.key] || row.cells[column.key] || '']))
          )
          .filter((row) => Object.values(row).some((value) => value.trim()))
      ])
    )

  const askSave = (close: boolean): void => {
    if (editing && !changed.length) {
      if (close) onClose()
      else setNotice('Изменений нет — записывать нечего')
      return
    }
    if (missing.length) {
      setShowMissing(true)
      setTab('main')
      setError(`Заполните: ${missing.map((field) => field.label).join(', ')}`)
      return
    }
    setError('')
    setPending(close ? 'save-close' : 'save')
  }

  async function save(close: boolean, post = false): Promise<void> {
    if (!request || !schema) return
    setBusy(true)
    setError('')
    try {
      if (request.mode === 'create') {
        const result = await createDocflowDocument(
          user,
          schema.id,
          payloadValues(),
          payloadTables(),
          files,
          request.prefill?.basis || null,
          post
        )
        if (!result.ok) {
          setError(result.error)
          setPending(null)
          return
        }
        if (!request.prefill) rememberLastValues(user.id, schema, values)
        onSaved(result.summary)
        if (close) onClose()
        else onRequest({ mode: 'edit', kind: schema.id, refKey: result.refKey })
        return
      }
      const result = await updateDocflowDocument(
        user,
        schema.id,
        request.refKey,
        payloadValues(),
        changed,
        payloadTables()
      )
      if (!result.ok) {
        setError(result.error)
        setPending(null)
        return
      }
      if (post) {
        const posted = await postDocflowDocument(user, schema.id, request.refKey)
        if (!posted.ok) {
          setError(posted.error)
          setPending(null)
          setReload((value) => value + 1)
          return
        }
        onSaved(posted.summary)
        if (close) onClose()
        else {
          setNotice(posted.summary)
          setPending(null)
          setReload((value) => value + 1)
        }
        return
      }
      onSaved(result.summary)
      if (close) onClose()
      else {
        setNotice(result.summary)
        setPending(null)
        setReload((value) => value + 1)
      }
    } finally {
      setBusy(false)
    }
  }

  async function attach(): Promise<void> {
    if (request?.mode !== 'edit' || !files.length) return
    setBusy(true)
    setError('')
    try {
      const result = await attachDocflowFiles(user, request.kind, request.refKey, files)
      if (!result.ok) {
        setError(result.error)
        setPending(null)
        return
      }
      setFiles((current) => current.filter((file) => result.failedFiles.includes(file.name)))
      setNotice(result.summary)
      setPending(null)
      setReload((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  async function createFrom(target: DocflowKindId): Promise<void> {
    if (request?.mode !== 'edit') return
    setBasisOpen(false)
    setBusy(true)
    setError('')
    try {
      const filled = await docflowBasisValues(user, request.kind, request.refKey, target)
      onRequest({ mode: 'create', kind: target, prefill: filled })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось заполнить документ')
    } finally {
      setBusy(false)
    }
  }

  const tryClose = (): void => {
    if (busy) return
    if (dirty && editing) setPending('close')
    else onClose()
  }

  const renderField = (field: DocflowField, wide = false): React.JSX.Element => {
    const invalid = showMissing && missingKeys.has(field.key)
    return (
      <div
        key={field.key}
        className={`df1c-row${wide ? ' df1c-row--wide' : ''}${invalid ? ' is-invalid' : ''}${
          field.required && !readOnly ? ' is-required' : ''
        }${autofilled.includes(field.key) ? ' is-autofilled' : ''}${changed.includes(field.key) && editing ? ' is-changed' : ''}`}
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
            readOnly={readOnly}
            onChange={(value) => setValue(field.key, value)}
          />
        </div>
      </div>
    )
  }

  const left = fields.filter((field) => (field.side || 'left') === 'left')
  const right = fields.filter((field) => field.side === 'right')
  const wide = fields.filter((field) => field.side === 'wide')
  const topic =
    values.ТемаСлужебнойЗаписки || values.theme || values.Заголовок || values.ОЧем || values.НазначениеПлатежа || ''
  const basisLabel = prefill?.label || card?.basisLabel || ''
  const changedLabels = fields.filter((field) => changed.includes(field.key)).map((field) => field.label)
  changedLabels.push(...schema.tables.filter((table) => changed.includes(table.key)).map((table) => table.label))

  const title = editing
    ? card
      ? `${schema.title} ${card.number}${card.date ? ` от ${dateLabel(card.date)}` : ''}`
      : schema.title
    : `${schema.title} (${prefill ? (prefill.copy ? 'копия' : 'создание на основании') : 'создание'})`

  const confirmText =
    pending === 'attach'
      ? `Прикрепить к документу ${card?.number || ''} файлов: ${files.length}?`
      : pending === 'close'
        ? 'Данные были изменены. Закрыть без записи?'
        : pending === 'post' || pending === 'post-close'
          ? `Провести документ${pending === 'post-close' ? ' и закрыть форму' : ''}${
              files.length && !editing ? `, файлов: ${files.length}` : ''
            }?`
          : editing
            ? `Записать изменения (${changedLabels.slice(0, 4).join(', ')}${changedLabels.length > 4 ? '…' : ''})?`
            : `Записать черновик${topic ? ` «${topic.trim().slice(0, 60)}»` : ''}${
                files.length ? `, файлов: ${files.length}` : ''
              }?`

  return createPortal(
    <div className="modal-overlay df1c-overlay" onClick={tryClose} role="presentation">
      <div
        className={`df1c-window${dragging ? ' is-dragging' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => {
          event.stopPropagation()
          if (basisOpen) setBasisOpen(false)
        }}
        onDragOver={(event) => {
          if (!schema.files || !event.dataTransfer.types.includes('Files') || (editing && !card)) return
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
          setDragging(false)
        }}
        onDrop={(event) => {
          if (!schema.files || (editing && !card)) return
          event.preventDefault()
          setDragging(false)
          void addFiles(event.dataTransfer.files)
        }}
      >
        <header className="df1c-title">
          <h2 id={titleId}>
            {title}
            {card?.deleted ? <span className="df1c-badge is-deleted">помечен на удаление</span> : null}
            {card && !card.deleted && card.posted ? <span className="df1c-badge is-posted">проведён</span> : null}
            {card && !card.deleted && !card.posted ? <span className="df1c-badge">черновик</span> : null}
            {card?.status ? <span className="df1c-badge is-status">{card.status}</span> : null}
          </h2>
          <button type="button" className="df1c-close" title="Закрыть" disabled={busy} onClick={tryClose}>
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
              Файлы{existingFiles.length + files.length ? ` (${existingFiles.length + files.length})` : ''}
            </button>
          ) : null}
        </nav>

        <div className="df1c-toolbar">
          {pending ? (
            <div className="df1c-confirm">
              <span>{confirmText}</span>
              <button
                type="button"
                className="df1c-btn df1c-btn--primary"
                disabled={busy}
                onClick={() => {
                  if (pending === 'attach') void attach()
                  else if (pending === 'close') onClose()
                  else void save(pending === 'save-close' || pending === 'post-close', pending === 'post' || pending === 'post-close')
                }}
              >
                {busy
                  ? pending === 'post' || pending === 'post-close'
                    ? 'Проводим…'
                    : 'Записываем…'
                  : pending === 'close'
                    ? 'Закрыть без записи'
                    : pending === 'attach'
                      ? 'Прикрепить'
                      : pending === 'post'
                        ? 'Провести'
                        : pending === 'post-close'
                          ? 'Провести и закрыть'
                          : 'Записать'}
              </button>
              <button
                type="button"
                className="df1c-btn"
                disabled={busy}
                onClick={() => {
                  if (pending === 'attach') setFiles([])
                  setPending(null)
                }}
              >
                {pending === 'attach' ? 'Не прикреплять' : 'Вернуться'}
              </button>
            </div>
          ) : (
            <>
              {!readOnly ? (
                <>
                  <button type="button" className="df1c-btn df1c-btn--primary" disabled={busy || cardLoading} onClick={() => askSave(false)}>
                    Записать
                  </button>
                  {schema.base === 'erp' ? (
                    <>
                      <button
                        type="button"
                        className="df1c-btn"
                        disabled={busy || cardLoading}
                        onClick={() => {
                          if (editing && !changed.length) {
                            setPending('post')
                            return
                          }
                          if (missing.length) {
                            setShowMissing(true)
                            setTab('main')
                            setError(`Заполните: ${missing.map((field) => field.label).join(', ')}`)
                            return
                          }
                          setError('')
                          setPending('post')
                        }}
                      >
                        Провести
                      </button>
                      <button
                        type="button"
                        className="df1c-btn"
                        disabled={busy || cardLoading}
                        onClick={() => {
                          if (missing.length) {
                            setShowMissing(true)
                            setTab('main')
                            setError(`Заполните: ${missing.map((field) => field.label).join(', ')}`)
                            return
                          }
                          setError('')
                          setPending('post-close')
                        }}
                      >
                        Провести и закрыть
                      </button>
                    </>
                  ) : (
                    <button type="button" className="df1c-btn" disabled={busy || cardLoading} onClick={() => askSave(true)}>
                      Записать и закрыть
                    </button>
                  )}
                </>
              ) : null}
              {editing && card && basisTargets.length ? (
                <div className="df1c-menu-wrap">
                  <button
                    type="button"
                    className="df1c-btn"
                    disabled={busy || changed.length > 0}
                    title={changed.length ? 'Сначала запишите изменения' : 'Создать новый документ, заполненный из этого'}
                    onClick={(event) => {
                      event.stopPropagation()
                      setBasisOpen((value) => !value)
                    }}
                  >
                    <FilePlus2 size={14} aria-hidden /> Создать на основании <ChevronDown size={13} aria-hidden />
                  </button>
                  {basisOpen ? (
                    <ul className="df1c-menu" role="menu">
                      {basisTargets.map((target) => (
                        <li key={target.id}>
                          <button type="button" role="menuitem" onClick={() => void createFrom(target.id)}>
                            {target.title}
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
              {editing && card && schema.copy ? (
                <button
                  type="button"
                  className="df1c-btn"
                  disabled={busy || changed.length > 0}
                  title={changed.length ? 'Сначала запишите изменения' : 'Новый документ с теми же реквизитами'}
                  onClick={() => void createFrom(schema.id)}
                >
                  <Copy size={14} aria-hidden /> Скопировать
                </button>
              ) : null}
              {schema.files && (!editing || (card && !card.deleted)) ? (
                <button type="button" className="df1c-btn" disabled={busy} onClick={() => fileInputRef.current?.click()}>
                  <Paperclip size={14} aria-hidden /> Прикрепить файл
                </button>
              ) : null}
              {card?.webUrl ? (
                <button
                  type="button"
                  className="df1c-btn"
                  title="Открыть этот документ в веб-клиенте 1С"
                  onClick={() => window.open(card.webUrl, '_blank', 'noopener,noreferrer')}
                >
                  <ExternalLink size={14} aria-hidden /> Открыть в 1С
                </button>
              ) : null}
              {editing ? (
                <button
                  type="button"
                  className="df1c-icon-btn df1c-refresh"
                  title="Перечитать из 1С"
                  disabled={busy || cardLoading}
                  onClick={() => (changed.length ? setPending('close') : setReload((value) => value + 1))}
                >
                  <RefreshCw size={14} aria-hidden />
                </button>
              ) : null}
              <button type="button" className="df1c-btn" disabled={busy} onClick={tryClose}>
                {editing ? 'Закрыть' : 'Отмена'}
              </button>
              {autofilled.length && !editing ? (
                <span className="df1c-autofill-note">
                  {prefill ? (prefill.copy ? 'Скопировано из документа' : 'Заполнено из основания') : 'Заполнено как в прошлом документе'}
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
        {notice && !error ? <p className="df1c-notice">{notice}</p> : null}
        {readOnly && card?.readonlyReason ? (
          <p className="df1c-readonly-banner">
            <Lock size={14} aria-hidden /> {card.readonlyReason}
          </p>
        ) : null}

        <div className="df1c-body">
          {editing && cardLoading && !card ? (
            <p className="df1c-muted df1c-loading">Открываем документ из 1С…</p>
          ) : editing && !card ? (
            <p className="df1c-muted df1c-loading">
              Документ не открылся.{' '}
              <button type="button" className="df1c-link" onClick={() => setReload((value) => value + 1)}>
                Повторить
              </button>
            </p>
          ) : tab === 'main' ? (
            <>
              <div className="df1c-columns">
                <div className="df1c-col">
                  <div className="df1c-row">
                    <label className="df1c-label">Номер:</label>
                    <div className="df1c-control df1c-inline">
                      <input
                        className="df1c-input df1c-readonly"
                        value={card ? card.number || '—' : 'присвоит 1С'}
                        readOnly
                        tabIndex={-1}
                      />
                      <span className="df1c-inline-label">от:</span>
                      <input
                        className="df1c-input df1c-readonly"
                        value={card ? dateLabel(card.date) : openedAt}
                        readOnly
                        tabIndex={-1}
                      />
                    </div>
                  </div>
                  {basisLabel ? (
                    <div className="df1c-row">
                      <label className="df1c-label">Документ-основание:</label>
                      <div className="df1c-control">
                        <input className="df1c-input df1c-readonly" value={basisLabel} readOnly tabIndex={-1} />
                      </div>
                    </div>
                  ) : null}
                  {left.map((field) => renderField(field))}
                </div>
                <div className="df1c-col">{right.map((field) => renderField(field))}</div>
              </div>
              {wide.map((field) => renderField(field, true))}

              {schema.tables.map((table) => (
                <section key={table.key} className={`df1c-table${changed.includes(table.key) && editing ? ' is-changed' : ''}`}>
                  <div className="df1c-table-head">
                    <h3>{table.label}</h3>
                    {!readOnly ? (
                      <button
                        type="button"
                        className="df1c-btn"
                        onClick={() => updateTable(table.key, (rows) => [...rows, newRow()])}
                      >
                        <Plus size={14} aria-hidden /> Добавить
                      </button>
                    ) : null}
                  </div>
                  {(tables[table.key] || []).length ? (
                    <table>
                      <thead>
                        <tr>
                          <th className="df1c-num">N</th>
                          {table.columns.map((column) => (
                            <th key={column.key}>{column.label}</th>
                          ))}
                          {!readOnly ? <th /> : null}
                        </tr>
                      </thead>
                      <tbody>
                        {(tables[table.key] || []).map((row, index) => (
                          <tr key={row.id}>
                            <td className="df1c-num">{index + 1}</td>
                            {table.columns.map((column) => (
                              <td key={column.key}>
                                <FieldInput
                                  user={user}
                                  kind={schema.id}
                                  field={column}
                                  value={row.cells[column.key] || ''}
                                  userHints={userHints}
                                  readOnly={readOnly}
                                  onChange={(value) => patchRow(table.key, row.id, column.key, value)}
                                />
                              </td>
                            ))}
                            {!readOnly ? (
                              <td>
                                <button
                                  type="button"
                                  className="df1c-icon-btn"
                                  title="Удалить строку"
                                  onClick={() => updateTable(table.key, (rows) => rows.filter((item) => item.id !== row.id))}
                                >
                                  <Trash2 size={14} aria-hidden />
                                </button>
                              </td>
                            ) : null}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="df1c-muted">
                      {editing
                        ? 'Строк нет.'
                        : schema.id === 'assignment'
                          ? 'Строк нет — 1С получит одно мероприятие с темой поручения.'
                          : 'Строк нет — 1С получит одну строку на всю сумму документа.'}
                    </p>
                  )}
                </section>
              ))}

              {schema.base === 'do' ? (
                <p className="df1c-muted">
                  Документ Документооборота записывается под вашей учёткой. Файлы и маршрут согласования — в самой 1С.
                </p>
              ) : editing ? (
                <p className="df1c-muted">
                  {card?.editable
                    ? '«Записать» сохраняет черновик. «Провести» проводит документ и оставляет форму. «Провести и закрыть» проводит и закрывает форму.'
                    : 'Проведённый документ здесь только для просмотра. Новый документ можно создать на основании или копированием.'}
                </p>
              ) : (
                <p className="df1c-muted">
                  «Записать» сохраняет черновик. «Провести» проводит документ и оставляет форму. «Провести и закрыть»
                  проводит и закрывает форму.
                </p>
              )}
            </>
          ) : (
            <div className="df1c-files">
              {!editing || (card && !card.deleted) ? (
                <button type="button" className="df1c-drop" onClick={() => fileInputRef.current?.click()}>
                  <Upload size={22} aria-hidden />
                  <strong>Перетащите файлы сюда или нажмите, чтобы выбрать</strong>
                  <span>
                    До {maxFiles} файлов за раз, каждый до {schema.max_file_mb || 20} МБ.{' '}
                    {editing ? 'Прикрепятся к документу в 1С после подтверждения.' : 'Прикрепятся сразу после записи документа.'}
                  </span>
                </button>
              ) : null}
              {existingFiles.length ? (
                <>
                  <h3 className="df1c-files-head">В 1С</h3>
                  <ul className="df1c-file-list">
                    {existingFiles.map((file) => (
                      <li key={file.id}>
                        <FileText size={16} aria-hidden />
                        <button
                          type="button"
                          className="df1c-file-name df1c-link"
                          title="Открыть файл"
                          onClick={() =>
                            void openDocflowAttachment(file).catch((err: unknown) =>
                              setError(err instanceof Error ? err.message : 'Файл не открылся')
                            )
                          }
                        >
                          {file.extension && !file.name.toLowerCase().endsWith(`.${file.extension.toLowerCase()}`)
                            ? `${file.name}.${file.extension}`
                            : file.name}
                        </button>
                        {Number(file.size) ? <span className="df1c-muted">{formatFileSize(Number(file.size))}</span> : null}
                      </li>
                    ))}
                  </ul>
                </>
              ) : editing ? (
                <p className="df1c-muted">К документу в 1С файлы не прикреплены.</p>
              ) : null}
              {files.length ? (
                <>
                  {editing ? <h3 className="df1c-files-head">Новые — ещё не в 1С</h3> : null}
                  <ul className="df1c-file-list">
                    {files.map((file) => (
                      <li key={file.name} className="is-pending">
                        <FileText size={16} aria-hidden />
                        <span className="df1c-file-name" title={file.name}>
                          {file.name}
                        </span>
                        <span className="df1c-muted">{formatFileSize(file.size)}</span>
                        <button
                          type="button"
                          className="df1c-icon-btn"
                          title="Убрать файл"
                          onClick={() => {
                            const rest = files.filter((item) => item.name !== file.name)
                            setFiles(rest)
                            if (!rest.length && pending === 'attach') setPending(null)
                          }}
                        >
                          <Trash2 size={14} aria-hidden />
                        </button>
                      </li>
                    ))}
                  </ul>
                  {editing && pending !== 'attach' ? (
                    <button type="button" className="df1c-btn df1c-btn--primary" onClick={() => setPending('attach')}>
                      <Paperclip size={14} aria-hidden /> Прикрепить к документу ({files.length})
                    </button>
                  ) : null}
                </>
              ) : null}
            </div>
          )}
        </div>

        {pending === 'save' || pending === 'save-close' || pending === 'post' || pending === 'post-close' ? (
          <footer className="df1c-summary">
            {fields
              .filter((field) => (editing ? changed.includes(field.key) : (values[field.key] || '').trim()))
              .slice(0, 8)
              .map((field) => (
                <span key={field.key}>
                  <b>{field.label}:</b> {displayValue(field, values[field.key] || '').slice(0, 80) || '(очистить)'}
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
