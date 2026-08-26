const TOKEN_KEY = 'constructor.session.token'
const FIO_KEY = 'constructor.session.fio'
const REMEMBER_KEY = 'constructor.session.remember'

export interface StoredSession {
  accessToken: string
  fio: string
}

export function loadSession(): StoredSession | null {
  const token = localStorage.getItem(TOKEN_KEY)
  if (!token) return null
  return { accessToken: token, fio: localStorage.getItem(FIO_KEY) ?? '' }
}

export function saveSession(session: StoredSession): void {
  localStorage.setItem(TOKEN_KEY, session.accessToken)
  localStorage.setItem(FIO_KEY, session.fio)
}

export function clearSession(keepFio = true): void {
  localStorage.removeItem(TOKEN_KEY)
  if (!keepFio) localStorage.removeItem(FIO_KEY)
}

export function savedFio(): string {
  return localStorage.getItem(FIO_KEY) ?? ''
}

export function rememberPreference(): boolean {
  return localStorage.getItem(REMEMBER_KEY) !== '0'
}

export function setRememberPreference(value: boolean): void {
  localStorage.setItem(REMEMBER_KEY, value ? '1' : '0')
}
