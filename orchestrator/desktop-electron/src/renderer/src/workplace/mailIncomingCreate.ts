import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { hasOutlookEntryId } from '../utils/outlookMailActions'
import { formatMailTimeRawForOneC } from '../utils/outlookMail'
import type { SpecMailRow } from './specV04DemoData'
import { onecComInvokeArgs } from './userContext'

export type IncomingDepartmentOption = {
  code: string
  name: string
}

export type IncomingCreateDraft = {
  departmentId: string
  departmentName: string
  theme: string
  partner: string
  organization: string
  emailSender: string
  emailRecipient: string
  content: string
}

export type IncomingCreateResult = {
  ok: boolean
  number?: string
  refKey?: string
  summary?: string
  attachmentWarning?: string
  error?: string
}

function entryIdOf(row: { entryId?: string; id: string }): string {
  const explicit = String(row.entryId || '').trim()
  if (explicit && !explicit.toLowerCase().startsWith('imap:')) return explicit
  return String(row.id || '').trim()
}

export function emptyIncomingCreateDraft(
  mail?: SpecMailRow,
  detail?: { subject?: string; sender?: string; bodyPreview?: string; recipient?: string }
): IncomingCreateDraft {
  return {
    departmentId: '',
    departmentName: '',
    theme: (detail?.subject || mail?.subject || '').trim(),
    partner: '',
    organization: 'НП',
    emailSender: (detail?.sender || mail?.sender || '').trim(),
    emailRecipient: (detail?.recipient || '').trim(),
    content: (detail?.bodyPreview || '').trim()
  }
}

export async function fetchIncomingDepartments(): Promise<IncomingDepartmentOption[]> {
  const response = await api.invokeServerTool(
    'onec.incoming_correspondence',
    { action: 'departments' },
    60_000
  )
  if (!response.ok) return []
  const result = response.result as Record<string, unknown> | undefined
  const rows = result?.departments
  if (!Array.isArray(rows)) return []
  return rows
    .map((row) => {
      if (!row || typeof row !== 'object') return null
      const item = row as Record<string, unknown>
      const code = String(item.code || '').trim()
      const name = String(item.name || '').trim()
      if (!code) return null
      return { code, name: name || code }
    })
    .filter((item): item is IncomingDepartmentOption => Boolean(item))
}

function parseWriteResult(result: unknown): Omit<IncomingCreateResult, 'ok' | 'error'> {
  if (!result || typeof result !== 'object') return {}
  const payload = result as Record<string, unknown>
  const data =
    payload.data && typeof payload.data === 'object'
      ? (payload.data as Record<string, unknown>)
      : undefined
  return {
    refKey: String(payload.erp_document_id || data?.Ref_Key || '').trim() || undefined,
    number: String(data?.Number || payload.number || '').trim() || undefined,
    summary: String(payload.summary || '').trim() || undefined,
    attachmentWarning: String(payload.attachment_warning || '').trim() || undefined
  }
}

export async function createIncomingFromMail(
  user: UserProfile | null,
  mail: SpecMailRow,
  draft: IncomingCreateDraft,
  detail?: { receivedAt?: string }
): Promise<IncomingCreateResult> {
  if (!hasOutlookEntryId(mail)) {
    return {
      ok: false,
      error: 'Регистрация входящей доступна для писем Outlook (COM).'
    }
  }

  const departmentId = draft.departmentId.trim()
  if (!departmentId) {
    return { ok: false, error: 'Укажите код подразделения (кому на исполнение)' }
  }
  const theme = draft.theme.trim()
  if (!theme) {
    return { ok: false, error: 'Укажите тему входящей' }
  }

  const entryId = entryIdOf(mail)
  const saveRes = await invokeLocalAcTool(
    'outlook.save_message',
    onecComInvokeArgs(
      {
        entry_id: entryId,
        stage_for_incoming: true
      },
      user
    ),
    180_000,
    user
  )
  if (!saveRes.ok || !saveRes.result) {
    return { ok: false, error: saveRes.error || 'Не удалось сохранить .msg из Outlook' }
  }

  const staged = saveRes.result
  const receivedRaw = detail?.receivedAt || mail.receivedAt || mail.time
  const args: Record<string, unknown> = {
    action: 'create',
    department_id: departmentId,
    department_name: draft.departmentName.trim(),
    theme,
    partner: draft.partner.trim(),
    organization: draft.organization.trim() || 'НП',
    email_sender: draft.emailSender.trim(),
    email_recipient: draft.emailRecipient.trim(),
    content: draft.content.trim() || theme,
    received_at: formatMailTimeRawForOneC(receivedRaw),
    attach_msg: true,
    staged_path: staged.staged_path,
    msg_file_path: staged.staged_path
  }
  const b64 = String(staged.msg_base64 || '').trim()
  if (b64) {
    args.msg_base64 = b64
    args.msg_filename = staged.msg_filename || 'message.msg'
  }

  const response = await api.invokeServerTool('onec.incoming_correspondence_write', args, 180_000)
  if (!response.ok) {
    return { ok: false, error: response.error || 'OData: не удалось создать входящую в 1С' }
  }
  const parsed = parseWriteResult(response.result)
  return {
    ok: true,
    ...parsed,
    summary:
      parsed.summary ||
      (parsed.number
        ? `Создана входящая ${parsed.number}`
        : 'Документ входящей создан в 1С через OData')
  }
}
