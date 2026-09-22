import { useEffect, useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import type { OutlookMailDetail } from '../../utils/outlookMailActions'
import {
  createIncomingFromMail,
  emptyIncomingCreateDraft,
  fetchIncomingCatalog,
  forwardIncomingMailToAi,
  INCOMING_AI_MAILBOX,
  INCOMING_DEPARTMENTS,
  INCOMING_ORGANIZATIONS,
  organizationLabel,
  type IncomingCreateDraft,
  type IncomingDepartmentOption,
  type IncomingOrganizationOption
} from '../../workplace/mailIncomingCreate'
import './extensionsGrid.css'
import './mailGrid.css'

const DEPT_HINTS: Record<string, string> = {
  '00-000001': 'председатель совет директоров руководство',
  '00-000002': 'бухгалтерия счета учет финансы',
  '00-000013': 'развитие',
  '00-000015': 'вэд внешняя торговля экспорт',
  '00-000025': 'метрология сертификация поверка',
  '00-000035': 'милака директор',
  '00-000040': 'качество технический директор',
  '00-000042': 'ключевые клиенты оркк продажи',
  '00-000044': 'юрист юристы договор юридический',
  '00-000046': 'ахо хозяйство административный',
  '00-000049': 'финансы финансовый директор',
  '00-000054': 'тендер закупка конкурс',
  '00-000058': 'коммерция продажи коммерческий директор',
  '00-000059': 'безопасность экономическая',
  '00-000063': 'кадры персонал hr сотрудники',
  '00-000065': 'омто снабжение закупки мто склад',
  '00-000066': 'дела канцелярия секретариат входящие корреспонденция',
  '00-000068': 'логистика доставка транспорт',
  '00-000074': 'опму продажи оборудование',
  '00-000076': 'газпром пао',
  '00-000080': 'метрогазсервис директор',
  '00-000099': 'поддержка техническая it helpdesk',
  '00-000100': 'отк качество контроль',
  '00-000101': 'отк качество контроль',
  '00-000104': 'сервис обслуживание ремонт',
  '00-000119': 'по асу программирование it софт',
  '00-000128': 'бми продажи блочно модульные',
  '00-000152': 'операционный директор руководство',
  '00-000155': 'дилеры продажи',
  '00-000163': 'технический директор',
  '00-000172': 'перспективные проекты',
  '00-000182': 'помощник операционный'
}

const ORG_HINTS: Record<string, string> = {
  НП: 'нпо турбулентность дон головная',
  АЛ: 'алмаз гранд счетчики',
  МГ: 'метрогазсервис',
  АМ: 'амурская легенда',
  МИ: 'милака',
  БМ: 'бми блочно модульные изделия'
}

function foldText(value: string): string {
  return value
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[«»"'`().,:;]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function matchScore(query: string, label: string, hints: string): number {
  const q = foldText(query)
  if (!q) return 1
  const name = foldText(label)
  const extra = foldText(hints)
  const hay = `${name} ${extra}`
  if (name.startsWith(q) || hay.includes(q)) return 8
  const tokens = q.split(' ').filter((token) => token.length >= 2)
  if (!tokens.length) return 0
  let score = 0
  for (const token of tokens) {
    if (name.includes(token)) score += 4
    else if (extra.includes(token)) score += 3
    else if (name.split(' ').some((word) => word.startsWith(token) || token.startsWith(word.slice(0, 4)))) {
      score += 2
    }
  }
  return score
}

function SemanticCombo({
  id,
  label,
  required,
  placeholder,
  query,
  options,
  hints,
  onQuery,
  onPick
}: {
  id: string
  label: string
  required?: boolean
  placeholder?: string
  query: string
  options: { code: string; name: string }[]
  hints: Record<string, string>
  onQuery: (value: string) => void
  onPick: (code: string, name: string) => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const matches = useMemo(() => {
    return options
      .map((item) => ({ item, score: matchScore(query, item.name, hints[item.code] || '') }))
      .filter((row) => row.score > 0)
      .sort((a, b) => b.score - a.score || a.item.name.localeCompare(b.item.name, 'ru'))
      .map((row) => row.item)
  }, [hints, options, query])

  return (
    <div className="registry-create-field registry-create-field--wide incoming-combo">
      <label className="modal-label" htmlFor={id}>
        {label}
        {required ? ' *' : ''}
      </label>
      <input
        id={id}
        className="onec-reconnect-input incoming-combo-input"
        type="text"
        autoComplete="off"
        value={query}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setOpen(true)
          onQuery(event.target.value)
        }}
        onBlur={() => {
          window.setTimeout(() => setOpen(false), 160)
        }}
      />
      {open ? (
        <ul className="incoming-combo-list" role="listbox">
          {matches.length ? (
            matches.map((item) => (
              <li key={item.code}>
                <button
                  type="button"
                  className="incoming-combo-option"
                  onMouseDown={(event) => {
                    event.preventDefault()
                    onPick(item.code, item.name)
                    setOpen(false)
                  }}
                >
                  {item.name}
                </button>
              </li>
            ))
          ) : (
            <li className="incoming-combo-empty">Нет подходящих вариантов</li>
          )}
        </ul>
      ) : null}
    </div>
  )
}

function ReviewRow({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <div className="incoming-review-row">
      <dt>{label}</dt>
      <dd>{value.trim() || '—'}</dd>
    </div>
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
  const [departments, setDepartments] = useState<IncomingDepartmentOption[]>(INCOMING_DEPARTMENTS)
  const [organizations, setOrganizations] = useState<IncomingOrganizationOption[]>(INCOMING_ORGANIZATIONS)
  const [step, setStep] = useState<'choice' | 'form' | 'confirm'>('choice')
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
    setStep('choice')
    setError('')
    setBusy(false)
    // Reset only when the dialog opens for another letter. Letter preview
    // updates must not wipe a filled form or abort the 1C submit.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- open + mail identity only
  }, [open, mail.id])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void fetchIncomingCatalog().then((catalog) => {
      if (cancelled) return
      setDepartments(catalog.departments)
      if (catalog.organizations.length) setOrganizations(catalog.organizations)
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

  const orgFullName = useMemo(() => {
    const hit = organizations.find((item) => item.code === draft.organization)
    return hit?.name || organizationLabel(draft.organization)
  }, [draft.organization, organizations])

  const goConfirm = (): void => {
    setError('')
    if (!draft.departmentId.trim()) {
      setError('Выберите подразделение из подсказок под полем')
      return
    }
    if (!organizations.some((item) => item.code === draft.organization)) {
      setError('Выберите организацию из подсказок под полем')
      return
    }
    if (!draft.theme.trim()) {
      setError('Укажите тему входящей')
      return
    }
    if (!draft.partner.trim()) {
      setError('Укажите партнёра — без него 1С не записывает входящую')
      return
    }
    setStep('confirm')
  }

  async function submitForward(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await forwardIncomingMailToAi(mail)
      if (!result.ok) {
        setError(result.error || 'Не удалось переслать письмо')
        return
      }
      onCreated(`Письмо переслано на ${INCOMING_AI_MAILBOX} для обработки ИИ`)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  async function submitCreate(): Promise<void> {
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
      if (result.attachmentWarning) {
        const createdLabel = result.number
          ? `Документ ${result.number} создан`
          : 'Документ создан'
        setError(
          `${createdLabel}, но .msg не прикреплён: ${result.attachmentWarning}. Проверьте вложение в 1С или повторите.`
        )
        onCreated(
          `${createdLabel}, но без вложения .msg: ${result.attachmentWarning}`
        )
        return
      }
      let msg = result.number
        ? `Создана входящая ${result.number}`
        : result.summary || 'Входящая создана в 1С (OData)'
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
              {step === 'choice'
                ? `Сначала можно переслать письмо на ${INCOMING_AI_MAILBOX}: его разберёт ИИ. Либо заполните входящую вручную.`
                : step === 'form'
                  ? 'Заполните маршрут и реквизиты. На следующем шаге проверьте сводку и создайте документ в 1С.'
                  : 'Проверьте сводку и нажмите «Создать в 1С» — документ запишется непроведённым, к нему прикрепится .msg.'}
            </p>
            <div className="registry-create-steps" aria-hidden>
              <span className={step === 'choice' ? 'is-active' : ''}>1. Способ</span>
              <span className={step === 'form' ? 'is-active' : ''}>2. Маршрут</span>
              <span className={step === 'confirm' ? 'is-active' : ''}>3. Проверка</span>
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

        {step === 'choice' ? (
          <div className="registry-create-body">
            <section className="registry-create-section">
              <p className="modal-note">
                Переадресация уйдёт из Outlook на {INCOMING_AI_MAILBOX}. Тема письма:{' '}
                {mail.subject || draft.theme || 'без темы'}.
              </p>
            </section>
            {error ? <p className="modal-error">{error}</p> : null}
            <footer className="registry-create-foot modal-actions">
              <button
                type="button"
                className="spec-btn-outline"
                disabled={busy}
                onClick={() => {
                  setError('')
                  setStep('form')
                }}
              >
                Продолжить заполнение вручную
              </button>
              <button
                type="button"
                className="spec-btn-launch"
                disabled={busy}
                onClick={() => void submitForward()}
              >
                {busy ? 'Отправка…' : 'Отправить на переадресацию ИИ'}
              </button>
            </footer>
          </div>
        ) : step === 'form' ? (
          <div className="registry-create-body">
            <section className="registry-create-section">
              <SemanticCombo
                id="incoming-dept"
                label="Кому на исполнение"
                required
                placeholder="Начните вводить: кадры, юристы, дела…"
                query={draft.departmentName}
                options={departments}
                hints={DEPT_HINTS}
                onQuery={(value) =>
                  setDraft((current) => ({
                    ...current,
                    departmentName: value,
                    departmentId: ''
                  }))
                }
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
                <span className="modal-label">Партнёр *</span>
                <input
                  className="onec-reconnect-input"
                  value={draft.partner}
                  placeholder="Название контрагента"
                  onChange={(event) => setDraft((c) => ({ ...c, partner: event.target.value }))}
                />
              </label>
              <SemanticCombo
                id="incoming-org"
                label="Организация"
                required
                placeholder="Например: турбулентность, алмаз, милака"
                query={organizationLabel(draft.organization)}
                options={organizations}
                hints={ORG_HINTS}
                onQuery={(value) => {
                  const hit = organizations.find(
                    (item) => item.name.toLowerCase() === value.trim().toLowerCase()
                  )
                  setDraft((current) => ({
                    ...current,
                    organization: hit?.code || value
                  }))
                }}
                onPick={(code) => setDraft((current) => ({ ...current, organization: code }))}
              />
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
            <dl className="incoming-review">
              <ReviewRow label="Организация" value={orgFullName} />
              <ReviewRow label="Кому на исполнение" value={draft.departmentName} />
              <ReviewRow label="Тема" value={draft.theme} />
              <ReviewRow label="Партнёр" value={draft.partner} />
              <ReviewRow label="Отправитель" value={draft.emailSender || mail.sender || ''} />
              {draft.content.trim() ? (
                <ReviewRow label="Содержание" value={draft.content} />
              ) : null}
            </dl>
            <p className="modal-note incoming-review-note">
              Будет создан непроведённый документ входящей корреспонденции в 1С, к нему
              прикрепится файл письма (.msg).
            </p>
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
                {busy ? 'Запись в 1С…' : 'Создать в 1С'}
              </button>
            </footer>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
