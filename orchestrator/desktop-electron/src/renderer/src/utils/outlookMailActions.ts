import { invokeLocalAcTool } from './localAcTool'

/** UI actions — короче, чем search_mail (180s), чтобы не «висеть» на кнопках. */
export const OUTLOOK_MAIL_ACTION_TIMEOUT_MS = 45_000

export interface OutlookMailAttachment {
  index: number
  file_name: string
  display_name?: string
  size?: number
}

export interface OutlookMailDetail {
  entryId: string
  subject: string
  sender: string
  body: string
  bodyPreview: string
  unread: boolean
  attachments: OutlookMailAttachment[]
}

export function hasOutlookEntryId(row: { entryId?: string; id: string; channel?: string }): boolean {
  const explicit = String(row.entryId || '').trim()
  if (explicit && !explicit.toLowerCase().startsWith('imap:')) return true
  if (row.channel === 'imap') return false
  const id = String(row.id || '').trim()
  return Boolean(id) && !id.toLowerCase().startsWith('imap:')
}

function entryIdOf(row: { entryId?: string; id: string; channel?: string }): string {
  if (!hasOutlookEntryId(row)) return ''
  const explicit = String(row.entryId || '').trim()
  if (explicit && !explicit.toLowerCase().startsWith('imap:')) return explicit
  return String(row.id || '').trim()
}

export async function fetchOutlookMailDetail(
  row: { entryId?: string; id: string }
): Promise<{ ok: true; detail: OutlookMailDetail } | { ok: false; error: string }> {
  const entryId = entryIdOf(row)
  if (!entryId) {
    return { ok: false, error: 'Нет идентификатора письма' }
  }
  const res = await invokeLocalAcTool(
    'outlook.fetch_message',
    { entry_id: entryId },
    OUTLOOK_MAIL_ACTION_TIMEOUT_MS
  )
  if (!res.ok || !res.result) {
    return { ok: false, error: res.error || 'Не удалось прочитать письмо' }
  }
  const raw = res.result
  const attachments = Array.isArray(raw.attachments)
    ? raw.attachments
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map((item) => ({
          index: Number(item.index) || 0,
          file_name: String(item.file_name || item.display_name || 'файл'),
          display_name: String(item.display_name || ''),
          size: typeof item.size === 'number' ? item.size : undefined
        }))
        .filter((item) => item.index > 0)
    : []
  return {
    ok: true,
    detail: {
      entryId,
      subject: String(raw.subject || ''),
      sender: String(raw.sender || ''),
      body: String(raw.body || raw.body_preview || ''),
      bodyPreview: String(raw.body_preview || raw.body || ''),
      unread: Boolean(raw.unread),
      attachments
    }
  }
}

export async function markOutlookMailRead(
  row: { entryId?: string; id: string },
  unread: boolean
): Promise<{ ok: boolean; error?: string }> {
  const entryId = entryIdOf(row)
  if (!entryId) return { ok: false, error: 'Нет идентификатора письма' }
  const res = await invokeLocalAcTool(
    'outlook.mark_read',
    { entry_id: entryId, unread },
    OUTLOOK_MAIL_ACTION_TIMEOUT_MS
  )
  if (!res.ok) return { ok: false, error: res.error || 'Не удалось изменить статус' }
  return { ok: true }
}

export async function displayOutlookMail(
  row: { entryId?: string; id: string },
  mode: 'open' | 'reply' | 'reply_all' | 'forward' = 'open'
): Promise<{ ok: boolean; error?: string }> {
  const entryId = entryIdOf(row)
  if (!entryId) return { ok: false, error: 'Нет идентификатора письма' }
  const res = await invokeLocalAcTool(
    'outlook.display_message',
    { entry_id: entryId, mode },
    OUTLOOK_MAIL_ACTION_TIMEOUT_MS
  )
  if (!res.ok) return { ok: false, error: res.error || 'Outlook не открыл письмо' }
  return { ok: true }
}

export async function saveOutlookAttachment(
  row: { entryId?: string; id: string },
  attachmentIndex: number
): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  const entryId = entryIdOf(row)
  if (!entryId) return { ok: false, error: 'Нет идентификатора письма' }
  const res = await invokeLocalAcTool(
    'outlook.save_attachment',
    { entry_id: entryId, attachment_index: attachmentIndex },
    OUTLOOK_MAIL_ACTION_TIMEOUT_MS
  )
  if (!res.ok || !res.result) {
    return { ok: false, error: res.error || 'Не удалось сохранить вложение' }
  }
  const path = String(res.result.saved_path || '').trim()
  if (!path) return { ok: false, error: 'Outlook не вернул путь к файлу' }
  return { ok: true, path }
}

export async function openSavedPath(path: string): Promise<{ ok: boolean; error?: string }> {
  const trimmed = path.trim()
  if (!trimmed) return { ok: false, error: 'Пустой путь к файлу' }
  if (typeof window.api?.openPath !== 'function') {
    return { ok: false, error: 'Открытие файлов доступно только в Electron' }
  }
  const res = await window.api.openPath(trimmed)
  if (!res.ok) {
    return { ok: false, error: res.error || 'Не удалось открыть файл' }
  }
  return { ok: true }
}
