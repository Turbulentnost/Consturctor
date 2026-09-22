import type { UserProfile } from '../api/types'
import type { SpecMailRow } from './specV04DemoData'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { formatMailTimeRawForOneC } from '../utils/outlookMail'
import { hasOutlookEntryId } from '../utils/outlookMailActions'
import { erpActorComUsername } from './userContext'
import { onecComInvokeArgs } from './userContext'
import { openHttpUrl } from './workplaceNav'

/** Новая входящая корреспонденция — форма документа в толстом клиенте. */
export const ONEC_INCOMING_DOC_FORM = 'Документ.ТД_ВходящаяКорреспонденция.Форма.ФормаДокумента'

export type RegisterIncomingFromMailResult = {
  ok: boolean
  error?: string
  msgPath?: string
  stagedPath?: string
  method?: string
}

function erpWebIncomingUrl(): string {
  const raw = (import.meta.env.VITE_1C_ERP_WEB_URL || import.meta.env.VITE_ODATA_WEB_BASE || '').trim()
  if (!raw) return ''
  const base = raw.replace(/\/+$/, '')
  if (base.includes('#')) return base
  return `${base}#e1cib/list/Document.ТД_ВходящаяКорреспонденция`
}

function entryIdOf(row: { entryId?: string; id: string }): string {
  const explicit = String(row.entryId || '').trim()
  if (explicit && !explicit.toLowerCase().startsWith('imap:')) return explicit
  return String(row.id || '').trim()
}

/** Сохранить .msg, staging (как agent-pochta) и открыть форму входящей в 1С. */
export async function registerIncomingFromMail(
  user: UserProfile | null,
  mail: SpecMailRow,
  detail?: { subject?: string; sender?: string; receivedAt?: string }
): Promise<RegisterIncomingFromMailResult> {
  if (!hasOutlookEntryId(mail)) {
    return {
      ok: false,
      error: 'Регистрация входящей доступна для писем Outlook (COM). Письмо только из IMAP — откройте в Outlook.'
    }
  }
  const entryId = entryIdOf(mail)
  const receivedRaw =
    detail?.receivedAt || mail.receivedAt || mail.time
  const receivedLabel = formatMailTimeRawForOneC(receivedRaw)

  const openRes = await invokeLocalAcTool(
    'onec.register_incoming_from_mail',
    onecComInvokeArgs(
      {
        entry_id: entryId,
        form: ONEC_INCOMING_DOC_FORM,
        mail_subject: detail?.subject || mail.subject,
        mail_sender: detail?.sender || mail.sender,
        mail_received_at: receivedLabel,
        username: erpActorComUsername(user)
      },
      user
    ),
    180_000,
    user
  )
  if (openRes.ok && openRes.result) {
    const raw = openRes.result
    const msgPath = String(raw.saved_path || raw.path || '').trim()
    const stagedPath = String(raw.staged_path || raw.mail_file_path || msgPath).trim()
    return {
      ok: true,
      msgPath: stagedPath || msgPath,
      stagedPath,
      method: String(raw.method || 'onec.register_incoming_from_mail')
    }
  }
  const web = erpWebIncomingUrl()
  if (web && openHttpUrl(web)) {
    return {
      ok: true,
      method: 'web_client',
      error: openRes.error || '1С не стартовала из конструктора — открыт веб-клиент'
    }
  }
  const rawErr = openRes.error || ''
  const comHint =
    /ONEC_COM_SERVER|ONEC_ENTERPRISE_DB|1cv8c|entry_id|Outlook/i.test(rawErr)
      ? ` ${rawErr}`
      : rawErr
  return {
    ok: false,
    error: comHint || 'Не удалось зарегистрировать входящую. Проверьте Outlook и ONEC_ENTERPRISE_DB в desktop/.env'
  }
}
