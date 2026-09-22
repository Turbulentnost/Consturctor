import { useEffect, useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import type { OutlookMailDetail } from '../../utils/outlookMailActions'
import {
  createIncomingFromMail,
  emptyIncomingCreateDraft,
  fetchIncomingDepartments,
  type IncomingCreateDraft,
  type IncomingDepartmentOption
} from '../../workplace/mailIncomingCreate'

function DeptSelect({
  id,
  label,
  value,
  nameValue,
  options,
  onPick
}: {
  id: string
  label: string
  value: string
  nameValue: string
  options: IncomingDepartmentOption[]
  onPick: (code: string, name: string) => void
}): React.JSX.Element {
  const listId = `${id}-list`
  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase()
    if (!q) return options.slice(0, 120)
    return options
      .filter(
        (item) =>
          item.code.toLowerCase().includes(q) ||
          item.name.toLowerCase().includes(q)
      )
      .slice(0, 120)
  }, [options, value])

  return (
    <label className="registry-create-field registry-create-field--wide" htmlFor={id}>
      <span className="modal-label">{label} *</span>
      <input
        id={id}
        className="onec-reconnect-input"
        type="text"
        list={listId}
        value={value}
        placeholder="00-000066 — код подразделения"
        onChange={(event) => {
          const next = event.target.value
          const hit = options.find((item) => item.code === next.trim())
          onPick(next, hit?.name || nameValue)
        }}
        onBlur={() => {
          const hit = options.find((item) => item.code === value.trim())
          if (hit) onPick(hit.code, hit.name)
        }}
      />
      <datalist id={listId}>
        {filtered.map((item) => (
          <option key={item.code} value={item.code}>
            {item.name}
          </option>
        ))}
      </datalist>
      {nameValue ? <span className="modal-note">{nameValue}</span> : null}
    </label>
  )
}

