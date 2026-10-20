import { api } from '../api/client'
import type { ToolStatus } from '../api/types'
import { comCredentials } from '../store/session'
import { dayKeyLocal } from './outlookMail'

/** Desktop never opens IMAP sockets — only POST /api/v1/tools/invoke. */

export type ImapSearchResult = {
  ok: boolean
  mode: string
  configuredHint: boolean
  messages: Record<string, unknown>[]
  error?: string
  host?: string
  mailbox?: string
  login?: string
}

const IMAP_NO_MAILBOX =
  'IMAP: нет логина почты или пароля — войдите в программу заново с паролем'

/** Логин ящика текущего пользователя (name_mail); пусто — IMAP не вызывается. */
export function imapMailboxLogin(): string {
  const { nameMail, password } = comCredentials()
  return password ? nameMail.trim().toLowerCase() : ''
}

function withMailbox(payload: Record<string, unknown>): Record<string, unknown> | null {
  const { nameMail, password } = comCredentials()
  const login = nameMail.trim().toLowerCase()
  if (!login || !password) return null
  return { ...payload, mail_login: login, mail_password: password }
}

function noMailbox(): ImapSearchResult {
  return { ok: false, mode: '', configuredHint: false, messages: [], error: IMAP_NO_MAILBOX }
}

export function nextDayKey(ymd: string): string {
  const [year, month, day] = ymd.split('-').map((part) => Number(part))
  if (!year || !month || !day) return ymd
  return dayKeyLocal(new Date(year, month - 1, day + 1))
}

export function formatImapStatusLine(status: Pick<ToolStatus, 'configured' | 'mode'> | null): string {
  if (!status) return 'IMAP: статус недоступен (GET /api/v1/tools/imap/status)'
  const mode = status.mode || (status.configured ? 'real' : 'stub')
  if (!status.configured || mode === 'stub') {
    return `IMAP: не настроен · mode=${mode}`
  }
  return `IMAP: подключен · mode=${mode}`
}

export function isImapStubMode(mode: string, configured?: boolean): boolean {
  const key = (mode || '').trim().toLowerCase()
  if (key === 'stub') return true
  if (configured === false) return true
  return false
}

function asRecordList(raw: unknown): Record<string, unknown>[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
}

export async function fetchImapStatus(): Promise<ToolStatus | null> {
  try {
    return await api.getToolStatus('imap')
  } catch {
    return null
  }
}

export async function fetchImapSearch(args: {
  since?: string
  before?: string
  date?: string
  query?: string
  limit?: number
}): Promise<ImapSearchResult> {
  const payload: Record<string, unknown> = {
    limit: args.limit ?? 50
  }
  if (args.date) payload.date = args.date
  if (args.since) payload.since = args.since
  if (args.before) payload.before = args.before
  if (args.query) payload.query = args.query

  const personal = withMailbox(payload)
  if (!personal) return noMailbox()
  const res = await api.invokeServerTool('imap.search', personal)
  if (!res.ok || !res.result || typeof res.result !== 'object') {
    return {
      ok: false,
      mode: '',
      configuredHint: false,
      messages: [],
      error: res.error || 'imap.search недоступен'
    }
  }
  const body = res.result as Record<string, unknown>
  const mode = String(body.mode || body.source || '')
  const messages = asRecordList(body.messages)
  return {
    ok: true,
    mode,
    configuredHint: mode === 'real' || mode === 'imap',
    messages,
    host: String(body.host || ''),
    mailbox: String(body.mailbox || ''),
    login: String(body.login || '')
  }
}

export async function fetchImapListUnread(limit = 50): Promise<ImapSearchResult> {
  const personal = withMailbox({ limit })
  if (!personal) return noMailbox()
  const res = await api.invokeServerTool('imap.list_unread', personal)
  if (!res.ok || !res.result || typeof res.result !== 'object') {
    return {
      ok: false,
      mode: '',
      configuredHint: false,
      messages: [],
      error: res.error || 'imap.list_unread недоступен'
    }
  }
  const body = res.result as Record<string, unknown>
  const mode = String(body.mode || body.source || '')
  return {
    ok: true,
    mode,
    configuredHint: mode === 'real' || mode === 'imap',
    messages: asRecordList(body.messages),
    host: String(body.host || ''),
    mailbox: String(body.mailbox || ''),
    login: String(body.login || '')
  }
}

export async function fetchImapMessage(uid: number): Promise<{
  ok: boolean
  subject: string
  from: string
  body: string
  error?: string
}> {
  const personal = withMailbox({ uid })
  if (!personal) return { ok: false, subject: '', from: '', body: '', error: IMAP_NO_MAILBOX }
  const res = await api.invokeServerTool('imap.fetch_message', personal)
  if (!res.ok || !res.result || typeof res.result !== 'object') {
    return { ok: false, subject: '', from: '', body: '', error: res.error || 'Не удалось загрузить письмо IMAP' }
  }
  const body = res.result as Record<string, unknown>
  return {
    ok: true,
    subject: String(body.subject || ''),
    from: String(body.from || ''),
    body: String(body.body_text || '')
  }
}

export function parseImapUid(row: { imapUid?: number; id: string }): number {
  if (row.imapUid && row.imapUid > 0) return row.imapUid
  const match = /^imap:(\d+)$/i.exec(String(row.id || ''))
  return match ? Number(match[1]) : 0
}
