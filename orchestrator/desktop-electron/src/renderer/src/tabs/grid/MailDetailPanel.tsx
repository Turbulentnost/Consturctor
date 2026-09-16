import { useCallback, useEffect, useState } from 'react'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import { SpecPill } from '../../workplace/specV04Components'
import {
  displayOutlookMail,
  fetchOutlookMailDetail,
  hasOutlookEntryId,
  markOutlookMailRead,
  saveOutlookAttachment,
  type OutlookMailAttachment,
  type OutlookMailDetail
} from '../../utils/outlookMailActions'
import { fetchImapMessage, parseImapUid } from '../../utils/imapMail'
import {
  downloadAttachmentCopy,
  ensureAttachmentSaved,
  loadAttachmentPreview,
  openAttachmentExternally
} from '../../utils/mailAttachmentPreview'
import { MailAttachmentsModal } from './MailAttachmentsModal'

export function MailDetailPanel({
  mail,
  onPatchRow,
  onAskOrchestrator
}: {
  mail: SpecMailRow
  onPatchRow?: (id: string, patch: Partial<SpecMailRow>) => void
  onAskOrchestrator?: (message: string) => void
}): React.JSX.Element {
  const [detail, setDetail] = useState<OutlookMailDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  const [attModalOpen, setAttModalOpen] = useState(false)
  const [attModalFocus, setAttModalFocus] = useState<number | undefined>()

  const showNote = useCallback((text: string, isError = false): void => {
    setNote(isError ? text : text)
    if (text) {
      window.setTimeout(() => setNote(''), 4000)
    }
  }, [])

  const canOutlookActions = hasOutlookEntryId(mail)

  useEffect(() => {
    let alive = true
    setDetail(null)
    setLoading(true)
    setNote('')
    const load = async (): Promise<void> => {
      if (hasOutlookEntryId(mail)) {
        const res = await fetchOutlookMailDetail(mail)
        if (!alive) return
        setLoading(false)
        if (res.ok) {
          setDetail(res.detail)
          if (typeof res.detail.unread === 'boolean') {
            onPatchRow?.(mail.id, {
              unread: res.detail.unread,
              status: res.detail.unread ? 'Непрочитано' : 'Прочитано',
              stTone: res.detail.unread ? 'orange' : 'blue'
            })
          }
          return
        }
        showNote(res.error, true)
        return
      }
      const uid = parseImapUid(mail)
      if (!uid) {
        setLoading(false)
        return
      }
      const res = await fetchImapMessage(uid)
      if (!alive) return
      setLoading(false)
      if (res.ok) {
        setDetail({
          entryId: '',
          subject: res.subject || mail.subject,
          sender: res.from || mail.sender,
          body: res.body,
          bodyPreview: res.body.slice(0, 400),
          unread: Boolean(mail.unread),
          attachments: []
        })
        return
      }
      showNote(res.error || 'IMAP: не удалось загрузить письмо', true)
    }
    void load()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when selection changes
  }, [mail.id, mail.entryId, mail.imapUid])

  const runAction = async (label: string, fn: () => Promise<{ ok: boolean; error?: string }>): Promise<void> => {
    if (busy) return
    setBusy(label)
    try {
      const res = await fn()
      if (res.ok) showNote('Готово')
      else showNote(res.error || 'Ошибка', true)
    } finally {
      setBusy('')
    }
  }

  const openInOrchestrator = (att: OutlookMailAttachment): void => {
    setAttModalFocus(att.index)
    setAttModalOpen(true)
  }

  const quickOpenAttachment = async (att: OutlookMailAttachment): Promise<void> => {
    if (busy) return
    setBusy('attachment')
    try {
      const saved = await ensureAttachmentSaved(mail, att)
      if (!saved.ok) {
        showNote(saved.error, true)
        return
      }
      const preview = await loadAttachmentPreview(saved.path)
      if (preview.kind === 'external' || preview.kind === 'too_large') {
        const opened = await openAttachmentExternally(saved.path)
        if (opened.ok) showNote('Открыто')
        else showNote(opened.error || 'Ошибка', true)
        return
      }
      if (preview.kind === 'error') {
        showNote(preview.message, true)
        return
      }
      setAttModalFocus(att.index)
      setAttModalOpen(true)
    } finally {
      setBusy('')
    }
  }

  const quickDownloadAttachment = async (att: OutlookMailAttachment): Promise<void> => {
    await runAction('download', async () => {
      const saved = await saveOutlookAttachment(mail, att.index)
      if (!saved.ok) return { ok: false, error: saved.error }
      const res = await downloadAttachmentCopy(saved.path, att.file_name)
      if (res.canceled) return { ok: true }
      return res
    })
  }

  const bodyText =
    detail?.body?.trim() ||
    detail?.bodyPreview?.trim() ||
    mail.bodyPreview?.trim() ||
    (loading ? 'Загружаем текст…' : 'Текст письма недоступен')

  const attachments: OutlookMailAttachment[] =
    detail?.attachments?.length
      ? detail.attachments
      : (mail.attachmentNames || []).map((name, idx) => ({
          index: idx + 1,
          file_name: name
        }))

  return (
    <>
      <div className="spec-detail-card spec-mail-preview wp-card">
        <h2>{mail.subject}</h2>
        <p className="spec-v04-muted">
          От: {mail.sender} · {mail.time}
        </p>
        <div className="spec-detail-tags">
          <SpecPill tone={mail.priTone}>{mail.priority}</SpecPill>
          <SpecPill tone={mail.stTone}>{mail.status}</SpecPill>
          <SpecPill tone={mail.catTone}>{mail.category}</SpecPill>
        </div>
        {note ? <p className="spec-v04-muted spec-mail-action-note">{note}</p> : null}
        {!canOutlookActions ? (
          <p className="spec-v04-muted spec-mail-action-note">
            Ответ / открыть / прочитано — через Outlook COM (письмо только в IMAP).
          </p>
        ) : null}
        <div className="spec-mail-body-preview">{bodyText}</div>
        {attachments.length ? (
          <div className="spec-attachments spec-mail-attachments">
            <div className="spec-mail-att-head">
              <h4 className="spec-detail-pane">Вложения ({attachments.length})</h4>
              <button
                type="button"
                className="spec-btn-outline spec-mail-att-open-all"
                disabled={Boolean(busy)}
                onClick={() => {
                  setAttModalFocus(undefined)
                  setAttModalOpen(true)
                }}
              >
                Все вложения
              </button>
            </div>
            <ul className="spec-mail-att-compact-list">
              {attachments.map((att) => (
                <li key={`${mail.id}-${att.index}`} className="spec-mail-att-compact-row">
                  <span className="spec-mail-att-name">{att.file_name}</span>
                  <div className="spec-mail-att-compact-actions">
                    <button
                      type="button"
                      className="spec-btn-launch spec-mail-att-action-btn"
                      disabled={Boolean(busy)}
                      onClick={() => void quickOpenAttachment(att)}
                    >
                      Открыть
                    </button>
                    <button
                      type="button"
                      className="spec-btn-outline spec-mail-att-action-btn"
                      disabled={Boolean(busy)}
                      onClick={() => void quickDownloadAttachment(att)}
                    >
                      Скачать
                    </button>
                    <button
                      type="button"
                      className="spec-btn-outline spec-mail-att-action-btn"
                      disabled={Boolean(busy)}
                      onClick={() => openInOrchestrator(att)}
                    >
                      В оркестраторе
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <footer className="spec-detail-actions spec-mail-detail-actions">
          <button
            type="button"
            className="spec-btn-launch spec-btn-launch-block"
            disabled={Boolean(busy) || !canOutlookActions}
            onClick={() => void runAction('reply', () => displayOutlookMail(mail, 'reply'))}
          >
            {busy === 'reply' ? '…' : 'Ответить'}
          </button>
          <button
            type="button"
            className="spec-btn-outline spec-btn-outline-block"
            disabled={Boolean(busy) || !canOutlookActions}
            onClick={() => void runAction('reply_all', () => displayOutlookMail(mail, 'reply_all'))}
          >
            {busy === 'reply_all' ? '…' : 'Ответить всем'}
          </button>
          <button
            type="button"
            className="spec-btn-outline spec-btn-outline-block"
            disabled={Boolean(busy) || !canOutlookActions}
            onClick={() => void runAction('open', () => displayOutlookMail(mail, 'open'))}
          >
            {busy === 'open' ? '…' : 'В Outlook'}
          </button>
          <div className="spec-mail-read-row">
            <button
              type="button"
              className="spec-btn-outline spec-mail-read-btn"
              disabled={Boolean(busy) || !canOutlookActions}
              onClick={() =>
                void runAction('read', async () => {
                  const res = await markOutlookMailRead(mail, false)
                  if (res.ok) {
                    onPatchRow?.(mail.id, {
                      unread: false,
                      status: 'Прочитано',
                      stTone: 'blue',
                      priority: 'Средний',
                      priTone: 'orange'
                    })
                    setDetail((prev) => (prev ? { ...prev, unread: false } : prev))
                  }
                  return res
                })
              }
            >
              Прочитано
            </button>
            <button
              type="button"
              className="spec-btn-outline spec-mail-read-btn"
              disabled={Boolean(busy) || !canOutlookActions}
              onClick={() =>
                void runAction('unread', async () => {
                  const res = await markOutlookMailRead(mail, true)
                  if (res.ok) {
                    onPatchRow?.(mail.id, {
                      unread: true,
                      status: 'Непрочитано',
                      stTone: 'orange',
                      priority: 'Высокий',
                      priTone: 'red'
                    })
                    setDetail((prev) => (prev ? { ...prev, unread: true } : prev))
                  }
                  return res
                })
              }
            >
              Непрочитано
            </button>
          </div>
          {onAskOrchestrator ? (
            <button
              type="button"
              className="spec-btn-launch spec-btn-launch-block"
              disabled={Boolean(busy)}
              onClick={() =>
                onAskOrchestrator(`Помоги с письмом «${mail.subject}» от ${mail.sender}`)
              }
            >
              Передать ИИ
            </button>
          ) : null}
        </footer>
      </div>
      <MailAttachmentsModal
        open={attModalOpen}
        mail={mail}
        attachments={attachments}
        initialIndex={attModalFocus}
        onClose={() => setAttModalOpen(false)}
        onToast={showNote}
      />
    </>
  )
}
