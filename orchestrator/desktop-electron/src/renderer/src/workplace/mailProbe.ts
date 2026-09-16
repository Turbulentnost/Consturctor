import type { SpecMailRow } from './specV04DemoData'
import { imapMessageToMailRow, outlookMessageToMailRow } from './specV04Mappers'
import {
  fetchImapListUnread,
  fetchImapSearch,
  fetchImapStatus,
  formatImapStatusLine,
  isImapStubMode,
  nextDayKey
} from '../utils/imapMail'
import {
  dayKeyLocal,
  fetchOutlookMailForDay,
  fetchOutlookMailForRange,
  outlookMailWeekRange,
  skipOutlookCom
} from '../utils/outlookMail'

export type MailPrimary = 'imap' | 'outlook'

export type MailProbeResult = {
  primary: MailPrimary
  imapPrimary: boolean
  imapUsable: boolean
  extrasCount: number
  statusLine: string
  imapMode: string
  comError: string
  imapError: string
  imapToday: Record<string, unknown>[]
  comToday: Record<string, unknown>[]
}

export type OrchestratorMailLoad = {
  rows: SpecMailRow[]
  sourceLabel: string
  primary: MailPrimary
  imapPrimary: boolean
  comError: string
  imapError: string
  imapStatus: string
}

const PROBE_TTL_MS = 120_000
let probeCache: { at: number; day: string; result: MailProbeResult } | null = null

const RE_PREFIX = /^(re|fw|fwd|ответ|пересл)\s*:\s*/i

export function normalizeMessageId(raw: string): string {
  return raw.trim().toLowerCase().replace(/^<|>$/g, '')
}

export function normalizeMailSubject(raw: string): string {
  let text = raw.trim().toLowerCase().replace(/\s+/g, ' ')
  for (let i = 0; i < 4; i += 1) {
    const next = text.replace(RE_PREFIX, '')
    if (next === text) break
    text = next.trim()
  }
  return text
}

export function extractMailEmails(raw: string): string[] {
  const matches = raw.toLowerCase().match(/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/g)
  return matches ? [...new Set(matches)] : []
}

