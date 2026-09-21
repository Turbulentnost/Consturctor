import type { UserProfile } from '../api/types'
import { comCredentials } from './session'

const STORAGE_KEY = 'orchestrator.session.onecProfile.v1'

export type OneCSessionProfileSource = 'login' | 'me' | 'jwt' | 'manual'

/** Локальный снимок пользователя 1С для COM/gateway (временно, до полноценного профиля). */
export interface OneCSessionProfile {
  orchestratorUserId: string
  fio: string
  nameMail: string
  department: string
  position: string
  /** Ref_Key Catalog_Пользователи в erp_pm */
  onecCatalogRefKey: string
  savedAt: string
  source: OneCSessionProfileSource
}

let profileRevision = 0

export function getOneCProfileRevision(): number {
  return profileRevision
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const normalized = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((ch) => `%${ch.charCodeAt(0).toString(16).padStart(2, '0')}`)
        .join('')
    )
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return null
  }
}

export function onecRefFromAccessToken(token: string): string {
  const payload = decodeJwtPayload(token)
  const raw = payload?.onec_ref ?? payload?.onecRef
  return typeof raw === 'string' ? raw.trim() : ''
}

export function loadOneCSessionProfile(): OneCSessionProfile | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<OneCSessionProfile>
    if (!parsed.fio && !parsed.orchestratorUserId && !parsed.onecCatalogRefKey) return null
    return {
      orchestratorUserId: String(parsed.orchestratorUserId ?? '').trim(),
      fio: String(parsed.fio ?? '').trim(),
      nameMail: String(parsed.nameMail ?? '').trim(),
      department: String(parsed.department ?? '').trim(),
      position: String(parsed.position ?? '').trim(),
      onecCatalogRefKey: String(parsed.onecCatalogRefKey ?? '').trim(),
      savedAt: String(parsed.savedAt ?? '').trim(),
      source: (parsed.source as OneCSessionProfileSource) || 'manual'
    }
  } catch {
    return null
  }
}

function writeOneCSessionProfile(profile: OneCSessionProfile | null): void {
  profileRevision += 1
  try {
    if (!profile) {
      localStorage.removeItem(STORAGE_KEY)
      return
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile))
  } catch {
    /* ignore quota */
  }
}

export function clearOneCSessionProfile(): void {
  writeOneCSessionProfile(null)
}

export function saveOneCSessionProfileFromUser(
  user: UserProfile,
  source: OneCSessionProfileSource,
  accessToken?: string | null
): OneCSessionProfile {
  const prev = loadOneCSessionProfile()
  const fromJwt = accessToken ? onecRefFromAccessToken(accessToken) : ''
  const ref =
    (user.onecCatalogRefKey || '').trim() ||
    fromJwt ||
    (prev?.onecCatalogRefKey || '').trim()
  const next: OneCSessionProfile = {
    orchestratorUserId: (user.id || prev?.orchestratorUserId || '').trim(),
    fio: (user.fio || prev?.fio || '').trim(),
    nameMail: (user.nameMail || prev?.nameMail || '').trim(),
    department: (user.department || prev?.department || '').trim(),
    position: (user.position || prev?.position || '').trim(),
    onecCatalogRefKey: ref,
    savedAt: new Date().toISOString(),
    source
  }
  writeOneCSessionProfile(next)
  return next
}

/** Поля сессии для sidecar / COM / gateway (идентификатор 1С + учётка). */
export function buildSidecarSessionFields(
  user: UserProfile | null,
  opts?: { login?: string; password?: string }
): Record<string, unknown> {
  const stored = loadOneCSessionProfile()
  const creds = comCredentials()
  const login = (opts?.login ?? creds.login ?? user?.fio ?? stored?.fio ?? '').trim()
  const password = opts?.password ?? creds.password ?? ''
  const nameMail = (user?.nameMail ?? stored?.nameMail ?? creds.nameMail ?? '').trim()
  const userId = (user?.id ?? stored?.orchestratorUserId ?? '').trim()
  const ref = (user?.onecCatalogRefKey ?? stored?.onecCatalogRefKey ?? '').trim()

  const out: Record<string, unknown> = {
    login,
    fio: login,
    erp_login: login
  }
  if (password) {
    out.password = password
    out.erp_password = password
  }
  if (nameMail) {
    out.nameMail = nameMail
    out.name_mail = nameMail
  }
  if (userId) {
    out.user_id = userId
    out.userId = userId
  }
  if (ref) {
    out.onecCatalogRefKey = ref
    out.onec_catalog_ref_key = ref
    out.session_onec_ref = ref
    out.session_customer_key = ref
  }
  return out
}

export function mergeUserWithOneCProfile(user: UserProfile): UserProfile {
  const stored = loadOneCSessionProfile()
  if (!stored) return user
  return {
    ...user,
    id: user.id || stored.orchestratorUserId,
    fio: user.fio || stored.fio,
    nameMail: user.nameMail || stored.nameMail,
    department: user.department || stored.department,
    position: user.position || stored.position,
    onecCatalogRefKey: user.onecCatalogRefKey || stored.onecCatalogRefKey || undefined
  }
}