export function MailIncomingCreateDialog({
  open,
  mail,
  user,
  detail,
  onClose,
  onCreated
}: {
  open: boolean
  mail: SpecMailRow
  user: UserProfile
  detail: OutlookMailDetail | null
  onClose: () => void
  onCreated: (message: string, isError?: boolean) => void
}): React.JSX.Element | null {
  const titleId = useId()
  const [draft, setDraft] = useState<IncomingCreateDraft>(() =>
    emptyIncomingCreateDraft(mail, {
      subject: detail?.subject,
      sender: detail?.sender,
      bodyPreview: detail?.bodyPreview
    })
  )
  const [departments, setDepartments] = useState<IncomingDepartmentOption[]>([])
  const [step, setStep] = useState<'form' | 'confirm'>('form')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setDraft(
      emptyIncomingCreateDraft(mail, {
        subject: detail?.subject || mail.subject,
        sender: detail?.sender || mail.sender,
        bodyPreview: detail?.bodyPreview
      })
    )
    setStep('form')
    setConfirmed(false)
    setError('')
    setBusy(false)
  }, [open, mail.id, detail?.subject, detail?.sender, mail.subject, mail.sender, detail?.bodyPreview])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void fetchIncomingDepartments().then((items) => {
      if (!cancelled) setDepartments(items)
    })
    return () => {
      cancelled = true
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  const goConfirm = (): void => {
    setError('')
    if (!draft.departmentId.trim()) {
      setError('Укажите подразделение (кому на исполнение)')
      return
    }
    if (!draft.theme.trim()) {
      setError('Укажите тему входящей')
      return
    }
    setStep('confirm')
    setConfirmed(false)
  }

  async function submitCreate(): Promise<void> {
    if (!confirmed) {
      setError('Подтвердите запись документа в 1С')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await createIncomingFromMail(user, mail, draft, {
        receivedAt: mail.receivedAt || mail.time
      })
      if (!result.ok) {
        setError(result.error || 'Ошибка создания')
        return
      }
      let msg = result.number
        ? `Создана входящая ${result.number}`
        : result.summary || 'Входящая создана в 1С (OData)'
      if (result.attachmentWarning) {
        msg += `. Вложение .msg: ${result.attachmentWarning}`
      }
      onCreated(msg)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return createPortal(
    <div className="modal-overlay registry-create-overlay" onClick={() => !busy && onClose()} role="presentation">
      <div
        className="modal-card registry-create-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="registry-create-head">
          <div className="registry-create-head-text">
            <h2 className="modal-title" id={titleId}>
              Входящая из письма
            </h2>
            <p className="modal-note registry-create-sub">
              Как agent-pochta: заполните маршрут (кому на исполнение), затем запись в 1С через OData HTTP и
              прикрепление .msg.
            </p>
            <div className="registry-create-steps" aria-hidden>
              <span className={step === 'form' ? 'is-active' : ''}>1. Маршрут</span>
              <span className={step === 'confirm' ? 'is-active' : ''}>2. Проверка</span>
            </div>
          </div>
          <button
            type="button"
            className="registry-detail-close registry-create-close"
            title="Закрыть"
            disabled={busy}
            onClick={onClose}
          >
            <X size={18} aria-hidden />
          </button>
        </header>

        {step === 'form' ? (
          <div className="registry-create-body">
            <section className="registry-create-section">
              <DeptSelect
                id="incoming-dept"
                label="Кому на исполнение (код подразделения)"
                value={draft.departmentId}
                nameValue={draft.departmentName}
                options={departments}
                onPick={(code, name) =>
                  setDraft((current) => ({
                    ...current,
                    departmentId: code,
                    departmentName: name
                  }))
                }
              />
              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">Тема *</span>
                <input
                  className="onec-reconnect-input"
                  value={draft.theme}
                  onChange={(event) => setDraft((c) => ({ ...c, theme: event.target.value }))}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Партнёр</span>
                <input
                  className="onec-reconnect-input"
                  value={draft.partner}
                  onChange={(event) => setDraft((c) => ({ ...c, partner: event.target.value }))}
                />
              </label>
              <label className="registry-create-field">
                <span className="modal-label">Организация</span>
                <input
                  className="onec-reconnect-input"
                  value={draft.organization}
                  onChange={(event) => setDraft((c) => ({ ...c, organization: event.target.value }))}
                />
              </label>
              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">Отправитель (e-mail)</span>
                <input
                  className="onec-reconnect-input"
                  value={draft.emailSender}
                  onChange={(event) => setDraft((c) => ({ ...c, emailSender: event.target.value }))}
                />
              </label>
              <label className="registry-create-field registry-create-field--wide">
                <span className="modal-label">Содержание / задача ИИ</span>
                <textarea
                  className="onec-reconnect-input registry-create-textarea"
                  rows={4}
                  value={draft.content}
                  onChange={(event) => setDraft((c) => ({ ...c, content: event.target.value }))}
                />
              </label>
            </section>
            {error ? <p className="modal-error">{error}</p> : null}
            <footer className="registry-create-foot">
              <button type="button" className="spec-btn-outline" disabled={busy} onClick={onClose}>
                Отмена
              </button>
              <button type="button" className="spec-btn-launch" disabled={busy} onClick={goConfirm}>
                Далее
              </button>
            </footer>
          </div>
        ) : (
          <div className="registry-create-body">
            <dl className="registry-create-review">
              <div>
                <dt>Подразделение</dt>
                <dd>
                  {draft.departmentId}
                  {draft.departmentName ? ` — ${draft.departmentName}` : ''}
                </dd>
              </div>
              <div>
                <dt>Тема</dt>
                <dd>{draft.theme}</dd>
              </div>
              {draft.partner ? (
                <div>
                  <dt>Партнёр</dt>
                  <dd>{draft.partner}</dd>
                </div>
              ) : null}
            </dl>
            <label className="registry-create-confirm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              Создать документ входящей в 1С (OData) и прикрепить .msg письма
            </label>
            {error ? <p className="modal-error">{error}</p> : null}
            <footer className="registry-create-foot">
              <button
                type="button"
                className="spec-btn-outline"
                disabled={busy}
                onClick={() => setStep('form')}
              >
                Назад
              </button>
              <button type="button" className="spec-btn-launch" disabled={busy} onClick={() => void submitCreate()}>
                {busy ? '1С OData…' : 'Создать в 1С'}
              </button>
            </footer>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
