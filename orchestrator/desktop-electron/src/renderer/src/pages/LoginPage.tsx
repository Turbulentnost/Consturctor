import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type LoginResult } from '../api/types'
import { rememberPreference, savedFio, setRememberPreference } from '../store/session'
import { AppUpdatePanel } from '../components/AppUpdatePanel'
import { FioSuggest } from '../components/FioSuggest'
import logoUrl from '../assets/logo.png'
import cloudsUrl from '../assets/login-clouds.jpg'

const TEST_USER_FIO = 'Анна Де Армас'

function loginErrorMessage(err: unknown): string {
  const raw = err instanceof ApiError ? err.message.trim() : ''
  if (!raw) return 'Ошибка входа'
  if (/OSError|Errno \d+|pyodbc|Traceback|sqlalchemy|Invalid argument/i.test(raw)) {
    return 'Не удалось войти: нет связи с 1С или сервером. Проверьте сеть и попробуйте снова.'
  }
  return raw
}

function testLoginResult(): LoginResult {
  return {
    accessToken: '',
    user: {
      id: 'A11ADEA24A5000000000000000000001',
      fio: TEST_USER_FIO,
      department: 'Тест',
      position: 'Тестовый пользователь',
      role: 'user',
      isAdmin: false,
      nameMail: '',
      avatarUrl: null,
      canChangeDepartment: true,
      activityStatus: 'online',
      isSupport: false
    }
  }
}

interface LoginPageProps {
  onLoggedIn: (result: LoginResult, remember: boolean, password: string, typedLogin: string) => void
  banner?: string
}

export function LoginPage({ onLoggedIn, banner }: LoginPageProps): React.JSX.Element {
  const [fio, setFio] = useState(savedFio())
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(rememberPreference())
  const [error, setError] = useState('')
  const [toastLeaving, setToastLeaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [waitSec, setWaitSec] = useState(0)

  useEffect(() => {
    if (!busy) {
      setWaitSec(0)
      return
    }
    const timer = window.setInterval(() => setWaitSec((sec) => sec + 1), 1000)
    return () => window.clearInterval(timer)
  }, [busy])

  useEffect(() => {
    void api.searchUsers('', undefined, true).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!error) {
      setToastLeaving(false)
      return
    }
    setToastLeaving(false)
    const hide = window.setTimeout(() => setToastLeaving(true), 5200)
    const gone = window.setTimeout(() => setError(''), 5600)
    return () => {
      window.clearTimeout(hide)
      window.clearTimeout(gone)
    }
  }, [error])

  async function copyError(): Promise<void> {
    if (!error) return
    try {
      await navigator.clipboard.writeText(error)
    } catch {
      const area = document.createElement('textarea')
      area.value = error
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  async function submit(): Promise<void> {
    setError('')
    if (!fio.trim() || !password) {
      setError('Введите ФИО и пароль')
      return
    }
    setBusy(true)
    try {
      let result: LoginResult
      if (fio.trim().toLowerCase() === TEST_USER_FIO.toLowerCase()) {
        result = testLoginResult()
      } else {
        result = await api.login(fio.trim(), password)
      }
      setRememberPreference(remember)
      onLoggedIn(result, remember, password, fio.trim())
    } catch (err) {
      setError(loginErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      {error ? (
        <div className={toastLeaving ? 'login-toast is-leaving' : 'login-toast'} role="alert">
          <p>{error}</p>
          <button type="button" className="login-toast-copy" onClick={() => void copyError()} title="Скопировать">
            {copied ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M5 12.5l4.2 4.2L19 7.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                <rect x="8" y="8" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.7" />
                <path d="M6 16V6.5A1.5 1.5 0 017.5 5H16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            )}
          </button>
        </div>
      ) : null}
      <div className="login-shell">
        <aside className="login-hero" style={{ backgroundImage: `url(${cloudsUrl})` }}>
          <div className="login-hero-copy">
            <p>Добро пожаловать</p>
            <span className="login-brand-ring">
              <img src={logoUrl} alt="" />
            </span>
            <h1>Оркестратор</h1>
            <span>Рабочее место должности. Вход по учётной записи 1С.</span>
          </div>
        </aside>
        <form
          className="login-form"
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <h2>Вход</h2>
          {banner ? <div className="login-banner">{banner}</div> : null}
          <label>ФИО</label>
          <FioSuggest
            value={fio}
            onChange={setFio}
            onSelect={setFio}
            placeholder="Фамилия Имя Отчество"
            inputClassName="login-input"
            onEnter={submit}
            publicOnly
          />
          <label htmlFor="login-password">Пароль</label>
          <div className="password-field">
            <input
              id="login-password"
              className="login-input"
              type={showPassword ? 'text' : 'password'}
              value={password}
              placeholder="Пароль 1С"
              autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
            <button
              type="button"
              className="password-toggle"
              title={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? 'Скрыть' : 'Показать'}
            </button>
          </div>
          <label className="login-remember">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            Запомнить на этом компьютере
          </label>
          <button className="login-submit" type="submit" disabled={busy}>
            {busy ? (waitSec >= 3 ? `Входим… ${waitSec} с` : 'Входим…') : 'Войти'}
          </button>
          <AppUpdatePanel />
        </form>
      </div>
    </div>
  )
}
