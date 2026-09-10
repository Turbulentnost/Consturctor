import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type LoginResult } from '../api/types'
import { rememberPreference, savedFio, setRememberPreference } from '../store/session'
import { FioSuggest } from '../components/FioSuggest'
import logoUrl from '../assets/logo.png'

const TEST_USER_FIO = 'Анна Де Армас'

function testLoginResult(): LoginResult {
  return {
    accessToken: '',
    user: {
      id: 'A11ADEA24A5000000000000000000001',
      fio: TEST_USER_FIO,
      department: 'Тест',
      position: 'Тестовый пользователь',
      avatarUrl: null,
      canChangeDepartment: true,
      activityStatus: 'online',
      isSupport: false
    }
  }
}

interface LoginPageProps {
  onLoggedIn: (result: LoginResult, remember: boolean, password: string) => void
}

export function LoginPage({ onLoggedIn }: LoginPageProps): React.JSX.Element {
  const [fio, setFio] = useState(savedFio())
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(rememberPreference())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [waitSec, setWaitSec] = useState(0)
  const [backendHint, setBackendHint] = useState('')

  useEffect(() => {
    if (!busy) {
      setWaitSec(0)
      return
    }
    const timer = window.setInterval(() => setWaitSec((sec) => sec + 1), 1000)
    return () => window.clearInterval(timer)
  }, [busy])

  useEffect(() => {
    let alive = true
    void window.api
      .request({ method: 'GET', path: '/health', timeoutMs: 5000 })
      .then((res) => {
        if (!alive || res.ok) {
          if (res.ok) setBackendHint('')
          return
        }
        setBackendHint(
          `Backend недоступен (${res.error || 'нет ответа'}). Запустите orchestrator\\backend\\run_dev.bat.`
        )
      })
      .catch(() => {
        if (!alive) return
        setBackendHint('Backend недоступен. Запустите orchestrator\\backend\\run_dev.bat.')
      })
    return () => {
      alive = false
    }
  }, [])

  async function submit(): Promise<void> {
    setError('')
    setBackendHint('')
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
      onLoggedIn(result, remember, password)
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(
          err.message ||
            'Сервис аутентификации 1С недоступен. Проверьте VPN и что backend запущен (run_dev.bat).'
        )
      } else {
        setError(err instanceof ApiError ? err.message : 'Ошибка входа')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-bg" />
      <div className="login-card">
        <img className="login-logo" src={logoUrl} alt="turbobot" />
        <div className="brand">turbobot</div>
        <div className="subtitle">Вход через учётную запись 1С</div>
        <div className="hint">Укажите ФИО и пароль из erp_pm</div>

        <label>ФИО</label>
        <FioSuggest
          value={fio}
          onChange={setFio}
          onSelect={setFio}
          placeholder="Фамилия Имя Отчество"
          inputClassName="login-input"
          variant="dark"
          onEnter={submit}
        />

        <label>Пароль</label>
        <div className="password-field">
          <input
            className="login-input"
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
          <button
            type="button"
            className="password-toggle"
            title={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
            onClick={() => setShowPassword((v) => !v)}
          >
            {showPassword ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M3 3l18 18M10.6 10.7a2 2 0 002.8 2.8M9.4 5.2A9.8 9.8 0 0112 5c5 0 9 4.5 9 7 0 1-.7 2.3-1.9 3.5M6.1 6.2C3.9 7.6 3 9.8 3 12c0 2.5 4 7 9 7 1.3 0 2.5-.3 3.6-.8"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"
                  stroke="currentColor"
                  strokeWidth="1.7"
                />
                <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.7" />
              </svg>
            )}
          </button>
        </div>

        <label className="remember">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          Запомнить пользователя
        </label>

        <div className="error">{backendHint || error}</div>

        <button className="btn-light" onClick={submit} disabled={busy}>
          {busy
            ? waitSec >= 3
              ? `Входим... ${waitSec}с, ждём erp_pm`
              : 'Входим...'
            : 'Войти'}
        </button>
      </div>
    </div>
  )
}
