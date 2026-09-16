const TOKEN_KEY = 'orchestrator.session.token'
const FIO_KEY = 'orchestrator.session.fio'
const REMEMBER_KEY = 'orchestrator.session.remember'

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

/**
 * In-memory 1C password from Orchestrator login (FIO in localStorage token session only).
 * Used for SOAP документооборот (FIO+password), gateway OData and COM; not written to disk.
 * After JWT restore without re-login the password is empty — UI shows the 1C reconnect dialog
 * instead of requiring DOK_HTTP_USER/PASSWORD in backend/.env.
 */
let comLogin = ''
let comPassword = ''
/** v8users.Name (латинский логин 1С) для COM Usr= / OData username. */
let comNameMail = ''
let comCredentialsRevision = 0

/** Dev-only: workspace `.env` via Electron main (not Vite); never persisted. */
let devGatewayPassword = ''
let devGatewayNameMail = ''
let devGatewayFio = ''

export function setComCredentials(login: string, password: string, nameMail = ''): void {
  comLogin = (login || '').trim()
  comPassword = password || ''
  comNameMail = (nameMail || '').trim()
  comCredentialsRevision += 1
}

/** After JWT restore: sync v8users.Name / FIO from profile without touching password. */
export function syncComProfileFromUser(user: { fio?: string; nameMail?: string } | null): void {
  if (!user) return
  const nextMail = (user.nameMail || '').trim()
  const nextLogin = (user.fio || '').trim()
  let changed = false
  if (nextMail && nextMail !== comNameMail) {
    comNameMail = nextMail
    changed = true
  }
  if (!comLogin && nextLogin) {
    comLogin = nextLogin
    changed = true
  }
  if (changed) comCredentialsRevision += 1
}

export function clearComCredentials(): void {
  comLogin = ''
  comPassword = ''
  comNameMail = ''
  comCredentialsRevision += 1
}

export function comCredentials(): { login: string; password: string; nameMail: string } {
  return { login: comLogin, password: comPassword, nameMail: comNameMail }
}

export function hasComPassword(): boolean {
  return Boolean(comPassword)
}

export function setDevGatewayCredentials(opts: {
  password?: string
  nameMail?: string
  fio?: string
}): void {
  devGatewayPassword = (opts.password || '').trim()
  devGatewayNameMail = (opts.nameMail || '').trim().toLowerCase()
  devGatewayFio = (opts.fio || '').trim()
  if (devGatewayPassword || devGatewayNameMail || devGatewayFio) {
    comCredentialsRevision += 1
  }
}

export function devGatewayCredentials(): {
  password: string
  nameMail: string
  fio: string
} {
  return {
    password: devGatewayPassword,
    nameMail: devGatewayNameMail,
    fio: devGatewayFio
  }
}

/** Пароль, введённый на экране входа / в диалоге 1С. Не пароль из .env. */
export function gatewaySessionPassword(): string {
  return comPassword
}

/** Bumps on set/clear — use in React deps to refetch 1C after re-login. */
export function getComCredentialsRevision(): number {
  return comCredentialsRevision
}
