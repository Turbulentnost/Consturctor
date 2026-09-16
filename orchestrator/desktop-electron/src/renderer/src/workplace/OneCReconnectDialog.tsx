import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api/client'
import { agentClient } from '../api/agent'
import type { UserProfile } from '../api/types'
import { comCredentials, setComCredentials } from '../store/session'
import { erpActorComUsername, erpActorFio } from './userContext'
import { isDoubleOneCAuthHint, userFacingOneCError } from './onecSessionHints'
import { useBumpComCredentialsRevision } from './ComCredentialsRevisionContext'
import { useGridDataRefreshContext } from './GridDataRefreshContext'

export function OneCReconnectDialog({
  open,
  onClose,
  user,
  errorHint = '',
  submitLabel = 'Подключить 1С'
}: {
  open: boolean
  onClose: () => void
  user: UserProfile
  errorHint?: string
  submitLabel?: string
}): React.JSX.Element | null {
  const titleId = useId()
  const passwordRef = useRef<HTMLInputElement>(null)
  const bumpRevision = useBumpComCredentialsRevision()
  const { forceRefresh } = useGridDataRefreshContext()
  const [fio, setFio] = useState('')
  const [nameMail, setNameMail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [awaitSecondAuth, setAwaitSecondAuth] = useState(false)

  useEffect(() => {
    if (!open) return
    const creds = comCredentials()
    setFio((creds.login || erpActorFio(user)).trim())
    setNameMail((creds.nameMail || erpActorComUsername(user)).trim())
    setPassword('')
    setFormError('')
    setAwaitSecondAuth(isDoubleOneCAuthHint(errorHint))
    const timer = window.setTimeout(() => passwordRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open, user, errorHint])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  async function submit(): Promise<void> {
    setFormError('')
    const login = fio.trim()
    if (!login || !password) {
      setFormError('Укажите ФИО и пароль 1С')
      return
    }
    setBusy(true)
    try {
      const mail = nameMail.trim()
      setComCredentials(login, password, mail)
      bumpRevision()
      const token = api.getToken()
      await agentClient
        .ready(token, {
          login,
          password
        })
        .catch(() => undefined)
      forceRefresh()
      if (isDoubleOneCAuthHint(errorHint)) {
        setAwaitSecondAuth(true)
        setPassword('')
        passwordRef.current?.focus()
      } else {
        onClose()
      }
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const doubleHint = awaitSecondAuth || isDoubleOneCAuthHint(errorHint)
  const safeHint = userFacingOneCError(errorHint)

  return createPortal(
    <div className="modal-overlay onec-reconnect-overlay" onClick={() => !busy && onClose()} role="presentation">
      <div
        className="modal-card onec-reconnect-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <h4 className="modal-title" id={titleId}>
          Подключение к 1С
        </h4>
        <p className="modal-note">
          {doubleHint
            ? '1С может запросить двойную авторизацию — введите пароль ещё раз и нажмите «Повторить».'
            : 'Введите учётные данные 1С. Пароль хранится только в памяти приложения до закрытия.'}
        </p>
        {safeHint ? <p className="modal-note onec-reconnect-error-hint">{safeHint}</p> : null}
        {formError ? <p className="onec-reconnect-form-error">{formError}</p> : null}

        <label className="modal-label" htmlFor="onec-reconnect-fio">
          ФИО (логин 1С)
        </label>
        <input
          id="onec-reconnect-fio"
          className="onec-reconnect-input"
          value={fio}
          onChange={(event) => setFio(event.target.value)}
          autoComplete="username"
          disabled={busy}
        />

        <label className="modal-label" htmlFor="onec-reconnect-mail">
          Логин 1С (nameMail / ONEC_COM_USR), если пусто в профиле
        </label>
        <input
          id="onec-reconnect-mail"
          className="onec-reconnect-input"
          value={nameMail}
          onChange={(event) => setNameMail(event.target.value)}
          placeholder={user.nameMail || 'lat_login'}
          autoComplete="off"
          disabled={busy}
        />

        <label className="modal-label" htmlFor="onec-reconnect-password">
          Пароль 1С
        </label>
        <input
          ref={passwordRef}
          id="onec-reconnect-password"
          className="onec-reconnect-input"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && void submit()}
          autoComplete="current-password"
          disabled={busy}
        />

        <div className="modal-actions">
          <button type="button" className="btn-light" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="button" className="btn-primary" onClick={() => void submit()} disabled={busy}>
            {busy ? 'Подключение…' : doubleHint ? 'Повторить' : submitLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

/** Inline CTA under empty 1C table — opens reconnect modal. */
export function OneCReconnectInline({
  errorHint,
  onOpen
}: {
  errorHint?: string
  onOpen: () => void
}): React.JSX.Element {
  return (
    <div className="onec-reconnect-inline">
      <p className="spec-v04-muted">
        {userFacingOneCError(errorHint || '') || 'Не удалось загрузить задачи 1С — проверьте пароль сеанса.'}
      </p>
      <button type="button" className="btn-primary onec-reconnect-inline-btn" onClick={onOpen}>
        Подключить 1С
      </button>
    </div>
  )
}
