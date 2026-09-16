import type { UserProfile } from '../api/types'
import {
  comCredentials,
  devGatewayCredentials,
  gatewaySessionPassword,
  savedFio
} from '../store/session'

export const TURBO_DON_MAIL_DOMAIN = 'turbo-don.ru'

/** Почта Outlook: только связка {name_mail}@turbo-don.ru из профиля 1С. */
export function outlookMailboxAddress(user: UserProfile | null): string {
  const slug = (user?.nameMail || '').trim().toLowerCase()
  if (!slug) return ''
  return `${slug}@${TURBO_DON_MAIL_DOMAIN}`
}

/** ФИО / логин 1С для COM и erp_tasks (данные с экрана входа). */
export function erpActorFio(user: UserProfile | null): string {
  const fromCom = (comCredentials().login || '').trim()
  if (fromCom) return fromCom
  const fromProfile = (user?.fio || savedFio() || '').trim()
  if (fromProfile) return fromProfile
  const fromDev = devGatewayCredentials().fio
  if (fromDev) return fromDev
  return String(import.meta.env.VITE_MY_NAME ?? '').trim()
}

export function erpActorUserId(user: UserProfile | null): string {
  return (user?.id || '').trim()
}

/** v8users.Name for 1C auth when known; otherwise FIO from login screen. */
export function erpActorComUsername(user: UserProfile | null): string {
  const fromSession = (comCredentials().nameMail || '').trim()
  if (fromSession) return fromSession
  const fromProfile = (user?.nameMail || '').trim()
  if (fromProfile) return fromProfile
  return erpActorFio(user)
}

/** Latin 1C login for TurboProject / Outlook — never FIO. */
export function turboNameMailSlug(user: UserProfile | null): string {
  const fromSession = (comCredentials().nameMail || '').trim().toLowerCase()
  if (fromSession) return fromSession
  const fromProfile = (user?.nameMail || '').trim().toLowerCase()
  if (fromProfile) return fromProfile
  const fromDev = devGatewayCredentials().nameMail
  if (fromDev) return fromDev
  return String(import.meta.env.VITE_MY_NAME_MAIL ?? '').trim().toLowerCase()
}

/** Gateway onec.* invoke: только логин и пароль с экрана входа, без .env / OData. */
export function onecGatewayInvokeArgs(
  user: UserProfile | null,
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  const creds = comCredentials()
  const fio = erpActorFio(user)
  const userId = erpActorUserId(user)
  const password = gatewaySessionPassword() || devGatewayCredentials().password
  const typedLogin = (creds.login || '').trim()
  const username = erpActorComUsername(user)
  return {
    ...extra,
    fio,
    user_id: userId,
    session_login: typedLogin || fio,
    erp_login: typedLogin || fio,
    password,
    erp_password: password,
    ...(username ? { username } : {})
  }
}

/** Gateway turboproject.*: portfolio employee + TurboProject login from session (email + password). */
export function turboProjectInvokeArgs(
  user: UserProfile | null,
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  const employee = erpActorFio(user)
  const password = gatewaySessionPassword()
  const nameMail = turboNameMailSlug(user)
  const email = nameMail ? `${nameMail}@${TURBO_DON_MAIL_DOMAIN}` : ''
  const args: Record<string, unknown> = {
    ...extra,
    employee,
    fio: employee
  }
  if (nameMail) {
    args.name_mail = nameMail
  }
  if (email) args.email = email
  if (password) args.password = password
  return args
}

/** Live Turbo session: latin login + password from the login screen (not gateway stub). */
export function hasTurboSessionCredentials(user: UserProfile | null): boolean {
  return Boolean(turboNameMailSlug(user) && gatewaySessionPassword())
}

/** COM onec.* via sidecar: FIO + session password (Usr= in COM is FIO, not nameMail). */
export function onecComInvokeArgs(
  extra: Record<string, unknown> = {},
  user: UserProfile | null = null
): Record<string, unknown> {
  const { login, password } = comCredentials()
  const args: Record<string, unknown> = { ...extra }
  const fio = (login || user?.fio || savedFio() || '').trim()
  if (fio) {
    args.fio = fio
    args.erp_login = fio
  }
  if (password) {
    args.password = password
    args.erp_password = password
  }
  return args
}

/** Имя для приветствия и шапки (без отчества / полного ФИО). */
export function userGivenName(fio: string): string {
  const trimmed = fio.trim()
  if (!trimmed) return 'коллега'
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length >= 2 && parts[1].length > 2 && !parts[1].includes('.')) {
    return parts[1]
  }
  if (parts[0].toLowerCase().includes('иванов')) {
    return 'Иван'
  }
  return parts[0]
}