export function normalizeMailFrom(raw: string): string[] {
  const text = raw.trim().toLowerCase().replace(/\s+/g, ' ')
  const emails = extractMailEmails(text)
  const name = text.replace(/<[^>]+>/g, '').replace(/["']/g, '').trim()
  const tokens = new Set<string>()
  for (const email of emails) tokens.add(email)
  if (name) tokens.add(name)
  return [...tokens]
}

export function normalizeMailDate(raw: string): string {
  const text = raw.trim()
  if (!text) return ''
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(text)
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`
  const dmy = /^(\d{1,2})[.](\d{1,2})[.](\d{4})/.exec(text)
  if (dmy) {
    return `${dmy[3]}-${dmy[2].padStart(2, '0')}-${dmy[1].padStart(2, '0')}`
  }
  const parsed = new Date(text)
  if (!Number.isNaN(parsed.getTime())) return dayKeyLocal(parsed)
  return ''
}

function messageDate(msg: Record<string, unknown>): string {
  return normalizeMailDate(
    String(msg.date || msg.datetime || msg.received_at || msg.sent_at || '')
  )
}

function messageFrom(msg: Record<string, unknown>): string {
  return String(msg.from || msg.sender || '')
}

function messageSubject(msg: Record<string, unknown>): string {
  return String(msg.subject || '')
}

function messageIdOf(msg: Record<string, unknown>): string {
  return normalizeMessageId(
    String(msg.message_id || msg.messageId || msg.internet_message_id || '')
  )
}

export function mailIdentityKeys(msg: Record<string, unknown>): string[] {
  const keys = new Set<string>()
  const mid = messageIdOf(msg)
  if (mid) keys.add(`id:${mid}`)
  const subject = normalizeMailSubject(messageSubject(msg))
  const date = messageDate(msg)
  if (subject && date) {
    for (const from of normalizeMailFrom(messageFrom(msg))) {
      keys.add(`t:${from}|${subject}|${date}`)
    }
  }
  return [...keys]
}

export function filterMessagesOnDay(messages: Record<string, unknown>[], dayKey: string): Record<string, unknown>[] {
  return messages.filter((msg) => messageDate(msg) === dayKey)
}

export function imapExtrasVsOutlook(
  imapMessages: Record<string, unknown>[],
  outlookMessages: Record<string, unknown>[]
): Record<string, unknown>[] {
  const outlookKeys = new Set<string>()
  for (const msg of outlookMessages) {
    for (const key of mailIdentityKeys(msg)) outlookKeys.add(key)
  }
  return imapMessages.filter((msg) => {
    const keys = mailIdentityKeys(msg)
    if (!keys.length) return true
    return !keys.some((key) => outlookKeys.has(key))
  })
}

export function attachOutlookEntryIds(
  imapRows: SpecMailRow[],
  outlookMessages: Record<string, unknown>[]
): SpecMailRow[] {
  const byKey = new Map<string, string>()
  outlookMessages.forEach((msg, index) => {
    const entryId = String(msg.entry_id || '').trim()
    if (!entryId) return
    for (const key of mailIdentityKeys(msg)) {
      if (!byKey.has(key)) byKey.set(key, entryId)
    }
    const fallback = outlookMessageToMailRow(msg, index).entryId
    if (fallback) {
      for (const key of mailIdentityKeys(msg)) {
        if (!byKey.has(key)) byKey.set(key, fallback)
      }
    }
  })
  return imapRows.map((row) => {
    if (row.entryId) return row
    const keys = mailIdentityKeys({
      message_id: row.messageId,
      from: row.sender,
      subject: row.subject,
      date: row.time
    })
    const entryId = keys.map((key) => byKey.get(key)).find(Boolean)
    return entryId ? { ...row, entryId } : row
  })
}

export function decideMailPrimary(input: {
  imapMessages: Record<string, unknown>[]
  outlookMessages: Record<string, unknown>[]
  imapMode: string
  imapConfigured?: boolean
  outlookOk: boolean
}): { primary: MailPrimary; extrasCount: number; imapUsable: boolean } {
  const stub = isImapStubMode(input.imapMode, input.imapConfigured)
  const extras = stub ? [] : imapExtrasVsOutlook(input.imapMessages, input.outlookMessages)
  const hasRealImap = !stub && input.imapMessages.length > 0
  if (stub || !hasRealImap) {
    return { primary: 'outlook', extrasCount: 0, imapUsable: false }
  }
  if (extras.length > 0) {
    return { primary: 'imap', extrasCount: extras.length, imapUsable: true }
  }
  if (!input.outlookOk && hasRealImap) {
    return { primary: 'imap', extrasCount: input.imapMessages.length, imapUsable: true }
  }
  return { primary: 'outlook', extrasCount: 0, imapUsable: true }
}

function mergeImapMessages(...batches: Record<string, unknown>[][]): Record<string, unknown>[] {
  const seen = new Set<string>()
  const out: Record<string, unknown>[] = []
  for (const batch of batches) {
    for (const msg of batch) {
      const uid = String(msg.uid ?? '')
      const mid = messageIdOf(msg)
      const key = mid ? `id:${mid}` : uid ? `uid:${uid}` : mailIdentityKeys(msg)[0] || JSON.stringify(msg)
      if (seen.has(key)) continue
      seen.add(key)
      out.push(msg)
    }
  }
  return out
}

export async function probeMailToday(now = new Date()): Promise<MailProbeResult> {
  const day = dayKeyLocal(now)
  if (probeCache && probeCache.day === day && Date.now() - probeCache.at < PROBE_TTL_MS) {
    return probeCache.result
  }

  const comPromise = skipOutlookCom()
    ? Promise.resolve({ ok: false, messages: [] as Record<string, unknown>[], error: 'Outlook COM отключён' })
    : fetchOutlookMailForDay(now, { folder: 'Inbox', maxResults: 50 })

  const [comRes, imapStatus, imapSearch, imapUnread] = await Promise.all([
    comPromise.catch((err) => ({
      ok: false,
      messages: [] as Record<string, unknown>[],
      error: err instanceof Error ? err.message : 'Outlook недоступен'
    })),
    fetchImapStatus(),
    fetchImapSearch({ date: day, limit: 50 }),
    fetchImapListUnread(50)
  ])

  const imapMode = imapSearch.mode || imapUnread.mode || imapStatus?.mode || ''
  const configured = imapStatus?.configured
  const imapMerged = mergeImapMessages(imapSearch.messages, imapUnread.messages)
  const imapToday = isImapStubMode(imapMode, configured)
    ? []
    : filterMessagesOnDay(imapMerged, day)
  const comToday = comRes.ok ? comRes.messages : []
  const decision = decideMailPrimary({
    imapMessages: imapToday,
    outlookMessages: comToday,
    imapMode,
    imapConfigured: configured,
    outlookOk: comRes.ok
  })

  const imapErrorParts = [imapSearch.error, imapUnread.error].filter(Boolean)
  if (!imapStatus) imapErrorParts.push('GET /api/v1/tools/imap/status недоступен')
  const result: MailProbeResult = {
    primary: decision.primary,
    imapPrimary: decision.primary === 'imap',
    imapUsable: decision.imapUsable,
    extrasCount: decision.extrasCount,
    statusLine: formatImapStatusLine(imapStatus),
    imapMode,
    comError: comRes.ok ? '' : comRes.error || 'Outlook недоступен',
    imapError: imapSearch.ok || imapUnread.ok ? '' : imapErrorParts.join(' · '),
    imapToday,
    comToday
  }
  probeCache = { at: Date.now(), day, result }
  return result
}

export function pickMailRows(input: {
  primary: MailPrimary
  imapUsable: boolean
  imapRows: SpecMailRow[]
  comRows: SpecMailRow[]
}): SpecMailRow[] {
  if (input.primary === 'imap' && input.imapRows.length) return input.imapRows
  if (input.comRows.length) return input.comRows
  if (input.imapUsable && input.imapRows.length) return input.imapRows
  return []
}

export async function loadOrchestratorMail(outlookMailbox: string): Promise<OrchestratorMailLoad> {
  const range = outlookMailWeekRange()
  const [probe, comWeek, imapWeek] = await Promise.all([
    probeMailToday(),
    skipOutlookCom()
      ? Promise.resolve({
          ok: false,
          messages: [] as Record<string, unknown>[],
          error: 'Outlook COM отключён (VITE_SKIP_OUTLOOK_COM)',
          source: ''
        })
      : fetchOutlookMailForRange(range.dateFrom, range.dateTo, { folder: 'All', maxResults: 50 }),
    fetchImapSearch({ since: range.dateFrom, before: nextDayKey(range.dateTo), limit: 50 })
  ])

  const comError = uniqueMailErrors(probe.comError, comWeek.ok ? '' : comWeek.error || 'Outlook недоступен')
  const imapError = uniqueMailErrors(probe.imapError, imapWeek.ok ? '' : imapWeek.error || '')
  const imapWeekMessages = probe.imapUsable
    ? imapWeek.messages.length
      ? imapWeek.messages
      : probe.imapToday
    : []
  const imapRows = attachOutlookEntryIds(
    imapWeekMessages.map((msg, index) => imapMessageToMailRow(msg, index)),
    [...(comWeek.ok ? comWeek.messages : []), ...probe.comToday]
  )
  const comRows = (comWeek.ok ? comWeek.messages : []).map((msg, index) =>
    outlookMessageToMailRow(msg, index)
  )
  const rows = pickMailRows({
    primary: probe.primary,
    imapUsable: probe.imapUsable,
    imapRows,
    comRows
  })

  const sourceLabel = probe.imapPrimary
    ? `imap (primary, today extras=${probe.extrasCount})`
    : comWeek.ok
      ? comWeek.source || `outlook_mail (${range.dateFrom}…${range.dateTo}, All)`
      : comError || (outlookMailbox ? `Outlook: ${outlookMailbox}` : 'outlook_mail')

  return {
    rows,
    sourceLabel,
    primary: probe.primary,
    imapPrimary: probe.imapPrimary,
    comError,
    imapError,
    imapStatus: probe.imapPrimary ? probe.statusLine : probe.statusLine
  }
}

function uniqueMailErrors(...chunks: (string | undefined | null)[]): string {
  const seen = new Set<string>()
  const parts: string[] = []
  for (const chunk of chunks) {
    if (!chunk?.trim()) continue
    const text = chunk.trim()
    if (seen.has(text)) continue
    seen.add(text)
    parts.push(text)
  }
  return parts.join(' · ')
}

export function mailListEmptyHint(input: {
  loading: boolean
  imapPrimary: boolean
  mailbox: string
  imapStatus: string
}): string {
  if (input.loading) return 'Загружаем письма…'
  if (input.imapPrimary) {
    return `Нет писем в IMAP. ${input.imapStatus}`
  }
  const box = input.mailbox ? ` Ящик: ${input.mailbox}.` : ''
  return `Нет писем за неделю (Outlook COM).${box} ${input.imapStatus}`
}
