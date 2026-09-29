import type { SpecPillTone } from './specV04DemoData'

export type MailFolderColor = 'red' | 'orange' | 'yellow' | 'green' | 'blue' | 'purple' | 'gray'

export type MailFolder = {
  id: string
  name: string
  color: MailFolderColor
}

/** Per-mail overrides stored in the app (not Outlook). */
export type MailRowMeta = {
  priority?: string
  priTone?: SpecPillTone
  /** Folder id, or null/undefined when not filed. */
  appFolderId?: string | null
}

export const MAIL_FOLDER_COLORS: MailFolderColor[] = [
  'red',
  'orange',
  'yellow',
  'green',
  'blue',
  'purple',
  'gray'
]

export const DEFAULT_MAIL_FOLDER_ID = 'proj'

export const DEFAULT_MAIL_FOLDERS: MailFolder[] = [
  { id: DEFAULT_MAIL_FOLDER_ID, name: 'Проектные', color: 'purple' }
]

const PRIORITY_OPTIONS = ['Высокий', 'Средний', 'Низкий'] as const

export type MailPriorityLabel = (typeof PRIORITY_OPTIONS)[number]

export const MAIL_PRIORITY_OPTIONS: MailPriorityLabel[] = [...PRIORITY_OPTIONS]

export function priorityToneForLabel(priority: string): SpecPillTone {
  if (/высок/i.test(priority)) return 'red'
  if (/низк/i.test(priority)) return 'gray'
  if (/средн/i.test(priority)) return 'orange'
  return 'orange'
}

function foldersStorageKey(userId: string): string {
  return `orch.mail.folders.${userId || 'anon'}`
}

function metaStorageKey(userId: string): string {
  return `orch.mail.meta.${userId || 'anon'}`
}

function isFolderColor(value: unknown): value is MailFolderColor {
  return typeof value === 'string' && (MAIL_FOLDER_COLORS as string[]).includes(value)
}

function normalizeFolders(raw: unknown): MailFolder[] {
  const list: MailFolder[] = []
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (!item || typeof item !== 'object') continue
      const rec = item as Record<string, unknown>
      const id = String(rec.id || '').trim()
      const name = String(rec.name || '').trim()
      const color = isFolderColor(rec.color) ? rec.color : 'gray'
      if (!id || !name) continue
      list.push({ id, name, color })
    }
  }
  if (!list.some((f) => f.id === DEFAULT_MAIL_FOLDER_ID)) {
    return [...DEFAULT_MAIL_FOLDERS, ...list]
  }
  return list
}

export function loadMailFolders(userId: string): MailFolder[] {
  if (typeof window === 'undefined') return [...DEFAULT_MAIL_FOLDERS]
  try {
    const raw = window.localStorage.getItem(foldersStorageKey(userId))
    if (!raw) return [...DEFAULT_MAIL_FOLDERS]
    return normalizeFolders(JSON.parse(raw) as unknown)
  } catch {
    return [...DEFAULT_MAIL_FOLDERS]
  }
}

export function saveMailFolders(userId: string, folders: MailFolder[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(foldersStorageKey(userId), JSON.stringify(normalizeFolders(folders)))
  } catch {
    /* ignore quota */
  }
}

export function loadMailMeta(userId: string): Record<string, MailRowMeta> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(metaStorageKey(userId))
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    const out: Record<string, MailRowMeta> = {}
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!id || !value || typeof value !== 'object') continue
      const rec = value as Record<string, unknown>
      const meta: MailRowMeta = {}
      if (typeof rec.priority === 'string' && rec.priority.trim()) {
        meta.priority = rec.priority.trim()
        meta.priTone =
          typeof rec.priTone === 'string'
            ? (rec.priTone as SpecPillTone)
            : priorityToneForLabel(meta.priority)
      }
      if (rec.appFolderId === null) {
        meta.appFolderId = null
      } else if (typeof rec.appFolderId === 'string' && rec.appFolderId.trim()) {
        meta.appFolderId = rec.appFolderId.trim()
      }
      if (meta.priority || meta.appFolderId !== undefined) out[id] = meta
    }
    return out
  } catch {
    return {}
  }
}

export function saveMailMeta(userId: string, meta: Record<string, MailRowMeta>): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(metaStorageKey(userId), JSON.stringify(meta))
  } catch {
    /* ignore quota */
  }
}

export function createMailFolderId(): string {
  return `f_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

/** Apply stored meta onto a mail row (folder + optional priority override). */
export function applyMailMeta(row: {
  id: string
  priority: string
  priTone: SpecPillTone
  appFolderId?: string
}, meta: MailRowMeta | undefined): {
  priority: string
  priTone: SpecPillTone
  appFolderId?: string
} {
  if (!meta) {
    return {
      priority: row.priority,
      priTone: row.priTone,
      appFolderId: row.appFolderId
    }
  }
  const folderId =
    meta.appFolderId === null
      ? undefined
      : typeof meta.appFolderId === 'string'
        ? meta.appFolderId
        : row.appFolderId
  if (meta.priority) {
    return {
      priority: meta.priority,
      priTone: meta.priTone || priorityToneForLabel(meta.priority),
      appFolderId: folderId
    }
  }
  return {
    priority: row.priority,
    priTone: row.priTone,
    appFolderId: folderId
  }
}

export function isDefaultMailFolder(folderId: string): boolean {
  return folderId === DEFAULT_MAIL_FOLDER_ID
}
